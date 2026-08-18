"""The forecast-regression detector.

The project's release gate says a full-corpus rebuild must still produce
identical forecasts to the published numbers. Nothing could check that before
this file existed. Here we re-run a fixed, deterministic query matrix and
require the output to be byte-identical to
tests/fixtures/golden_forecasts.json.

Hermetic by construction:
  * no HTTP: the engine is called directly, and conftest's autouse fixture
    makes any URL open raise
  * no live feeds: every case supplies its own `published` value
  * no wall-clock or date dependence: every case supplies an explicit
    day and hour, so "now" is never consulted

If this file fails, ONE of two things happened. Either the corpus or the
forecast maths changed on purpose, in which case run
``uv run python -m tests.regen_golden`` and commit the diff on its own, or
something regressed, in which case the diff below is the bug report.
"""

from __future__ import annotations

import json

import pytest

from tests._support import GOLDEN, current_fingerprint, read_json
from tests.golden_matrix import QUERY_CASES, RECORDED_FIELDS, THIN_CASES, run_matrix

REGEN = "cd engine && uv run python -m tests.regen_golden"


@pytest.fixture(scope="module")
def golden():
    if not GOLDEN.exists():
        pytest.fail(f"missing golden file {GOLDEN}, create it with `{REGEN}`")
    return read_json(GOLDEN)


@pytest.fixture
def actual(fast_engine):
    return run_matrix()


# ---------------------------------------------------------------------------
# Is the golden file even describing this corpus?
# ---------------------------------------------------------------------------

def test_golden_file_was_generated_against_this_corpus(golden):
    recorded = golden["_corpus_fingerprint"]
    now = current_fingerprint()
    assert recorded == now, (
        "STALE GOLDEN FILE: it was generated against a different corpus.\n"
        f"  golden says : {recorded}\n"
        f"  on disk now : {now}\n"
        "Every forecast number below therefore describes a corpus that no "
        "longer exists. If the corpus change was intentional (e.g. a "
        f"September backfill merged in), run `{REGEN}` and commit the diff on "
        "its own so the forecast movement is reviewable."
    )


def test_golden_file_is_not_vacuous(golden):
    """A golden test that locks nothing is worse than no golden test."""
    cases = golden["cases"]
    assert len(cases) == len(QUERY_CASES) + len(THIN_CASES)
    assert len(cases) >= 60

    answered = [c for c in cases.values() if c["answered"]]
    refused = [c for c in cases.values() if not c["answered"]]
    assert len(answered) >= 50, "almost nothing is actually being forecast"
    assert refused, "no refusal case: the 'not enough data' path is unlocked"

    bases = {c["basis"] for c in answered}
    assert "exact_hour" in bases
    assert "hour_window" in bases, "the ±1-hour window branch is not covered"
    assert "all_hours" in bases, "the pooled fallback is not covered"

    verdicts = {c["verdict"] for c in answered}
    assert {"reliable", "caution", "misleading", "no_live_data"} <= verdicts, (
        f"verdict ladder not fully exercised: {sorted(verdicts)}"
    )

    hospitals = {c["_input"]["hospital"] for c in cases.values()}
    assert len(hospitals) >= 18
    assert "St John Hospital" in hospitals, "the ferry-only hospital is not covered"


# ---------------------------------------------------------------------------
# The actual lock
# ---------------------------------------------------------------------------

