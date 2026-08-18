"""Location-aware routing layer for the A&E wait-time tool.

What this module adds to the forecaster: *how long it takes you to get there*.
A hospital with a 40-minute wait that is 55 minutes away is worse than a
hospital with a 70-minute wait 10 minutes away, and no published A&E figure
tells you that.

HONESTY CONTRACT
----------------
Nothing in here is a measured door-to-door trip time. Every number this module
produces is a model output, so every TravelEstimate carries:

  * `basis`: which computation actually ran (see TravelBasis). Every
                  degradation step changes it. There are no silent fallbacks.
  * `is_estimate`: always True. We never measured your journey.
  * `assumption`: a plain-English sentence naming every constant that went
                  into the number, so a reader can disagree with it.

WHAT IS MEASURED vs WHAT IS ASSUMED
-----------------------------------
Measured (car mode, `live_corridor*` bases):
  - Current speeds from Transport Department inductive-loop detectors on
    strategic major roads, refreshed every 30 seconds.
Assumed (everywhere):
  - That straight-line distance × a circuity factor approximates road distance.
  - That detector speeds on strategic roads represent the whole journey,
    including surface streets and junctions (they do not, hence the cap).
  - Everything about transit: Hong Kong publishes no free point-to-point
    public-transport routing API, so transit mode is a *speed model*, not a
    route. It does not know the MTR exists.

DATA SOURCES
------------
1. Detector coordinates: static CSV, ~808 rows, changes rarely.
   Cached on disk under data/, refreshed at most every COORD_CSV_MAX_AGE_DAYS.
2. Live per-detector lane speeds: XML, ~700 KB, 30-second periods.
   Cached in memory for XML_CACHE_TTL_S so one page load does not hammer the
   government server.

Neither fetch may ever raise into a caller. A dead feed degrades the `basis`
and keeps answering.
"""

from __future__ import annotations

import csv
import io
import math
import os
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from engine import (
    HOSPITAL_COORDS,
    TailEstimate,
    LIVE_URL,
    _parse_live_str,
    build_buckets,
    haversine,
    load_corpus,
    score_normality,
    score_reliability,
    score_tail,
)

DATA = Path(__file__).resolve().parent.parent / "data"
COORD_CACHE_PATH = DATA / "td_detector_coords.csv"

# --- Sources -----------------------------------------------------------------
# The XML URL is overridable by environment variable purely so the failure path
# can be exercised (point it at an unroutable host and watch the basis change).
COORD_CSV_URL = os.environ.get(
    "AE_TRAFFIC_CSV_URL",
    "https://static.data.gov.hk/td/traffic-data-strategic-major-roads/info/"
    "traffic_speed_volume_occ_info.csv",
)
SPEED_XML_URL = os.environ.get(
    "AE_TRAFFIC_XML_URL",
    "https://resource.data.one.gov.hk/td/traffic-detectors/rawSpeedVol-all.xml",
)

# ---------------------------------------------------------------------------
# Constants. Every one of these is an assumption, and each says why it has the
# value it has, and each appears in a user-visible assumption string.
# ---------------------------------------------------------------------------

HTTP_TIMEOUT_S = 8.0
# Every network call is bounded. A hung government feed must not hang a page
# load: 8s is generous for a 700 KB file on a local network and still well
# under a browser's patience.

XML_CACHE_TTL_S = 180.0
# The feed publishes 30-second periods, but a user comparing 18 hospitals
# triggers one snapshot, not 18. Three minutes keeps the number meaningfully
# "now" while capping us at ~20 requests/hour against data.one.gov.hk.

FAILED_RETRY_BACKOFF_S = 30.0
# Circuit breaker. Ranking 18 hospitals calls the snapshot getter 18 times, so
# if a failed fetch were retried each time, one dead feed would cost
# 18 × HTTP_TIMEOUT_S = over two minutes per page load. After a failure we stop
# trying for 30 seconds and answer immediately from the fallback instead.
# Measured: without this, a request against an unroutable feed took 144 s.

STALE_SERVE_MAX_S = 900.0
# If a refresh fails we keep serving the last good snapshot for 15 minutes,
# flagged `stale` (traffic_live goes false, basis gains a _stale suffix).
# Beyond 15 minutes rush-hour conditions have changed enough that the data is
# no longer evidence, and we drop to the static fallback instead.

COORD_CSV_MAX_AGE_DAYS = 30.0
# Detector coordinates are physical infrastructure. Monthly is ample.

ROAD_CIRCUITY_FACTOR = 1.35
# Straight-line km understates driving km: roads bend, harbours need tunnels.
# The detour ratio for dense urban networks is commonly 1.3-1.4, and we take
# the midpoint. This is the single largest source of error in car mode for
# cross-harbour trips, where the true factor can exceed 2.

CORRIDOR_WIDTH_KM = 2.0
# A detector counts as "on your route" if it sits within 2 km of the straight
# line from you to the hospital. Wide enough to catch the actual road (which
# bends away from the straight line), narrow enough to exclude a different
# district's traffic.

CORRIDOR_WIDTH_WIDENED_KM = 5.0
# One widening step before we give up on corridor-specific traffic.

