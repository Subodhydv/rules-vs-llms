"""Task 4: measure every detector on every problem type. Writes results/project_b_metrics.json (via run_all).

Protocol
  * reference half of the clean pool -> fit lookup tables / statistics; evaluation half -> batches
  * N_CLEAN clean batches  -> false-alarm rate
  * N_CORRUPT corrupted batches per problem (default rates in injector.DEFAULT_RATE, else 2%) -> detection
  * row-level problems: detection = share of injected rows flagged (a duplicate counts if either copy is flagged)
    batch-level problems (a, b, g): detection = share of corrupted batches with an alert that names the right
    column/agency; false alarm = share of clean batches with any alert from that detector
  * LLM review is run on samples (free-tier quota): per row-level problem, POS injected rows + the same number
    of untouched rows from the same batches, reviewed 40 rows per call; plus clean-only samples for false alarms;
    schema review on a few corrupted and clean batches.
"""
from __future__ import annotations

import os
import platform
import time

import numpy as np
import pandas as pd

from common.llm import GeminiClient, LLMUnavailable, llm_status
from project_b import data_io, profile_data
from project_b.detectors import rules, stats
from project_b.detectors.llm_review import LLMRowReviewer, LLMSchemaReviewer
from project_b.injector import PROBLEMS, Injector

BATCH = int(os.environ.get("B_BATCH_ROWS", "2000"))
N_CLEAN = int(os.environ.get("B_CLEAN_BATCHES", "10"))
N_CORRUPT = int(os.environ.get("B_CORRUPT_BATCHES", "5"))
LLM_POS = int(os.environ.get("LLM_SAMPLE_B_POS", "8"))


def detection(problem, res, inj) -> float:
    level = PROBLEMS[problem][1]
    if level == "batch":
        target = inj.detail.get("agency") or inj.detail.get("column")
        text = " ".join(res.alerts)
        return float(res.batch_alert and (target is None or str(target) in text or
                                          (inj.detail.get("to") and inj.detail["to"] in text)))
    lab = np.flatnonzero(inj.labels)
    if not len(lab):
        return float("nan")
    f = res.row_flags
    hit = [f[i] or (inj.partner[i] >= 0 and f[inj.partner[i]]) for i in lab]
    return float(np.mean(hit))


def precision(res, inj) -> float | None:
    flagged = np.flatnonzero(res.row_flags)
    if not len(flagged):
        return None
    good = inj.labels.copy()
    good[inj.partner[inj.partner >= 0]] = True
    return float(good[flagged].mean())


def run_detectors(ref, pool, raw, seed=0) -> dict:
    inj = Injector(ref, seed=seed)
    dets = {}
    t_fit = {}
    for D in rules.ALL + stats.ALL:
        t0 = time.perf_counter()
        d = D().fit(ref)
        t_fit[(d.problem, d.family)] = time.perf_counter() - t0
        dets[(d.problem, d.family)] = d
    clean = data_io.batches(pool, N_CLEAN, BATCH, seed=100 + seed)
    raw_b = data_io.batches(raw, 5, BATCH, seed=200 + seed)
    out = {}
    for (problem, family), d in dets.items():
        level = PROBLEMS[problem][1]
        t_rows, t_sec = 0, 0.0
        fa_rows = fa_batches = 0
        for b in clean:
            t0 = time.perf_counter()
            r = d.detect(b)
            t_sec += time.perf_counter() - t0
            t_rows += len(b)
            fa_rows += int(r.row_flags.sum())
            fa_batches += int(r.batch_alert)
        raw_alerts = 0
        raw_examples = []
        for b in raw_b:
            r = d.detect(b)
            raw_alerts += int(r.row_flags.sum()) if level == "row" else int(r.batch_alert)
            raw_examples += r.alerts[:1]
        dets_rate, precs, examples = [], [], []
        for k in range(N_CORRUPT):
            base = data_io.batches(pool, 1, BATCH, seed=1000 + 37 * k + seed)[0]
            injd = inj.inject(base, problem)
            t0 = time.perf_counter()
            r = d.detect(injd.df)
            t_sec += time.perf_counter() - t0
            t_rows += len(injd.df)
            dets_rate.append(detection(problem, r, injd))
            p = precision(r, injd)
            if p is not None:
                precs.append(p)
            examples += r.alerts[:1]
        out[f"{problem}|{family}"] = {
            "problem": problem, "family": family, "detector": d.name, "level": level,
            "detection_rate": float(np.nanmean(dets_rate)),
            "precision_on_corrupted": float(np.mean(precs)) if precs else None,
            "false_alarm_rate": (fa_rows / sum(len(b) for b in clean)) if level == "row" else fa_batches / len(clean),
            "false_alarm_unit": "rows" if level == "row" else "batches",
            "alerts_on_raw_batches": raw_alerts, "raw_example": raw_examples[:1],
            "rows_per_sec": t_rows / t_sec if t_sec else None,
            "cpu_sec_per_million_rows": 1e6 * t_sec / t_rows if t_rows else None,
            "api_usd_per_million_rows": 0.0, "fit_sec": t_fit[(problem, family)],
            "explain_score": d.explain_score, "example_alert": (examples[:1] or [d.example_alert])[0],
        }
    return out


