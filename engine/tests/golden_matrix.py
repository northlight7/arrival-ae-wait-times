"""The fixed query matrix behind tests/fixtures/golden_forecasts.json.

Shared by ``tests.regen_golden`` (which writes the file) and
``tests/test_forecast_golden.py`` (which re-runs the matrix and demands
byte-identical output). Keeping the definition in one place is what makes an
intentional corpus change produce a reviewable diff instead of a mystery.

WHAT IS AND IS NOT RECORDED
---------------------------
Recorded: forecast_median, forecast_p25, forecast_p75, basis, pooled,
n_observations, verdict, answered, all of which are a pure function of the
corpus plus the ``published`` figure the case supplies explicitly.

NOT recorded: live published minutes, travel time, traffic. Those come from
feeds that move every 15 minutes, and pinning them would make this suite fail
for reasons that have nothing to do with a forecast regression.

``published`` is therefore an explicit input on every case, never a live
lookup. That is also what lets the matrix exercise all four verdicts
(reliable / caution / misleading / no_live_data) offline.

TWO SECTIONS, AND WHY
---------------------
Section A calls ``engine.query`` on the real corpus.

Section B calls ``engine.score_reliability`` against real corpus buckets that
have been deterministically thinned. It exists because, on the corpus as it
stands today, EVERY ONE of the 6,048 hospital x {t3,t45} x hour-of-week
combinations resolves to basis='exact_hour': the ±1-hour window and
all-hours pooling branches are unreachable through ``query``. (See the note in
tests/README.md: the 71/2.4/26 percent split quoted in server.py and
WORKFLOW.md does not describe this corpus.) Those two branches are still live
code that the UI has amber states for, so they get locked too, using real
observed values, with the only synthetic element being which buckets are thin.
"""

from __future__ import annotations

from dataclasses import dataclass

HOSPITALS = [
    "Alice Ho Miu Ling Nethersole Hospital",
    "Caritas Medical Centre",
    "Kwong Wah Hospital",
    "North District Hospital",
    "North Lantau Hospital",
    "Pamela Youde Nethersole Eastern Hospital",
    "Pok Oi Hospital",
    "Prince of Wales Hospital",
    "Princess Margaret Hospital",
    "Queen Elizabeth Hospital",
    "Queen Mary Hospital",
    "Ruttonjee Hospital",
    "St John Hospital",          # the ferry-only island A&E
    "Tin Shui Wai Hospital",
    "Tseung Kwan O Hospital",
    "Tuen Mun Hospital",
    "United Christian Hospital",
    "Yan Chai Hospital",
]

RECORDED_FIELDS = (
    "answered",
    "forecast_median",
    "forecast_p25",
    "forecast_p75",
    "basis",
    "pooled",
    "n_observations",
    "verdict",
)


@dataclass(frozen=True)
class Case:
    """One deterministic query. ``published`` is an input, never a feed read."""
    case_id: str
    hospital: str
    triage: str
    day: str
    hour: int
    published: float | None
    why: str