CORRIDOR_ENDPOINT_MARGIN = 0.15
# Detectors may sit up to 15% of the trip length beyond either endpoint and
# still count: approach roads matter, and the straight line is not the route.

MIN_CORRIDOR_DETECTORS = 3
# Fewer than three detectors is one road's local incident, not a corridor
# condition. Below this we widen rather than trust it.

EFFECTIVE_SPEED_CAP_KPH = 60.0
# Detectors sit on *strategic major roads* (tunnels, trunk roads, the Route 3
# corridor) where free flow is 80-100 km/h. No door-to-door urban trip
# averages that, because it also includes surface streets, signals, and the
# last kilometre. We cap the corridor average so a clear expressway cannot
# produce a fantasy arrival time.

EFFECTIVE_SPEED_FLOOR_KPH = 8.0
# A jammed detector reads 0. Clamping at 8 km/h stops one stopped loop from
# sending the estimate to infinity, and 8 km/h is roughly crawling traffic.

CAR_ACCESS_OVERHEAD_MIN = 4.0
# Getting out of where you are and into A&E: parking or dropping off, then
# walking in. Deliberately small, and it is not a substitute for measurement.

FALLBACK_CAR_SPEED_KPH = 30.0
# Used only when the traffic feed is unusable. Typical Hong Kong urban
# arterial average across a mixed trip. Basis becomes `static_fallback`, so
# the UI can say "no live traffic" rather than implying this was observed.

TRANSIT_LINE_HAUL_KPH = 22.0
# Hong Kong has NO free point-to-point public-transport routing API, and this
# module refuses to invent an MTR graph it cannot verify. Instead: a speed
# model. Research-backed HK door-to-door public-transport averages run about
# 18–22 km/h *including* walking and waiting. We separate those out (see
# below), so the travelling portion takes the top of that range.

TRANSIT_ACCESS_OVERHEAD_MIN = 10.0
# Walk to the stop/station, wait for the vehicle, walk from the stop to A&E,
# summed over both ends of the trip. Held separate from the line-haul speed so
# short trips are not flattered by an average built from long ones.

HA_LIVE_TTL_S = 120.0
# The Hospital Authority feed itself updates every 15 minutes. Two minutes of
# caching collapses 18 per-hospital fetches into one for a ranking call.

MIN_FORECAST_OBSERVATIONS = 5
# Mirrors engine.score_reliability's own threshold.

FERRY_ONLY_HOSPITALS = {
    "St John Hospital": (
        "St John Hospital is on Cheung Chau, a car-free island with no road "
        "link to the rest of Hong Kong. Reaching it means a scheduled ferry "
        "from Central, so neither the road-traffic model nor the transit "
        "speed model can produce an honest travel time: the answer depends "
        "on the sailing timetable, which this tool does not have. If you are "
        "already on Cheung Chau, this is your local A&E and the walk is short."
    ),
}
# Straight-line distance times a road-circuity factor quietly assumes a road
# exists. For this one hospital it does not, and the model would otherwise
# advertise a 20-minute drive to an island. We refuse to produce a number
# rather than produce a wrong one.


# ---------------------------------------------------------------------------
# Basis vocabulary. The UI switches on these strings, and they are the contract.
# ---------------------------------------------------------------------------

class TravelBasis:
    """How a travel estimate was actually computed. Never guess, read this."""

    LIVE_CORRIDOR = "live_corridor"
    # Live detector speeds within CORRIDOR_WIDTH_KM of the origin→hospital line.

    LIVE_CORRIDOR_WIDENED = "live_corridor_widened"
    # Same, after one widening to CORRIDOR_WIDTH_WIDENED_KM.

    LIVE_TERRITORY_AVG = "live_territory_avg"
    # No detectors near this route, so this is the territory-wide average of
    # all valid detectors. Live, but not route-specific.

    STATIC_FALLBACK = "static_fallback"
    # No usable live traffic at all. Fixed FALLBACK_CAR_SPEED_KPH.

    TRANSIT_MODEL = "transit_model"
    # Speed model. No routing API was consulted, because none exists for free.

    NOT_ROAD_REACHABLE = "not_road_reachable"
    # No road route exists (island A&E). travel_minutes is None, on purpose.

    STALE_SUFFIX = "_stale"
    # Appended to any live_* basis when the snapshot could not be refreshed and
    # we are serving the last good one. traffic_live is false in that case.


class ForecastBasis:
    """Which slice of history the wait forecast came from."""

    HOUR_BUCKET = "hour_bucket"          # exact hospital × triage × hour-of-week
    HOUR_WINDOW = "hour_window"          # ±1 hour, exact bucket too thin
    POOLED_ALL_HOURS = "pooled_all_hours"  # all hours, engine's `pooled` flag
    UNAVAILABLE = "unavailable"          # no forecast, see `reason`


# ---------------------------------------------------------------------------
# Traffic snapshot
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Detector:
    detector_id: str
    lat: float
    lon: float
    speed_kph: float      # mean of that detector's valid lanes
    lanes_valid: int


