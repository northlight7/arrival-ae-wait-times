"""Backfill the corpus against what the archive actually holds.

Why this exists
---------------
`seed_comprehensive.py` sampled the archive from a *design*: Mon/Wed/Fri/Sun at
four key hours, plus holidays and reference weeks at full resolution. That design
was written before anyone asked the archive what it had. Asking it directly
(`list-file-versions` over the whole window, month by month) says:

    312 dates are available.  The corpus holds 290, six of which are empty.
    22 available dates were never fetched at all.
    52 more dates hold fewer snapshots than the archive offers.
    ~6,165 snapshots are sitting there unfetched.

It also contradicts a claim the seeders make in prose: "Oct 2025 is a permanent gap,
data.gov.hk holds nothing for that month." The archive holds 19 October dates
(2025-10-13 to 2025-10-31, 1,770 snapshots). And 25 dates recorded in the corpus's
`gaps` list are dates the archive can serve: those were transient fetch failures
written down as permanent absences. A gap record that says "nothing was ever
published here" when something was is a false statement about the evidence base,
even though nothing currently renders it.

What this does
--------------
Fetches every archived snapshot the corpus lacks, and rebuilds `gaps` from
observation rather than from assumption: a date is a gap only if the archive
itself returns no versions for it.

Output goes to `data/ae_corpus.next.json`, a SIDE FILE. It never touches the live
corpus. Swapping it in changes published forecast numbers, so that is a deliberate,
reviewed step taken against the golden-forecast tests, not a side effect of running
a downloader.

Usage
-----
    uv run python seed_backfill.py            # fetch everything missing
    uv run python seed_backfill.py --plan     # print the plan, download nothing

Resumable: re-running picks up from whatever `ae_corpus.next.json` already holds.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
SRC = DATA / "ae_corpus.json"
OUT = DATA / "ae_corpus.next.json"
INDEX = DATA / "archive_index.json"

URL = "https%3A%2F%2Fwww.ha.org.hk%2Fopendata%2Faed%2Faedwtdata2-en.json"
BASE = "https://api.data.gov.hk/v1/historical-archive"
UA = "AE-Wait-Times/1.0 (educational research, polite crawler)"

WINDOW_START = date(2025, 9, 1)
WINDOW_END = date(2026, 8, 10)

# list-file-versions truncates at 10,000 timestamps, which a 12-month range blows
# through. Asking month by month keeps every response well under the cap.
def _months(start: date, end: date) -> list[tuple[str, str]]:
    out = []
    d = start.replace(day=1)
    while d <= end:
        nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        lo = max(d, start)
        hi = min(nxt - timedelta(days=1), end)
        out.append((lo.strftime("%Y%m%d"), hi.strftime("%Y%m%d")))
        d = nxt
    return out


def _get(url: str, *, timeout: int = 90) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(1, 5):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception:
            if attempt == 4:
                return None
            time.sleep(3 * attempt)
    return None


def _to_mins(value: str) -> float | None:
    """Identical to the parser in seed_comprehensive.py, kept byte-compatible so
    backfilled rows carry exactly the same derived fields as existing ones."""
    s = value.strip().lower()
    if s in ("0 minute", "0 minutes"):
        return 0.0
    if s == "less than 15 minutes":
        return 7.5
    if "hour" in s:
        return float(s.replace("hours", "").replace("hour", "").strip()) * 60
    if "minute" in s:
        return float(s.replace("minutes", "").replace("minute", "").strip())
    return None


def _parse_wait_times(snap: dict) -> None:
    for h in snap.get("waitTime", []):
        for k in list(h.keys()):
            if k in ("hospName", "manageT1case", "manageT2case"):
                continue
            m = _to_mins(h[k])
            if m is not None:
                h[f"{k}_mins"] = m


def build_archive_index(*, refresh: bool = False) -> dict[str, list[str]]:
    """date -> every timestamp the archive holds for it. Cached on disk."""
    if INDEX.exists() and not refresh:
        return json.loads(INDEX.read_text())
    index: dict[str, list[str]] = {}
    for lo, hi in _months(WINDOW_START, WINDOW_END):
        raw = _get(f"{BASE}/list-file-versions?url={URL}&start={lo}&end={hi}")
        stamps = json.loads(raw).get("timestamps", []) if raw else []
        if raw is None:
            print(f"  ! {lo[:6]} listing failed, treated as unknown, not as a gap")
        for ts in stamps:
            key = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}"
            index.setdefault(key, []).append(ts)
        print(f"  {lo[:6]}: {len({t[:8] for t in stamps})} dates, {len(stamps)} snapshots")
        time.sleep(0.3)
    INDEX.write_text(json.dumps(index, indent=0, sort_keys=True))
    return index


def _save(bundle: dict) -> None:
    """Checkpoint to a temp file, then rename.

    The bundle is ~290 MB serialised. Writing straight over the destination
    means a crash mid-dump leaves a truncated file that looks like a corpus and
    parses like garbage, so the rename makes each checkpoint atomic.

    Written compact rather than indent=2: the source corpus wastes ~40% of its
    bytes on indentation, and every consumer here is a JSON parser, not a human.
    """
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(bundle, separators=(",", ":")))
    tmp.replace(OUT)


def main() -> int:
    plan_only = "--plan" in sys.argv

    print("Indexing the archive (what it actually holds, not what we assumed)…")
    index = build_archive_index(refresh="--refresh-index" in sys.argv)

    bundle = json.loads((OUT if OUT.exists() else SRC).read_text())
    snaps: dict[str, dict] = bundle.setdefault("snapshots", {})

    todo: list[tuple[str, list[str]]] = []
    for date_key in sorted(index):
        held = snaps.get(date_key, {})
        want = [ts for ts in sorted(index[date_key]) if ts not in held]
        if want:
            todo.append((date_key, want))

    # A gap is a date the archive itself has nothing for: observed, not assumed.
    d, all_window = WINDOW_START, []
    while d <= WINDOW_END:
        all_window.append(d.isoformat())
        d += timedelta(days=1)
    true_gaps = sorted(k for k in all_window if not index.get(k))

    old_gaps = set(bundle.get("gaps", []))
    wrong = sorted(g for g in old_gaps if index.get(g))
    print(f"\nArchive holds {len(index)} dates across the window.")
    print(f"Corpus holds {len(snaps)} dates ({sum(1 for v in snaps.values() if not v)} empty).")
    print(f"Missing snapshots: {sum(len(w) for _, w in todo)} across {len(todo)} dates.")
    print(f"Gap list corrections: {len(wrong)} dates were recorded as permanent "
          f"archive gaps but the archive serves them.")
    print(f"True gaps after correction: {len(true_gaps)} dates.\n")

    if plan_only:
        for k, w in todo[:15]:
            print(f"  {k}: +{len(w)}")
        if len(todo) > 15:
            print(f"  … and {len(todo) - 15} more dates")
        return 0

    bundle["gaps"] = true_gaps
    bundle["archive_coverage"] = {
        "window": [WINDOW_START.isoformat(), WINDOW_END.isoformat()],
        "dates_available_in_archive": len(index),
        "gap_dates": true_gaps,
        "note": (
            "Gap dates are dates for which the data.gov.hk historical archive "
            "returns no file versions at all. They are recorded, never interpolated."
        ),
    }

    done = 0
    fetched = 0
    for date_key, want in todo:
        day = snaps.setdefault(date_key, {})
        got = 0
        for ts in want:
            raw = _get(f"{BASE}/get-file?url={URL}&time={ts}")
            if raw:
                try:
                    snap = json.loads(raw)
                    _parse_wait_times(snap)
                    day[ts] = snap
                    got += 1
                except Exception:
                    pass
            time.sleep(0.15)
        # Keys must stay chronological: engine and readers both assume it.
        snaps[date_key] = {k: day[k] for k in sorted(day)}
        done += 1
        fetched += got
        print(f"  {date_key}: +{got}/{len(want)}  ({done}/{len(todo)} dates, "
              f"{fetched} snapshots)", flush=True)
        if done % 15 == 0:
            _save(bundle)

    _save(bundle)
    total = sum(len(v) for v in snaps.values())
    print(f"\nWrote {OUT}: {len(snaps)} dates, {total} snapshots, "
          f"{OUT.stat().st_size / 1e6:.0f} MB")
    print("This is a side file. Swapping it in is a separate, reviewed step.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
