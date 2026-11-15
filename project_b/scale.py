"""Task 6: project cost and latency of the hybrid pipeline at 50 million rows/day across 120 customers.

Everything is computed from the measured numbers in results/project_b_metrics.json. Where an LLM figure was not
measured (no API key), the per-row LLM cost is estimated from the prompt size of a real row (tokens ~= chars/4)
at list price, and labelled as an estimate.
"""
from __future__ import annotations

import json

from common.llm import DEFAULT_MODEL, PRICES
from project_b import data_io
from project_b.detectors.llm_review import ROWS_PER_CALL, _rows_json

ROWS_PER_DAY = 50_000_000
CUSTOMERS = 120
PEAK_FACTOR = 5          # assume the busiest hour carries 5x the average rate


def estimated_llm_usd_per_row(sample) -> float:
    chars = len(_rows_json(sample)) / len(sample)
    in_tok = chars / 4 + 600 / ROWS_PER_CALL          # row payload + share of instructions
    out_tok = 25                                        # most rows produce no flag; flagged rows ~60 tokens
    pin, pout = PRICES.get(DEFAULT_MODEL, PRICES["gemini-2.5-flash"])
    return in_tok / 1e6 * pin + out_tok / 1e6 * pout


def project(metrics: dict) -> dict:
    hy = metrics["hybrid"]
    thr = hy["rows_per_sec_excl_llm"]
    raw, _ = data_io.load_raw()
    llm_rows = metrics.get("llm_rows", {})
    if "usd_per_row" in llm_rows and llm_rows["usd_per_row"]:
        per_row, basis = llm_rows["usd_per_row"], "measured"
    else:
        per_row, basis = estimated_llm_usd_per_row(raw.sample(200, random_state=0)), "estimated from prompt size"
    share = hy.get("llm_share_of_rows") or 0.0
    stage = hy.get("llm_stage", "")
    if stage == "live":
        share_basis = "measured"
    elif stage.startswith("available"):
        share, share_basis = 0.002, "measured 0% (plan sent no rows); 0.2% used as headroom"
    else:
        share, share_basis = 0.002, "assumed upper bound (LLM stage not run)"
    avg_rps = ROWS_PER_DAY / 86400
    out = {
        "rows_per_day": ROWS_PER_DAY, "customers": CUSTOMERS, "rows_per_customer_per_day": ROWS_PER_DAY / CUSTOMERS,
        "avg_rows_per_sec": avg_rps, "peak_rows_per_sec": avg_rps * PEAK_FACTOR,
        "measured_single_core_rows_per_sec": thr,
        "cpu_core_hours_per_day": ROWS_PER_DAY / thr / 3600 if thr else None,
        "cores_needed_at_peak": avg_rps * PEAK_FACTOR / thr if thr else None,
        "llm_usd_per_row": per_row, "llm_cost_basis": basis,
        "llm_share_of_rows": share, "llm_share_basis": share_basis,
        "llm_usd_per_day_hybrid": ROWS_PER_DAY * share * per_row,
        "llm_calls_per_day_hybrid": ROWS_PER_DAY * share / ROWS_PER_CALL,
        "llm_usd_per_day_if_every_row": ROWS_PER_DAY * per_row,
        "llm_calls_per_day_if_every_row": ROWS_PER_DAY / ROWS_PER_CALL,
    }
    out["llm_usd_per_month_hybrid"] = out["llm_usd_per_day_hybrid"] * 30
    out["llm_usd_per_month_if_every_row"] = out["llm_usd_per_day_if_every_row"] * 30
    return out


if __name__ == "__main__":
    m = json.load(open("results/project_b_metrics.json"))
    print(json.dumps(project(m), indent=1))