@dataclass
class TrafficSnapshot:
    detectors: list[Detector]
    observed_at: str | None          # e.g. '2026-08-10 14:36:30' (feed clock)
    fetched_at: float                # epoch seconds, our clock
    stale: bool = False              # served past its TTL after a failed refresh
    error: str | None = None         # why the last refresh failed, if it did

    @property
    def territory_avg_speed(self) -> float | None:
        if not self.detectors:
            return None
        return round(
            sum(d.speed_kph for d in self.detectors) / len(self.detectors), 1
        )

    @property
    def age_s(self) -> float:
        return time.time() - self.fetched_at


@dataclass
class TravelEstimate:
    minutes: float
    mode: str
    basis: str
    is_estimate: bool
    assumption: str
    straight_km: float
    road_km: float
    effective_speed_kph: float | None
    detectors_used: int
    traffic_live: bool


# --- internal caches ---------------------------------------------------------

_coord_cache: dict[str, tuple[float, float]] | None = None
_snapshot_cache: TrafficSnapshot | None = None
_snapshot_error: str | None = None
_snapshot_failed_at: float | None = None   # epoch of last failed fetch
_ha_cache: tuple[float, dict[str, dict[str, float | None]]] | None = None
_bucket_cache: tuple[float, dict] | None = None


def _http_get(url: str, timeout: float = HTTP_TIMEOUT_S) -> bytes | None:
    """Fetch bytes, or None. Never raises, since a dead feed is a normal condition."""
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "AE-Wait-Times-Routing/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Source 1: detector coordinates (disk-cached)
# ---------------------------------------------------------------------------

def load_detector_coords(force_refresh: bool = False) -> dict[str, tuple[float, float]]:
    """AID_ID_Number -> (lat, lon). Disk-cached, {} if unavailable.

    Refresh policy: use the on-disk copy unless it is missing or older than
    COORD_CSV_MAX_AGE_DAYS. If the network fetch fails we keep the old copy
    however old it is: stale coordinates for fixed infrastructure are far
    better than no traffic at all.
    """
    global _coord_cache
    if _coord_cache is not None and not force_refresh:
        return _coord_cache

    raw: bytes | None = None
    fresh_enough = (
        COORD_CACHE_PATH.exists()
        and (time.time() - COORD_CACHE_PATH.stat().st_mtime)
        < COORD_CSV_MAX_AGE_DAYS * 86400
    )
    if fresh_enough and not force_refresh:
        try:
            raw = COORD_CACHE_PATH.read_bytes()
        except OSError:
            raw = None

    if raw is None:
        raw = _http_get(COORD_CSV_URL)
        if raw is not None:
            try:
                DATA.mkdir(parents=True, exist_ok=True)
                COORD_CACHE_PATH.write_bytes(raw)
            except OSError:
                pass  # cache write is an optimisation, not a requirement
        elif COORD_CACHE_PATH.exists():
            try:
                raw = COORD_CACHE_PATH.read_bytes()  # stale beats nothing
            except OSError:
                raw = None

    if raw is None:
        _coord_cache = {}
        return _coord_cache

    coords: dict[str, tuple[float, float]] = {}
    try:
        text = raw.decode("utf-8-sig", errors="replace")
        for row in csv.DictReader(io.StringIO(text)):
            aid = (row.get("AID_ID_Number") or "").strip()
            try:
                lat = float(row["Latitude"])
                lon = float(row["Longitude"])
            except (TypeError, ValueError, KeyError):
                continue
            if aid:
                coords[aid] = (lat, lon)
    except Exception:
        coords = {}

    _coord_cache = coords
    return coords


# ---------------------------------------------------------------------------
# Source 2: live per-detector speeds (memory-cached, short TTL)
# ---------------------------------------------------------------------------

def _parse_speed_xml(raw: bytes) -> tuple[list[tuple[str, float, int]], str | None]:
    """-> ([(detector_id, mean_valid_lane_speed, n_valid_lanes)], period_from).

    Uses the LAST period in the document (the feed carries two 30-second
    periods, and the last one is the most recent). Only <valid>Y</valid> lanes
    are counted: an invalid lane is a broken loop, not a free-flowing road.
    """
    root = ET.fromstring(raw)
    date = (root.findtext("date") or "").strip()
    periods = root.findall(".//period")
    if not periods:
        return [], None
    period = periods[-1]
    period_from = (period.findtext("period_from") or "").strip()
    observed_at = f"{date} {period_from}".strip() or None

    out: list[tuple[str, float, int]] = []
    for det in period.findall(".//detector"):
        did = (det.findtext("detector_id") or "").strip()
        if not did:
            continue
        speeds: list[float] = []
        for lane in det.findall(".//lane"):
            if (lane.findtext("valid") or "").strip().upper() != "Y":
                continue
            try:
                speeds.append(float((lane.findtext("speed") or "").strip()))
            except ValueError:
                continue
        if speeds:
            out.append((did, sum(speeds) / len(speeds), len(speeds)))
    return out, observed_at


