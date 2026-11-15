"""Compile rule text into executable rules with an LLM — once per Budget, not per request.

Pipeline:  rule text --(Gemini)--> candidate JSON --(static validation)--> --(test-suite gate)--> human review
           --> promoted to compiled/fy<YYYY_YY>.json (the only file the runtime ever loads).

Run:  python -m project_a.impl_llm_compiled.compile --fy 2025-26
Writes compiled/candidates/fy<..>.gemini.json and prints validation + test-suite results. Promotion is a
deliberate manual copy after review (see REVIEW_LOG.md); nothing here overwrites a reviewed file.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from common.llm import GeminiClient
from project_a.impl_llm_compiled import dsl
from project_a.models import Profile, rule_text

CANDIDATES = dsl.COMPILED_DIR / "candidates"

DSL_SPEC = """You must output ONE JSON document in this exact format (no prose):
{
  "fy": "<financial year>",
  "tables": {"<table name>": [[lower_bound, rate_on_income_above_lower_bound], ...], ...},
  "regimes": {
    "old": {"steps": [STEP, ...], "total_income": "<step name>", "tax_payable": "<step name>"},
    "new": {"steps": [STEP, ...], "total_income": "<step name>", "tax_payable": "<step name>"}
  }
}
STEP = {"name": "<snake_case, unique>", "expr": "<expression>", "clause": "<clause ID from the rule text>",
        "line_item": null | {"label": "<short label>", "stage": "income" | "tax", "sign": 1 | -1}}

Expressions use Python syntax restricted to: numbers, True/False, string literals (only as table names),
+ - * /, comparisons, and/or/not, `A if COND else B`, and the functions min(...), max(...),
round10(x) (sections 288A/288B rounding) and slab_tax(income, table_name).
Names available: the input fields below and the names of EARLIER steps.
Input fields: age (int), resident (bool), gross_salary, basic_da, hra_received, rent_paid (ints), metro (bool),
sec80c, sec80ccd1b, sec80d_self_family, sec80d_parents (ints), spouse_senior, parents_senior (bools),
home_loan_interest (int). All amounts are annual rupees.

Line items: steps with stage "income" (value * sign) must sum to total_income; steps with stage "tax"
(value * sign) must sum to tax_payable. Include the gross salary (+), each exemption/deduction (-),
income rounding, slab tax (+), rebate (-), surcharge (+), marginal relief (-), cess (+) and tax rounding.
Every step's clause must be one of the bracketed IDs in the rule text."""


def compile_rules(fy: str, client: GeminiClient | None = None) -> tuple[dict | None, dict]:
    client = client or GeminiClient()
    prompt = (f"Convert this tax rule text into executable rules.\n\n{DSL_SPEC}\n\nRULE TEXT\n=========\n"
              f"{rule_text(fy)}")
    t0 = time.time()
    resp = client.generate_json(prompt, system="You compile legal rule text into a small, exact rules DSL. "
                                               "Output JSON only.", max_output_tokens=32768)
    info = {"latency_ms": resp.latency_ms, "input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens,
            "cost_usd": resp.cost_usd, "cached": resp.cached, "wall_s": round(time.time() - t0, 1),
            "parse_error": resp.error}
    return (resp.data if isinstance(resp.data, dict) else None), info


def gate(doc: dict, fy: str) -> dict:
    """Static validation + run against the full test suite for that year."""
    problems = dsl.validate(doc, fy)
    result = {"static_problems": problems, "cases": 0, "correct": 0, "runtime_errors": 0, "failures": []}
    if problems:
        return result
    cases = json.loads((Path(__file__).parents[1] / "tests" / "data" /
                        f"cases_fy{fy.replace('-', '_')}.json").read_text())
    for c in cases:
        result["cases"] += 1
        try:
            r = dsl.compute(Profile.from_dict(c["profile"]), doc)
            ok = (r.old.tax_payable, r.new.tax_payable) == (c["expected"]["old"], c["expected"]["new"])
            result["correct"] += ok
            if not ok and len(result["failures"]) < 10:
                result["failures"].append({"id": c["id"], "desc": c["description"], "expected": c["expected"],
                                           "got": {"old": r.old.tax_payable, "new": r.new.tax_payable}})
        except Exception as e:  # noqa: BLE001 - a crash is a measured outcome
            result["runtime_errors"] += 1
            if len(result["failures"]) < 10:
                result["failures"].append({"id": c["id"], "error": f"{type(e).__name__}: {e}"})
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fy", default="2024-25")
    a = ap.parse_args()
    doc, info = compile_rules(a.fy)
    print("compile:", info)
    if doc is None:
        print("No parseable JSON returned.")
        return
    CANDIDATES.mkdir(parents=True, exist_ok=True)
    out = CANDIDATES / f"fy{a.fy.replace('-', '_')}.gemini.json"
    out.write_text(json.dumps(doc, indent=1))
    print("wrote", out)
    print(json.dumps(gate(doc, a.fy), indent=1))


if __name__ == "__main__":
    main()
