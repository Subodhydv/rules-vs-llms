"""Task 5: the hybrid data-quality pipeline.

    stage 1  schema gate (every batch): column set + dtypes. A failing batch is quarantined whole.
    stage 2  row checks (every row): the winning detector per problem, chosen from the Task 4 measurements.
    stage 3  batch statistics (every batch): per-agency null spikes and any statistical winner.
    stage 4  LLM confirmation (only rows a fuzzy detector flagged and no high-precision check did), capped per
             batch. The LLM keeps or drops each candidate and writes the reason.

`select_winners()` turns measurements into the plan, so the design is reproducible from the numbers:
score = detection - 20 x false-alarm-rate (one false alarm per 1,000 rows costs 2 points of detection);
ties go to the rule (auditable, deterministic, cheapest). A second detector is added only if it raises
detection by >2 points: accepted directly if its false-alarm rate is no worse, otherwise routed to the LLM
for confirmation - and only if the LLM measured >= 60% detection on that problem.
"""
from __future__ import annotations

import os
import time

import numpy as np
import pandas as pd

from common.llm import GeminiClient, LLMUnavailable
from project_b import data_io
from project_b.detectors import rules, stats
from project_b.detectors.llm_review import ROW_CODES, LLMRowReviewer
from project_b.injector import PROBLEMS, Injector

LLM_CAP_PER_BATCH = int(os.environ.get("HYBRID_LLM_ROWS_PER_BATCH", "40"))
ROW_PROBLEMS = [p for p, (_, lvl) in PROBLEMS.items() if lvl == "row"]


def score(m):
    return m["detection_rate"] - 20 * m["false_alarm_rate"]


def select_winners(det: dict, llm_rows: dict | None) -> dict:
    plan = {}
    llm_ok = isinstance(llm_rows, dict) and "per_problem" in llm_rows
    for p in PROBLEMS:
        r, s = det[f"{p}|rule"], det[f"{p}|stat"]
        ranked = sorted([("rule", r), ("stat", s)], key=lambda x: (round(score(x[1]), 3), x[0] == "rule"), reverse=True)
        (bf, bm), (of, om) = ranked
        entry = {"accept": [bf], "candidates": [],
                 "why": f"{bf} score {score(bm):.3f} vs {of} {score(om):.3f}"}
        if om["detection_rate"] > bm["detection_rate"] + 0.02:
            if om["false_alarm_rate"] <= bm["false_alarm_rate"] + 1e-4:
                entry["accept"].append(of)
                entry["why"] += f"; {of} adds detection at no extra false alarms -> union"
            elif llm_ok and (llm_rows["per_problem"].get(p, {}).get("detection_rate") or 0) >= 0.6:
                entry["candidates"].append(of)
                entry["why"] += f"; {of} adds detection but noisier -> LLM confirms its extra flags"
            else:
                entry["why"] += f"; {of} would add detection but is noisier and no LLM confirmation available"
        plan[p] = entry
    return plan


class HybridPipeline:
    def __init__(self, ref: pd.DataFrame, plan: dict, client: GeminiClient | None = None):
        self.plan = plan
        self.det = {}
        for D in rules.ALL + stats.ALL:
            d = D()
            if any(d.family in (e["accept"] + e["candidates"]) for p, e in plan.items() if p == d.problem):
                self.det[(d.problem, d.family)] = d.fit(ref)
        self.schema = [rules.SchemaColumns(), rules.DtypeCheck()]
        self.client = client
        self.reviewer = LLMRowReviewer(client) if client else None
        self.llm_used = False
        self.llm_skipped = 0

    def run(self, df: pd.DataFrame) -> dict:
        out = {"quarantined": False, "batch_alerts": [], "row_flags": {}, "llm_confirmed": 0, "llm_rejected": 0}
        for d in self.schema:
            r = d.detect(df)
            if r.batch_alert:
                out["quarantined"] = True
                out["batch_alerts"] += [(d.problem, a) for a in r.alerts]
        if out["quarantined"]:
            return out
        candidates = {}
        for p, e in self.plan.items():
            if p in ("a_schema_column", "b_type_change"):
                continue
            acc = np.zeros(len(df), bool)
            for fam in e["accept"]:
                r = self.det[(p, fam)].detect(df)
                acc |= r.row_flags
                if PROBLEMS[p][1] == "batch" and r.batch_alert:
                    out["batch_alerts"] += [(p, a) for a in r.alerts]
            for fam in e["candidates"]:
                r = self.det[(p, fam)].detect(df)
                for i in np.flatnonzero(r.row_flags & ~acc):
                    candidates.setdefault(int(i), set()).add(p)
            out["row_flags"][p] = acc
        if candidates:
            idx = sorted(candidates)[:LLM_CAP_PER_BATCH]
            self.llm_skipped += max(0, len(candidates) - LLM_CAP_PER_BATCH)
            verdict = {}
            if self.reviewer is not None:
                try:
                    codes = {p[0]: ROW_CODES[p[0]] for ps in candidates.values() for p in ps}
                    verdict = self.reviewer.review(df.iloc[idx], codes=codes)
                    self.llm_used = True
                except LLMUnavailable:
                    verdict = None
            for i in idx:
                for p in candidates[i]:
                    if verdict is not None and p[0] in verdict.get(df.index[i], {}).get("codes", set()):
                        out["row_flags"][p][i] = True
                        out["llm_confirmed"] += 1
                    else:
                        out["llm_rejected"] += 1
        return out