def get_traffic_snapshot(force_refresh: bool = False) -> TrafficSnapshot | None:
    """Current detector speeds joined to coordinates. Never raises.

    Returns None only when we have no usable data at all (no live fetch and no
    snapshot young enough to serve). A returned snapshot with .stale == True is
    real data that we could not refresh, and callers must surface that.
    """
    global _snapshot_cache, _snapshot_error, _snapshot_failed_at

    cached = _snapshot_cache
    if cached is not None and not force_refresh and cached.age_s < XML_CACHE_TTL_S:
        return cached

    def _degrade() -> TrafficSnapshot | None:
        """Serve the last good snapshot if it is young enough, else nothing."""
        if cached is not None and cached.age_s < STALE_SERVE_MAX_S:
            cached.stale = True
            cached.error = _snapshot_error
            return cached
        return None

    # Circuit breaker: don't re-dial a feed we just failed to reach.
    if (
        not force_refresh
        and _snapshot_failed_at is not None
        and time.time() - _snapshot_failed_at < FAILED_RETRY_BACKOFF_S
    ):
        return _degrade()

    raw = _http_get(SPEED_XML_URL)
    if raw is None:
        _snapshot_error = f"traffic feed unreachable ({SPEED_XML_URL})"
        _snapshot_failed_at = time.time()
        return _degrade()

    try:
        readings, observed_at = _parse_speed_xml(raw)
    except Exception as exc:
        _snapshot_error = f"traffic feed unparseable: {type(exc).__name__}"
        _snapshot_failed_at = time.time()
        return _degrade()

    coords = load_detector_coords()
    detectors = [
        Detector(did, coords[did][0], coords[did][1], speed, n)
        for did, speed, n in readings
        if did in coords
    ]
    if not detectors:
        # Either the coordinate CSV is missing or the join failed entirely.
        # Live speeds we cannot place on a map are useless for corridors.
        _snapshot_error = (
            "no detector coordinates available" if not coords
            else "live speeds did not join to any known detector"
        )
        _snapshot_failed_at = time.time()
        return _degrade()

    _snapshot_error = None
    _snapshot_failed_at = None
    _snapshot_cache = TrafficSnapshot(
        detectors=detectors, observed_at=observed_at, fetched_at=time.time()
    )
    return _snapshot_cache


def traffic_status() -> dict:
    """Honest one-glance answer to 'is live traffic actually in play?'."""
    snap = get_traffic_snapshot()
    if snap is None:
        return {
            "live": False,
            "detectors_used": 0,
            "observed_at": None,
            "territory_avg_speed": None,
            "message": (
                (_snapshot_error or "traffic feed unavailable")
                + f", so car estimates fall back to a fixed "
                  f"{FALLBACK_CAR_SPEED_KPH:.0f} km/h assumption"
            ),
        }
    if snap.stale:
        return {
            "live": False,
            "detectors_used": len(snap.detectors),
            "observed_at": snap.observed_at,
            "territory_avg_speed": snap.territory_avg_speed,
            "message": (
                f"serving the last good snapshot, {snap.age_s / 60:.0f} min old "
                f"({snap.error or 'refresh failed'})"
            ),
        }
    return {
        "live": True,
        "detectors_used": len(snap.detectors),
        "observed_at": snap.observed_at,
        "territory_avg_speed": snap.territory_avg_speed,
        "message": (
            f"live: {len(snap.detectors)} Transport Department detectors, "
            f"observed {snap.observed_at}, territory average "
            f"{snap.territory_avg_speed} km/h"
        ),
    }


# ---------------------------------------------------------------------------
# Corridor geometry
# ---------------------------------------------------------------------------

_KM_PER_DEG_LAT = 110.574
_KM_PER_DEG_LON_EQ = 111.320


