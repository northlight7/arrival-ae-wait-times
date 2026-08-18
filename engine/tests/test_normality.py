""""Is today normal?" is judged against each department's OWN spread.

WHAT THIS FILE EXISTS TO PREVENT
--------------------------------
The verdict used to be a flat `abs(published - median) <= 15`, which ignored
`forecast_p25`/`forecast_p75` even though it computed and returned them, and
even though the page DRAWS them. The result was a page that contradicted
itself. Measured live at Wednesday 10:00, Queen Mary, urgent:

    band 24–29 min      published 39 min      verdict "reliable"

rendered as a green tick and "Typical for this hour" / "well inside its normal
spread", while the chart annotation 30 pixels away said, in red, "10 minutes
above the range". Ten of thirty-six live rows were in that state.

Worse in the other direction: the flat rule called figures sitting INSIDE a
department's own middle-50% band "misleading". From the reviewed golden diff:

    North District t45   band 120–270   published 240 (inside)   "misleading"
    Tin Shui Wai   t45   band  90–270   published 240 (inside)   "misleading"

A flat threshold cannot work when the bands differ by orders of magnitude:
across all 6,048 p50 buckets with n>=5 the IQR runs min 0, median 17.25,
p90 127.5, max 300 minutes.

The rule these tests hold: the badge and the chart are computed from ONE
number, so they cannot disagree.
"""

from __future__ import annotations

import pytest

from engine import (
    FAR_FROM_NORMAL_IQRS,
    MIN_ABNORMAL_MINUTES,
    normal_excess,
    score_normality,
)


# ---------------------------------------------------------------------------
# The regression itself
# ---------------------------------------------------------------------------

def test_the_queen_mary_case_is_no_longer_typical():
    """The exact figures that exposed the regression, as a test."""
    verdict, excess = score_normality(published=39.0, p25=24.0, p75=29.0)
    assert excess == pytest.approx(10.0)
    assert verdict != "reliable", (
        "a figure 10 minutes past the top of a 5-minute-wide band was called "
        "typical, while the chart drew it outside the band in red"
    )


def test_a_figure_inside_the_band_is_always_typical():
    """Inside its own middle 50% is the definition of normal.

    The flat rule called several of these 'misleading' purely because the
    department's band was wide, punishing departments for being
    variable, which is the opposite of what the reader needs to know.
    """
    for p25, p75, pub in (
        (120.0, 270.0, 240.0),   # North District t45, was "misleading"
        (90.0, 270.0, 240.0),    # Tin Shui Wai t45, was "misleading"
        (180.0, 420.0, 240.0),   # Pamela Youde t45, was "caution"
        (24.0, 29.0, 24.0),      # exactly on the lower edge
        (24.0, 29.0, 29.0),      # exactly on the upper edge
    ):
        verdict, excess = score_normality(pub, p25, p75)
        assert excess == 0.0, (pub, p25, p75)
        assert verdict == "reliable", (pub, p25, p75)


# ---------------------------------------------------------------------------
# The floor: do not manufacture alarm on narrow bands
# ---------------------------------------------------------------------------

def test_a_zero_width_band_does_not_cry_wolf():
    """1.4% of real buckets (83 of 6,048) have p25 == p75.

    Judging purely on "outside the band" would call a department abnormal for
    being one minute away from a band with no width, the same class of
    falsehood as the bug being fixed, pointing the other way.
    """
    verdict, excess = score_normality(published=15.0, p25=14.0, p75=14.0)
    assert excess == pytest.approx(1.0)
    assert verdict == "reliable"


def test_the_floor_is_the_stated_number_and_is_inclusive():
    v_at, _ = score_normality(20.0 + MIN_ABNORMAL_MINUTES, 10.0, 20.0)
    assert v_at == "reliable", "the floor must be inclusive"
    v_past, _ = score_normality(20.0 + MIN_ABNORMAL_MINUTES + 0.1, 10.0, 20.0)
    assert v_past != "reliable"


def test_tolerance_scales_with_the_department_not_the_clock():
    """The same excess means different things at different spreads.

    16 minutes past the band is routine for a department whose normal range is
    two hours wide, and remarkable for one whose range is five minutes. A flat
    threshold is deaf to the first and hysterical about the second.
    """
    narrow, _ = score_normality(45.0, 24.0, 29.0)    # 16 past a 5-wide band
    wide, _ = score_normality(216.0, 80.0, 200.0)    # 16 past a 120-wide band
    assert narrow == "misleading"
    assert wide == "caution"


# ---------------------------------------------------------------------------
# Direction is separate from distance
# ---------------------------------------------------------------------------

def test_quieter_than_normal_is_a_distance_not_a_reassurance():
    """Unusually quiet is still unusual, and must not be silently normalised."""
    verdict, excess = score_normality(published=5.0, p25=60.0, p75=90.0)
    assert excess == pytest.approx(55.0)
    assert verdict == "misleading"


def test_normal_excess_is_never_negative():
    for pub, p25, p75 in ((5.0, 10.0, 20.0), (25.0, 10.0, 20.0), (15.0, 10.0, 20.0)):
        assert normal_excess(pub, p25, p75) >= 0.0


# ---------------------------------------------------------------------------
# The invariant that actually prevents the regression coming back
# ---------------------------------------------------------------------------

def test_no_bucket_can_be_typical_while_materially_outside_its_own_band(buckets):
    """Swept over the REAL corpus, not over invented numbers.

    For every real p50 bucket, probe a published figure just past each edge of
    the band and assert the badge never says "typical" about a figure the chart
    would draw outside the band by more than the stated floor. This is the
    machine-checkable form of "the badge and the chart never contradict".
    """
    checked = 0
    for (hosp, triage, pct, _how), b in buckets.items():
        if pct != "p50" or triage not in ("t3", "t45") or b.n < 5:
            continue
        p25, p75 = b.p25, b.p75
        if p25 is None or p75 is None:
            continue
        for pub in (p75 + MIN_ABNORMAL_MINUTES + 1, p25 - MIN_ABNORMAL_MINUTES - 1):
            verdict, excess = score_normality(pub, p25, p75)
            assert excess > MIN_ABNORMAL_MINUTES
            assert verdict != "reliable", (
                f"{hosp} {triage}: band {p25}-{p75}, published {pub} "
                f"({excess:g} outside) still reported as typical"
            )
        checked += 1
    assert checked > 5000, f"swept only {checked} buckets: fixture too thin to prove anything"


def test_the_far_fence_is_the_stated_multiple(buckets):
    """`FAR_FROM_NORMAL_IQRS` is the real knob, not a decorative constant."""
    p25, p75 = 20.0, 40.0          # 20-wide band
    scale = (p75 - p25) * FAR_FROM_NORMAL_IQRS
    just_inside, _ = score_normality(p75 + scale - 0.1, p25, p75)
    just_outside, _ = score_normality(p75 + scale + 0.1, p25, p75)
    assert just_inside == "caution"
    assert just_outside == "misleading"
