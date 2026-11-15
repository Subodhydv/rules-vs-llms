"""Family (b): statistical / ML detectors, fitted on the reference data. One per problem type."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from project_b.detectors.base import Detector, Result, col
from project_b.schema import COLUMNS, NUMERIC, OPEN_STATUSES


def _dt(s):
    return pd.to_datetime(s, errors="coerce", format="ISO8601")


def _profile(s: pd.Series) -> np.ndarray:
    st = s.dropna().fillna("").astype(str)
    return np.array([s.isna().mean(), st.str.len().mean() if len(st) else 0, st.nunique() / max(len(st), 1),
                     pd.to_numeric(st, errors="coerce").notna().mean() if len(st) else 0])


class ColumnProfileDrift(Detector):
    problem, family, name, explain_score = "a_schema_column", "stat", "column-profile match (renames by profile)", 2
    example_alert = "profile: reference column 'incident_zip' absent; new column 'zip_code' matches its profile (distance 0.03)"

    def fit(self, ref):
        self.ref = {c: _profile(ref[c]) for c in COLUMNS}
        return self

    def detect(self, df):
        alerts = []
        missing = [c for c in self.ref if c not in df.columns]
        new = [c for c in df.columns if c not in self.ref]
        for m in missing:
            if new:
                d = {n: float(np.abs((_profile(df[n]) - self.ref[m]) / (np.abs(self.ref[m]) + 1)).mean()) for n in new}
                best = min(d, key=d.get)
                alerts.append(f"profile: reference column '{m}' absent; new column '{best}' matches its profile "
                              f"(distance {d[best]:.2f})")
            else:
                alerts.append(f"profile: reference column '{m}' absent from batch")
        for n in new:
            if not missing:
                alerts.append(f"profile: unseen column '{n}'")
        return Result(np.zeros(len(df), bool), bool(alerts), alerts)


class ParseRateDrift(Detector):
    problem, family, name, explain_score = "b_type_change", "stat", "numeric parse-rate vs reference (binomial z)", 2
    example_alert = "parse-rate: 'latitude' 95.0% numeric vs 100.0% in reference (z=-22)"

    def fit(self, ref):
        self.p = {c: float(pd.to_numeric(ref[c], errors="coerce").notna()[ref[c].notna()].mean()) for c in NUMERIC}
        return self

    def detect(self, df):
        alerts, flags = [], np.zeros(len(df), bool)
        for c in NUMERIC:
            if c not in df:
                continue
            s = df[c][df[c].notna()]
            if not len(s):
                continue
            num = pd.to_numeric(s, errors="coerce").notna()
            p0 = min(self.p[c], 0.9999)
            z = (num.mean() - p0) / np.sqrt(p0 * (1 - p0) / len(s))
            if z < -6:
                alerts.append(f"parse-rate: '{c}' {num.mean():.1%} numeric vs {self.p[c]:.1%} in reference (z={z:.0f})")
                flags[s.index[~num.values]] = True
        return Result(flags, bool(alerts), alerts)


def _shape(x: str) -> str:
    return re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "9", x))


class DatePatternFrequency(Detector):
    problem, family, name, explain_score = "c_date_format", "stat", "date shape-pattern frequency", 2
    example_alert = "date-shape: row 1400 shape '99/99/9999 99:99:99 AA' has reference frequency 0 (usual '9999-99-99A99:99:99.999')"

    def fit(self, ref):
        self.freq = ref.created_date.dropna().fillna("").astype(str).map(_shape).value_counts(normalize=True).to_dict()
        self.top = max(self.freq, key=self.freq.get)
        return self

    def detect(self, df):
        flags = np.zeros(len(df), bool)
        for c in ("created_date", "closed_date"):
            s = col(df, c)
            shp = s.dropna().fillna("").astype(str).map(_shape)
            rare = shp.map(lambda x: self.freq.get(x, 0.0) < 1e-4)
            flags[rare.index[rare.values]] = True
        shape = col(df, "created_date").fillna("").astype(str).map(_shape)
        return self.rows_result(df, flags, lambda i: f"date-shape: row {i} shape {shape.iloc[i]!r} rare in reference "
                                f"(usual {self.top!r})")


class GeoIsolationForest(Detector):
    problem, family, name, explain_score = "d_latlon_swap", "stat", "IsolationForest on (lat, lon)", 1
    example_alert = "geo-outlier: row 88 (lat -73.95, lon 40.71) anomaly score -0.31 < threshold -0.12"

    def fit(self, ref):
        x = ref[["latitude", "longitude"]].dropna().to_numpy()
        self.model = IsolationForest(n_estimators=100, random_state=0).fit(x)
        self.thr = float(np.quantile(self.model.score_samples(x), 0.0005))
        return self

    def detect(self, df):
        lat = pd.to_numeric(col(df, "latitude"), errors="coerce")
        lon = pd.to_numeric(col(df, "longitude"), errors="coerce")
        ok = (lat.notna() & lon.notna()).values
        flags = np.zeros(len(df), bool)
        scores = np.full(len(df), np.nan)
        if ok.any():
            scores[ok] = self.model.score_samples(np.c_[lat[ok], lon[ok]])
            flags[ok] = scores[ok] < self.thr
        return self.rows_result(df, flags, lambda i: f"geo-outlier: row {i} (lat {lat.iloc[i]}, lon {lon.iloc[i]}) "
                                f"score {scores[i]:.2f} < {self.thr:.2f}")


class HashDupRate(Detector):
    problem, family, name, explain_score = "e_exact_dup", "stat", "row-hash duplicate rate vs reference", 2
    example_alert = "dup-rate: 2.0% of rows repeat an earlier row-hash (reference 0.00%); row 912 is one"

    def fit(self, ref):
        self.base = float(pd.util.hash_pandas_object(ref.astype(str), index=False).duplicated().mean())
        return self

    def detect(self, df):
        h = pd.util.hash_pandas_object(df.astype(str), index=False)
        d = h.duplicated(keep="first").values
        rate = d.mean() if len(d) else 0
        alert = rate > self.base + 3 * np.sqrt(max(self.base, 1e-4) / max(len(df), 1))
        res = self.rows_result(df, d, lambda i: f"dup-rate: {rate:.2%} of rows repeat a row-hash "
                               f"(reference {self.base:.2%}); row {i} is one")
        res.batch_alert = bool(alert and d.any())
        return res


class TfidfNearDup(Detector):
    problem, family, name, explain_score = "f_near_dup", "stat", "TF-IDF cosine within (type, ZIP) block, <1h", 2
    example_alert = "near-dup: row 594 ~ row 403 (cosine 0.97, 7 min apart, same type & ZIP)"

    def fit(self, ref):
        txt = self._text(ref)
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 4), min_df=2, max_features=50000).fit(txt)
        return self

    @staticmethod
    def _text(df):
        return (col(df, "incident_address").fillna("").astype(str) + " | " + col(df, "descriptor").fillna("").astype(str)
                + " | " + col(df, "resolution_description").fillna("").astype(str)).str.lower()

    def detect(self, df):
        flags = np.zeros(len(df), bool)
        pairs = {}
        t = _dt(col(df, "created_date"))
        X = self.vec.transform(self._text(df))
        blocks = (col(df, "complaint_type").fillna("").astype(str) + "|" + col(df, "incident_zip").fillna("").astype(str))
        for _, idx in blocks.groupby(blocks).groups.items():
            idx = np.asarray(sorted(idx))
            if len(idx) < 2:
                continue
            S = (X[idx] @ X[idx].T).toarray()
            for a in range(len(idx)):
                for b in range(a + 1, len(idx)):
                    i, j = idx[a], idx[b]
                    dt_ = abs((t.iloc[i] - t.iloc[j]).total_seconds()) if pd.notna(t.iloc[i]) and pd.notna(t.iloc[j]) else 1e9
                    if S[a, b] > 0.9 and dt_ <= 3600 and col(df, "unique_key").iloc[i] != col(df, "unique_key").iloc[j]:
                        later = j if t.iloc[j] >= t.iloc[i] else i
                        flags[later] = True
                        pairs[later] = (i if later == j else j, S[a, b], dt_)
        return self.rows_result(df, flags, lambda i: f"near-dup: row {i} ~ row {pairs[i][0]} (cosine {pairs[i][1]:.2f}, "
                                f"{pairs[i][2] / 60:.0f} min apart, same type & ZIP)")


class AgencyNullZ(Detector):
    problem, family, name, explain_score = "g_null_spike", "stat", "per-agency null-rate z-score vs reference", 2
    example_alert = "null-spike: DOT incident_zip null 52% vs reference 1.1% (z=31, n=348)"
    COLS = NullCols = ["incident_zip", "incident_address", "latitude", "longitude", "descriptor", "resolution_description"]

    def fit(self, ref):
        self.p = {(a, c): max(float(g[c].isna().mean()), 0.005) for a, g in ref.groupby("agency") for c in self.COLS}
        self.p_all = {c: max(float(ref[c].isna().mean()), 0.005) for c in self.COLS}
        return self

    def detect(self, df):
        alerts, flags = [], np.zeros(len(df), bool)
        for ag, g in df.groupby(col(df, "agency").fillna("?")):
            for c in self.COLS:
                if c not in g or len(g) < 10:
                    continue
                p = self.p.get((ag, c), self.p_all[c])
                obs = g[c].isna().mean()
                z = (obs - p) / np.sqrt(p * (1 - p) / len(g))
                if z > 6 and obs - p > 0.10:
                    alerts.append(f"null-spike: {ag} {c} null {obs:.0%} vs reference {p:.1%} (z={z:.0f}, n={len(g)})")
                    flags[g.index[g[c].isna()].values] = True
        return Result(flags, bool(alerts), alerts[:6])


class DurationQuantile(Detector):
    problem, family, name, explain_score = "h_closed_before_created", "stat", "duration below reference 0.05th pct", 2
    example_alert = "duration: row 5 closed-created = -71.0 h, below reference 0.05th percentile (0.0 h)"

    def fit(self, ref):
        d = (_dt(ref.closed_date) - _dt(ref.created_date)).dt.total_seconds().dropna()
        self.lo = float(np.quantile(d, 0.0005)) if len(d) else 0.0
        return self

    def detect(self, df):
        d = (_dt(col(df, "closed_date")) - _dt(col(df, "created_date"))).dt.total_seconds()
        flags = (d < min(self.lo, 0)).fillna(False).values
        return self.rows_result(df, flags, lambda i: f"duration: row {i} closed-created = {d.iloc[i] / 3600:.1f} h, "
                                f"below reference 0.05th percentile ({self.lo / 3600:.1f} h)")


class ZipBoroughProb(Detector):
    problem, family, name, explain_score = "i_zip_borough", "stat", "P(borough | ZIP) < 2%", 2
    example_alert = "zip-prob: row 31 P(QUEENS | 11226) = 0.1% (n=412)"

    def fit(self, ref):
        g = ref.groupby(["incident_zip", "borough"]).size()
        self.n = ref.groupby("incident_zip").size().to_dict()
        self.c = g.to_dict()
        return self

    def detect(self, df):
        z, b = col(df, "incident_zip").fillna("").astype(str), col(df, "borough")
        probs = np.array([(self.c.get((zz, bb), 0) + 0.5) / (self.n.get(zz, 0) + 2.5) for zz, bb in zip(z, b)])
        seen = np.array([self.n.get(zz, 0) >= 10 for zz in z])
        flags = seen & (probs < 0.02)
        return self.rows_result(df, flags, lambda i: f"zip-prob: row {i} P({b.iloc[i]} | {z.iloc[i]}) = {probs[i]:.1%} "
                                f"(n={self.n.get(z.iloc[i], 0)})")


class DescriptorProb(Detector):
    problem, family, name, explain_score = "j_type_descriptor", "stat", "P(descriptor | type) < 0.2%", 2
    example_alert = "pair-prob: row 77 P('Pothole' | 'Noise - Residential') = 0.01% (n=6120)"

    def fit(self, ref):
        self.n = ref.groupby("complaint_type").size().to_dict()
        self.c = ref.groupby(["complaint_type", "descriptor"]).size().to_dict()
        self.k = ref.groupby("complaint_type").descriptor.nunique().to_dict()
        return self

    def detect(self, df):
        t, d = col(df, "complaint_type"), col(df, "descriptor")
        p = np.array([(self.c.get((tt, dd), 0) + 0.1) / (self.n.get(tt, 0) + 0.1 * (self.k.get(tt, 0) + 1))
                      for tt, dd in zip(t, d)])
        seen = np.array([self.n.get(tt, 0) >= 30 for tt in t])
        flags = seen & (p < 0.002)
        return self.rows_result(df, flags, lambda i: f"pair-prob: row {i} P({d.iloc[i]!r} | {t.iloc[i]!r}) = {p[i]:.2%}")


class StatusTextClassifier(Detector):
    problem, family, name, explain_score = "k_resolution_status", "stat", "TF-IDF + logistic regression: text -> closed?", 1
    example_alert = "status-model: row 12 status 'Open' but P(closed | text) = 0.99"

    def fit(self, ref):
        y = (ref.status == "Closed").astype(int)
        self.ok = y.nunique() == 2 and min(y.sum(), (1 - y).sum()) >= 20
        if self.ok:
            self.vec = TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=30000)
            X = self.vec.fit_transform(ref.resolution_description.fillna("").astype(str))
            self.model = LogisticRegression(max_iter=1000, class_weight="balanced").fit(X, y)
        return self

    def detect(self, df):
        if not self.ok or "status" not in df:
            return Result(np.zeros(len(df), bool), False, ["status-model: not enough open rows in reference to train"])
        p = self.model.predict_proba(self.vec.transform(col(df, "resolution_description").fillna("").astype(str)))[:, 1]
        s = col(df, "status").fillna("")
        closed = (s == "Closed").values
        is_open = s.isin(OPEN_STATUSES).values
        flags = (closed & (p < 0.05)) | (is_open & (p > 0.95))
        return self.rows_result(df, flags, lambda i: f"status-model: row {i} status {s.iloc[i]!r} but P(closed | text) = {p[i]:.2f}")


class TextOOV(Detector):
    problem, family, name, explain_score = "l_pii", "stat", "out-of-vocabulary tokens vs reference text", 2
    example_alert = "text-oov: row 44 has unseen tokens ['maria', 'gonzalez'] / digit run '9175550142'"

    def fit(self, ref):
        txt = pd.concat([ref.descriptor, ref.resolution_description]).dropna().fillna("").astype(str).str.lower()
        counts = txt.str.findall(r"[a-z']+").explode().value_counts()
        self.vocab = set(counts[counts >= 3].index)
        return self

    def detect(self, df):
        flags = np.zeros(len(df), bool)
        why = {}
        for c in ("descriptor", "resolution_description"):
            s = col(df, c).fillna("").astype(str)
            for i, t in enumerate(s):
                low = t.lower()
                oov = [w for w in re.findall(r"[a-z']+", low) if w not in self.vocab and len(w) > 2]
                digits = re.findall(r"\d[\d\s().-]{8,}\d", low)
                if len(oov) >= 2 or digits or "@" in low:
                    flags[i] = True
                    why[i] = f"unseen tokens {oov[:3]}" + (f" / digit run {digits[0]!r}" if digits else "")
        return self.rows_result(df, flags, lambda i: f"text-oov: row {i} {why.get(i, '')}")


ALL = [ColumnProfileDrift, ParseRateDrift, DatePatternFrequency, GeoIsolationForest, HashDupRate, TfidfNearDup,
       AgencyNullZ, DurationQuantile, ZipBoroughProb, DescriptorProb, StatusTextClassifier, TextOOV]
