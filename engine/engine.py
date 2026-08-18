"""A&E waiting-time engine.

WHAT THE NUMBERS IN THIS FILE ACTUALLY ARE
------------------------------------------
Read this before writing any copy, comment or chart label about them.

Every value in a bucket is one figure the Hospital Authority *published* at one
moment in time. It is **not** an observed patient outcome. HA's own Data
Specification for Accident and Emergency Waiting Time (the spec for
`aedwtdata2-en.json`, the exact feed this project consumes) defines the fields
verbatim as:

    t3p50  "Estimated A&E waiting time for triage category III (Urgent) cases.
            Half of the waiting patients can receive consultation within this
            time."
            Remark: "Estimated waiting time upon arrival at the A&E department
            in minutes"

    t3p95  "…Majority of the waiting patients can receive consultation within
            this time."
            Remark: "Estimated waiting time upon arrival at the A&E department
            in minutes"

Source: https://www.ha.org.hk/opendata/Data-Specification-for-A&E-Waiting-Time-en.pdf

So the published figure is **prospective**, HA's estimate for a patient
arriving at that moment, not a retrospective record of patients already
treated. An earlier version of this docstring said the opposite ("the Hospital
Authority publishes a number that describes patients *already treated*"). That
was false, and it was carried over from HA's older top-wait feed
(`aedwtdata-en`), which genuinely was retrospective.

Consequently:

* A bucket holds HA's published estimates for one hospital × triage ×
  percentile × hour-of-week, sampled every 15 minutes across the corpus.
* A bucket's p25–p75 is therefore **the middle 50% of published estimates for
  that hospital-hour across history**. It is NOT the middle 50% of patient
  outcomes, and it is materially narrower than patient spread would be.
* The delta against the live figure means "how far today's HA estimate sits
  from this hospital-hour's history", NOT "how far the board is lagging
  reality".

This engine's honest contribution is: it turns HA's single point estimate into
an interval drawn from how that estimate has behaved at this hospital-hour
across the whole corpus, it surfaces HA's own p95 tail alongside its p50, and
it adds travel time and ranking, none of which HA publishes.

THE TWO SERIES
--------------
`p50` and `p95` are both HA's, for the same instant, and both are bucketed here.
`score_reliability` scores the `p50` series (the middle). `score_tail` reports
the `p95` series (the tail) using the *same* hour-resolution fallback ladder, so
the tail is never quoted at a finer resolution than the median beside it. The
tail refuses rather than guesses: it is never derived by scaling the p50.

Architecture
------------
1. SNAPSHOT CORPUS: 15-minute snapshots from data.gov.hk historical archive.
   Each snapshot is an 18-hospital cross-section with triage-level waits.
2. LAST-OBSERVATION BASELINE: what every existing app does, quote the latest
   published figure. This is the competitor we measure against.
3. HOUR-BUCKET MODEL: for each hospital × triage × hour-of-week, compute the
   historical distribution of HA's published estimates. This is the forecast.
4. RELIABILITY DELTA: the signed difference between the last-observation
   baseline and the hour-bucket median. Positive means the published figure
   sits above this hospital-hour's history, negative means below it.
5. TAIL: the same treatment applied to HA's p95 series, so the product can say
   what the bad case looks like instead of only the middle.
6. REROUTING: for any hospital, find the nearest alternatives whose
   hour-bucket median + interval ceiling is lower.

Output contract: every number is an interval. Never a point estimate.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import median as stat_median
from zoneinfo import ZoneInfo

from stats import median as _median, quantile as _quantile

DATA = Path(__file__).resolve().parent.parent / "data"
CORPUS_PATH = DATA / "ae_corpus.json"
CORPUS_GZ_PATH = DATA / "ae_corpus.json.gz"

# The live URL, for the "what the hospital says right now" side of the delta.
LIVE_URL = "https://www.ha.org.hk/opendata/aed/aedwtdata2-en.json"

HOSPITAL_COORDS = {
    "Alice Ho Miu Ling Nethersole Hospital": (22.4585, 114.1758),
    "Caritas Medical Centre": (22.3405, 114.1544),
    "Kwong Wah Hospital": (22.3150, 114.1732),
    "North District Hospital": (22.4980, 114.1290),
    "North Lantau Hospital": (22.2822, 113.9396),
    "Pamela Youde Nethersole Eastern Hospital": (22.2788, 114.2350),
    "Pok Oi Hospital": (22.4458, 114.0387),
    "Prince of Wales Hospital": (22.3760, 114.2007),
    "Princess Margaret Hospital": (22.3417, 114.1353),
    "Queen Elizabeth Hospital": (22.3090, 114.1770),
    "Queen Mary Hospital": (22.2683, 114.1312),
    "Ruttonjee Hospital": (22.2776, 114.1746),
    "St John Hospital": (22.2683, 114.2504),
    "Tin Shui Wai Hospital": (22.4583, 114.0017),
    "Tseung Kwan O Hospital": (22.3166, 114.2715),
    "Tuen Mun Hospital": (22.4067, 113.9765),
    "United Christian Hospital": (22.3233, 114.2289),
    "Yan Chai Hospital": (22.3698, 114.1076),
}


# ---------------------------------------------------------------------------
# "Now", in the only timezone this product is about
# ---------------------------------------------------------------------------
# The Hospital Authority's live board publishes ONE figure: its estimate for a
# patient arriving at the moment it was published. It carries no hour label and
# no forecast for any other hour. So that figure is evidence about exactly one
# hour of the week, the current Hong Kong hour, and about no other.
#
# Everything below exists so the rest of the code can ask "is the hour the user
# asked about the hour this board figure is actually about?" and get an answer
# that does not depend on where the server happens to be running. Hong Kong has
# had no DST since 1979 (UTC+8 year-round), but zoneinfo is used rather than a
# hardcoded +8 so the answer stays right if that ever changes and so the
# machine's own TZ setting can never leak in.

HK_TZ = ZoneInfo("Asia/Hong_Kong")

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday",
             "Friday", "Saturday", "Sunday"]


def _utcnow() -> datetime:
    """The wall clock, as an aware UTC datetime.

    The single seam the whole codebase reads the current time through. Tests
    replace THIS (not `datetime.now`) so they can pin an instant without
    monkeypatching the stdlib, and so a test can prove the Asia/Hong_Kong
    conversion really happens instead of asserting against real time.
    """
    return datetime.now(timezone.utc)


def hk_now() -> datetime:
    """Current time in Asia/Hong_Kong, whatever timezone this server is in."""
    return _utcnow().astimezone(HK_TZ)


def hk_now_day_hour() -> tuple[str, int]:
    """(weekday name, hour 0-23) in Asia/Hong_Kong."""
    n = hk_now()
    return DAY_NAMES[n.weekday()], n.hour


def is_arrival_now(day: str, hour: int) -> bool:
    """Is the requested arrival slot the hour the live board is about?

    True iff BOTH the weekday name and the hour match Hong Kong's current
    weekday and hour. Nothing else counts as now: not "the same hour
    yesterday", not "an hour from now". The live figure is evidence for one
    hour-of-week cell and scoring it against any other cell manufactures a
    result.
    """
    now_day, now_hour = hk_now_day_hour()
    return day == now_day and hour == now_hour


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class HourBucket:
    """Waits observed at a specific hospital × triage × hour-of-week."""
    hospital: str
    triage: str          # 't3' or 't45'
    percentile: str       # 'p50' or 'p95'
    hour_of_week: int     # 0 = Monday 00:00, 167 = Sunday 23:00
    values: list[float] = field(default_factory=list)
    n: int = 0

    @property
    def median(self) -> float | None:
        return float(_median(self.values)) if self.values else None

    @property
    def p25(self) -> float | None:
        return float(_quantile(self.values, 0.25)) if self.values else None

    @property
    def p75(self) -> float | None:
        return float(_quantile(self.values, 0.75)) if self.values else None

    @property
    def p10(self) -> float | None:
        return float(_quantile(self.values, 0.10)) if self.values else None

    @property
    def p90(self) -> float | None:
        return float(_quantile(self.values, 0.90)) if self.values else None


# --- How "normal" is decided -----------------------------------------------
#
# The rule is RELATIVE TO EACH DEPARTMENT'S OWN SPREAD, because that is the only
# thing the page ever claims to measure and it is what the page's own chart
# draws.
#
# The rule used to be a flat `abs(published - median) <= 15` and it produced a
# self-contradicting page. Measured live at Wednesday 10:00 across both triage
# bands, **10 of 36 rows** showed a green tick and the words "Typical for this
# hour" / "well inside its normal spread" while the marker sat OUTSIDE the drawn
# band with its excess labelled in red 30 pixels away:
#
#     Queen Mary        band 24–29     published 39   (+10 past the band)  "Typical"
#     United Christian  band 19–31     published 39   (+8)                 "Typical"
#
# A flat threshold cannot work here because the bands differ by more than an
# order of magnitude: measured across all 6,048 p50 buckets with n>=5, the IQR
# width runs min 0, p25 9, median 17.25, p90 127.5, max 300 minutes. Fifteen
# minutes is most of a narrow department's whole range and a rounding error in a
# wide one, so one number is either deaf or hysterical depending on the row.
#
# MIN_ABNORMAL_MINUTES exists because the band alone is not enough either:
# **83 of 6,048 buckets (1.4%) have a zero-width band** and 10.7% are 5 minutes
# or narrower. Judging purely on "outside the band" would call a department
# abnormal for being one minute off a band with no width, which is its own
# falsehood in the alarming direction. Five minutes is the floor at which this
# tool is willing to say anything at all: HA publishes rounded figures, and a
# sub-5-minute difference is not a reason to drive somewhere else at 2am.
MIN_ABNORMAL_MINUTES = 5.0

# How far past the band counts as "unusual" before it counts as "far from
# normal", in units of the department's own band width. 1.5 IQRs beyond the
# quartile is Tukey's standard outlier fence, used here for the same reason
# he used it: it scales with the spread instead of assuming one.
FAR_FROM_NORMAL_IQRS = 1.5


def normal_excess(published: float, p25: float, p75: float) -> float:
    """How far outside its own normal range this figure sits, in minutes.

    Zero when the figure is inside the band (including exactly on an edge).
    Always non-negative: the DIRECTION is a separate question, because
    "unusually quiet" and "unusually busy" are both distances from normal and
    only one of them is a reason to go elsewhere.
    """
    if published > p75:
        return published - p75
    if published < p25:
        return p25 - published
    return 0.0


def score_normality(published: float, p25: float, p75: float) -> tuple[str, float]:
    """(verdict, excess_minutes) for one published figure against one band.

    Verdict values are unchanged (`reliable` / `caution` / `misleading`) because
    renaming them is a coordinated API + golden + frontend change that is still
    deferred. Only the RULE changed. Their rendered meanings are, in order:
    "typical for this hour", "busier/quieter than usual", "far from normal".
    """
    excess = normal_excess(published, p25, p75)
    if excess <= MIN_ABNORMAL_MINUTES:
        return "reliable", excess
    scale = max(p75 - p25, MIN_ABNORMAL_MINUTES)
    if excess <= scale * FAR_FROM_NORMAL_IQRS:
        return "caution", excess
    return "misleading", excess


@dataclass
class ReliabilityScore:
    """How trustworthy is the published figure for a specific query?"""
    hospital: str
    triage: str
    published_minutes: float | None  # what the hospital says RIGHT NOW (None if unreachable)
    forecast_median: float           # what history says you'll actually wait
    forecast_p25: float
    forecast_p75: float
    delta_minutes: float | None      # None when published is unavailable
    n_observations: int              # how many data points this is based on
    verdict: str                     # 'reliable' | 'caution' | 'misleading' | 'no_live_data'
    pooled: bool = False             # True: exact hour was empty, used all-hours fallback
    basis: str = "exact_hour"        # exact_hour | hour_window | all_hours
    # Minutes outside this department's own p25-p75 band (0.0 when inside it).
    # Exposed so the page can state the SAME quantity its chart draws, rather
    # than deriving a second one that can drift from the badge beside it.
    excess_minutes: float | None = None

    @property
    def delta_direction(self) -> str:
        """Where today's figure sits relative to this department's own normal.

        This used to return "hospital understates wait" / "hospital overstates
        wait" on the same flat ±15 rule. Both strings were false in a way this
        project has already corrected everywhere else: there is no public record
        of what any patient actually waited, so the board's error is not a
        measurable quantity and this tool has never measured it. An earlier
        pass rewrote every rendered string that said otherwise but left this
        one, because it lives in the API rather than the UI.
        """
        if self.delta_minutes is None:
            return "live feed unavailable"
        if self.excess_minutes is not None and self.excess_minutes <= 0:
            return "inside its normal range"
        if self.delta_minutes > 0:
            return "busier than its normal"
        return "quieter than its normal"

    @property
    def interval_str(self) -> str:
        return f"{self._fmt(self.forecast_p25)} – {self._fmt(self.forecast_p75)}"

    @staticmethod
    def _fmt(m: float) -> str:
        if m < 60:
            return f"{round(m)} min"
        h = m / 60
        if h < 2:
            return f"{h:.1f} hr"
        return f"{round(h * 2) / 2:.1f} hr"


# The hour-resolution ladder, coarsest last. `score_reliability` walks it for
# the p50 series. `score_tail` walks the SAME rungs for p95 and may be told to
# start lower down so it can never claim a finer resolution than the median it
# is printed next to.
BASIS_LADDER = ("exact_hour", "hour_window", "all_hours")


@dataclass
class TailEstimate:
    """HA's own p95 series for one hospital × triage × hour-of-week.

    The p95 field is HA's published "majority of the waiting patients can
    receive consultation within this time" estimate. These are the same kind of
    numbers as the p50 bucket (published estimates, sampled every 15 minutes),
    so `p95_p25`/`p95_p75` are the middle 50% of *published p95 estimates* for
    that hospital-hour, not the middle 50% of patient outcomes.

    `available=False` means the p95 series was too thin at every rung of the
    ladder. Everything else is then None. We do not scale the p50 to fill the
    gap: a fabricated tail is worse than no tail, because the tail is the number
    a frightened reader would act on.
    """
    hospital: str
    triage: str
    available: bool
    p95_median: float | None = None
    p95_p25: float | None = None
    p95_p75: float | None = None
    n_observations: int = 0
    basis: str | None = None
    reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "p95_median": self.p95_median,
            "p95_p25": self.p95_p25,
            "p95_p75": self.p95_p75,
            "n_observations": self.n_observations,
            "basis": self.basis,
            "available": self.available,
            "reason": self.reason,
        }


def score_tail(
    hospital: str,
    triage: str,
    hour: int,
    buckets: dict,
    *,
    min_observations: int = 5,
    floor_basis: str | None = None,
) -> TailEstimate:
    """The p95 tail for this hospital × triage × hour-of-week.

    Walks the identical fallback ladder `score_reliability` uses for p50
    (exact hour, then a ±1-hour window, then all hours) against the `p95`
    buckets that `build_buckets` has always produced and nothing has ever read.

    `floor_basis` is the basis the accompanying p50 forecast actually used. The
    ladder starts at that rung, so the tail can never be quoted at a finer
    hour-resolution than the median it accompanies. It is reported in `basis`
    independently, and it names the rung that really produced these numbers.
    It never claims a better one.

    Returns a TailEstimate with `available=False` and every number None if the
    p95 series is too thin at every remaining rung. It never falls back to
    scaling the p50.
    """
    start = 0
    if floor_basis in BASIS_LADDER:
        start = BASIS_LADDER.index(floor_basis)

    def _refuse(reason: str) -> TailEstimate:
        return TailEstimate(
            hospital=hospital, triage=triage, available=False, reason=reason,
        )

    for rung in BASIS_LADDER[start:]:
        if rung == "exact_hour":
            b = buckets.get((hospital, triage, "p95", hour))
            vals = list(b.values) if b else []
        elif rung == "hour_window":
            vals = []
            for offset in (-1, 0, 1):
                b = buckets.get((hospital, triage, "p95", (hour + offset) % 168))
                if b:
                    vals.extend(b.values)
        else:
            vals = []
            for (h, t, p, _), b in buckets.items():
                if h == hospital and t == triage and p == "p95":
                    vals.extend(b.values)

        if len(vals) < min_observations:
            continue

        return TailEstimate(
            hospital=hospital, triage=triage, available=True,
            p95_median=float(_median(vals)),
            p95_p25=float(_quantile(vals, 0.25)),
            p95_p75=float(_quantile(vals, 0.75)),
            n_observations=len(vals),
            basis=rung,
        )

    tried = ", ".join(BASIS_LADDER[start:])
    return _refuse(
        f"fewer than {min_observations} archived p95 observations for "
        f"{triage} at {hospital} (tried {tried}). No tail is reported rather "
        f"than one inferred from the p50."
    )


@dataclass
class RerouteSuggestion:
    hospital: str
    distance_km: float
    forecast_median: float
    forecast_interval: str
    reliability: str


def hour_of_week(ts: str) -> int:
    """Monday 00:00 = 0, Sunday 23:00 = 167.

    Accepts either ISO format ('2026-08-09T12:00') or the archive format
    ('20260809-1200').
    """
    from datetime import datetime
    # Archive format: '20260809-1200'
    if '-' in ts and 'T' not in ts and len(ts) == 13:
        dt = datetime.strptime(ts, "%Y%m%d-%H%M")
    else:
        dt = datetime.fromisoformat(ts)
    return dt.weekday() * 24 + dt.hour


def _parse_triage_key(field_name: str) -> tuple[str, str] | None:
    """Map snapshot field names to (triage, percentile).

    't3p50_mins' -> ('t3', 'p50')
    't45p95_mins' -> ('t45', 'p95')
    """
    if not field_name.endswith("_mins"):
        return None
    base = field_name[:-5]  # 't3p50'
    for t in ("t1", "t2", "t3", "t45"):
        if base.startswith(t):
            pct = base[len(t):]  # 'p50' or 'p95'
            return (t, pct)
    return None


# ---------------------------------------------------------------------------
# Corpus loader
# ---------------------------------------------------------------------------

_CORPUS_CACHE: tuple[tuple, dict] | None = None


def load_corpus() -> dict:
    """Load the snapshot corpus, gzipped or plain.

    The corpus is ~144 MB of JSON and compresses to under 5 MB, so the shipped
    copy is `ae_corpus.json.gz`. A plain `.json` is preferred when present so a
    freshly-run seeder is picked up without a compression step.

    Cached against the source file's (path, mtime, size). `query()` called this
    on every request and threw the result away, so each API call re-parsed the
    whole corpus and rebuilt every bucket: measured 0.6 s to parse plus 2.2 s to
    bucket, ~3.0 s per request, and it serialised, so four concurrent requests
    took 8.4 s each. `routing._buckets()` was already caching the same work
    against mtime, and this brings the engine's own path in line.

    Keying on mtime (not just existence) preserves the reload-on-change
    behaviour `server._ensure_corpus()` depends on: a seeder run while the
    server is up still takes effect, because the mtime moves.
    """
    global _CORPUS_CACHE
    for path, opener in ((CORPUS_PATH, open), (CORPUS_GZ_PATH, None)):
        if not path.exists():
            continue
        try:
            st = path.stat()
            key = (str(path), st.st_mtime, st.st_size)
        except OSError:
            key = None
        if key is not None and _CORPUS_CACHE is not None and _CORPUS_CACHE[0] == key:
            return _CORPUS_CACHE[1]
        if opener is not None:
            with open(path) as f:
                data = json.load(f)
        else:
            import gzip
            with gzip.open(path, "rt", encoding="utf-8") as f:
                data = json.load(f)
        if key is not None:
            _CORPUS_CACHE = (key, data)
        return data
    print(f"Corpus not found at {CORPUS_PATH} or {CORPUS_GZ_PATH}: run seed_data.py first")
    return {}


_BUCKET_CACHE: tuple[int, dict] | None = None


def build_buckets(corpus: dict) -> dict[tuple[str, str, str, int], HourBucket]:
    """Ingest all snapshots into hour-of-week buckets.

    Returns: {(hospital, triage, percentile, hour_of_week): HourBucket}

    Cached by corpus identity. `query()` called this on EVERY request, which
    measured at ~3.0 s per call against the 290-day corpus (the entire
    per-request cost of the API), and it serialised, so four concurrent requests
    took 8.4 s each. `routing._buckets()` already caches the same computation
    against the corpus file's mtime, and this is the same idea keyed on the
    loaded object, because `query()` is handed a dict rather than a path.

    Keyed on `id(corpus)` PLUS snapshot count: `load_corpus()` returns a fresh
    object each call, so a stale id can only be reused if CPython has recycled
    the address of a freed corpus. A recycled address holding a dict with
    an identical snapshot count is not a case that arises from a corpus swap,
    which changes the count. Callers that reload get a new object and rebuild.
    """
    global _BUCKET_CACHE
    snaps = corpus.get("snapshots", {})
    key = (id(corpus), len(snaps))
    if _BUCKET_CACHE is not None and _BUCKET_CACHE[0] == key:
        return _BUCKET_CACHE[1]

    buckets: dict[tuple[str, str, str, int], HourBucket] = {}

    for date_key, day_data in snaps.items():
        for ts, snap in day_data.items():
            how = hour_of_week(ts)
            for entry in snap.get("waitTime", []):
                hosp = entry["hospName"]
                for field, value in entry.items():
                    parsed = _parse_triage_key(field)
                    if parsed is None:
                        continue
                    triage, pct = parsed
                    if not isinstance(value, (int, float)):
                        continue
                    bkey = (hosp, triage, pct, how)
                    if bkey not in buckets:
                        buckets[bkey] = HourBucket(
                            hospital=hosp, triage=triage,
                            percentile=pct, hour_of_week=how,
                        )
                    buckets[bkey].values.append(float(value))
                    buckets[bkey].n += 1

    _BUCKET_CACHE = (key, buckets)
    return buckets


# ---------------------------------------------------------------------------
# Reliability scoring
# ---------------------------------------------------------------------------

def score_reliability(
    hospital: str,
    triage: str,
    hour: int,
    published_minutes: float,
    buckets: dict,
    *,
    min_observations: int = 5,
) -> ReliabilityScore | None:
    """Score how trustworthy the published figure is.

    Compares the hospital's published number against the historical distribution
    for that hospital × triage × hour-of-week. Returns None if there isn't
    enough data to make the call.
    """
    # First try exact hour bucket
    key = (hospital, triage, "p50", hour)
    bucket = buckets.get(key)

    # Fall back to ±1 hour window
    if bucket is None or bucket.n < min_observations:
        window = []
        for offset in (-1, 0, 1):
            k = (hospital, triage, "p50", (hour + offset) % 168)
            b = buckets.get(k)
            if b:
                window.extend(b.values)
        if len(window) >= min_observations:
            vals = window
            n = len(window)
            # Adjacent hours only. Not the exact hour, but close enough that the
            # UI does not have to disown it: `basis` still records what happened.
            pooled = False
            basis = "hour_window"
            p25 = float(_quantile(vals, 0.25))
            p75 = float(_quantile(vals, 0.75))
            median = float(_median(vals))
        else:
            # Last resort: all hours for this hospital × triage.
            # Flagged as pooled so the UI can say "based on all hours" not
            # "at this hour".
            all_vals = []
            for (h, t, p, _), b in buckets.items():
                if h == hospital and t == triage and p == "p50":
                    all_vals.extend(b.values)
            if len(all_vals) < min_observations:
                return None
            vals = all_vals
            n = len(all_vals)
            pooled = True
            basis = "all_hours"
            p25 = float(_quantile(vals, 0.25))
            p75 = float(_quantile(vals, 0.75))
            median = float(_median(vals))
    else:
        vals = bucket.values
        n = bucket.n
        pooled = False
        basis = "exact_hour"
        p25 = bucket.p25 or 0
        p75 = bucket.p75 or 0
        median = bucket.median or 0

    # Live feed was unreachable, so no delta can be computed.
    if published_minutes is None:
        return ReliabilityScore(
            hospital=hospital, triage=triage,
            published_minutes=None,
            forecast_median=median, forecast_p25=p25, forecast_p75=p75,
            delta_minutes=None, n_observations=n,
            verdict="no_live_data", pooled=pooled, basis=basis,
        )

    delta = published_minutes - median

    # Judged against THIS department's own band, not a flat number of minutes.
    # See score_normality and MIN_ABNORMAL_MINUTES for why, and for the measured
    # evidence that the flat rule made the page contradict its own chart.
    verdict, excess = score_normality(published_minutes, p25, p75)

    return ReliabilityScore(
        hospital=hospital, triage=triage,
        published_minutes=published_minutes,
        forecast_median=median, forecast_p25=p25, forecast_p75=p75,
        delta_minutes=delta, n_observations=n,
        verdict=verdict, pooled=pooled, basis=basis,
        excess_minutes=excess,
    )


# ---------------------------------------------------------------------------
# Rerouting
# ---------------------------------------------------------------------------

def find_alternatives(
    hospital: str,
    triage: str,
    hour: int,
    buckets: dict,
    coords: dict[str, tuple[float, float]],
    *,
    max_results: int = 3,
) -> list[RerouteSuggestion]:
    """Suggest alternative hospitals with lower forecast waits.

    Sorted by a composite: lower median wait, weighted by proximity.
    """
    if hospital not in coords:
        return []

    h_lat, h_lon = coords[hospital]
    this_key = (hospital, triage, "p50", hour)
    if this_key not in buckets:
        return []  # cannot compare, so don't guess
    this_median = buckets[this_key].median
    if this_median is None:
        return []

    candidates = []
    for other, (o_lat, o_lon) in coords.items():
        if other == hospital:
            continue
        key = (other, triage, "p50", hour)
        if key not in buckets or buckets[key].n < 3:
            continue

        dist = haversine(h_lat, h_lon, o_lat, o_lon)
        b = buckets[key]
        m = b.median or 999

        # Only suggest if meaningfully better
        if m >= this_median:
            continue

        reliability = "reliable" if b.n >= 10 else "caution"
        candidates.append(RerouteSuggestion(
            hospital=other, distance_km=round(dist, 1),
            forecast_median=m,
            forecast_interval=f"{_fmt_min(b.p25)} – {_fmt_min(b.p75)}",
            reliability=reliability,
        ))

    # Sort by score: lower median gets more weight, but proximity matters too
    candidates.sort(key=lambda c: c.forecast_median + c.distance_km * 3)
    return candidates[:max_results]


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in km between two lat/lon points."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _fmt_min(m: float | None) -> str:
    if m is None:
        return "?"
    if m < 60:
        return f"{round(m)} min"
    return f"{m / 60:.1f} hr"


# ---------------------------------------------------------------------------
# Top-level query
# ---------------------------------------------------------------------------

@dataclass
class QueryResult:
    hospital: str
    triage: str
    hour: int
    hour_label: str
    forecast: ReliabilityScore | None
    alternatives: list[RerouteSuggestion] = field(default_factory=list)
    all_hospitals_summary: list[dict] = field(default_factory=list)
    # Was the requested arrival slot the current Hong Kong hour? Decides
    # whether the live board was consulted at all (see `query`).
    arrival_is_now: bool = False

    @property
    def answered(self) -> bool:
        return self.forecast is not None


def query(
    hospital: str,
    triage: str,
    day: str,        # 'Monday' through 'Sunday'
    hour: int,        # 0–23
    published_minutes: float | None = None,
    *,
    arrival_is_now: bool | None = None,
) -> QueryResult:
    """Top-level query: what should someone arriving at `day`/`hour` expect?

    The live board is consulted ONLY when the requested slot is the current
    Hong Kong hour. Previously this fetched today's board figure whenever
    `published_minutes` was None, whatever day and hour had been asked for, and
    handed it to `score_reliability` to be scored against that other hour's
    history. One reading then produced a different "delta" and a different
    verdict for every hour of the week, each rendered as an observation. It was
    not one: the board carries no figure for Sunday 03:00 on a Tuesday
    afternoon. So when the slot is not now we do not fetch at all, and we
    don't fetch and discard either, because a figure that is not evidence for
    the requested hour must not exist anywhere downstream to be picked up by
    accident.

    An explicitly supplied `published_minutes` is unchanged in every case: it
    is the caller's own input (the golden matrix and the API's testing hook
    both rely on it), and this function neither invents nor suppresses it. The
    *presentation* of a supplied figure at a non-now hour is the server's
    problem, and server.py flags it as not comparable.

    `arrival_is_now` may be passed in by a caller that has already determined
    it, so the caller's answer and this one cannot disagree across an
    hour boundary. Left None, it is computed here from `is_arrival_now`.
    """
    days = DAY_NAMES
    day_idx = days.index(day) if day in days else 0
    how = day_idx * 24 + hour
    label = f"{day} {hour:02d}:00"

    if arrival_is_now is None:
        arrival_is_now = is_arrival_now(day, hour)

    corpus = load_corpus()
    if not corpus:
        return QueryResult(hospital=hospital, triage=triage, hour=how, hour_label=label,
                           forecast=None, arrival_is_now=arrival_is_now)

    buckets = build_buckets(corpus)
    coords = corpus.get("hospitals", {})

    # Fetch the live figure only when it is a figure about the hour asked for.
    if published_minutes is None and arrival_is_now:
        published_minutes = _fetch_live_triage(hospital, triage)

    forecast = score_reliability(hospital, triage, how,
                                 published_minutes, buckets)

    alternatives = find_alternatives(hospital, triage, how, buckets, coords)

    # Summary of all hospitals for comparison
    summary = []
    for h, (lat, lon) in coords.items():
        key = (h, triage, "p50", how)
        b = buckets.get(key)
        if b is None or b.n < 3:
            continue
        # Same rule per row as for the headline: no live figure is attached to
        # a row for an hour the live board says nothing about.
        published = _fetch_live_triage(h, triage) if arrival_is_now else None
        summary.append({
            "hospital": h,
            "forecast_median": b.median,
            "forecast_p25": b.p25,
            "forecast_p75": b.p75,
            "published": published,
            "n": b.n,
            "distance_km": round(haversine(
                coords[hospital][0], coords[hospital][1], lat, lon), 1)
            if hospital in coords else None,
        })
    summary.sort(key=lambda s: s["forecast_median"] if s["forecast_median"] is not None else 9999)

    return QueryResult(
        hospital=hospital, triage=triage, hour=how, hour_label=label,
        forecast=forecast, alternatives=alternatives,
        all_hospitals_summary=summary,
        arrival_is_now=arrival_is_now,
    )


def _fetch_live_triage(hospital: str, triage: str) -> float | None:
    """Get the currently published wait for one hospital × triage.

    Returns None if the live feed is unreachable or the parse fails.
    The caller (score_reliability) handles None by returning verdict='no_live_data'
    rather than fabricating a number.
    """
    try:
        import urllib.request
        data = json.loads(urllib.request.urlopen(
            urllib.request.Request(LIVE_URL,
                                   headers={"User-Agent": "AE-Wait-Times/1.0"}),
            timeout=10,
        ).read())
        for entry in data.get("waitTime", []):
            if entry["hospName"] == hospital:
                raw = entry.get(f"{triage}p50", "")
                return _parse_live_str(raw)
    except Exception:
        pass
    return None


def _parse_live_str(value: str) -> float | None:
    """Parse a live-feed wait string like '30 minutes' or '1.5 hours'."""
    if not value:
        return None
    s = value.strip().lower()
    if s in ("0 minute", "0 minutes"):
        return 0.0
    if "less than" in s:
        return 7.5
    if "hour" in s:
        return float(s.replace("hours", "").replace("hour", "").strip()) * 60
    if "minute" in s:
        return float(s.replace("minutes", "").replace("minute", "").strip())
    return None
