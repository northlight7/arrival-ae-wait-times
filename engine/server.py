"""Thin Flask API around the A&E engine. One endpoint, then static files."""

from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import engine as _engine
from engine import query, load_corpus, HOSPITAL_COORDS
from routing import (
    live_published_minutes,
    rank_hospitals,
    traffic_status,
)

# --- Performance shim, not a behaviour change --------------------------------
# engine.query() calls engine._fetch_live_triage() once per hospital, and each
# call downloads the ENTIRE Hospital Authority live JSON. That is 19 sequential
# HTTPS round-trips per request and measured at ~14 s locally.
#
# This replaces it with a lookup into routing's cached parse of the SAME feed,
# parsed by the SAME engine._parse_live_str. Same numbers, one download, ~120 s
# TTL against a feed that only updates every 15 minutes. Failure still yields
# None, so engine still reports verdict='no_live_data' rather than inventing a
# figure. Remove this the moment engine.py fetches the feed once itself.
def _cached_fetch_live_triage(hospital: str, triage: str) -> float | None:
    table = live_published_minutes()
    if not table:
        return None
    return (table.get(hospital) or {}).get(triage)


_engine._fetch_live_triage = _cached_fetch_live_triage

VALID_MODES = ("car", "transit")

# Hong Kong's bounding box, generously drawn. An origin outside it is not
# rejected, since the user might genuinely be on a boat or just over the
# border, but it is flagged, because every distance in the response would
# then be a straight line across territory this tool has no traffic data for.
HK_BBOX = (22.1, 22.65, 113.80, 114.50)  # lat_min, lat_max, lon_min, lon_max

app = Flask(
    __name__,
    static_folder=str(Path(__file__).resolve().parent.parent / "frontend" / "dist"),
    static_url_path="",
)

HERE = Path(__file__).resolve().parent
CORPUS = {}
_CORPUS_MTIME = None


def _ensure_corpus():
    """Load the corpus, and reload it if the file has changed on disk.

    The previous version cached on first use and never looked again. A seeder
    run while the server was up therefore had no effect until someone restarted
    it, and worse, /api/corpus-stats kept reporting the old day count, so the
    page told readers it was built on far less evidence than it actually was.
    This does a cheap mtime check on each call: the parse only repeats when
    the file moves.
    """
    global CORPUS, _CORPUS_MTIME
    from engine import CORPUS_PATH
    try:
        mtime = CORPUS_PATH.stat().st_mtime
    except OSError:
        mtime = None
    if not CORPUS or mtime != _CORPUS_MTIME:
        CORPUS = load_corpus()
        _CORPUS_MTIME = mtime


@app.get("/api/hospitals")
def hospitals():
    return jsonify([
        {"name": name, "lat": lat, "lon": lon}
        for name, (lat, lon) in HOSPITAL_COORDS.items()
    ])


@app.get("/api/dates")
def dates():
    _ensure_corpus()
    return jsonify(sorted(CORPUS.get("snapshots", {}).keys()))