def _query_cases() -> list[Case]:
    cases: list[Case] = []

    # --- dense exact-hour coverage, every hospital -------------------------
    # Monday 14:00 with a published figure close to reality, and Sunday 03:00
    # (the quiet hour the workflow doc calls out) with the feed down.
    for h in HOSPITALS:
        cases.append(Case(
            case_id=f"exact|{h}|t3|Monday|14|pub60",
            hospital=h, triage="t3", day="Monday", hour=14, published=60.0,
            why="dense weekday-afternoon exact-hour bucket, live figure supplied",
        ))
        cases.append(Case(
            case_id=f"exact|{h}|t3|Sunday|03|nopub",
            hospital=h, triage="t3", day="Sunday", hour=3, published=None,
            why="quiet hour with the live feed unavailable -> verdict no_live_data",
        ))

    # --- the long-wait triage, and the verdict ladder -----------------------
    for h in HOSPITALS:
        cases.append(Case(
            case_id=f"exact|{h}|t45|Friday|20|pub240",
            hospital=h, triage="t45", day="Friday", hour=20, published=240.0,
            why="Friday-evening peak, semi-urgent triage",
        ))

    # A single hospital swept across the verdict thresholds (|delta| <= 15
    # reliable, <= 45 caution, else misleading) so a change to those cut-offs
    # shows up here rather than only in the UI.
    for pub in (0.0, 30.0, 60.0, 90.0, 150.0, 600.0):
        cases.append(Case(
            case_id=f"verdict|Queen Mary Hospital|t3|Wednesday|09|pub{pub:g}",
            hospital="Queen Mary Hospital", triage="t3", day="Wednesday",
            hour=9, published=pub,
            why="sweeps the reliable/caution/misleading thresholds",
        ))

    # --- the ferry-only hospital, explicitly ------------------------------
    for day, hour in (("Saturday", 11), ("Tuesday", 2)):
        cases.append(Case(
            case_id=f"stjohn|St John Hospital|t3|{day}|{hour}|nopub",
            hospital="St John Hospital", triage="t3", day=day, hour=hour,
            published=None,
            why="Cheung Chau island A&E: forecasts normally, must never be "
                "dropped or given a road journey",
        ))

    # --- refusals ----------------------------------------------------------
    # t1 and t2 are archived as a single waiting time ('t1wt_mins'), so the
    # corpus holds no 'p50' percentile for them and score_reliability has
    # nothing to score. The engine must refuse, not guess.
    for h in ("Queen Elizabeth Hospital", "St John Hospital", "Tuen Mun Hospital"):
        for triage in ("t1", "t2"):
            cases.append(Case(
                case_id=f"refuse|{h}|{triage}|Monday|14|pub60",
                hospital=h, triage=triage, day="Monday", hour=14, published=60.0,
                why="no p50 percentile archived for this triage level -> refuse",
            ))

    # A hospital name that does not exist anywhere in the corpus.
    cases.append(Case(
        case_id="refuse|Nonexistent Hospital|t3|Monday|14|pub60",
        hospital="Nonexistent Hospital", triage="t3", day="Monday", hour=14,
        published=60.0,
        why="unknown hospital -> refuse rather than fall through to a default",
    ))

    # --- boundary hours ----------------------------------------------------
    for day, hour in (("Monday", 0), ("Sunday", 23), ("Thursday", 12)):
        cases.append(Case(
            case_id=f"bound|Prince of Wales Hospital|t3|{day}|{hour}|pub45",
            hospital="Prince of Wales Hospital", triage="t3",
            day=day, hour=hour, published=45.0,
            why="hour-of-week arithmetic at the ends of the week",
        ))

    return cases


QUERY_CASES = _query_cases()


# ---------------------------------------------------------------------------
# Section B: thinned-bucket cases for the two unreachable branches
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ThinCase:
    case_id: str
    hospital: str
    triage: str
    day: str
    hour: int
    published: float | None
    thin_hours: str      # 'exact' | 'window' | 'all'
    keep: int            # how many real values survive in each thinned bucket
    expect_basis: str | None
    why: str


