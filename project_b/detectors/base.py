from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Result:
    row_flags: np.ndarray          # bool per row (all False for purely batch-level checks)
    batch_alert: bool
    alerts: list = field(default_factory=list)   # human-readable explanations (first few)
    cost_usd: float = 0.0
    llm_calls: int = 0


class Detector:
    problem: str = ""
    family: str = ""               # "rule" | "stat" | "llm"
    name: str = ""
    explain_score: int = 0         # 3 = row + field + violated rule/expected value; 2 = field + statistic; 1 = opaque
    example_alert: str = ""

    def fit(self, ref: pd.DataFrame) -> "Detector":
        return self

    def detect(self, df: pd.DataFrame) -> Result:
        raise NotImplementedError

    @staticmethod
    def rows_result(df, mask, fmt, limit=5, batch_threshold=1) -> Result:
        mask = np.asarray(mask, bool)
        idx = np.flatnonzero(mask)
        alerts = [fmt(i) for i in idx[:limit]]
        return Result(mask, len(idx) >= batch_threshold, alerts)


def col(df, name):
    return df[name] if name in df.columns else pd.Series([None] * len(df), index=df.index, dtype=object)
