"""Download NYC 311 Service Requests created in calendar year 2023 from NYC Open Data (dataset erm2-nwe9).

Two things are fetched:
1. A day-stratified sample of raw rows (default 300 rows for each of the 365 days ~= 110k rows), saved to
   project_b/data/raw/nyc311_2023_sample.csv.gz. Rows are taken in unique_key order within each day.
2. Server-side SoQL aggregates over the FULL year (3.2M rows) for the profiling report, saved to
   results/project_b_soql_profile.json.

Optional env: SODA_APP_TOKEN (higher rate limits), NYC311_ROWS_PER_DAY (default 300).
Run: python -m project_b.fetch_data
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = Path(__file__).parent / "data" / "raw" / "nyc311_2023_sample.csv.gz"
API = "https://data.cityofnewyork.us/resource/erm2-nwe9.json"
COLS = ["unique_key", "created_date", "closed_date", "agency", "complaint_type", "descriptor", "location_type",
        "incident_zip", "incident_address", "borough", "status", "resolution_description", "latitude",
        "longitude", "open_data_channel_type"]
YEAR = "created_date >= '2023-01-01T00:00:00' AND created_date < '2024-01-01T00:00:00'"

# Full-year profiling queries, run server-side (counts are exact over all 2023 rows).
SOQL_CHECKS = {
    "rows_2023": "",
    "closed_before_created": "closed_date < created_date",
    "closed_equals_created": "closed_date = created_date",
    "closed_date_null": "closed_date IS NULL",
    "latitude_null": "latitude IS NULL",
    "incident_zip_null": "incident_zip IS NULL",
    "incident_zip_not_5_digit_nyc": "incident_zip NOT LIKE '1____'",
    "borough_unspecified": "borough = 'Unspecified'",
    "closed_after_fetch_date": "closed_date > '2026-11-15'",
    "resolution_null": "resolution_description IS NULL",
    "descriptor_null": "descriptor IS NULL",
}


def _get(params: dict, tries: int = 5):
    import requests
    headers = {"X-App-Token": os.environ["SODA_APP_TOKEN"]} if os.environ.get("SODA_APP_TOKEN") else {}
    for i in range(tries):
        try:
            r = requests.get(API, params=params, headers=headers, timeout=120)
            if r.status_code == 200:
                return r.json()
            time.sleep(2 ** i)
        except Exception:  # noqa: BLE001 - network hiccups: retry
            time.sleep(2 ** i)
    raise RuntimeError(f"NYC Open Data request failed: {params}")


def fetch_sample(rows_per_day: int | None = None) -> pd.DataFrame:
    import concurrent.futures
    rows_per_day = rows_per_day or int(os.environ.get("NYC311_ROWS_PER_DAY", "300"))
    d = date(2023, 1, 1)
    days = []
    while d.year == 2023:
        days.append(d)
        d += timedelta(days=1)

    def _fetch_day(day):
        nxt = day + timedelta(days=1)
        return _get({"$select": ",".join(COLS), "$where": f"created_date >= '{day}T00:00:00' AND "
                     f"created_date < '{nxt}T00:00:00'", "$limit": rows_per_day})

    frames = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for day, data in zip(days, ex.map(_fetch_day, days)):
            frames.append(pd.DataFrame(data))
            if day.day == 1:
                print(f"  fetched through {day} ({sum(len(f) for f in frames):,} rows)")
    df = pd.concat(frames, ignore_index=True)
    for c in COLS:
        if c not in df:
            df[c] = None
    RAW.parent.mkdir(parents=True, exist_ok=True)
    df[COLS].to_csv(RAW, index=False, compression="gzip")
    return df


def fetch_soql_profile() -> dict:
    out = {"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "counts": {}}
    for name, cond in SOQL_CHECKS.items():
        where = YEAR + (f" AND {cond}" if cond else "")
        try:
            out["counts"][name] = int(_get({"$select": "count(*)", "$where": where})[0]["count"])
        except Exception as e:  # noqa: BLE001
            out["counts"][name] = f"error: {e}"
    for name, group in (("status", "status"), ("borough", "borough"), ("top_agencies", "agency")):
        try:
            out[name] = _get({"$select": f"{group}, count(*) AS n", "$where": YEAR, "$group": group,
                              "$order": "n DESC", "$limit": 20})
        except Exception as e:  # noqa: BLE001
            out[name] = f"error: {e}"
    if isinstance(out["counts"].get("rows_2023"), int):   # only keep a live profile if the API answered
        (ROOT / "results").mkdir(exist_ok=True)
        (ROOT / "results" / "project_b_soql_profile.json").write_text(json.dumps(out, indent=1))
    else:
        raise RuntimeError(f"SoQL profile failed: {out['counts'].get('rows_2023')}")
    return out


if __name__ == "__main__":
    print(json.dumps(fetch_soql_profile()["counts"], indent=1))
    fetch_sample()
    print("saved", RAW)
