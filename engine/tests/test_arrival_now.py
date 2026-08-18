"""The published figure may only be compared against the hour it is about.

WHAT THIS FILE EXISTS TO PREVENT
--------------------------------
The Hospital Authority board publishes one figure: an estimate for a patient
arriving RIGHT NOW. It is evidence about exactly one hour-of-week cell.

`engine.query()` used to fetch that figure whenever `published_minutes` was
None, regardless of which day and hour the caller asked about, and then score
it against that hour's historical distribution and report the result as fact.
Measured against the live board (Hong Kong time Tuesday 17:00, North Lantau t3
reading "18 minutes"), one reading produced four different "facts":

    Tuesday   17:00  published=18.0  forecast=17-21 min  delta= -0.5  reliable
    Sunday    03:00  published=18.0  forecast=15-20 min  delta= +0.5  reliable
    Thursday  09:00  published=18.0  forecast=15-19 min  delta= +1.5  reliable
    Saturday  23:00  published=18.0  forecast=19-23 min  delta= -3.0  reliable

Per-row it manufactured badges: Ruttonjee's delta swung from -9.5 min at
Tuesday 17:00 to 0.0 at Sunday 03:00 on the very same board figure, flipping it
between "Typical" and "Far from normal" purely as an artefact of the hour the
user selected.

That is the exact error the rest of the product is an argument against: a
single published figure presented without the context that gives it meaning.
The rule these tests hold:

    Outside the current Hong Kong hour there is NO comparison, and the response
    says so in a sentence rather than leaving a blank.

Every test pins the clock through `engine._utcnow` (see conftest), so none of
this depends on when the suite is run.
"""

from __future__ import annotations

import pytest

QMH = "Queen Mary Hospital"


def _post(client, **overrides):
    body = {"hospital": QMH, "triage": "t3", "day": "Monday", "hour": 14}
    body.update(overrides)
    r = client.post("/api/query", json=body)
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    return r.get_json()


# ---------------------------------------------------------------------------
# The regression itself
# ---------------------------------------------------------------------------

def test_one_board_reading_cannot_become_four_different_facts(client, live_feed, hk_clock):
    """The headline bug, stated as a test.

    The board says 18 minutes and it is Tuesday 17:00. Asking about three other
    hours must not produce three more deltas from that one reading.
    """
    hk_clock("Tuesday", 17)
    live_feed({QMH: {"t3": 18.0}})

    now = _post(client, day="Tuesday", hour=17)
    assert now["published_minutes"] == 18.0
    assert now["delta_minutes"] is not None
    assert now["published_comparison"]["available"] is True

    for day, hour in (("Sunday", 3), ("Thursday", 9), ("Saturday", 23)):
        d = _post(client, day=day, hour=hour)
        assert d["published_minutes"] is None, (
            f"{day} {hour}:00 was handed the board's Tuesday-17:00 reading"
        )
        assert d["delta_minutes"] is None, (
            f"{day} {hour}:00 produced a delta from a figure about another hour"
        )
        assert d["verdict"] == "not_comparable"
        assert d["published_comparison"]["available"] is False
        # The forecast is history for that hour and is still perfectly valid.
        assert d["forecast_median"] is not None
        assert d["forecast_p25"] is not None
        assert d["forecast_p75"] is not None


def test_no_row_manufactures_a_badge_outside_the_current_hour(client, live_feed, hk_clock):
    """Ruttonjee swung Typical <-> Far from normal on one reading. Not any more.

    Checks every row, not just the queried hospital: the table and the chart
    read `all_hospitals`, and that is where the manufactured badges appeared.
    """
    hk_clock("Tuesday", 17)
    live_feed(None)  # irrelevant either way: nothing may be fetched at all

    d = _post(client, day="Sunday", hour=3)
    assert d["all_hospitals"], "no rows to check"
    for row in d["all_hospitals"]:
        assert row["published_minutes"] is None, row["hospital"]
        assert row["published"] is None, row["hospital"]
        assert row["delta_minutes"] is None, row["hospital"]
        assert row["verdict"] == "not_comparable", row["hospital"]


def test_the_live_feed_is_not_even_consulted_outside_the_current_hour(
    client, monkeypatch, hk_clock,
):
    """Suppression must happen at the fetch, not at the render.

    Fetching the figure and then hiding it leaves the falsehood one careless
    refactor away, and spends a network round-trip to acquire a number nobody
    may use.
    """
    import engine

    calls = []
    monkeypatch.setattr(
        engine, "_fetch_live_triage",
        lambda h, t: calls.append((h, t)) or 42.0,
    )

    hk_clock("Tuesday", 17)
    _post(client, day="Sunday", hour=3)
    assert calls == [], f"live feed consulted {len(calls)} times for a non-now hour"


