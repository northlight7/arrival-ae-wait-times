"""Deliberately regenerate tests/fixtures/golden_forecasts.json.

    cd engine
    uv run python -m tests.regen_golden          # write, showing a summary
    uv run python -m tests.regen_golden --check  # exit 1 if it would change

WHEN TO RUN THIS
----------------
Only after an INTENTIONAL change to the corpus or to the forecast maths, and
only as a separate commit whose diff a reviewer can read. The release gate is
"a full-corpus rebuild still produces identical forecasts", and regenerating the
golden file is how you say out loud that you meant to move the numbers.

If you run it to make a red test go green without knowing why the numbers
moved, you have deleted the only regression detector this project has.

The written file records the corpus fingerprint it was generated against, so a
golden file left behind by an old corpus is self-evident rather than mysterious.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _monkeypatch_free_setup():
    """Same hermetic setup the test fixtures install, without pytest."""
    import urllib.request

    import engine
    import routing

    from tests import _support

    def _blocked(*_a, **_kw):
        raise _support.NetworkAccessInTest("regen must not read live feeds")

    urllib.request.urlopen = _blocked
    routing._ha_cache = None
    routing._snapshot_cache = None

    corpus = _support.load_corpus_once()
    buckets = _support.build_buckets_once()
    engine.load_corpus = lambda: corpus
    engine.build_buckets = lambda _c: buckets
    return corpus, buckets


def build_payload() -> dict:
    from tests import _support
    from tests.golden_matrix import RECORDED_FIELDS, run_matrix

    corpus, buckets = _monkeypatch_free_setup()
    cases = run_matrix()

    return {
        "_what": (
            "Frozen forecast output for a fixed, deterministic query matrix. "
            "tests/test_forecast_golden.py re-runs the matrix and requires "
            "byte-identical results. This is the project's forecast-regression "
            "detector."
        ),
        "_regenerate_with": "cd engine && uv run python -m tests.regen_golden",
        "_read_this_first": (
            "Regenerate ONLY for an intentional corpus or maths change, as its "
            "own reviewable commit. If _corpus_fingerprint below no longer "
            "matches the corpus on disk, this file is stale and every number "
            "in it describes a corpus that no longer exists."
        ),
        "_excluded_on_purpose": (
            "live published minutes, travel time and traffic are NOT recorded: "
            "they change every 15 minutes and would make the suite flaky. "
            "Every case supplies its own `published` value as an explicit input."
        ),
        "_recorded_fields": list(RECORDED_FIELDS),
        "_corpus_fingerprint": _support.corpus_fingerprint(corpus, buckets),
        "n_cases": len(cases),
        "cases": cases,
    }


def serialise(payload: dict) -> str:
    return json.dumps(payload, indent=1, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    from tests._support import GOLDEN

    text = serialise(build_payload())

    if "--check" in argv:
        if not GOLDEN.exists():
            print(f"MISSING {GOLDEN}")
            return 1
        current = GOLDEN.read_text(encoding="utf-8")
        if current == text:
            print("golden file is up to date")
            return 0
        print("golden file DIFFERS from what the engine produces now")
        return 1

    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    existed = GOLDEN.exists()
    previous = GOLDEN.read_text(encoding="utf-8") if existed else None
    GOLDEN.write_text(text, encoding="utf-8")

    payload = json.loads(text)
    fp = payload["_corpus_fingerprint"]
    print(f"wrote {GOLDEN}")
    print(f"  cases  : {payload['n_cases']}")
    print(f"  corpus : {fp['dates']} dates, {fp['snapshots']} snapshots, "
          f"sha256 {fp['sha256'][:16]}…")
    if existed and previous != text:
        print("  NOTE: the forecast numbers CHANGED. Review the diff before "
              "committing, that is the whole point of this file.")
    elif existed:
        print("  no change")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
