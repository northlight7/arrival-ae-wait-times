"""Extract a small, representative slice of the real corpus for the tests.

WHY: ``data/ae_corpus.json`` is 232 MB. Loading it inside a unit test to prove
``stats.quantile`` matches numpy would make the fast test slow and would tie a
pure-maths test to a huge binary-ish asset. So we pull a few thousand REAL
observed wait values out of it once, commit the result, and test against that.

The point of using real values rather than random ones is that real A&E waits
have properties random floats do not: heavy ties (dozens of identical 60.0s),
coarse quantisation (values arrive as whole minutes or clean half-hours), long
right tails, and exact zeros. Those are precisely the shapes where a
hand-rolled quantile can drift from numpy's.

Run:

    cd engine
    uv run python -m tests.make_corpus_fixture

Only re-run this when the corpus itself is intentionally rebuilt. The output
is committed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests._support import (  # noqa: E402
    CORPUS_SAMPLE,
    build_buckets_once,
    current_fingerprint,
    load_corpus_once,
)

# Six hospitals spanning the territory (New Territories East and West, Kowloon,
# Hong Kong Island, Lantau) plus the ferry-only island A&E, whose volumes are
# an order of magnitude smaller than everyone else's.
HOSPITALS = [
    "Alice Ho Miu Ling Nethersole Hospital",
    "Kwong Wah Hospital",
    "North Lantau Hospital",
    "Queen Mary Hospital",
    "St John Hospital",
    "Tuen Mun Hospital",
]

# Every distinct (triage, percentile) pair the corpus actually records.
# t1/t2 are stored as 'wt' (a single waiting time), t3/t45 as p50 and p95.
FIELDS = [
    ("t1", "wt"),
    ("t2", "wt"),
    ("t3", "p50"),
    ("t3", "p95"),
    ("t45", "p50"),
    ("t45", "p95"),
]

# Monday 03:00 (quiet), Monday 14:00 (busy weekday), Friday 20:00 (peak),
# Sunday 10:00 (weekend). Chosen to span the demand curve, not cherry-picked
# for agreeable numbers.
HOURS_OF_WEEK = [3, 14, 4 * 24 + 20, 6 * 24 + 10]

# One long pooled array: every hour of the week for one hospital x triage.
# This is the shape score_reliability's all-hours fallback actually produces,
# and the only array big enough to catch an O(n) indexing error.
POOLED = ("Prince of Wales Hospital", "t3", "p50")


def main() -> int:
    corpus = load_corpus_once()
    buckets = build_buckets_once()

    arrays = []
    for hosp in HOSPITALS:
        for triage, pct in FIELDS:
            for how in HOURS_OF_WEEK:
                b = buckets.get((hosp, triage, pct, how))
                if b is None or not b.values:
                    continue
                arrays.append({
                    "label": f"{hosp} | {triage}{pct} | hour_of_week={how}",
                    "hospital": hosp,
                    "triage": triage,
                    "percentile": pct,
                    "hour_of_week": how,
                    "values": [float(v) for v in b.values],
                })

    pooled_vals: list[float] = []
    for how in range(168):
        b = buckets.get((POOLED[0], POOLED[1], POOLED[2], how))
        if b:
            pooled_vals.extend(float(v) for v in b.values)
    if pooled_vals:
        arrays.append({
            "label": f"{POOLED[0]} | {POOLED[1]}{POOLED[2]} | pooled all hours",
            "hospital": POOLED[0],
            "triage": POOLED[1],
            "percentile": POOLED[2],
            "hour_of_week": None,
            "values": pooled_vals,
        })

    payload = {
        "_what": (
            "Real observed A&E wait values (minutes) pulled from "
            "data/ae_corpus.json. Test fixture for tests/test_stats.py, which "
            "asserts stats.quantile/median agree with numpy to 1e-9 on them."
        ),
        "_regenerate_with": "cd engine && uv run python -m tests.make_corpus_fixture",
        "_source_corpus": current_fingerprint(),
        "n_arrays": len(arrays),
        "n_values": sum(len(a["values"]) for a in arrays),
        "arrays": arrays,
    }

    CORPUS_SAMPLE.parent.mkdir(parents=True, exist_ok=True)
    with open(CORPUS_SAMPLE, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
        f.write("\n")

    size_kb = CORPUS_SAMPLE.stat().st_size / 1024
    print(f"wrote {CORPUS_SAMPLE}")
    print(f"  arrays : {payload['n_arrays']}")
    print(f"  values : {payload['n_values']}")
    print(f"  size   : {size_kb:.0f} KB")
    print(f"  corpus : {corpus.get('snapshots', {}).__len__()} dates, "
          f"{payload['_source_corpus']['sha256'][:16]}…")
    if size_kb > 1024:
        print("  WARNING: fixture is over 1 MB, trim HOURS_OF_WEEK or HOSPITALS")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
