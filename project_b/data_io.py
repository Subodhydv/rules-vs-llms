"""Load the 2023 sample, enforce the batch contract, build a clean pool, split reference vs evaluation data."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from project_b import fetch_data
from project_b.schema import BOROUGHS, COLUMNS, ISO_RE, LAT_MAX, LAT_MIN, LON_MAX, LON_MIN, OPEN_STATUSES

PII_RE = re.compile(r"\b\d{3}[\s.-]?\d{3}[\s.-]?\d{4}\b|[\w.+-]+@[\w-]+\.\w+")


def load_raw() -> tuple[pd.DataFrame, str]:
    """Returns (df, source) where source is 'nyc_open_data' or 'SYNTHETIC_FIXTURE'."""
    if fetch_data.RAW.exists():
        return coerce(pd.read_csv(fetch_data.RAW, dtype=str, keep_default_na=False, na_values=[""])), "nyc_open_data"
    from project_b import fixture
    return coerce(fixture.make()), "SYNTHETIC_FIXTURE"


def coerce(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c, t in COLUMNS.items():
        if c not in df:
            df[c] = None
        if t == "float64":
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
        elif t == "int64":
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(-1).astype("int64")
        else:
            df[c] = df[c].astype(object).where(df[c].notna(), None)
    return df[list(COLUMNS)]


def clean_mask(df: pd.DataFrame) -> pd.Series:
    """Rows that pass basic validity — the pool from which 'clean' batches are drawn. Deliberately simple and
    documented, because it is shared with the rule detectors (so their clean-batch false-alarm rate is partly
    by construction; we therefore also report alert rates on RAW batches)."""
    created = pd.to_datetime(df.created_date, errors="coerce", format="ISO8601")
    closed = pd.to_datetime(df.closed_date, errors="coerce", format="ISO8601")
    ok = df.created_date.fillna("").astype(str).str.match(ISO_RE) & created.notna()
    ok &= closed.isna() | (closed >= created)
    ok &= df.latitude.between(LAT_MIN, LAT_MAX) & df.longitude.between(LON_MIN, LON_MAX)
    ok &= df.incident_zip.fillna("").astype(str).str.fullmatch(r"1[0-1]\d{3}")
    ok &= df.borough.isin(BOROUGHS)
    ok &= df.agency.notna() & df.complaint_type.notna() & df.descriptor.notna()
    ok &= df.status.notna() & df.resolution_description.notna()
    ok &= ~(df.status.isin(OPEN_STATUSES) & df.closed_date.notna())
    for c in ("descriptor", "resolution_description"):
        ok &= ~df[c].fillna("").astype(str).str.contains(PII_RE)
    ok &= ~df.drop(columns="unique_key").duplicated(keep=False)
    # ZIP must map to its majority borough
    major = df[ok].groupby("incident_zip").borough.agg(lambda s: s.value_counts().index[0])
    ok &= df.borough == df.incident_zip.map(major)
    return ok


def split(df: pd.DataFrame, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reference half (to fit lookup tables and statistics) and evaluation half (to draw batches from)."""
    clean = df[clean_mask(df)].sample(frac=1, random_state=seed).reset_index(drop=True)
    half = len(clean) // 2
    return clean.iloc[:half].reset_index(drop=True), clean.iloc[half:].reset_index(drop=True)


def batches(pool: pd.DataFrame, n: int, size: int, seed: int) -> list[pd.DataFrame]:
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        idx = rng.choice(len(pool), size=min(size, len(pool)), replace=False)
        out.append(pool.iloc[np.sort(idx)].reset_index(drop=True))
    return out
