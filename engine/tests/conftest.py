"""Fixtures shared by the Arrival test suite.

Everything here exists to make the suite hermetic: no network, no wall-clock
dependence, no dependence on today's date. The engine's inputs are the corpus
on disk plus explicit day/hour/published arguments, and nothing else.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tests import _support

# The instant every test runs at unless it says otherwise.
#
# 2026-08-10 06:00 UTC is **Monday 14:00 in Hong Kong**, which is exactly the
# day/hour `test_api_contract._ok()` posts by default. That is deliberate: the
# published-figure comparison is only computed when the requested arrival slot
# IS the current Hong Kong hour, so pinning the clock here is what keeps the
# pre-existing "the feed is up / the feed is down" contract tests exercising the
# comparison path they were written for.
#
# Without this fixture those tests pass or fail according to what time the suite
# happens to be run at: they would exercise the comparison on a Monday
# afternoon and the suppression path every other hour of the week. conftest's
# own docstring promises "no wall-clock dependence", and this is what makes that
# true now that the engine has a clock at all.
FROZEN_UTC = datetime(2026, 8, 10, 6, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Applied to EVERY test. Any un-guarded URL open raises."""
    _support.go_offline(monkeypatch)


@pytest.fixture(autouse=True)
def _pinned_clock(monkeypatch):
    """Applied to EVERY test: pin `engine._utcnow` to `FROZEN_UTC`.

    Patches the seam, never `datetime.now`, so the Asia/Hong_Kong conversion
    under test is the real one rather than a stub.
    """
    import engine

    monkeypatch.setattr(engine, "_utcnow", lambda: FROZEN_UTC)


@pytest.fixture
def hk_clock(monkeypatch):
    """Factory: move the pinned clock to a given Hong Kong wall time.

        hk_clock("Sunday", 3)   # -> engine now believes it is Sunday 03:00 HKT

    Returns the (day, hour) it set, so a test can assert against it without
    restating the literal.
    """
    import engine

    def _set(day: str, hour: int):
        base = FROZEN_UTC.astimezone(engine.HK_TZ)
        delta_days = engine.DAY_NAMES.index(day) - base.weekday()
        pinned = (base + __import__("datetime").timedelta(days=delta_days)).replace(
            hour=hour, minute=0, second=0, microsecond=0,
        )
        monkeypatch.setattr(engine, "_utcnow", lambda: pinned.astimezone(timezone.utc))
        assert engine.hk_now_day_hour() == (day, hour)
        return day, hour

    return _set


@pytest.fixture
def corpus():
    return _support.load_corpus_once()


@pytest.fixture
def buckets():
    return _support.build_buckets_once()


@pytest.fixture
def fast_engine(monkeypatch):
    """engine.query, without re-reading 232 MB of JSON on every call."""
    _support.memoise_engine_corpus(monkeypatch)


@pytest.fixture
def client(monkeypatch):
    """Flask test client with the corpus memoised and the feeds dead.

    Importing server rebinds engine._fetch_live_triage to its own cached shim,
    which is exactly the code path production runs, so the contract tests
    exercise the real wiring, not a simplified copy of it.
    """
    import server

    _support.memoise_engine_corpus(monkeypatch)
    # routing keeps its own bucket cache keyed on the corpus mtime, point it at
    # the already-built buckets so rank_hospitals does not rebuild them.
    import routing
    monkeypatch.setattr(routing, "_buckets", _support.build_buckets_once)

    server.app.config.update(TESTING=True)
    with server.app.test_client() as c:
        yield c


@pytest.fixture
def live_feed(monkeypatch):
    """Factory: install a fixed published-minutes table.

        live_feed({"Queen Mary Hospital": {"t3": 55.0}})
        live_feed(None)   # feed down
    """
    def _install(table):
        _support.freeze_live_feeds(monkeypatch, table)
    return _install
