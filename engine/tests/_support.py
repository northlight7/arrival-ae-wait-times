"""Shared machinery for the Arrival test suite.

Three jobs:

1. Load the 232 MB corpus ONCE per process and hand out the same
   hour-of-week buckets to every test. ``engine.query`` re-reads and re-buckets
   the whole corpus on every call (~2 s), which would make a golden matrix of
   dozens of queries take minutes. Memoising two *pure* functions changes no
   number: it only stops us recomputing an identical result.

2. Fingerprint the corpus, so a golden file generated against a different
   corpus is self-evidently stale instead of mysteriously failing.

3. Take the test process offline. Every live feed in this app (Hospital
   Authority waiting times, Transport Department detector speeds) refreshes
   every few minutes: letting a test see one makes the suite flaky and
   dependent on the network. We hard-fail ``urllib.request.urlopen`` so any
   unguarded network call is loud, and rely on the app's own error handling to
   produce its documented "feed unavailable" degradation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent
TESTS_DIR = ENGINE_DIR / "tests"
FIXTURES = TESTS_DIR / "fixtures"

CORPUS_SAMPLE = FIXTURES / "corpus_sample.json"
GOLDEN = FIXTURES / "golden_forecasts.json"


# ---------------------------------------------------------------------------
# Corpus, loaded once
# ---------------------------------------------------------------------------

_corpus_cache: dict | None = None
_buckets_cache: dict | None = None


def load_corpus_once() -> dict:
    global _corpus_cache
    if _corpus_cache is None:
        import engine
        _corpus_cache = engine.load_corpus()
    return _corpus_cache


def build_buckets_once() -> dict:
    global _buckets_cache
    if _buckets_cache is None:
        import engine
        _buckets_cache = engine.build_buckets(load_corpus_once())
    return _buckets_cache


def memoise_engine_corpus(monkeypatch) -> None:
    """Make ``engine.query`` reuse the already-built corpus and buckets.

    ``load_corpus`` and ``build_buckets`` are both pure: same file in, same
    dict out. Replacing them with a cached call is not a behaviour change,
    it is the difference between a 20-second suite and a 20-minute one.
    """
    import engine

    corpus = load_corpus_once()
    buckets = build_buckets_once()

    monkeypatch.setattr(engine, "load_corpus", lambda: corpus)
    monkeypatch.setattr(engine, "build_buckets", lambda _c: buckets)


# ---------------------------------------------------------------------------
# Corpus fingerprint
# ---------------------------------------------------------------------------

def corpus_fingerprint(corpus: dict, buckets: dict) -> dict:
    """A cheap, order-independent digest of the evidence behind a forecast.

    Deliberately hashes the *bucket contents* (count and sum per
    hospital x triage x percentile x hour-of-week) rather than the raw file
    bytes: re-serialising the same observations in a different key order must
    not look like a corpus change, but adding, removing or editing an
    observation must.
    """
    snapshots = corpus.get("snapshots", {})
    h = hashlib.sha256()
    for key in sorted(buckets):
        b = buckets[key]
        h.update(f"{key}|{b.n}|{sum(b.values)!r}\n".encode())
    return {
        "dates": len(snapshots),
        "snapshots": sum(len(v) for v in snapshots.values()),
        "hospitals": len(corpus.get("hospitals", {})),
        "buckets": len(buckets),
        "sha256": h.hexdigest(),
    }


def current_fingerprint() -> dict:
    return corpus_fingerprint(load_corpus_once(), build_buckets_once())


# ---------------------------------------------------------------------------
# Offline
# ---------------------------------------------------------------------------

class NetworkAccessInTest(RuntimeError):
    """Raised if anything under test tries to open a URL."""


def go_offline(monkeypatch) -> None:
    """Sever every route to the network and clear every live-feed cache.

    Both ``engine._fetch_live_triage`` and ``routing._http_get`` swallow
    exceptions and return None, which is exactly the documented
    'feed unreachable' path, so this both guarantees hermeticity and exercises
    honest degradation. A caller that does NOT guard its fetch will raise
    NetworkAccessInTest and fail the test loudly.
    """
    import urllib.request

    import routing

    def _blocked(*_a, **_kw):
        raise NetworkAccessInTest(
            "the test suite must not touch the network: "
            "live feeds change every few minutes and would make this flaky"
        )

    monkeypatch.setattr(urllib.request, "urlopen", _blocked)

    # routing caches live-feed results in module globals with a TTL. A value
    # fetched before the patch (or by another test) would leak across tests.
    monkeypatch.setattr(routing, "_ha_cache", None, raising=False)
    monkeypatch.setattr(routing, "_snapshot_cache", None, raising=False)
    monkeypatch.setattr(routing, "_snapshot_error", None, raising=False)
    monkeypatch.setattr(routing, "_snapshot_failed_at", None, raising=False)


def freeze_live_feeds(monkeypatch, published: dict | None = None) -> None:
    """Replace the live feeds with a fixed table instead of 'unavailable'.

    ``published`` is {hospital: {triage: minutes}}, where None means the feed
    is down. Used by the API contract tests that need a *present* published
    figure without asking the internet for one.
    """
    import engine
    import routing

    table = published or {}

    monkeypatch.setattr(routing, "_live_published", lambda: table)
    monkeypatch.setattr(routing, "live_published_minutes", lambda: table)
    monkeypatch.setattr(
        engine,
        "_fetch_live_triage",
        lambda hospital, triage: (table.get(hospital) or {}).get(triage),
    )
    # server.py rebinds engine._fetch_live_triage at import time to its own
    # cached shim, and holds `query` by reference. Patch the shim's source too.
    import server
    monkeypatch.setattr(
        server,
        "live_published_minutes",
        lambda: table,
        raising=False,
    )


def read_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
