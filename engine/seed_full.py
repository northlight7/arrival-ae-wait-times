"""Full-corpus seeder: every snapshot, every available day, in parallel.

Downloads ALL 96 fifteen-minute snapshots for every date the archive holds across
Sept 2025 – Aug 2026. Uses concurrent workers so the entire corpus finishes in
~30 minutes rather than ~3 hours.

Mathematical rationale:
  With 96 snapshots/day across ~10 months, each hour-of-week bucket receives
  roughly 40 observations, enough for a meaningful nonparametric interval
  without pooling. The 4-key-hour strategy left most buckets with 4–8
  observations, forcing 26% of queries into the all-hours fallback.

Run:  uv run python seed_full.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
URL = "https%3A%2F%2Fwww.ha.org.hk%2Fopendata%2Faed%2Faedwtdata2-en.json"
BASE = "https://api.data.gov.hk/v1/historical-archive"
UA = "HKUST-AI-Literacy-Course/1.0 (educational, contact: course-admin@example.edu)"
WORKERS = 8
SAVE_EVERY = 20  # save to disk every N dates so a crash only loses minutes of work

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

COVERED = [
    (date(2025, 9, 1), date(2025, 9, 30)),
    (date(2025, 11, 1), date(2025, 11, 30)),
    (date(2025, 12, 1), date(2025, 12, 31)),
    (date(2026, 1, 1), date(2026, 1, 31)),
    (date(2026, 2, 1), date(2026, 2, 28)),
    (date(2026, 3, 1), date(2026, 3, 31)),
    (date(2026, 4, 1), date(2026, 4, 30)),
    (date(2026, 5, 1), date(2026, 5, 31)),
    (date(2026, 6, 1), date(2026, 6, 30)),
    (date(2026, 7, 1), date(2026, 7, 31)),
    (date(2026, 8, 1), date(2026, 8, 11)),
]

GAPS = ["2025-10"]  # documented permanent gap


def _get(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read()
        except Exception:
            if attempt == 3:
                return None
            time.sleep(2 * (attempt + 1))
    return None


def _to_mins(value: str) -> float | None:
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


def fetch_date(date_str: str) -> tuple[str, dict[str, dict]]:
    """Fetch ALL 96 snapshots for one date. Returns (date_key, {ts: snapshot})."""
    day_data = {}
    raw = _get(f"{BASE}/list-file-versions?url={URL}&start={date_str}&end={date_str}")
    if not raw:
        return (date_str, day_data)

    timestamps = json.loads(raw).get("timestamps", [])
    for ts in timestamps:
        raw2 = _get(f"{BASE}/get-file?url={URL}&time={ts}")
        if not raw2:
            continue
        try:
            snap = json.loads(raw2)
            _parse_wait_times(snap)
            day_data[ts] = snap
        except Exception:
            continue
        time.sleep(0.08)  # ~12 req/s per worker, gentle on the archive

    return (date_str, day_data)


def all_dates() -> list[str]:
    out = []
    for start, end in COVERED:
        d = start
        while d <= end:
            out.append(d.strftime("%Y%m%d"))
            d += timedelta(days=1)
    return out


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    out_path = DATA / "ae_corpus.json"

    if out_path.exists():
        bundle = json.loads(out_path.read_text())
    else:
        bundle = {"hospitals": HOSPITAL_COORDS, "snapshots": {}, "gaps": GAPS}

    dates = all_dates()
    existing = set(bundle.get("snapshots", {}).keys())
    to_fetch = [d for d in dates if f"{d[:4]}-{d[4:6]}-{d[6:]}" not in existing]

    if not to_fetch:
        print(f"Corpus already complete: {len(dates)} dates, all on disk.")
        return 0

    print(f"Corpus: {len(dates)} total dates across 11 months")
    print(f"  Already on disk: {len(existing)}")
    print(f"  To fetch: {len(to_fetch)}")
    print(f"  Target: {len(dates) * 96:,} snapshots (~{len(dates) * 96 * 18:,} hospital-observations)")
    print(f"  Workers: {WORKERS}")
    print(f"  Known gaps: {GAPS}\n")

    total = sum(len(v) for v in bundle.get("snapshots", {}).values())
    fetched = 0
    t0 = time.monotonic()

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fetch_date, d): d for d in to_fetch}
        for future in as_completed(futures):
            date_str, day_data = future.result()
            date_key = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

            if not day_data:
                print(f"  {date_key}: no data (gap in archive)")
                continue

            bundle["snapshots"][date_key] = day_data
            fetched += 1
            total += len(day_data)
            elapsed = time.monotonic() - t0
            rate = fetched / elapsed * 60 if elapsed > 0 else 0

            print(f"  {date_key}  {len(day_data):>3} snaps  "
                  f"({fetched}/{len(to_fetch)} dates, {total:,} total, "
                  f"{rate:.0f} dates/min)")

            if fetched % SAVE_EVERY == 0:
                json.dump(bundle, open(out_path, "w"), indent=2)

    json.dump(bundle, open(out_path, "w"), indent=2)
    elapsed = time.monotonic() - t0
    print(f"\nDone in {elapsed / 60:.1f} min.")
    print(f"  {len(bundle['snapshots'])} dates, {total:,} snapshots")
    print(f"  {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
