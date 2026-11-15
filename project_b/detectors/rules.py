"""Family (a): declarative rules and schema checks. One detector per problem type.

Reference tables (ZIP -> boroughs, allowed complaint/descriptor pairs) are *learned once* from the reference
data and then applied as fixed lookups; they are reviewable files, not models.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from project_b.detectors.base import Detector, Result, col
from project_b.schema import BOROUGHS, COLUMNS, ISO_RE, LAT_MAX, LAT_MIN, LON_MAX, LON_MIN, NUMERIC, OPEN_STATUSES

CLOSE_WORDS = re.compile(r"\b(?:responded|took action|was closed|has been closed|inspected|issued|repaired|"
                         r"no violation|were gone|not necessary|completed|corrected|resolved|collected|cleaned|"
                         r"found no|did not find|determined)\b", re.I)
OPEN_WORDS = re.compile(r"\b(?:will be|is being|still|being reviewed|has been assigned|scheduled|pending|"
                        r"in progress|under review|check back|has been received)\b", re.I)
PHONE = re.compile(r"(?:\+1[\s.-]?)?\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
NAME = re.compile(r"\b(?:[Tt]enant|[Cc]aller|[Cc]ontact|[Cc]omplainant|Mr\.?|Ms\.?|Mrs\.?)\s+[A-Z][a-z]+\s+[A-Z][a-z']+")
ZIP_PREFIX = {"100": "MANHATTAN", "101": "MANHATTAN", "102": "MANHATTAN", "103": "STATEN ISLAND",
              "104": "BRONX", "112": "BROOKLYN", "110": "QUEENS", "111": "QUEENS", "113": "QUEENS",
              "114": "QUEENS", "116": "QUEENS"}


def _dt(s):
    return pd.to_datetime(s, errors="coerce", format="ISO8601")


class SchemaColumns(Detector):
    problem, family, name, explain_score = "a_schema_column", "rule", "expected column set", 3
    example_alert = "schema: column 'borough' missing; unexpected column 'Borough'"

    def detect(self, df):
        missing = [c for c in COLUMNS if c not in df.columns]
        extra = [c for c in df.columns if c not in COLUMNS]
        alerts = [f"schema: column '{c}' missing" for c in missing] + [f"schema: unexpected column '{c}'" for c in extra]
        return Result(np.zeros(len(df), bool), bool(alerts), alerts)


class DtypeCheck(Detector):
    problem, family, name, explain_score = "b_type_change", "rule", "declared dtype per column", 3
    example_alert = "type: 'latitude' arrived as object (expected float64); row 17 value 'N/A' is not a number"

    def detect(self, df):
        alerts, flags = [], np.zeros(len(df), bool)
        for c in NUMERIC:
            if c in df.columns and not pd.api.types.is_numeric_dtype(df[c]):
                alerts.append(f"type: '{c}' arrived as {df[c].dtype} (expected {COLUMNS[c]})")
                bad = pd.to_numeric(df[c], errors="coerce").isna() & df[c].notna()
                flags |= bad.values
                for i in np.flatnonzero(bad.values)[:3]:
                    alerts.append(f"type: row {i} {c}={df[c].iloc[i]!r} is not a number")
        return Result(flags, bool(alerts), alerts)


class DateFormatRule(Detector):
    problem, family, name, explain_score = "c_date_format", "rule", "ISO-8601 regex on date columns", 3
    example_alert = "date: row 1400 created_date '03/14/2023 09:12:00 PM' is not ISO-8601 (YYYY-MM-DDTHH:MM:SS)"

    def detect(self, df):
        flags = np.zeros(len(df), bool)
        for c in ("created_date", "closed_date"):
            s = col(df, c)
            flags |= (s.notna() & ~s.fillna("").astype(str).str.match(ISO_RE)).values
        return self.rows_result(df, flags, lambda i: f"date: row {i} created_date {col(df, 'created_date').iloc[i]!r} is not ISO-8601")


class LatLonBounds(Detector):
    problem, family, name, explain_score = "d_latlon_swap", "rule", "NYC bounding box", 3
    example_alert = "geo: row 88 lat=-73.95 lon=40.71 outside NYC box (lat 40.47-40.93, lon -74.27 to -73.68); looks swapped"

    def detect(self, df):
        lat = pd.to_numeric(col(df, "latitude"), errors="coerce")
        lon = pd.to_numeric(col(df, "longitude"), errors="coerce")
        bad = lat.notna() & lon.notna() & ~(lat.between(LAT_MIN, LAT_MAX) & lon.between(LON_MIN, LON_MAX))
        swapped = lon.between(LAT_MIN, LAT_MAX) & lat.between(LON_MIN, LON_MAX)
        return self.rows_result(df, bad.values, lambda i: f"geo: row {i} lat={lat.iloc[i]} lon={lon.iloc[i]} outside "
                                f"NYC box{'; looks swapped' if swapped.iloc[i] else ''}")


class ExactDupRule(Detector):
    problem, family, name, explain_score = "e_exact_dup", "rule", "identical row (incl. unique_key)", 3
    example_alert = "dup: row 912 is identical to an earlier row (unique_key 56931202)"

    def detect(self, df):
        d = df.astype(str).duplicated(keep="first").values
        return self.rows_result(df, d, lambda i: f"dup: row {i} identical to an earlier row (unique_key {df.unique_key.iloc[i] if 'unique_key' in df else '?'})")


class NearDupRule(Detector):
    problem, family, name, explain_score = "f_near_dup", "rule", "same address+type+descriptor within 15 min", 3
    example_alert = "near-dup: row 403 matches row 594 (same address, type, descriptor) 7 min apart"

    def detect(self, df):
        key = (col(df, "incident_address").fillna("").astype(str).str.upper().str.strip() + "|" +
               col(df, "complaint_type").fillna("").astype(str).str.upper() + "|" +
               col(df, "descriptor").fillna("").astype(str).str.upper().str.strip())
        t = _dt(col(df, "created_date"))
        o = pd.DataFrame({"k": key, "t": t}).sort_values(["k", "t"])
        gap = o.groupby("k").t.diff().dt.total_seconds()
        hit = (gap >= 0) & (gap <= 900) & (o.k.str.len() > 3)
        flags = np.zeros(len(df), bool)
        flags[o.index[hit.values]] = True
        if "unique_key" in df:  # exact copies (same key) are e_exact_dup's job
            flags &= ~df.astype(str).duplicated(keep="first").values
        return self.rows_result(df, flags, lambda i: f"near-dup: row {i} same address/type/descriptor as another request within 15 min")


class NullRateRule(Detector):
    problem, family, name, explain_score = "g_null_spike", "rule", "per-agency null rate > 30% on location fields", 3
    example_alert = "nulls: agency DOT has 52% null incident_zip (threshold 30%, 181 of 348 rows)"
    COLS = ["incident_zip", "incident_address", "latitude", "longitude", "descriptor", "resolution_description"]

    def detect(self, df):
        alerts, flags = [], np.zeros(len(df), bool)
        for ag, g in df.groupby(col(df, "agency").fillna("?")):
            if len(g) < 20:
                continue
            for c in self.COLS:
                if c in g and g[c].isna().mean() > 0.30:
                    alerts.append(f"nulls: agency {ag} has {g[c].isna().mean():.0%} null {c} "
                                  f"(threshold 30%, {g[c].isna().sum()} of {len(g)} rows)")
                    flags[g.index[g[c].isna()].values] = True
        return Result(flags, bool(alerts), alerts[:6])


class ClosedBeforeCreatedRule(Detector):
    problem, family, name, explain_score = "h_closed_before_created", "rule", "closed_date >= created_date", 3
    example_alert = "dates: row 5 closed 2023-03-01T10:00 is before created 2023-03-04T08:12"

    def detect(self, df):
        c, d = _dt(col(df, "created_date")), _dt(col(df, "closed_date"))
        bad = (d < c).values
        return self.rows_result(df, bad, lambda i: f"dates: row {i} closed {d.iloc[i]} is before created {c.iloc[i]}")


class ZipBoroughRule(Detector):
    problem, family, name, explain_score = "i_zip_borough", "rule", "ZIP->borough lookup (+ prefix fallback)", 3
    example_alert = "zip: row 31 ZIP 11226 belongs to BROOKLYN but borough is QUEENS"

    def fit(self, ref):
        share = ref.groupby(["incident_zip", "borough"]).size() / ref.groupby("incident_zip").size()
        self.allowed = {}
        for (z, b), s in share.items():
            if s >= 0.05:
                self.allowed.setdefault(z, set()).add(b)
        return self

    def detect(self, df):
        z, b = col(df, "incident_zip").fillna("").astype(str), col(df, "borough")
        expected = []
        flags = np.zeros(len(df), bool)
        for i, (zz, bb) in enumerate(zip(z, b)):
            if bb not in BOROUGHS or not re.fullmatch(r"\d{5}", zz):
                expected.append(None)
                continue
            ok = self.allowed.get(zz) or ({ZIP_PREFIX[zz[:3]]} if zz[:3] in ZIP_PREFIX else None)
            expected.append(ok)
            flags[i] = ok is not None and bb not in ok
        return self.rows_result(df, flags, lambda i: f"zip: row {i} ZIP {z.iloc[i]} belongs to "
                                f"{'/'.join(sorted(expected[i]))} but borough is {b.iloc[i]}")


class PairAllowlistRule(Detector):
    problem, family, name, explain_score = "j_type_descriptor", "rule", "allowed (type, descriptor) pairs", 3
    example_alert = "pair: row 77 descriptor 'Pothole' never occurs with complaint type 'Noise - Residential'"

    def fit(self, ref):
        self.pairs = set(zip(ref.complaint_type, ref.descriptor))
        self.types = set(ref.complaint_type)
        return self

    def detect(self, df):
        t, d = col(df, "complaint_type"), col(df, "descriptor")
        flags = np.array([(tt in self.types) and (tt, dd) not in self.pairs for tt, dd in zip(t, d)])
        return self.rows_result(df, flags, lambda i: f"pair: row {i} descriptor {d.iloc[i]!r} never occurs with "
                                f"complaint type {t.iloc[i]!r}")


class StatusKeywordRule(Detector):
    problem, family, name, explain_score = "k_resolution_status", "rule", "closure/pending keywords vs status", 3
    example_alert = "status: row 12 status 'Open' but resolution says 'responded ... took action'"

    def detect(self, df):
        s, r = col(df, "status").fillna(""), col(df, "resolution_description").fillna("").astype(str)
        closed_txt, open_txt = r.str.contains(CLOSE_WORDS), r.str.contains(OPEN_WORDS)
        bad = (s.isin(OPEN_STATUSES) & closed_txt & ~open_txt) | ((s == "Closed") & open_txt & ~closed_txt)
        return self.rows_result(df, bad.values, lambda i: f"status: row {i} status {s.iloc[i]!r} but resolution "
                                f"reads {r.iloc[i][:70]!r}")


class PIIRegexRule(Detector):
    problem, family, name, explain_score = "l_pii", "rule", "phone/e-mail/name-after-title regex", 3
    example_alert = "pii: row 44 resolution_description contains phone '(917) 555-0142'"

    def detect(self, df):
        flags = np.zeros(len(df), bool)
        what = {}
        for c in ("descriptor", "resolution_description"):
            s = col(df, c).fillna("").astype(str)
            for lab, rx in (("phone", PHONE), ("e-mail", EMAIL), ("name", NAME)):
                m = s.str.contains(rx).values
                for i in np.flatnonzero(m & ~flags):
                    what[i] = f"{c} contains {lab}"
                flags |= m
        return self.rows_result(df, flags, lambda i: f"pii: row {i} {what.get(i, '')}")


ALL = [SchemaColumns, DtypeCheck, DateFormatRule, LatLonBounds, ExactDupRule, NearDupRule, NullRateRule,
       ClosedBeforeCreatedRule, ZipBoroughRule, PairAllowlistRule, StatusKeywordRule, PIIRegexRule]