THIN_CASES = [
    ThinCase(
        case_id="thin|hour_window|Queen Mary Hospital|t3|Monday|14",
        hospital="Queen Mary Hospital", triage="t3", day="Monday", hour=14,
        published=75.0, thin_hours="exact", keep=2,
        expect_basis="hour_window",
        why="exact bucket below min_observations, neighbours intact -> "
            "the ±1-hour window branch (pooled stays False)",
    ),
    ThinCase(
        case_id="thin|hour_window|St John Hospital|t45|Sunday|03",
        hospital="St John Hospital", triage="t45", day="Sunday", hour=3,
        published=None, thin_hours="exact", keep=4,
        expect_basis="hour_window",
        why="same branch on the smallest-volume hospital, feed down",
    ),
    ThinCase(
        case_id="thin|all_hours|Queen Mary Hospital|t3|Monday|14",
        hospital="Queen Mary Hospital", triage="t3", day="Monday", hour=14,
        published=75.0, thin_hours="window", keep=1,
        expect_basis="all_hours",
        why="the whole ±1-hour window is too thin -> pooled all-hours "
            "fallback, which the UI must label 'not hour-specific'",
    ),
    ThinCase(
        case_id="thin|all_hours|Tuen Mun Hospital|t45|Saturday|22",
        hospital="Tuen Mun Hospital", triage="t45", day="Saturday", hour=22,
        published=300.0, thin_hours="window", keep=0,
        expect_basis="all_hours",
        why="window emptied entirely -> pooled all-hours fallback",
    ),
    ThinCase(
        case_id="thin|refuse|Queen Mary Hospital|t3|Monday|14",
        hospital="Queen Mary Hospital", triage="t3", day="Monday", hour=14,
        published=75.0, thin_hours="all", keep=0,
        expect_basis=None,
        why="every hour emptied -> nothing left to pool, engine must refuse",
    ),
]

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday",
        "Friday", "Saturday", "Sunday"]


def _thinned(buckets: dict, case: ThinCase) -> dict:
    """A copy of the real buckets with selected hours truncated.

    Never mutates the shared bucket set. The surviving values are genuine
    observations from the corpus, taken from the front of the list, so the
    result is deterministic.
    """
    from engine import HourBucket

    how = DAYS.index(case.day) * 24 + case.hour
    if case.thin_hours == "exact":
        hours = [how]
    elif case.thin_hours == "window":
        hours = [(how - 1) % 168, how, (how + 1) % 168]
    else:
        hours = list(range(168))

    out = dict(buckets)
    for h in hours:
        key = (case.hospital, case.triage, "p50", h)
        src = out.get(key)
        if src is None:
            continue
        kept = list(src.values[: case.keep])
        out[key] = HourBucket(
            hospital=case.hospital, triage=case.triage, percentile="p50",
            hour_of_week=h, values=kept, n=len(kept),
        )
    return out


# ---------------------------------------------------------------------------
# Running the matrix
# ---------------------------------------------------------------------------

def _record(score, answered: bool) -> dict:
    if not answered or score is None:
        return {
            "answered": False,
            "forecast_median": None,
            "forecast_p25": None,
            "forecast_p75": None,
            "basis": None,
            "pooled": None,
            "n_observations": None,
            "verdict": None,
        }
    return {
        "answered": True,
        "forecast_median": score.forecast_median,
        "forecast_p25": score.forecast_p25,
        "forecast_p75": score.forecast_p75,
        "basis": score.basis,
        "pooled": score.pooled,
        "n_observations": score.n_observations,
        "verdict": score.verdict,
    }


def run_matrix() -> dict[str, dict]:
    """Execute every case and return {case_id: recorded fields}.

    Callers MUST have installed the offline guard and the corpus memoisation
    (see tests/_support.py) before calling this.
    """
    import engine

    from tests._support import build_buckets_once

    results: dict[str, dict] = {}

    for c in QUERY_CASES:
        r = engine.query(c.hospital, c.triage, c.day, c.hour, c.published)
        row = _record(r.forecast, r.answered)
        row["_input"] = {
            "section": "query",
            "hospital": c.hospital, "triage": c.triage,
            "day": c.day, "hour": c.hour, "published": c.published,
        }
        row["_why"] = c.why
        results[c.case_id] = row

    buckets = build_buckets_once()
    for t in THIN_CASES:
        how = DAYS.index(t.day) * 24 + t.hour
        score = engine.score_reliability(
            t.hospital, t.triage, how, t.published, _thinned(buckets, t)
        )
        row = _record(score, score is not None)
        row["_input"] = {
            "section": "thinned_buckets",
            "hospital": t.hospital, "triage": t.triage,
            "day": t.day, "hour": t.hour, "published": t.published,
            "thin_hours": t.thin_hours, "keep": t.keep,
        }
        row["_why"] = t.why
        results[t.case_id] = row

    return results