def _llm_row_eval(ref, pool, client, seed=0) -> dict:
    inj = Injector(ref, seed=seed + 5)
    rng = np.random.default_rng(seed)
    row_problems = [p for p, (_, lvl) in PROBLEMS.items() if lvl == "row"]
    pieces, meta = [], []
    for k, p in enumerate(row_problems):
        base = data_io.batches(pool, 1, BATCH, seed=3000 + k)[0]
        injd = inj.inject(base, p)
        lab = np.flatnonzero(injd.labels)
        pos = rng.choice(lab, size=min(LLM_POS, len(lab)), replace=False)
        keep = set(pos.tolist()) | {int(injd.partner[i]) for i in pos if injd.partner[i] >= 0}
        neg_pool = np.setdiff1d(np.arange(len(injd.df)), np.r_[lab, injd.partner[injd.partner >= 0]])
        keep |= set(rng.choice(neg_pool, size=LLM_POS, replace=False).tolist())
        part = injd.df.iloc[sorted(keep)].copy()
        part["_problem"] = p
        part["_label"] = [bool(injd.labels[i]) for i in sorted(keep)]
        part["_orig"] = sorted(keep)
        pmap = {i: int(injd.partner[i]) for i in sorted(keep)}
        part["_partner_orig"] = [pmap[i] for i in sorted(keep)]
        pieces.append(part)
    sample = pd.concat(pieces).reset_index(drop=True)
    # keep each problem's rows together (so duplicate pairs share a call), shuffle within the group
    sample["_r"] = rng.random(len(sample))
    sample = sample.sort_values(["_problem", "_r"]).drop(columns="_r").reset_index(drop=True)
    reviewer = LLMRowReviewer(client)
    flags = reviewer.review(sample.drop(columns=[c for c in sample if c.startswith("_")]))
    res = {}
    for p in row_problems:
        code = p[0]
        g = sample[sample._problem == p]
        pos = g[g._label]
        hit = []
        for i, r in pos.iterrows():
            partner_rows = g.index[(g._orig == r._partner_orig)].tolist()
            ok = code in flags.get(i, {}).get("codes", set()) or any(code in flags.get(j, {}).get("codes", set())
                                                                    for j in partner_rows)
            hit.append(ok)
        neg = g[~g._label & (g._partner_orig < 0)]
        fp = sum(bool(flags.get(i, {}).get("codes")) for i in neg.index)
        ex = next((f"llm: row {i} codes {sorted(flags[i]['codes'])}: {flags[i]['reason']}" for i in pos.index
                   if i in flags), "")
        res[p] = {"detection_rate": float(np.mean(hit)) if hit else None, "positives": len(hit),
                  "any_flag_on_untouched_rows": fp / max(len(neg), 1), "example_alert": ex}
    # clean-only sample for false-alarm rate per code
    clean = pd.concat(data_io.batches(pool, 3, 40, seed=4000)).reset_index(drop=True)
    cf = LLMRowReviewer(client).review(clean, tag=1)
    far_any = sum(bool(v["codes"]) for v in cf.values()) / len(clean)
    per_code = {c: sum(c in v["codes"] for v in cf.values()) / len(clean) for c in "cdefhijkl"}
    lat = np.median(reviewer.latency_ms) if reviewer.latency_ms else None
    return {"per_problem": res, "clean_rows": len(clean), "false_alarm_rate_any": far_any,
            "false_alarm_rate_by_code": per_code, "calls": reviewer.calls, "rows_reviewed": reviewer.rows_seen,
            "usd_per_row": reviewer.cost_per_row, "usd_per_million_rows": reviewer.cost_per_row * 1e6,
            "median_latency_ms_per_call": lat,
            "rows_per_sec_sequential": (40 / (lat / 1000)) if lat else None}


