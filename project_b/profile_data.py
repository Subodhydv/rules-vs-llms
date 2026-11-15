"""Task 1: profile the raw 2023 data and document the quality problems that already exist.

Combines (a) exact full-year counts from server-side SoQL (results/project_b_soql_profile.json if fetched,
else the committed snapshot) and (b) local checks on the downloaded sample, with examples.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from project_b.data_io import PII_RE
from project_b.schema import BOROUGHS, ISO_RE, LAT_MAX, LAT_MIN, LON_MAX, LON_MIN, OPEN_STATUSES

ROOT = Path(__file__).resolve().parents[1]
CLOSE_WORDS = re.compile(r"\b(?:responded|took action|was closed|has been closed|inspected|issued|repaired|"
                         r"no violation|were gone|not necessary|completed|corrected|resolved)\b", re.I)
OPEN_WORDS = re.compile(r"\b(?:will be|is being|still|being reviewed|has been assigned|scheduled|pending|in progress|"
                        r"under review|check back)\b", re.I)
SHOW = ["unique_key", "created_date", "closed_date", "agency", "complaint_type", "descriptor", "incident_zip",
        "borough", "status", "latitude", "longitude", "resolution_description"]


def _ex(df, mask, cols=SHOW, k=3):
    rows = df[mask].head(k)[[c for c in cols if c in df]]
    out = []
    for r in rows.to_dict("records"):
        out.append({c: (str(v)[:110] if v is not None and v == v else None) for c, v in r.items()})
    return out


def local_checks(df: pd.DataFrame) -> list[dict]:
    n = len(df)
    created = pd.to_datetime(df.created_date, errors="coerce", format="ISO8601")
    closed = pd.to_datetime(df.closed_date, errors="coerce", format="ISO8601")
    res = df.resolution_description.fillna("").astype(str)
    checks = {}
    checks["closed date before created date"] = closed < created
    checks["closed date equal to created date (zero-duration)"] = closed == created
    checks["closed date after 2026-11-15 or before 2023"] = (closed > pd.Timestamp("2026-11-15")) | (closed < pd.Timestamp("2023-01-01"))
    checks["created time exactly 00:00:00 (date-only precision)"] = (created.dt.hour == 0) & (created.dt.minute == 0) & (created.dt.second == 0)
    checks["created_date not ISO-8601"] = ~df.created_date.fillna("").astype(str).str.match(ISO_RE)
    checks["status open/in progress but closed_date set"] = df.status.isin(OPEN_STATUSES) & closed.notna()
    checks["status Closed but closed_date missing"] = (df.status == "Closed") & closed.isna()
    checks["status Closed but resolution_description missing"] = (df.status == "Closed") & df.resolution_description.isna()
    checks["resolution text says still open/pending while status is Closed"] = (df.status == "Closed") & res.str.contains(OPEN_WORDS) & ~res.str.contains(CLOSE_WORDS)
    checks["latitude/longitude missing"] = df.latitude.isna() | df.longitude.isna()
    checks["latitude/longitude outside NYC bounding box"] = df.latitude.notna() & ~(df.latitude.between(LAT_MIN, LAT_MAX) & df.longitude.between(LON_MIN, LON_MAX))
    checks["incident_zip missing"] = df.incident_zip.isna()
    checks["incident_zip not a NYC 5-digit ZIP (1xxxx)"] = df.incident_zip.notna() & ~df.incident_zip.fillna("").astype(str).str.fullmatch(r"1[0-1]\d{3}")
    checks["borough 'Unspecified' or missing"] = ~df.borough.isin(BOROUGHS)
    good = df.incident_zip.notna() & df.borough.isin(BOROUGHS)
    major = df[good].groupby("incident_zip").borough.agg(lambda s: s.value_counts().index[0])
    checks["ZIP disagrees with that ZIP's majority borough"] = good & (df.borough != df.incident_zip.map(major))
    checks["descriptor missing"] = df.descriptor.isna()
    checks["exact duplicate rows (all fields except unique_key)"] = df.drop(columns="unique_key").duplicated(keep="first")
    key = df.incident_address.fillna("") + "|" + df.complaint_type.fillna("") + "|" + df.descriptor.fillna("")
    order = df.assign(_k=key, _t=created).sort_values(["_k", "_t"])
    gap = order.groupby("_k")._t.diff().dt.total_seconds()
    nd = pd.Series(False, index=df.index)
    nd.loc[order.index] = ((gap >= 0) & (gap <= 3600) & (order._k.str.len() > 2)).values
    checks["near-duplicates: same address + type + descriptor within 1 hour"] = nd & ~checks["exact duplicate rows (all fields except unique_key)"]
    for c in ("descriptor", "resolution_description"):
        checks[f"phone number or e-mail pattern in {c}"] = df[c].fillna("").astype(str).str.contains(PII_RE)
    pairs = df.groupby(["complaint_type", "descriptor"]).size()
    rare = df.set_index(["complaint_type", "descriptor"]).index.map(pairs) <= 1
    checks["complaint_type/descriptor pair seen only once in the sample"] = pd.Series(rare, index=df.index) & df.descriptor.notna()
    ct = df.complaint_type.dropna().unique()
    lower = pd.Series(ct).str.lower().value_counts()
    casing_dups = sorted(t for t in ct if lower.get(t.lower(), 0) > 1)
    checks["complaint_type with the same name in different letter case"] = df.complaint_type.isin(casing_dups)

    out = []
    for name, mask in checks.items():
        mask = mask.fillna(False).astype(bool)
        out.append({"check": name, "count": int(mask.sum()), "pct": round(100 * mask.mean(), 3) if n else 0,
                    "examples": _ex(df, mask)})
    out.append({"check": "distinct complaint_type values", "count": int(df.complaint_type.nunique()),
                "pct": None, "examples": [{"casing_variants": casing_dups[:10]}]})
    return out


def soql_counts() -> dict:
    live = ROOT / "results" / "project_b_soql_profile.json"
    snap = Path(__file__).parent / "data" / "soql_snapshot_2026-11-15.json"
    src = live if live.exists() else snap
    d = json.loads(src.read_text())
    return {"source": src.name, **d}


def main(df: pd.DataFrame, source: str) -> dict:
    return {"data_source": source, "sample_rows": len(df), "soql_full_year": soql_counts(),
            "sample_checks": local_checks(df)}