def _to_local_km(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    """Equirectangular projection to km around (lat0, lon0).

    Hong Kong spans ~50 km, and over that span this approximation is accurate
    to well under the corridor widths we care about.
    """
    x = (lon - lon0) * _KM_PER_DEG_LON_EQ * math.cos(math.radians(lat0))
    y = (lat - lat0) * _KM_PER_DEG_LAT
    return x, y


def _corridor_detectors(
    snap: TrafficSnapshot,
    olat: float, olon: float, dlat: float, dlon: float,
    width_km: float,
) -> list[Detector]:
    """Detectors whose perpendicular distance to the origin→dest line is within
    width_km, and whose projection falls between the endpoints (± margin).

    If origin and destination coincide, this degenerates to a radius search
    around the point, which is the sensible reading of "traffic near you".
    """
    ax, ay = 0.0, 0.0
    bx, by = _to_local_km(dlat, dlon, olat, olon)
    abx, aby = bx - ax, by - ay
    ab2 = abx * abx + aby * aby

    hits: list[Detector] = []
    for d in snap.detectors:
        px, py = _to_local_km(d.lat, d.lon, olat, olon)
        if ab2 <= 1e-9:
            perp = math.hypot(px, py)
        else:
            t = (px * abx + py * aby) / ab2
            if t < -CORRIDOR_ENDPOINT_MARGIN or t > 1 + CORRIDOR_ENDPOINT_MARGIN:
                continue
            perp = math.hypot(px - t * abx, py - t * aby)
        if perp <= width_km:
            hits.append(d)
    return hits


def _effective_speed(detectors: list[Detector]) -> float:
    """Harmonic mean of detector speeds, clamped.

    Harmonic, not arithmetic: travel *time* over equal-length segments adds, so
    the time-correct average of speeds is the harmonic mean. One 10 km/h jam
    hurts your arrival time far more than one 90 km/h stretch helps it, and the
    arithmetic mean hides exactly that.
    """
    speeds = [max(d.speed_kph, EFFECTIVE_SPEED_FLOOR_KPH) for d in detectors]
    hm = len(speeds) / sum(1.0 / s for s in speeds)
    return min(hm, EFFECTIVE_SPEED_CAP_KPH)


# ---------------------------------------------------------------------------
# travel_estimate
# ---------------------------------------------------------------------------

def travel_estimate(
    origin_lat: float, origin_lon: float,
    dest_lat: float, dest_lon: float,
    mode: str = "car",
) -> TravelEstimate:
    """Model how long it takes to get from origin to destination.

    Never raises, never returns an unlabelled number. `basis` tells you which
    of the fallback rungs actually ran, and `assumption` names every constant.
    """
    straight_km = haversine(origin_lat, origin_lon, dest_lat, dest_lon)
    road_km = straight_km * ROAD_CIRCUITY_FACTOR

    if mode == "transit":
        minutes = (road_km / TRANSIT_LINE_HAUL_KPH) * 60 + TRANSIT_ACCESS_OVERHEAD_MIN
        return TravelEstimate(
            minutes=round(minutes, 1),
            mode="transit",
            basis=TravelBasis.TRANSIT_MODEL,
            is_estimate=True,
            assumption=(
                "Modelled, not routed: Hong Kong has no free point-to-point "
                "public-transport routing API, so this does not know which MTR "
                "line or bus you would take. It assumes "
                f"{straight_km:.1f} km straight-line × {ROAD_CIRCUITY_FACTOR} "
                f"circuity = {road_km:.1f} km travelled at "
                f"{TRANSIT_LINE_HAUL_KPH:.0f} km/h (the top of the 18–22 km/h "
                "range reported for Hong Kong door-to-door public transport), "
                f"plus a flat {TRANSIT_ACCESS_OVERHEAD_MIN:.0f} min for walking "
                "to and from stops and waiting. No live transit data exists in "
                "this figure."
            ),
            straight_km=round(straight_km, 2),
            road_km=round(road_km, 2),
            effective_speed_kph=TRANSIT_LINE_HAUL_KPH,
            detectors_used=0,
            traffic_live=False,
        )

    # --- car ----------------------------------------------------------------
    snap = get_traffic_snapshot()
    stale_suffix = TravelBasis.STALE_SUFFIX if (snap and snap.stale) else ""
    live = bool(snap and not snap.stale)

    detectors: list[Detector] = []
    basis = TravelBasis.STATIC_FALLBACK
    width_used: float | None = None

    if snap is not None:
        # Rung 1: detectors along the corridor.
        detectors = _corridor_detectors(
            snap, origin_lat, origin_lon, dest_lat, dest_lon, CORRIDOR_WIDTH_KM
        )
        if len(detectors) >= MIN_CORRIDOR_DETECTORS:
            basis = TravelBasis.LIVE_CORRIDOR + stale_suffix
            width_used = CORRIDOR_WIDTH_KM
        else:
            # Rung 2: widen once.
            detectors = _corridor_detectors(
                snap, origin_lat, origin_lon, dest_lat, dest_lon,
                CORRIDOR_WIDTH_WIDENED_KM,
            )
            if len(detectors) >= MIN_CORRIDOR_DETECTORS:
                basis = TravelBasis.LIVE_CORRIDOR_WIDENED + stale_suffix
                width_used = CORRIDOR_WIDTH_WIDENED_KM
            else:
                # Rung 3: territory-wide average of every valid detector.
                detectors = list(snap.detectors)
                if detectors:
                    basis = TravelBasis.LIVE_TERRITORY_AVG + stale_suffix
                else:
                    detectors = []

    if detectors:
        speed = _effective_speed(detectors)
        capped = speed >= EFFECTIVE_SPEED_CAP_KPH - 1e-9
        minutes = (road_km / speed) * 60 + CAR_ACCESS_OVERHEAD_MIN
        if basis.startswith(TravelBasis.LIVE_TERRITORY_AVG):
            where = (
                f"no detectors lie within {CORRIDOR_WIDTH_WIDENED_KM:.0f} km of "
                f"this route, so this uses the territory-wide average of all "
                f"{len(detectors)} valid detectors, live, but not specific to "
                "your journey"
            )
        else:
            where = (
                f"{len(detectors)} Transport Department detectors within "
                f"{width_used:.0f} km of the straight line from you to the "
                "hospital"
            )
        freshness = (
            f"last good reading {snap.age_s / 60:.0f} min old (refresh failed)"
            if snap and snap.stale
            else f"observed {snap.observed_at}" if snap else "unknown"
        )
        assumption = (
            f"Estimated from live traffic: {where}, {freshness}. "
            f"Their harmonic-mean speed is {speed:.0f} km/h"
            + (
                f" (capped at {EFFECTIVE_SPEED_CAP_KPH:.0f} km/h because "
                "detectors sit on expressways and trunk roads, not the surface "
                "streets at either end)" if capped else ""
            )
            + f". Distance is {straight_km:.1f} km straight-line × "
            f"{ROAD_CIRCUITY_FACTOR} road-circuity factor = {road_km:.1f} km, "
            f"plus {CAR_ACCESS_OVERHEAD_MIN:.0f} min to park and walk in. "
            "Not a routed journey: no turn-by-turn network was consulted, and "
            "cross-harbour trips will be understated."
        )
    else:
        speed = FALLBACK_CAR_SPEED_KPH
        minutes = (road_km / speed) * 60 + CAR_ACCESS_OVERHEAD_MIN
        assumption = (
            "No live traffic available "
            f"({_snapshot_error or 'traffic feed unavailable'}). Falls back to a "
            f"fixed {FALLBACK_CAR_SPEED_KPH:.0f} km/h urban average over "
            f"{straight_km:.1f} km straight-line × {ROAD_CIRCUITY_FACTOR} "
            f"circuity = {road_km:.1f} km, plus "
            f"{CAR_ACCESS_OVERHEAD_MIN:.0f} min to park and walk in. Nothing "
            "about current road conditions is reflected in this number."
        )
        live = False

    return TravelEstimate(
        minutes=round(minutes, 1),
        mode="car",
        basis=basis,
        is_estimate=True,
        assumption=assumption,
        straight_km=round(straight_km, 2),
        road_km=round(road_km, 2),
        effective_speed_kph=round(speed, 1),
        detectors_used=len(detectors),
        traffic_live=live,
    )


# ---------------------------------------------------------------------------
# Forecast helpers
# ---------------------------------------------------------------------------

def _buckets() -> dict:
    """Hour-of-week buckets, cached against the corpus file's mtime.

    The corpus is 28 MB, and rebuilding it per hospital per request would
    dominate the response time.
    """
    global _bucket_cache
    try:
        mtime = (DATA / "ae_corpus.json").stat().st_mtime
    except OSError:
        mtime = 0.0
    if _bucket_cache is not None and _bucket_cache[0] == mtime:
        return _bucket_cache[1]
    buckets = build_buckets(load_corpus())
    _bucket_cache = (mtime, buckets)
    return buckets


def _live_published() -> dict[str, dict[str, float | None]]:
    """{hospital: {triage: minutes}} from ONE fetch of the HA feed.

    engine._fetch_live_triage re-downloads the whole feed per hospital, so
    ranking 18 hospitals that way is 18 HTTPS round-trips. Returns {} if
    unreachable, and callers then pass published=None and the engine reports
    'no_live_data'.
    """
    global _ha_cache
    now = time.time()
    if _ha_cache is not None and now - _ha_cache[0] < HA_LIVE_TTL_S:
        return _ha_cache[1]

    raw = _http_get(LIVE_URL)
    out: dict[str, dict[str, float | None]] = {}
    if raw is not None:
        try:
            import json
            data = json.loads(raw)
            for entry in data.get("waitTime", []):
                name = entry.get("hospName")
                if not name:
                    continue
                out[name] = {
                    t: _parse_live_str(entry.get(f"{t}p50", ""))
                    for t in ("t1", "t2", "t3", "t45")
                }
        except Exception:
            out = {}
    _ha_cache = (now, out)
    return out


def live_published_minutes() -> dict[str, dict[str, float | None]]:
    """Public accessor for the cached HA live feed: {hospital: {triage: mins}}.

    Empty dict means the feed was unreachable, and callers must treat that as
    'no live data', never as zero.
    """
    return _live_published()


def _forecast_basis(hospital: str, triage: str, how: int, buckets: dict,
                    pooled: bool) -> str:
    if pooled:
        return ForecastBasis.POOLED_ALL_HOURS
    b = buckets.get((hospital, triage, "p50", how))
    if b is not None and b.n >= MIN_FORECAST_OBSERVATIONS:
        return ForecastBasis.HOUR_BUCKET
    return ForecastBasis.HOUR_WINDOW


def _window_forecast(hospital: str, triage: str, how: int, buckets: dict):
    """Reimplementation of engine.score_reliability's ±1-hour window branch.

    WHY THIS EXISTS: engine.score_reliability raises UnboundLocalError on that
    branch (`pooled` is assigned in the exact-bucket and all-hours branches but
    not the window branch), which fires for ~2% of hospital × triage × hour
    combinations. engine.py is owned by another agent and must not be edited
    from here, so routing catches the error and recomputes the same numbers.
    Delete this the moment the engine sets `pooled = False` in that branch.

    Returns (median, p25, p75, n) or None.
    """
    from stats import median as _median, quantile as _quantile
    vals: list[float] = []
    for offset in (-1, 0, 1):
        b = buckets.get((hospital, triage, "p50", (how + offset) % 168))
        if b:
            vals.extend(b.values)
    if len(vals) < MIN_FORECAST_OBSERVATIONS:
        return None
    return (
        float(_median(vals)),
        float(_quantile(vals, 0.25)),
        float(_quantile(vals, 0.75)),
        len(vals),
    )


def _fmt_interval(p25: float | None, p75: float | None) -> str:
    def f(m: float | None) -> str:
        if m is None:
            return "?"
        if m < 60:
            return f"{round(m)} min"
        h = m / 60
        return f"{h:.1f} hr" if h < 2 else f"{round(h * 2) / 2:.1f} hr"
    return f"{f(p25)} – {f(p75)}"


# ---------------------------------------------------------------------------
# rank_hospitals
# ---------------------------------------------------------------------------

# The row-level `tail` when there is no TailEstimate at all: this happens
# only when the row has no p50 forecast either, so there is no median for a
# tail to be the tail of. Same keys as TailEstimate.as_dict(), so the frontend
# reads one shape and never has to null-check the object itself. Built through
# TailEstimate so the two can never drift apart.
def _no_tail_dict() -> dict:
    return TailEstimate(
        hospital="", triage="", available=False,
        reason="no forecast for this hospital at this hour, so there is no "
               "median for a tail to accompany",
    ).as_dict()


@dataclass
class RankedHospital:
    hospital: str
    lat: float
    lon: float
    distance_km: float | None
    travel_minutes: float | None
    travel_basis: str | None
    travel_is_estimate: bool
    travel_assumption: str | None
    forecast_median: float | None
    forecast_p25: float | None
    forecast_p75: float | None
    forecast_interval: str | None
    forecast_basis: str
    verdict: str | None
    pooled: bool
    n_observations: int
    published_minutes: float | None
    delta_minutes: float | None
    total_minutes: float | None
    reason: str | None = None       # why forecast/travel is missing, if it is
    # Minutes outside this department's own p25-p75 band, 0.0 when inside it.
    # The badge, the table cell and the chart annotation all render from THIS
    # one number, so they cannot disagree the way they did when each derived
    # its own.
    excess_minutes: float | None = None
    # HA's own p95 series for this hospital-hour, resolved on the same ladder
    # as the p50 forecast above. None when the p95 series is too thin, or when
    # there is no p50 forecast to hang it off. Never derived from the p50.
    tail: TailEstimate | None = None

    def as_dict(self) -> dict:
        return {
            "hospital": self.hospital,
            "lat": self.lat,
            "lon": self.lon,
            "distance_km": self.distance_km,
            "travel_minutes": self.travel_minutes,
            "travel_basis": self.travel_basis,
            "travel_is_estimate": self.travel_is_estimate,
            "travel_assumption": self.travel_assumption,
            "forecast_median": self.forecast_median,
            "forecast_p25": self.forecast_p25,
            "forecast_p75": self.forecast_p75,
            "forecast_interval": self.forecast_interval,
            "forecast_basis": self.forecast_basis,
            "verdict": self.verdict,
            "pooled": self.pooled,
            "n_observations": self.n_observations,
            "published_minutes": self.published_minutes,
            "delta_minutes": self.delta_minutes,
            "excess_minutes": self.excess_minutes,
            "total_minutes": self.total_minutes,
            "reason": self.reason,
            # HA's published p95 ("majority seen within") for THIS row's
            # hospital-hour, in the same shape as the response's top-level
            # `tail`. Per-row rather than top-level-only because the UI's
            # answer card is driven by a row, and a tail rendered from the top
            # level onto a different row's name would attach one department's
            # long wait to another department's card.
            #
            # Full object, not a bare median: the project's invariant is that
            # no unqualified wait number may appear, so a lone median with no
            # interval, no basis and no observation count is unusable.
            "tail": self.tail.as_dict() if self.tail else _no_tail_dict(),
            # Retained scalar alias. Always equals tail["p95_median"].
            "tail_p95_median": self.tail.p95_median if self.tail else None,
        }


DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday",
        "Friday", "Saturday", "Sunday"]