def _mixed_batch(pool, inj, seed, rate=0.01):
    """One batch with every row-level problem injected into its own slice (labels never overlap)."""
    base = data_io.batches(pool, 1, 2000, seed=seed)[0]
    chunks = np.array_split(np.arange(len(base)), len(ROW_PROBLEMS))
    parts, labels, offset = [], {}, 0
    for p, ch in zip(ROW_PROBLEMS, chunks):
        sub = base.iloc[ch].reset_index(drop=True)
        r = inj.inject(sub, p, rate=rate * len(base) / len(sub) if p != "c_date_format" else 0.3)
        parts.append(r.df)
        partner = {int(i) + offset: int(r.partner[i]) + offset for i in np.flatnonzero(r.labels) if r.partner[i] >= 0}
        labels[p] = (np.flatnonzero(r.labels) + offset, partner)
        offset += len(r.df)
    df = pd.concat(parts, ignore_index=True)
    return df, labels, offset


def evaluate(ref, pool, client, measurements) -> dict:
    llm_live = isinstance(measurements.get("llm_rows"), dict) and "per_problem" in measurements["llm_rows"]
    plan = select_winners(measurements["detectors"], measurements.get("llm_rows"))
    pipe = HybridPipeline(ref, plan, client if llm_live else None)
    inj = Injector(ref, seed=77)
    n_mixed = int(os.environ.get("HYBRID_BATCHES", "5"))
    caught = {p: [] for p in ROW_PROBLEMS}
    t_sec, rows = 0.0, 0
    for k in range(n_mixed):
        df, labels, n = _mixed_batch(pool, inj, seed=7000 + k)
        t0 = time.perf_counter()
        o = pipe.run(df)
        t_sec += time.perf_counter() - t0
        rows += n
        for p, (lab, partner) in labels.items():
            f = o["row_flags"].get(p, np.zeros(n, bool))
            for i in lab:
                caught[p].append(bool(f[i] or (i in partner and f[partner[i]])))
    # clean batches: any row flagged by any check is a false alarm
    fa_rows, clean_rows, llm_confirm_clean = 0, 0, 0
    for k, b in enumerate(data_io.batches(pool, 5, 2000, seed=8000)):
        t0 = time.perf_counter()
        o = pipe.run(b)
        t_sec += time.perf_counter() - t0
        any_flag = np.zeros(len(b), bool)
        for f in o["row_flags"].values():
            any_flag |= f
        fa_rows += int(any_flag.sum())
        clean_rows += len(b)
        llm_confirm_clean += o["llm_confirmed"]
        rows += len(b)
    # batch-level problems
    batch_det = {}
    for p in ("a_schema_column", "b_type_change", "g_null_spike"):
        hits = []
        for k in range(3):
            r = inj.inject(data_io.batches(pool, 1, 2000, seed=9000 + k)[0], p)
            o = pipe.run(r.df)
            target = str(r.detail.get("agency") or r.detail.get("column"))
            hits.append(any(pp == p and target in a for pp, a in o["batch_alerts"]) or
                        (p != "g_null_spike" and o["quarantined"]))
        batch_det[p] = float(np.mean(hits))
    rev = pipe.reviewer
    llm_cost = rev.cost if (rev and pipe.llm_used) else 0.0
    return {
        "plan": plan,
        "llm_stage": ("live" if pipe.llm_used else
                      "available, but the measured plan routed no rows to the LLM" if pipe.reviewer is not None else
                      "skipped (no LLM available: candidates not confirmed)"),
        "row_problem_catch_rate": {p: float(np.mean(v)) for p, v in caught.items()},
        "batch_problem_catch_rate": batch_det,
        "clean_false_alarm_rate_rows": fa_rows / clean_rows,
        "rows_processed": rows, "rows_per_sec_excl_llm": rows / t_sec if t_sec else None,
        "llm_calls": rev.calls if rev else 0, "llm_rows_reviewed": rev.rows_seen if rev else 0,
        "llm_share_of_rows": (rev.rows_seen / rows) if rev else 0.0,
        "llm_usd_total": llm_cost, "usd_per_million_rows": llm_cost / rows * 1e6 if rows else 0.0,
        "llm_rows_skipped_by_cap": pipe.llm_skipped,
    }
