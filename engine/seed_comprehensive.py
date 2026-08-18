"""Comprehensive corpus seeder: every available day across 12 months.

Strategy:
  - Regular weekdays (Mon/Wed/Fri/Sun): 4 key hours (00, 08, 14, 20)
  - Public holidays: all 96 snapshots (captures anomalous diurnal pattern)
  - 4 reference weeks (one per season): all 96 snapshots

Covers Sept 2025 – Aug 2026 (the archive boundary).

WARNING: the Oct 2025 claim this docstring used to make is FALSE. It said "Oct 2025
is a permanent gap, data.gov.hk holds nothing for that month". The archive holds 19
October dates (2025-10-13 to 2025-10-31, 1,770 snapshots). More broadly this seeder
samples from a design rather than from what the archive actually has, and it records
transient fetch failures in `gaps` as if they were permanent absences: 25 such dates
are wrong. Use `seed_backfill.py`, which asks the archive first.

Estimated: ~200 days, ~4,000 snapshots, ~2 hours of polite downloading.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
URL = "https%3A%2F%2Fwww.ha.org.hk%2Fopendata%2Faed%2Faedwtdata2-en.json"
BASE = "https://api.data.gov.hk/v1/historical-archive"
UA = "HKUST-AI-Literacy-Course/1.0 (educational, contact: course-admin@example.edu)"

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

# Hong Kong public holidays in the archive window, plus the day before and after,
# since holiday-adjacent days often show displaced demand.
HK_HOLIDAYS = {
    date(2025, 9, 1): "day after Summer holiday",
    date(2025, 12, 24): "Christmas Eve",
    date(2025, 12, 25): "Christmas Day",
    date(2025, 12, 26): "Boxing Day",
    date(2025, 12, 27): "day after Boxing Day",
    date(2025, 12, 31): "New Year's Eve",
    date(2026, 1, 1): "New Year's Day",
    date(2026, 1, 2): "day after New Year",
    date(2026, 2, 16): "Lunar New Year's Eve",
    date(2026, 2, 17): "Lunar New Year Day 1",
    date(2026, 2, 18): "Lunar New Year Day 2",
    date(2026, 2, 19): "Lunar New Year Day 3",
    date(2026, 4, 3): "Good Friday",
    date(2026, 4, 4): "day after Good Friday",
    date(2026, 4, 5): "Ching Ming + Easter Monday",
    date(2026, 4, 6): "day after Easter",
    date(2026, 5, 1): "Labour Day",
    date(2026, 5, 2): "day after Labour Day",
    date(2026, 5, 24): "Buddha's Birthday",
    date(2026, 6, 19): "Tuen Ng Festival",
    date(2026, 6, 20): "day after Tuen Ng",
    date(2026, 7, 1): "HKSAR Establishment Day",
    date(2026, 7, 2): "day after Establishment Day",
}

# Four reference weeks, one per season, for full diurnal capture.
REFERENCE_WEEKS = [
    (date(2025, 11, 10), date(2025, 11, 16)),   # autumn
    (date(2026, 1, 12), date(2026, 1, 18)),       # winter
    (date(2026, 4, 13), date(2026, 4, 19)),       # spring
    (date(2026, 7, 13), date(2026, 7, 19)),       # summer
]


def _get(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(1, 5):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read()
        except Exception:
            if attempt == 4:
                return None
            time.sleep(3 * attempt)
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


def _fetch_timestamps(date_str: str) -> list[str]:
    raw = _get(f"{BASE}/list-file-versions?url={URL}&start={date_str}&end={date_str}")
    if not raw:
        return []
    return json.loads(raw).get("timestamps", [])


def _fetch_one_snapshot(ts: str, *, first_error: list[str]) -> dict | None:
    raw = _get(f"{BASE}/get-file?url={URL}&time={ts}")
    if not raw:
        if len(first_error) < 3:
            first_error.append(f"{ts}")
        return None
    try:
        snap = json.loads(raw)
        _parse_wait_times(snap)
        return snap
    except Exception:
        if len(first_error) < 3:
            first_error.append(f"{ts} (parse)")
        return None


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    out_path = DATA / "ae_corpus.json"

    # Load existing corpus so we can append.
    if out_path.exists():
        bundle = json.loads(out_path.read_text())
    else:
        bundle = {"hospitals": HOSPITAL_COORDS, "snapshots": {}, "gaps": []}

    # Build the date set: all Mon/Wed/Fri/Sun in each covered month, plus
    # holidays and reference weeks.
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
        (date(2026, 8, 1), date(2026, 8, 10)),
    ]

    wanted: dict[str, str] = {}  # date_key -> reason

    for start, end in COVERED:
        d = start
        while d <= end:
            if d.weekday() in (0, 2, 4, 6):  # Mon, Wed, Fri, Sun
                wanted[d.isoformat()] = f"regular {d.strftime('%A')}"
            d += timedelta(days=1)

    for dt, reason in HK_HOLIDAYS.items():
        wanted[dt.isoformat()] = reason

    for start, end in REFERENCE_WEEKS:
        d = start
        while d <= end:
            wanted[d.isoformat()] = f"reference week ({d.strftime('%A')})"
            d += timedelta(days=1)

    # Remove dates already in the corpus.
    existing = set(bundle.get("snapshots", {}).keys())
    to_fetch = [(k, v) for k, v in sorted(wanted.items()) if k not in existing]

    if not to_fetch:
        print("Corpus already complete: every wanted date is on disk.")
        return 0

    print(f"Coverage: {len(wanted)} dates wanted, {len(existing)} already on disk, "
          f"{len(to_fetch)} to fetch")
    print(f"  Months with data: {len(COVERED)}")
    print(f"  Regular sampling: Mon/Wed/Fri/Sun in each month")
    print(f"  Public holidays: {len(HK_HOLIDAYS)} dates + adjacent days")
    print(f"  Reference weeks: {len(REFERENCE_WEEKS)} weeks (full 96/day)")
    print(f"  Known gaps: Oct 2025 (archive holds nothing)\n")

    # Determine per-date strategy.
    holiday_dates = {d.isoformat() for d in HK_HOLIDAYS}
    reference_dates = set()
    for start, end in REFERENCE_WEEKS:
        d = start
        while d <= end:
            reference_dates.add(d.isoformat())
            d += timedelta(days=1)

    first_error: list[str] = []
    total_snaps = sum(len(v) for v in bundle.get("snapshots", {}).values())
    fetched_dates = 0
    skipped_dates = 0
    gaps: set[str] = set(bundle.get("gaps", []))

    for date_key, reason in to_fetch:
        date_str = date_key.replace("-", "")
        full_day = date_key in holiday_dates or date_key in reference_dates

        print(f"  {date_key} ({reason})", end=" ", flush=True)
        timestamps = _fetch_timestamps(date_str)
        if not timestamps:
            print("no data in archive")
            gaps.add(date_key)
            skipped_dates += 1
            time.sleep(0.5)
            continue

        day_data = {}
        wanted_hours = None if full_day else {"00", "08", "14", "20"}

        for ts in timestamps:
            if wanted_hours is not None:
                hh = ts.split("-")[1][:2]
                if hh not in wanted_hours:
                    continue
            snap = _fetch_one_snapshot(ts, first_error=first_error)
            if snap:
                day_data[ts] = snap
            time.sleep(0.2)

        bundle["snapshots"][date_key] = day_data
        bundle["gaps"] = sorted(gaps)
        fetched_dates += 1
        total_snaps += len(day_data)
        print(f"{len(day_data)} snapshots "
              f"({'full day' if full_day else '4 key hours'}) "
              f"({fetched_dates} new, {total_snaps} total)")

        # Save incrementally so a crash doesn't lose everything.
        if fetched_dates % 10 == 0:
            json.dump(bundle, open(out_path, "w"), indent=2)

    json.dump(bundle, open(out_path, "w"), indent=2)

    print(f"\n{'=' * 60}")
    print(f"Done. {fetched_dates} dates fetched, {skipped_dates} skipped (gaps)")
    print(f"  {total_snaps} snapshots across {len(bundle['snapshots'])} days")
    print(f"  {len(gaps)} dates with no archive data")
    print(f"  {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")
    if first_error:
        print(f"  First errors: {first_error[:5]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