# ---------------------------------------------------------------------------
# The three states stay distinguishable
# ---------------------------------------------------------------------------

def test_now_with_a_live_figure_still_compares_exactly_as_before(client, live_feed, hk_clock):
    hk_clock("Monday", 14)
    live_feed({QMH: {"t3": 400.0}})
    d = _post(client, day="Monday", hour=14)

    assert d["arrival_is_now"] is True
    assert d["published_minutes"] == 400.0
    assert d["verdict"] in ("reliable", "caution", "misleading")
    assert d["delta_minutes"] == pytest.approx(400.0 - d["forecast_median"])
    assert d["published_comparison"]["available"] is True
    assert d["published_comparison"]["reason"] is None


def test_now_with_a_dead_feed_is_no_live_data_not_not_comparable(client, live_feed, hk_clock):
    """Different problem, different remedy, so it must stay a different state.

    'The feed is down' means come back in a minute. 'Not comparable' means no
    such figure will ever exist for that hour. Collapsing them would tell a
    user to wait for something that is never coming.
    """
    hk_clock("Monday", 14)
    live_feed(None)
    d = _post(client, day="Monday", hour=14)

    assert d["arrival_is_now"] is True
    assert d["verdict"] == "no_live_data"
    assert d["published_comparison"]["available"] is False
    assert "could not be reached" in d["published_comparison"]["reason"]


def test_every_refusal_states_a_reason(client, live_feed, hk_clock):
    """A blank where a number was is not a refusal, it is a mystery.

    The whole product's argument is that a figure without context misleads:
    withholding one without saying why commits a quieter version of it.
    """
    hk_clock("Monday", 14)
    live_feed({QMH: {"t3": 30.0}})

    for day, hour in (("Sunday", 3), ("Monday", 15), ("Friday", 0)):
        d = _post(client, day=day, hour=hour)
        pc = d["published_comparison"]
        assert pc["available"] is False
        reason = pc["reason"]
        assert isinstance(reason, str) and reason.strip(), f"{day} {hour}: no reason"
        # Must name the hour it is refusing about, or the sentence is generic
        # enough to read as a bug rather than a decision.
        assert d["hour_label"] in reason, f"{day} {hour}: reason omits the hour"
        assert reason.strip().endswith("."), f"{day} {hour}: not a sentence"


def test_a_caller_supplied_figure_is_never_presented_as_a_comparison(client, hk_clock):
    """The API's testing hook must not become a way to fabricate a comparison."""
    hk_clock("Monday", 14)
    d = _post(client, day="Sunday", hour=3, published=999.0)

    assert d["published_comparison"]["available"] is False
    assert d["verdict"] == "not_comparable"
    assert "supplied with this request" in d["published_comparison"]["reason"]


# ---------------------------------------------------------------------------
# The clock is Hong Kong's, not the machine's
# ---------------------------------------------------------------------------

def test_now_is_hong_kong_not_the_machine_timezone(monkeypatch):
    """Pin a UTC instant and prove the conversion really happens.

    2026-08-10 20:00 UTC is Monday evening in London and already **Tuesday
    04:00** in Hong Kong. A server running in UTC must answer Tuesday 04:00.
    """
    from datetime import datetime, timezone

    import engine

    monkeypatch.setattr(
        engine, "_utcnow",
        lambda: datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc),
    )
    assert engine.hk_now_day_hour() == ("Tuesday", 4)
    assert engine.is_arrival_now("Tuesday", 4) is True
    assert engine.is_arrival_now("Monday", 20) is False, (
        "answered with the UTC weekday/hour instead of Hong Kong's"
    )


def test_is_arrival_now_requires_both_day_and_hour(monkeypatch):
    """'Same hour, different day' is not now. Neither is 'today, other hour'."""
    from datetime import datetime, timezone

    import engine

    monkeypatch.setattr(
        engine, "_utcnow",
        lambda: datetime(2026, 8, 10, 6, 0, tzinfo=timezone.utc),  # Mon 14:00 HKT
    )
    assert engine.is_arrival_now("Monday", 14) is True
    assert engine.is_arrival_now("Monday", 15) is False
    assert engine.is_arrival_now("Tuesday", 14) is False