def test_forecasts_are_byte_identical_to_the_golden_file(golden, actual):
    expected = golden["cases"]

    missing = sorted(set(expected) - set(actual))
    added = sorted(set(actual) - set(expected))
    assert not missing, f"cases in the golden file that the matrix no longer runs: {missing}"
    assert not added, f"new cases not in the golden file, run `{REGEN}`: {added}"

    diffs = []
    for case_id in sorted(expected):
        want, got = expected[case_id], actual[case_id]
        for field in RECORDED_FIELDS:
            if want[field] != got[field]:
                diffs.append(
                    f"  {case_id}\n"
                    f"    {field}: golden={want[field]!r} now={got[field]!r}"
                )
    assert not diffs, (
        "FORECAST REGRESSION: the engine no longer produces the published "
        f"numbers.\n" + "\n".join(diffs[:40])
        + (f"\n  … and {len(diffs) - 40} more" if len(diffs) > 40 else "")
        + f"\n\nIf this change was intentional, run `{REGEN}`."
    )

    # Byte-level: catches a float that round-trips to a different repr, which a
    # field-by-field == would also catch, but this is the literal promise.
    for case_id in sorted(expected):
        want = {k: expected[case_id][k] for k in RECORDED_FIELDS}
        got = {k: actual[case_id][k] for k in RECORDED_FIELDS}
        assert json.dumps(want, sort_keys=True) == json.dumps(got, sort_keys=True), (
            f"serialised forecast for {case_id} differs"
        )


def test_regen_would_be_a_no_op(golden, actual):
    """`--check` must agree with the assertions above, or the documented
    regeneration workflow is lying about what it would write."""
    from tests.regen_golden import serialise

    payload = dict(golden)
    payload["cases"] = actual
    payload["_corpus_fingerprint"] = current_fingerprint()
    payload["n_cases"] = len(actual)
    assert serialise(payload) == GOLDEN.read_text(encoding="utf-8"), (
        f"the golden file on disk is not what regen_golden would write, run `{REGEN}`"
    )


# ---------------------------------------------------------------------------
# Determinism and hermeticity of the matrix itself
# ---------------------------------------------------------------------------

def test_running_the_matrix_twice_gives_the_same_answer(actual, fast_engine):
    again = run_matrix()
    assert actual == again, "the forecast matrix is not deterministic"


def test_every_answered_case_carries_an_ordered_interval(golden):
    """The product's central promise: never a bare point estimate."""
    for case_id, c in golden["cases"].items():
        if not c["answered"]:
            continue
        assert c["forecast_p25"] is not None, case_id
        assert c["forecast_p75"] is not None, case_id
        assert c["forecast_p25"] <= c["forecast_median"] <= c["forecast_p75"], (
            f"{case_id}: interval is not ordered "
            f"({c['forecast_p25']}, {c['forecast_median']}, {c['forecast_p75']})"
        )
        assert c["n_observations"] >= 5, (
            f"{case_id} was answered from {c['n_observations']} observations, "
            f"below the engine's own min_observations=5 floor"
        )


def test_pooled_flag_and_basis_agree(golden):
    for case_id, c in golden["cases"].items():
        if not c["answered"]:
            continue
        assert c["pooled"] == (c["basis"] == "all_hours"), (
            f"{case_id}: pooled={c['pooled']} but basis={c['basis']!r}. "
            "The UI switches its amber 'not hour-specific' notice on these two "
            "fields, and they must never disagree."
        )


def test_refusals_are_total(golden):
    """A refusal must not leak a half-answer the UI could render."""
    for case_id, c in golden["cases"].items():
        if c["answered"]:
            continue
        assert c["forecast_median"] is None, case_id
        assert c["forecast_p25"] is None, case_id
        assert c["forecast_p75"] is None, case_id
        assert c["verdict"] is None, case_id


def test_matrix_does_not_consult_the_clock(fast_engine, monkeypatch):
    """Freeze time far into the future: the answers must not move.

    engine.hour_of_week parses timestamps out of the corpus rather than
    reading `now`, and every case passes an explicit day/hour: this proves it.
    """
    import datetime as _dt

    before = run_matrix()

    class _FrozenDatetime(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2031, 3, 3, 3, 3, 3, tzinfo=tz)

        @classmethod
        def today(cls):
            return cls(2031, 3, 3, 3, 3, 3)

    monkeypatch.setattr(_dt, "datetime", _FrozenDatetime)
    monkeypatch.setattr("time.time", lambda: 1_930_000_000.0)

    assert run_matrix() == before, "forecast output depends on the current time"
