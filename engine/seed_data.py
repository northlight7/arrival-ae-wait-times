"""Download a representative sample of A&E archive snapshots.

data.gov.hk retains 15-minute snapshots back to at least September 2025.
Rather than download everything (hundreds of thousands of snapshots), we grab
a stratified sample: three days per available month, covering weekdays,
weekends and public holidays. That gives the engine real patterns to learn
without saturating disk.

The archive API is:
  GET /v1/historical-archive/list-file-versions?url=...&start=YYYYMMDD&end=YYYYMMDD
  -> returns timestamps

  GET /v1/historical-archive/get-file?url=...&time=YYYYMMDD-HHMM
  -> 302 to S3, follow it to get the actual JSON

Rate limit: the archive returns 403 if you hit it too fast. This script sleeps
between requests and retries on failure.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
URL = "https%3A%2F%2Fwww.ha.org.hk%2Fopendata%2Faed%2Faedwtdata2-en.json"
BASE = "https://api.data.gov.hk/v1/historical-archive"
UA = "HKUST-AI-Literacy-Course/1.0 (educational, contact: course-admin@example.edu)"

# Three days per month (a Monday, a Friday, and a Sunday) so we capture
# weekday peak, weekday off-peak, and weekend patterns.
SAMPLE_DAYS = {
    "202602": ["20260202", "20260206", "20260208"],  # Mon, Fri, Sun
    "202603": ["20260302", "20260306", "20260308"],
    "202604": ["20260406", "20260410", "20260412"],
    "202605": ["20260504", "20260508", "20260510"],
    "202606": ["20260601", "20260605", "20260607"],
    "202607": ["20260706", "20260710", "20260712"],
    "202608": ["20260803", "20260807", "20260809"],
    "202511": ["20251103", "20251107", "20251109"],
    "202509": ["20250901", "20250905", "20250907"],
}

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
    "St. Teresa's Hospital": (22.3253, 114.1775),
    "Tseung Kwan O Hospital": (22.3166, 114.2715),
    "Tuen Mun Hospital": (22.4067, 113.9765),
    "United Christian Hospital": (22.3233, 114.2289),
    "Yan Chai Hospital": (22.3698, 114.1076),
}


def _to_minutes(value: str) -> float | None:
    """Parse a HA wait-time string into minutes.

    Handles: '0 minute', 'less than 15 minutes', '30 minutes',
    '1 hour', '1.5 hours', '2.5 hours', '3 hours', etc.
    """
    s = value.strip().lower()
    if s in ("0 minute", "0 minutes"):
        return 0.0
    if s == "less than 15 minutes":
        return 7.5  # midpoint of [0,15)
    if "hour" in s:
        hours = float(s.replace("hours", "").replace("hour", "").strip())
        return hours * 60
    if "minute" in s:
        return float(s.replace("minutes", "").replace("minute", "").strip())
    return None


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(1, 5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception:
            if attempt == 4:
                raise
            time.sleep(3 * attempt)


def _parse_minutes_field(wait_times):
    """Parse all wait time string fields into float minutes in place."""
    for h in wait_times:
        for key in list(h.keys()):
            if key in ("hospName", "manageT1case", "manageT2case"):
                continue
            val = _to_minutes(h[key])
            if val is not None:
                h[f"{key}_mins"] = val


def fetch_timestamps(date_str: str) -> list[str]:
    """Get all 15-min timestamps for a given date."""
    url = f"{BASE}/list-file-versions?url={URL}&start={date_str}&end={date_str}"
    data = json.loads(_get(url))
    return data.get("timestamps", [])


def fetch_snapshot(timestamp: str) -> dict:
    """Fetch one snapshot and parse its wait times into numeric minutes."""
    url = f"{BASE}/get-file?url={URL}&time={timestamp}"
    data = json.loads(_get(url))
    _parse_minutes_field(data.get("waitTime", []))
    return data


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)

    # Bundle hospital coordinates so every snapshot carries geo
    bundle = {"hospitals": HOSPITAL_COORDS, "snapshots": {}}

    total_dates = sum(len(days) for days in SAMPLE_DAYS.values())
    fetched = 0

    for month, days in SAMPLE_DAYS.items():
        for date_str in days:
            key = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
            if key in bundle["snapshots"]:
                continue

            print(f"  {key} ...", end=" ", flush=True)
            try:
                timestamps = fetch_timestamps(date_str)
            except Exception as e:
                print(f"ERROR listing: {e}")
                continue

            if not timestamps:
                print("no data for this date")
                continue

            day_data = {}
            for ts in timestamps:
                try:
                    snap = fetch_snapshot(ts)
                    day_data[ts] = snap
                except Exception as e:
                    print(f"WARN {ts}: {e}", end=" ", flush=True)
                    time.sleep(5)
                    continue
                time.sleep(0.3)  # be polite to the archive

            bundle["snapshots"][key] = day_data
            print(f"{len(day_data)} snapshots")
            fetched += 1

    # Save
    out = DATA / "ae_corpus.json"
    with open(out, "w") as f:
        json.dump(bundle, f, indent=2, default=str)
    print(f"\nWrote {out} ({out.stat().st_size / 1e6:.1f} MB)")
    print(f"  {fetched} dates, {sum(len(v) for v in bundle['snapshots'].values())} snapshots total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