@app.post("/api/query")
def api_query():
    body = request.get_json(force=True) or {}
    hospital = body.get("hospital", "")
    triage = body.get("triage", "t3")
    day = body.get("day", "Monday")
    hour_raw = body.get("hour", 14)

    if not hospital:
        return jsonify({"error": "hospital is required"}), 400

    # Validate day/hour so bogus values don't silently produce wrong answers.
    valid_days = {"Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"}
    if day not in valid_days:
        return jsonify({"error": f"Invalid day: {day}"}), 400
    try:
        hour = int(hour_raw)
    except (TypeError, ValueError):
        return jsonify({"error": f"Invalid hour: {hour_raw}"}), 400
    if hour < 0 or hour > 23:
        return jsonify({"error": f"Hour must be 0–23, got {hour}"}), 400

    # Accept a user-supplied published figure (for testing), but validate it.
    published = body.get("published")
    if published is not None:
        try:
            published = float(published)
        except (TypeError, ValueError):
            return jsonify({"error": f"Invalid published value: {published}"}), 400

    # --- routing inputs -----------------------------------------------------
    mode = body.get("mode", "car")
    if mode not in VALID_MODES:
        return jsonify({
            "error": f"Invalid mode: {mode!r}. Expected one of {list(VALID_MODES)}"
        }), 400

    # origin is optional and may be explicitly null. We never substitute a
    # default location: a fabricated origin would produce confident travel
    # times for a place the user is not.
    origin_raw = body.get("origin")
    origin = None
    if origin_raw is not None:
        if not isinstance(origin_raw, dict):
            return jsonify({
                "error": "Invalid origin: expected {\"lat\": float, \"lon\": float} or null"
            }), 400
        try:
            o_lat = float(origin_raw["lat"])
            o_lon = float(origin_raw["lon"])
        except (KeyError, TypeError, ValueError):
            return jsonify({
                "error": "Invalid origin: lat and lon must both be numbers"
            }), 400
        if not (-90 <= o_lat <= 90) or not (-180 <= o_lon <= 180):
            return jsonify({
                "error": f"Origin out of range: lat={o_lat}, lon={o_lon}"
            }), 400
        origin = (o_lat, o_lon)

    outside_hk = origin is not None and not (
        HK_BBOX[0] <= origin[0] <= HK_BBOX[1]
        and HK_BBOX[2] <= origin[1] <= HK_BBOX[3]
    )

    # --- is the hour being asked about the hour the live board is about? -----
    # Determined once, here, in Asia/Hong_Kong, and threaded through both
    # engine.query and rank_hospitals so the headline and the 18 rows cannot
    # disagree if the request happens to straddle an hour boundary.
    now_day, now_hour = _engine.hk_now_day_hour()
    arrival_is_now = (day == now_day and hour == now_hour)

    result = query(hospital, triage, day, hour, published,
                   arrival_is_now=arrival_is_now)
    if not result.answered:
        return jsonify({
            "error": "Not enough data yet. The corpus is still being built.",
            "hospital": hospital,
        }), 503

    f = result.forecast

    # --- routing layer ------------------------------------------------------
    ranked = rank_hospitals(origin, mode, triage, day, hour,
                            live_enabled=arrival_is_now)
    tstatus = traffic_status()

    # Legacy all_hospitals carried distance measured FROM THE QUERIED HOSPITAL.
    # Keep that meaning available under an unambiguous name, and let the plain
    # `distance_km` mean "from you" only when the user actually gave us an
    # origin. With no origin, `distance_km` keeps its original meaning exactly.
    legacy_distance = {
        row["hospital"]: row.get("distance_km")
        for row in result.all_hospitals_summary
    }

    all_hospitals = []
    for r in ranked:
        d = r.as_dict()
        d["distance_from_origin_km"] = r.distance_km
        d["distance_from_query_hospital_km"] = legacy_distance.get(r.hospital)
        if origin is None:
            d["distance_km"] = legacy_distance.get(r.hospital)
        # Legacy field names the existing frontend already reads.
        d["published"] = r.published_minutes
        d["n"] = r.n_observations
        all_hospitals.append(d)

    # Top-level travel figures describe the hospital that was actually queried.
    mine = next((r for r in ranked if r.hospital == hospital), None)
    travel_minutes = mine.travel_minutes if mine else None
    travel_basis = mine.travel_basis if mine else None
    travel_is_estimate = bool(mine.travel_is_estimate) if mine else False
    travel_assumption = mine.travel_assumption if mine else None
    total_minutes = mine.total_minutes if mine else None

    # --- the p95 tail -------------------------------------------------------
    # HA publishes two estimates per triage band for the same instant: p50
    # ("half of the waiting patients can receive consultation within this
    # time") and p95 ("majority ..."). Until now only p50 was read, so the page
    # showed the middle of the distribution and never its tail.
    #
    # Every row of all_hospitals carries its OWN `tail`, resolved on the same
    # hour-resolution ladder as that row's p50 forecast and floored at that
    # row's own basis, so a tail can never be quoted at a finer resolution than
    # the median printed beside it. If the p95 series is too thin at every
    # rung, `available` is false and every number is null: the p50 is never
    # scaled to manufacture a tail.
    #
    # The top-level `tail` is then LITERALLY the queried hospital's row object,
    # not a second computation of it. Recomputing it here is how the headline
    # and the table would eventually come to disagree. Taking the same dict
    # makes that impossible rather than merely tested.
    _queried_row = next(
        (r for r in all_hospitals if r["hospital"] == hospital), None
    )
    if _queried_row is not None:
        tail = _queried_row["tail"]
    else:
        # The hospital answered a forecast but is absent from the ranking:
        # only reachable if it is missing from HOSPITAL_COORDS. Refuse.
        tail = {
            "p95_median": None, "p95_p25": None, "p95_p75": None,
            "n_observations": 0, "basis": None, "available": False,
            "reason": "this hospital is not in the ranked set, so no p95 "
                      "series was resolved for it",
        }

    if origin is None:
        # No origin means no travel time, so total_minutes is then wait only.
        travel_assumption = (
            "No origin supplied, so no travel time was computed and none was "
            "assumed. Hospitals are ranked by forecast wait alone. The nearest "
            "hospital may still be the faster choice overall."
        )
        total_minutes = mine.forecast_median if mine else None

    # --- may the page compare the published figure against normal? ----------
    # The Hospital Authority's live board publishes exactly one number: its
    # estimate for someone arriving at the moment of publication. It is
    # evidence about the current Hong Kong hour and about no other hour.
    #
    # This endpoint used to fetch that number for every request and score it
    # against whichever hour had been asked for. Measured on a Tuesday at
    # 17:00 with North Lantau's board reading 18 minutes, one reading produced
    # four different "deltas" and four "reliable" verdicts for Tuesday 17:00,
    # Sunday 03:00, Thursday 09:00 and Saturday 23:00. Ruttonjee's delta
    # moved from -9.5 to 0.0 across those hours purely as an artefact of which
    # history it was subtracted from. The page rendered each as an observation.
    #
    # So: outside the current hour there is no comparison, and the response
    # says so in a sentence rather than leaving a blank. Three states, kept
    # distinguishable because they have different remedies:
    #
    #   arrival_is_now and a figure   -> available, compare as before
    #   arrival_is_now, feed down     -> unavailable, verdict 'no_live_data'
    #                                    (come back in a minute)
    #   not arrival_is_now            -> unavailable, verdict 'not_comparable'
    #                                    (no figure exists for that hour, ever)
    label = result.hour_label
    verdict = f.verdict
    delta_direction = f.delta_direction

    if arrival_is_now and f.published_minutes is not None:
        comparison_available = True
        comparison_reason = None
    elif arrival_is_now:
        comparison_available = False
        comparison_reason = (
            "The Hospital Authority's live board could not be reached just "
            "now, so there is no published figure to compare against. The "
            f"range below is still this department's own history at {label}."
        )
        # verdict stays 'no_live_data': the feed, not the hour, is the problem.
    elif published is not None:
        # The caller supplied the figure themselves (the API's testing hook).
        # It is echoed and its delta is still computed, exactly as before:
        # this endpoint does not silently rewrite a caller's own input. But it
        # was not observed at the hour asked about, so it is not a comparison
        # the page may present as one.
        comparison_available = False
        comparison_reason = (
            f"The figure of {published:g} minutes was supplied with this "
            f"request. It was not observed on the Hospital Authority board at "
            f"{label}, since the board only ever publishes a figure for right "
            f"now, so it is not shown as a comparison. The range below is "
            f"still this department's own history at {label}."
        )
        verdict = "not_comparable"
        delta_direction = "supplied figure, not observed at this hour"
    else:
        comparison_available = False
        comparison_reason = (
            "The Hospital Authority publishes one figure for right now, not "
            f"for {label}. Comparing today's board against a different hour "
            "would invent a result, so no comparison is shown for this time. "
            "The range below is still this department's own history at "
            f"{label}."
        )
        verdict = "not_comparable"
        delta_direction = "no published figure exists for this hour"

    if not comparison_available:
        for row in all_hospitals:
            # Rows never carry a caller-supplied figure, so there is nothing
            # to preserve: whatever a row holds here was fetched, and outside
            # the current hour nothing was fetched at all.
            if not arrival_is_now:
                row["verdict"] = "not_comparable"

    return jsonify({
        "arrival_is_now": arrival_is_now,
        "now_day": now_day,
        "now_hour": now_hour,
        "published_comparison": {
            "available": comparison_available,
            "reason": comparison_reason,
        },
        "mode": mode,
        "origin_provided": origin is not None,
        "origin_outside_hong_kong": outside_hk,
        "travel_minutes": travel_minutes,
        "travel_basis": travel_basis,
        "travel_is_estimate": travel_is_estimate,
        "travel_assumption": travel_assumption,
        "total_minutes": total_minutes,
        # traffic_live answers "did live traffic inform THIS number?": false
        # for transit (which never consults traffic), false with no origin, and
        # false when we are serving a stale snapshot. The separate
        # traffic_feed_live reports whether the feed itself is up, which is what
        # /api/traffic-status covers.
        "traffic_live": bool(
            travel_basis
            and travel_basis.startswith("live_")
            and not travel_basis.endswith("_stale")
        ),
        "traffic_feed_live": bool(tstatus["live"]),

        # --- everything below is the original contract, unchanged -----------
        "hospital": result.hospital,
        "triage": result.triage,
        "hour_label": result.hour_label,
        "published_minutes": f.published_minutes,
        "forecast_median": f.forecast_median,
        "forecast_interval": f.interval_str,
        "forecast_p25": f.forecast_p25,
        "forecast_p75": f.forecast_p75,
        "delta_minutes": f.delta_minutes,
        # Minutes outside this department's own p25-p75 band (0.0 when inside).
        # Suppressed with the rest of the comparison when there is nothing to
        # compare against.
        "excess_minutes": f.excess_minutes if comparison_available else None,
        # The LOCALS, not `f.delta_direction` / `f.verdict`.
        #
        # The engine scores the p50 series and knows nothing about whether the
        # published figure it was handed is even about the hour being asked
        # about: that is this layer's decision, made in the block above. Send
        # the engine's own values here and a non-now query reports
        # 'no_live_data' (which invites the reader to try again in a minute for
        # a figure that will never exist for that hour) or, when the caller
        # supplied the figure themselves, a full 'misleading' verdict computed
        # from a comparison this endpoint has just declared unavailable.
        "delta_direction": delta_direction,
        "verdict": verdict,
        "pooled": f.pooled,
        # Finer-grained than `pooled`: exact_hour | hour_window | all_hours.
        #
        # Measured against the corpus as it stands (18 hospitals x {t3, t45} x
        # 168 hours of the week = 6,048 combinations): 100% resolve to
        # exact_hour (6,048 of 6,048). Zero widen to adjacent hours and zero
        # pool the whole week. An earlier comment here claimed 71% / 2.4% / 26%,
        # but those numbers describe no corpus this project has ever shipped.
        #
        # The hour_window and all_hours branches are NOT dead code: they are
        # live and reachable, just not with a corpus this dense. They are what
        # answers a query against a freshly-seeded or partially-backfilled
        # corpus, and the UI's amber "not hour-specific" state hangs off them.
        # tests/golden_matrix.THIN_CASES locks both by deterministically
        # thinning real corpus buckets, so they stay covered even while no live
        # query can reach them. `pooled` stays as-is for compatibility.
        "basis": f.basis,
        "n_observations": f.n_observations,
        "tail": tail,
        "alternatives": [
            {
                "hospital": a.hospital,
                "distance_km": a.distance_km,
                "forecast_median": a.forecast_median,
                "forecast_interval": a.forecast_interval,
                "reliability": a.reliability,
            }
            for a in result.alternatives
        ],
        # Same key, now covering ALL hospitals (none dropped for thin data) and
        # carrying the routing fields. Legacy keys published/n/distance_km are
        # preserved on every entry.
        "all_hospitals": all_hospitals,
    })


@app.get("/api/traffic-status")
def api_traffic_status():
    """Is live traffic actually in play right now? Answer honestly."""
    return jsonify(traffic_status())


@app.get("/api/corpus-stats")
def corpus_stats():
    _ensure_corpus()
    snaps = CORPUS.get("snapshots", {})
    total = sum(len(v) for v in snaps.values())
    hospitals = len(CORPUS.get("hospitals", {}))
    return jsonify({
        "dates": len(snaps),
        "snapshots": total,
        "hospitals": hospitals,
        "observations": total * hospitals,
    })


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.errorhandler(404)
def _spa(_e):
    return send_from_directory(app.static_folder, "index.html")


def main():
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8094
    _ensure_corpus()
    print(f"  A&E Wait Times: http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