def travel_for_hospital(
    origin: tuple[float, float], hospital: str, lat: float, lon: float, mode: str,
) -> tuple[TravelEstimate | None, str | None]:
    """travel_estimate, but aware that one hospital has no road to it.

    Returns (estimate, reason). Exactly one of them is None.
    """
    if hospital in FERRY_ONLY_HOSPITALS:
        return None, FERRY_ONLY_HOSPITALS[hospital]
    return travel_estimate(origin[0], origin[1], lat, lon, mode), None


def rank_hospitals(
    origin: tuple[float, float] | None,
    mode: str,
    triage: str,
    day: str,
    hour: int,
    *,
    live_enabled: bool = True,
) -> list[RankedHospital]:
    """Every hospital, scored by forecast wait + travel time, best first.

    origin=None is a legitimate state, not an error: we do NOT invent a
    location. The ranking then falls back to wait time alone, every travel
    field is None, and the caller is expected to tell the user that distance
    was not considered.

    Hospitals whose forecast cannot be computed are STILL RETURNED, with
    forecast fields None, forecast_basis='unavailable', a `reason` string, and
    total_minutes None. They sort last. Dropping them would quietly rewrite the
    map, and ranking them at 0 minutes would recommend them.

    `live_enabled=False` says the requested `day`/`hour` is not the current
    Hong Kong hour, so the Hospital Authority's live board holds no figure
    about it. The feed is then NOT fetched (not fetched-and-discarded), every
    row's `published_minutes` and `delta_minutes` stay None, and any row that
    has a forecast gets verdict 'not_comparable'. That value is distinct from
    'no_live_data', which means the hour IS now and the feed could not be
    reached: a different state, with a different remedy, and the UI must be
    able to tell them apart.
    """
    day_idx = DAYS.index(day) if day in DAYS else 0
    how = day_idx * 24 + hour
    buckets = _buckets()
    published_all = _live_published() if live_enabled else {}

    rows: list[RankedHospital] = []
    for name, (lat, lon) in HOSPITAL_COORDS.items():
        published = (published_all.get(name) or {}).get(triage)

        median = p25 = p75 = None
        verdict: str | None = None
        pooled = False
        n_obs = 0
        delta: float | None = None
        excess: float | None = None
        fbasis = ForecastBasis.UNAVAILABLE
        reason: str | None = None

        try:
            score = score_reliability(name, triage, how, published, buckets)
        except Exception:
            score = None
            win = _window_forecast(name, triage, how, buckets)
            if win is not None:
                median, p25, p75, n_obs = win
                pooled = False
                fbasis = ForecastBasis.HOUR_WINDOW
                if published is not None:
                    delta = published - median
                    # The SAME rule the main path uses, imported rather than
                    # restated. This branch used to carry its own copy of the
                    # flat ±15 thresholds, so a fix to the rule would have been
                    # silently ignored on exactly the rows that fell back here.
                    verdict, excess = score_normality(published, p25, p75)
                else:
                    verdict = "no_live_data"
            else:
                reason = "forecast engine could not score this hour"

        if score is not None:
            median = score.forecast_median
            p25 = score.forecast_p25
            p75 = score.forecast_p75
            verdict = score.verdict
            pooled = score.pooled
            n_obs = score.n_observations
            delta = score.delta_minutes
            excess = score.excess_minutes
            fbasis = _forecast_basis(name, triage, how, buckets, pooled)
        elif median is None and reason is None:
            reason = (
                f"fewer than {MIN_FORECAST_OBSERVATIONS} historical "
                f"observations for {triage} at this hour"
            )

        if not live_enabled and median is not None:
            # score_reliability sees published=None and calls that
            # 'no_live_data', which here would be a lie: the feed is fine, it
            # simply publishes nothing about this hour. Say the true thing.
            verdict = "not_comparable"
            # No comparison means no distance-from-normal either. Leaving a
            # stale excess here would let the UI render "N min above the range"
            # beside a card that has just refused to compare anything.
            excess = None

        # HA's p95 tail, on the same ladder rung (or coarser) as the p50 above.
        # No p50 forecast means no tail: a tail with no median beside it has
        # nothing to be the tail *of*.
        tail: TailEstimate | None = None
        if median is not None:
            floor = score.basis if score is not None else (
                "hour_window" if fbasis == ForecastBasis.HOUR_WINDOW else None
            )
            tail = score_tail(name, triage, how, buckets, floor_basis=floor)

        if origin is None:
            rows.append(RankedHospital(
                hospital=name, lat=lat, lon=lon,
                distance_km=None,
                travel_minutes=None, travel_basis=None,
                travel_is_estimate=False, travel_assumption=None,
                forecast_median=median, forecast_p25=p25, forecast_p75=p75,
                forecast_interval=_fmt_interval(p25, p75) if median is not None else None,
                forecast_basis=fbasis, verdict=verdict, pooled=pooled,
                n_observations=n_obs, published_minutes=published,
                delta_minutes=delta, excess_minutes=excess,
                total_minutes=median,   # wait only: no origin, no travel time
                reason=reason,
                tail=tail,
            ))
            continue

        tr, no_road = travel_for_hospital(origin, name, lat, lon, mode)
        if tr is None:
            # No road route: report the wait honestly, refuse the travel time,
            # and keep it out of the ranked-by-total ordering.
            rows.append(RankedHospital(
                hospital=name, lat=lat, lon=lon,
                distance_km=round(haversine(origin[0], origin[1], lat, lon), 2),
                travel_minutes=None,
                travel_basis=TravelBasis.NOT_ROAD_REACHABLE,
                travel_is_estimate=False, travel_assumption=no_road,
                forecast_median=median, forecast_p25=p25, forecast_p75=p75,
                forecast_interval=_fmt_interval(p25, p75) if median is not None else None,
                forecast_basis=fbasis, verdict=verdict, pooled=pooled,
                n_observations=n_obs, published_minutes=published,
                delta_minutes=delta, excess_minutes=excess,
                total_minutes=None,
                reason=no_road if reason is None else f"{reason}, {no_road}",
                tail=tail,
            ))
            continue

        rows.append(RankedHospital(
            hospital=name, lat=lat, lon=lon,
            distance_km=round(haversine(origin[0], origin[1], lat, lon), 2),
            travel_minutes=tr.minutes, travel_basis=tr.basis,
            travel_is_estimate=tr.is_estimate, travel_assumption=tr.assumption,
            forecast_median=median, forecast_p25=p25, forecast_p75=p75,
            forecast_interval=_fmt_interval(p25, p75) if median is not None else None,
            forecast_basis=fbasis, verdict=verdict, pooled=pooled,
            n_observations=n_obs, published_minutes=published,
            delta_minutes=delta, excess_minutes=excess,
            total_minutes=round(median + tr.minutes, 1) if median is not None else None,
            reason=reason,
            tail=tail,
        ))

    # Unscoreable hospitals sort last: never presented as the fast option.
    rows.sort(key=lambda r: (r.total_minutes is None, r.total_minutes or 0.0))
    return rows
