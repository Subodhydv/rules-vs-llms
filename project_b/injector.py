"""Task 2: inject each of the 12 problem types into a clean batch at a controlled rate, with ground-truth labels.

    inj = Injector(reference_df, seed=1)
    out = inj.inject(batch, "h_closed_before_created", rate=0.02)
    out.df, out.labels (bool per row), out.partner (row index of the original for duplicates, else -1),
    out.level ("row" or "batch"), out.detail (what was done, for batch-level problems)

Replacement values are drawn from the reference data wherever possible (real ZIPs of other boroughs, real
descriptors of other complaint types, real resolution texts) so detectors can't win on artefacts of the injector.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from project_b.schema import BOROUGHS, OPEN_STATUSES

PROBLEMS = {
    "a_schema_column": ("Renamed or dropped column", "batch"),
    "b_type_change": ("Column type change (numbers as strings)", "batch"),
    "c_date_format": ("Date format switch partway through batch", "row"),
    "d_latlon_swap": ("Latitude and longitude swapped", "row"),
    "e_exact_dup": ("Exact duplicates", "row"),
    "f_near_dup": ("Near-duplicates", "row"),
    "g_null_spike": ("Null spike in one agency's records", "batch"),
    "h_closed_before_created": ("Closed date earlier than created date", "row"),
    "i_zip_borough": ("ZIP inconsistent with borough", "row"),
    "j_type_descriptor": ("Complaint Type inconsistent with Descriptor", "row"),
    "k_resolution_status": ("Resolution Description contradicting Status", "row"),
    "l_pii": ("Personal data in free text", "row"),
}
DEFAULT_RATE = {"g_null_spike": 0.5, "c_date_format": 0.3, "b_type_change": 0.05}

FIRST = ["Maria", "John", "Wei", "Aisha", "Carlos", "Priya", "David", "Fatima", "Kevin", "Olga", "Jamal", "Lucia"]
LAST = ["Gonzalez", "Smith", "Chen", "Khan", "Rodriguez", "Patel", "Cohen", "Ali", "O'Brien", "Ivanova", "Brown"]
FALLBACK_OPEN_TEXT = ["The complaint has been received and is being reviewed by the agency.",
                      "This request has been assigned to an inspector; a visit will be scheduled.",
                      "Your request is still in progress. Please check back later for an update."]


@dataclass
class Injected:
    df: pd.DataFrame
    labels: np.ndarray
    partner: np.ndarray
    level: str
    detail: dict = field(default_factory=dict)


def _fmt_us(s: pd.Series) -> pd.Series:
    d = pd.to_datetime(s, errors="coerce", format="ISO8601")
    return d.dt.strftime("%m/%d/%Y %I:%M:%S %p").where(d.notna(), None)


class Injector:
    def __init__(self, reference: pd.DataFrame, seed: int = 0):
        self.rng = np.random.default_rng(seed)
        ref = reference
        self.zips_by_borough = {b: sorted(ref.loc[ref.borough == b, "incident_zip"].dropna().unique())
                                for b in BOROUGHS}
        self.pairs = ref.groupby("complaint_type").descriptor.agg(lambda s: sorted(s.dropna().unique())).to_dict()
        closed = ref.loc[ref.status == "Closed", "resolution_description"].dropna()
        opened = ref.loc[ref.status.isin(OPEN_STATUSES), "resolution_description"].dropna()
        self.closed_texts = closed.sample(min(len(closed), 500), random_state=seed).tolist() if len(closed) else []
        self.open_texts = (opened.drop_duplicates().tolist() if opened.nunique() >= 5 else []) or FALLBACK_OPEN_TEXT

    def _pick(self, n_rows: int, rate: float, eligible: np.ndarray | None = None,
              of_eligible: bool = False) -> np.ndarray:
        pool = np.arange(n_rows) if eligible is None else np.flatnonzero(eligible)
        k = max(1, int(round(rate * (len(pool) if of_eligible else n_rows))))
        return np.sort(self.rng.choice(pool, size=min(k, len(pool)), replace=False))

    def inject(self, batch: pd.DataFrame, problem: str, rate: float | None = None) -> Injected:
        rate = DEFAULT_RATE.get(problem, 0.02) if rate is None else rate
        return getattr(self, "_" + problem)(batch.copy().reset_index(drop=True), rate)

    def _out(self, df, rows=None, level="row", partner=None, **detail):
        labels = np.zeros(len(df), bool)
        if rows is not None:
            labels[rows] = True
        partner = np.full(len(df), -1) if partner is None else partner
        return Injected(df, labels, partner, level, detail)

    # a. renamed or dropped column ---------------------------------------------------------------------
    def _a_schema_column(self, df, rate):
        col = self.rng.choice(["incident_zip", "borough", "resolution_description", "latitude", "status"])
        if self.rng.random() < 0.5:
            new = {"incident_zip": "zip_code", "borough": "Borough", "resolution_description": "resolution",
                   "latitude": "lat", "status": "request_status"}[col]
            return self._out(df.rename(columns={col: new}), level="batch", action="renamed", column=str(col), to=new)
        return self._out(df.drop(columns=[col]), level="batch", action="dropped", column=str(col))

    # b. numbers arriving as strings -------------------------------------------------------------------
    def _b_type_change(self, df, rate):
        col = self.rng.choice(["latitude", "longitude", "unique_key"])
        s = df[col].fillna("").astype(str).astype(object)
        rows = self._pick(len(df), rate)
        bad = self.rng.choice(["N/A", "{v} N", "{v},0", " {v} "], size=len(rows))
        s.iloc[rows] = [b.format(v=s.iloc[r]) for r, b in zip(rows, bad)]
        df[col] = s
        return self._out(df, rows, level="batch", column=str(col))

    # c. date format switch partway -------------------------------------------------------------------
    def _c_date_format(self, df, rate):
        start = int(len(df) * (1 - rate))
        rows = np.arange(start, len(df))
        for c in ("created_date", "closed_date"):
            df.loc[rows, c] = _fmt_us(df.loc[rows, c])
        return self._out(df, rows, switch_at_row=start, fmt="%m/%d/%Y %I:%M:%S %p")

    # d. lat/lon swapped ------------------------------------------------------------------------------
    def _d_latlon_swap(self, df, rate):
        rows = self._pick(len(df), rate, df.latitude.notna().values)
        df.loc[rows, ["latitude", "longitude"]] = df.loc[rows, ["longitude", "latitude"]].values
        return self._out(df, rows)

    # e/f. duplicates -----------------------------------------------------------------------------------
    def _dups(self, df, rate, near):
        src = self._pick(len(df), rate)
        copies = df.iloc[src].copy()
        if near:
            shift = pd.to_timedelta(self.rng.integers(5, 600, size=len(src)), unit="s")
            for c in ("created_date", "closed_date"):
                d = pd.to_datetime(copies[c], errors="coerce", format="ISO8601") + shift
                copies[c] = d.dt.strftime("%Y-%m-%dT%H:%M:%S.000").where(d.notna(), None)
            copies["unique_key"] = copies["unique_key"] + 90_000_000
            tweak = self.rng.random(len(src)) < 0.5
            txt = copies["resolution_description"].fillna("").astype(str)
            copies.loc[tweak, "resolution_description"] = [
                t.upper() if self.rng.random() < 0.5 else t.replace(" the ", " the  ", 1) for t in txt[tweak]]
        # insert copies at random positions after their originals
        order = list(range(len(df)))
        n_total = len(df) + len(src)
        positions = {}
        for j, s in enumerate(src):
            positions[j] = int(self.rng.integers(s + 1, len(order) + 1))
            order.insert(positions[j], ("copy", j))
        rows, partner_of = [], {}
        out_rows = []
        for new_idx, item in enumerate(order):
            if isinstance(item, tuple):
                out_rows.append(copies.iloc[item[1]])
                rows.append(new_idx)
                partner_of[new_idx] = int(src[item[1]])
            else:
                out_rows.append(df.iloc[item])
        out = pd.DataFrame(out_rows).reset_index(drop=True)
        # map original indices to their new positions
        new_pos = {}
        k = 0
        for new_idx, item in enumerate(order):
            if not isinstance(item, tuple):
                new_pos[k] = new_idx
                k += 1
        partner = np.full(n_total, -1)
        for new_idx, orig in partner_of.items():
            partner[new_idx] = new_pos[orig]
            partner[new_pos[orig]] = new_idx
        return self._out(out.astype(df.dtypes.to_dict()), np.array(rows), partner=partner)

    def _e_exact_dup(self, df, rate):
        return self._dups(df, rate, near=False)

    def _f_near_dup(self, df, rate):
        return self._dups(df, rate, near=True)

    # g. null spike in one agency ---------------------------------------------------------------------
    def _g_null_spike(self, df, rate):
        counts = df.agency.value_counts()
        agency = self.rng.choice(counts[counts >= 30].index[:4]) if (counts >= 30).any() else counts.index[0]
        rows = self._pick(len(df), rate, (df.agency == agency).values, of_eligible=True)
        cols = ["incident_zip", "incident_address", "latitude", "longitude"]
        df.loc[rows, cols] = None
        df[["latitude", "longitude"]] = df[["latitude", "longitude"]].astype("float64")
        return self._out(df, rows, level="batch", agency=str(agency), columns=cols)

    # h. closed before created ------------------------------------------------------------------------
    def _h_closed_before_created(self, df, rate):
        rows = self._pick(len(df), rate, df.created_date.notna().values)
        created = pd.to_datetime(df.loc[rows, "created_date"], format="ISO8601")
        back = pd.to_timedelta(self.rng.integers(3600, 30 * 86400, size=len(rows)), unit="s")
        df.loc[rows, "closed_date"] = (created - back).dt.strftime("%Y-%m-%dT%H:%M:%S.000").values
        return self._out(df, rows)

    # i. ZIP from another borough ---------------------------------------------------------------------
    def _i_zip_borough(self, df, rate):
        rows = self._pick(len(df), rate, df.borough.isin(BOROUGHS).values)
        for r in rows:
            other = self.rng.choice([b for b in BOROUGHS if b != df.at[r, "borough"] and self.zips_by_borough[b]])
            df.at[r, "incident_zip"] = str(self.rng.choice(self.zips_by_borough[other]))
        return self._out(df, rows)

    # j. descriptor from another complaint type --------------------------------------------------------
    def _j_type_descriptor(self, df, rate):
        rows = self._pick(len(df), rate)
        types = list(self.pairs)
        for r in rows:
            own = set(self.pairs.get(df.at[r, "complaint_type"], []))
            for _ in range(20):
                cand = self.rng.choice(self.pairs[self.rng.choice(types)])
                if cand not in own:
                    df.at[r, "descriptor"] = str(cand)
                    break
        return self._out(df, rows)

    # k. resolution contradicts status -----------------------------------------------------------------
    def _k_resolution_status(self, df, rate):
        rows = self._pick(len(df), rate, (df.status == "Closed").values)
        half = self.rng.random(len(rows)) < 0.5
        for r, flip_status in zip(rows, half):
            if flip_status:   # says it was resolved, status claims still open
                df.at[r, "status"] = str(self.rng.choice(["Open", "In Progress"]))
                df.at[r, "closed_date"] = None
            else:             # status Closed, text says still pending
                df.at[r, "resolution_description"] = str(self.rng.choice(self.open_texts))
        return self._out(df, rows, flipped_status=int(half.sum()), open_text=int((~half).sum()))

    # l. personal data in free text --------------------------------------------------------------------
    def _l_pii(self, df, rate):
        rows = self._pick(len(df), rate)
        kinds = self.rng.choice(["phone", "email", "name", "name+phone"], size=len(rows))
        for r, kind in zip(rows, kinds):
            first, last = self.rng.choice(FIRST), self.rng.choice(LAST)
            phone = self.rng.choice(["{a}-{b}-{c}", "({a}) {b}-{c}", "{a}.{b}.{c}", "+1 {a} {b} {c}"]).format(
                a=self.rng.choice(["212", "718", "917", "646", "347"]), b=self.rng.integers(200, 999),
                c=f"{self.rng.integers(0, 9999):04d}")
            email = f"{first.lower()}.{last.lower().replace(chr(39), '')}{self.rng.integers(1, 99)}@gmail.com"
            add = {"phone": f" Caller can be reached at {phone}.", "email": f" Follow-up sent to {email}.",
                   "name": f" Tenant {first} {last} confirmed the condition.",
                   "name+phone": f" Contact {first} {last} at {phone}."}[kind]
            col = "resolution_description" if self.rng.random() < 0.7 else "descriptor"
            df.at[r, col] = f"{df.at[r, col] or ''}{add}".strip()
        return self._out(df, rows, kinds={k: int((kinds == k).sum()) for k in set(kinds)})