def _llm_schema_eval(ref, pool, client, seed=0) -> dict:
    inj = Injector(ref, seed=seed + 9)
    rev = LLMSchemaReviewer(client)
    out = {}
    n = int(os.environ.get("LLM_SCHEMA_BATCHES", "2"))
    for p in ("a_schema_column", "b_type_change", "g_null_spike"):
        hits, ex = [], ""
        for k in range(n):
            injd = inj.inject(data_io.batches(pool, 1, BATCH, seed=5000 + k)[0], p)
            issues = rev.review(injd.df, tag=k)
            target = str(injd.detail.get("agency") or injd.detail.get("column"))
            ok = any(i.get("code") == p[0] and (target in str(i.get("detail")) or
                                                str(injd.detail.get("to")) in str(i.get("detail"))) for i in issues)
            hits.append(ok)
            ex = ex or "; ".join(f"{i.get('code')}: {i.get('detail')}" for i in issues)[:200]
        out[p] = {"detection_rate": float(np.mean(hits)), "batches": n, "example_alert": ex}
    fa = 0
    for k in range(n):
        issues = LLMSchemaReviewer(client).review(data_io.batches(pool, 1, BATCH, seed=6000 + k)[0], tag=k)
        fa += bool(issues)
    out["false_alarm_rate_batches"] = fa / n
    out["calls"] = rev.calls + n
    out["usd_per_batch"] = rev.cost / rev.calls if rev.calls else None
    out["usd_per_million_rows"] = (rev.cost / rev.calls) * (1e6 / BATCH) if rev.calls else None
    out["median_latency_ms"] = float(np.median(rev.latency_ms)) if rev.latency_ms else None
    return out


def main() -> dict:
    t0 = time.time()
    raw, source = data_io.load_raw()
    res = {"data_source": source, "llm_status": llm_status(),
           "machine": f"{platform.processor() or platform.machine()}, {os.cpu_count()} CPUs, Python {platform.python_version()}",
           "config": {"batch_rows": BATCH, "clean_batches": N_CLEAN, "corrupt_batches_per_problem": N_CORRUPT}}
    res["profile"] = profile_data.main(raw, source)
    ref, pool = data_io.split(raw)
    res["sizes"] = {"raw_rows": len(raw), "clean_pool_rows": len(ref) + len(pool), "reference_rows": len(ref)}
    res["detectors"] = run_detectors(ref, pool, raw)
    client = GeminiClient()
    try:
        res["llm_rows"] = _llm_row_eval(ref, pool, client)
    except LLMUnavailable as e:
        res["llm_rows"] = {"status": f"not run: {e}"}
    try:
        res["llm_schema"] = _llm_schema_eval(ref, pool, client)
    except LLMUnavailable as e:
        res["llm_schema"] = {"status": f"not run: {e}"}
    from project_b import pipeline
    res["hybrid"] = pipeline.evaluate(ref, pool, client, res)
    res["elapsed_sec"] = round(time.time() - t0, 1)
    return res
