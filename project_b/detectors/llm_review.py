"""Family (c): LLM review with Gemini — on samples of rows, and on a batch summary for schema-level problems.

Row review: up to ROWS_PER_CALL rows per request, compact JSON, the model returns problem codes per row with a
reason. Batch review: expected vs observed schema, a few sample rows and a per-agency null table.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from common.llm import GeminiClient
from project_b.schema import COLUMNS

ROWS_PER_CALL = 40
ROW_CODES = {
    "c": "date not in the ISO format used by the other rows (YYYY-MM-DDTHH:MM:SS)",
    "d": "latitude and longitude swapped or outside New York City",
    "e": "exact duplicate of another row shown",
    "f": "near-duplicate of another row shown (same request, slightly different time or text)",
    "h": "closed_date earlier than created_date",
    "i": "incident_zip does not belong to the stated borough",
    "j": "descriptor does not fit the complaint_type",
    "k": "resolution_description contradicts status (says resolved while open, or pending while Closed)",
    "l": "personal data in free text (phone number, e-mail address, or a person's name)",
}
SHOW = ["unique_key", "created_date", "closed_date", "agency", "complaint_type", "descriptor", "incident_zip",
        "incident_address", "borough", "status", "resolution_description", "latitude", "longitude"]
SYSTEM = ("You are a meticulous data-quality reviewer for New York City 311 service-request data. "
          "Flag only clear problems. Return JSON only.")


def _rows_json(df: pd.DataFrame) -> str:
    recs = []
    for i, r in df[[c for c in SHOW if c in df]].iterrows():
        recs.append({"row": int(i), **{k: (None if (v is None or (isinstance(v, float) and np.isnan(v))) else
                                           (v if isinstance(v, (int, float)) else str(v))) for k, v in r.items()}})
    return json.dumps(recs, separators=(",", ":"), default=str)


class LLMRowReviewer:
    family = "llm"

    def __init__(self, client: GeminiClient | None = None):
        self.client = client or GeminiClient()
        self.calls = 0
        self.cost = 0.0
        self.rows_seen = 0
        self.latency_ms = []

    def review(self, df: pd.DataFrame, codes: dict | None = None, tag: int = 0) -> dict:
        """Returns {row_index: {"codes": set, "reason": str}} for the rows in df (index preserved)."""
        codes = codes or ROW_CODES
        out = {}
        for start in range(0, len(df), ROWS_PER_CALL):
            chunk = df.iloc[start:start + ROWS_PER_CALL]
            prompt = ("Problem codes:\n" + "\n".join(f"{k}: {v}" for k, v in codes.items()) +
                      "\n\nRows (JSON):\n" + _rows_json(chunk) +
                      '\n\nReturn {"flags": [{"row": <row>, "codes": ["<code>", ...], "reason": "<short reason>"}]} '
                      "listing only rows with at least one problem. Use an empty list if none.")
            r = self.client.generate_json(prompt, system=SYSTEM, variant=tag)
            self.calls += 1
            self.cost += r.cost_usd
            self.rows_seen += len(chunk)
            self.latency_ms.append(r.latency_ms)
            data = r.data if isinstance(r.data, dict) else {}
            for f in data.get("flags", []) or []:
                try:
                    idx = int(f.get("row"))
                except (TypeError, ValueError):
                    continue
                if idx in chunk.index:
                    out.setdefault(idx, {"codes": set(), "reason": ""})
                    out[idx]["codes"] |= {str(c).lower()[:1] for c in f.get("codes", [])}
                    out[idx]["reason"] = str(f.get("reason", ""))[:200]
        return out

    @property
    def cost_per_row(self) -> float:
        return self.cost / self.rows_seen if self.rows_seen else 0.0


class LLMSchemaReviewer:
    family = "llm"

    def __init__(self, client: GeminiClient | None = None):
        self.client = client or GeminiClient()
        self.calls = 0
        self.cost = 0.0
        self.latency_ms = []

    def review(self, df: pd.DataFrame, tag: int = 0) -> list[dict]:
        nulls = (df.isna().groupby(df["agency"] if "agency" in df else 0).mean() * 100).round(0)
        keep = [c for c in ("incident_zip", "incident_address", "latitude", "longitude", "descriptor",
                            "resolution_description") if c in nulls.columns]
        summary = {
            "expected_schema": COLUMNS,
            "observed_schema": {c: str(t) for c, t in df.dtypes.items()},
            "rows_in_batch": len(df),
            "sample_rows": json.loads(_rows_json(df.sample(min(5, len(df)), random_state=tag))),
            "null_percent_by_agency": nulls[keep].to_dict(orient="index") if keep else {},
        }
        prompt = ("Review this batch summary of NYC 311 data for batch-level problems:\n"
                  "a: a column renamed or dropped compared with the expected schema\n"
                  "b: a column's type changed (e.g. numbers arriving as strings)\n"
                  "g: an unusual spike of missing values in one agency's records\n\n"
                  f"{json.dumps(summary, default=str)}\n\n"
                  'Return {"issues": [{"code": "a"|"b"|"g", "detail": "<column/agency and why>"}]} (empty list if none).')
        r = self.client.generate_json(prompt, system=SYSTEM, variant=tag)
        self.calls += 1
        self.cost += r.cost_usd
        self.latency_ms.append(r.latency_ms)
        data = r.data if isinstance(r.data, dict) else {}
        return [i for i in data.get("issues", []) or [] if isinstance(i, dict)]
