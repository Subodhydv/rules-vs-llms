"""Task 5: the law changes (Finance Act 2025, FY 2025-26). Measures what broke and what failed silently.

For each implementation we measure on the FY 2025-26 suite (230 cases, written before the change):
  1. stale state  - what happens if a FY 2025-26 request hits the FY 2024-25 rules
  2. updated      - accuracy after the update
  3. partial updates (mutation test) - realistic incomplete edits; how many cases go wrong, and does anything
     raise an error? A wrong answer with no error is a SILENT failure.
"""
from __future__ import annotations

import copy
import json
import subprocess
import time
from pathlib import Path

from common.llm import GeminiClient, LLMUnavailable
from project_a.impl_llm_compiled import dsl
from project_a.impl_llm_compiled.compile import compile_rules, gate
from project_a.impl_llm_query import engine as llmq
from project_a.impl_rules import engine as rules
from project_a.models import Comparison, Profile, explain, recommend, rule_text

ROOT = Path(__file__).parent
CASES = json.loads((ROOT / "tests/data/cases_fy2025_26.json").read_text())


def run_suite(fn, cases=CASES) -> dict:
    wrong = errors = 0
    examples = []
    for c in cases:
        try:
            r = fn(Profile.from_dict(c["profile"]))
            if (r.old.tax_payable, r.new.tax_payable) != (c["expected"]["old"], c["expected"]["new"]):
                wrong += 1
                if len(examples) < 3:
                    examples.append({"id": c["id"], "desc": c["description"],
                                     "expected_new": c["expected"]["new"], "got_new": r.new.tax_payable})
        except LLMUnavailable:
            raise
        except Exception as e:  # noqa: BLE001
            errors += 1
            if len(examples) < 3:
                examples.append({"id": c["id"], "error": f"{type(e).__name__}: {e}"[:120]})
    n = len(cases)
    return {"n": n, "correct": n - wrong - errors, "wrong_silent": wrong, "loud_errors": errors, "examples": examples}


def rules_with(cfg):
    def fn(p):
        o, n = rules.compute_regime(p, "old", cfg), rules.compute_regime(p, "new", cfg)
        c = Comparison(p.fy, o, n, recommend(o.tax_payable, n.tax_payable))
        c.explanation = explain(c)
        return c
    return fn


def diff_lines(a: Path, b: Path) -> int:
    out = subprocess.run(["diff", str(a), str(b)], capture_output=True, text=True).stdout
    return sum(1 for line in out.splitlines() if line.startswith(">"))


def rules_mutations() -> dict:
    good = rules.load_config("2025-26")
    stale = rules.load_config("2024-25")
    muts = {}

    m = copy.deepcopy(good)
    m["regimes"]["new"]["rebate"].update(income_limit=700000, max_rebate=25000)
    muts["slabs updated, 87A rebate left at 7L / 25k"] = m
    m = copy.deepcopy(good)
    m["regimes"]["new"]["rebate"].update(income_limit=700000)
    muts["87A max raised to 60k but limit left at 7L"] = m
    m = copy.deepcopy(good)
    m["regimes"]["new"]["rebate"].update(max_rebate=25000)
    muts["87A limit raised to 12L but max left at 25k"] = m
    m = copy.deepcopy(good)
    m["regimes"]["new"]["slabs"]["all_ages"] = [b for b in m["regimes"]["new"]["slabs"]["all_ages"] if b[0] != 2000000]
    muts["new 25% band (20L-24L) omitted"] = m
    m = copy.deepcopy(stale)
    m["fy"] = "2025-26"
    muts["file copied, only the year label changed"] = m
    return {k: run_suite(rules_with(v)) for k, v in muts.items()}


def compiled_mutations() -> dict:
    good = dsl.load("2025-26")
    muts = {}
    m = copy.deepcopy(good)
    for s in m["regimes"]["new"]["steps"]:
        if s["name"] == "rebate_marginal_relief":
            s["expr"] = s["expr"].replace("1200000", "700000")
    muts["87A updated but marginal-relief step still uses 7L"] = m
    m = copy.deepcopy(good)
    for s in m["regimes"]["new"]["steps"]:
        if s["name"] in ("rebate", "rebate_marginal_relief"):
            s["expr"] = s["expr"].replace("1200000", "700000").replace("60000", "25000")
    muts["slab table updated, rebate steps untouched"] = m
    out = {}
    for k, v in muts.items():
        out[k] = {"static_problems": dsl.validate(v, "2025-26"), **run_suite(lambda p, d=v: dsl.compute(p, d))}
    return out


def llm_part(sample_n: int) -> dict:
    client = GeminiClient()
    sample = [c for c in CASES if c["category"] in ("new_87a_edge", "new_slab_edge")][:sample_n]
    old_text = rule_text("2024-25")
    res = {"sample_n": len(sample)}
    try:
        res["stale_text"] = run_suite(lambda p: llmq.compute(p, client, fy_text=old_text), sample)
        res["updated_text"] = run_suite(lambda p: llmq.compute(p, client), sample)
    except LLMUnavailable as e:
        return {"status": f"not run: {e}"}
    try:
        t0 = time.time()
        doc, info = compile_rules("2025-26", client)
        res["gemini_recompile"] = {"info": info, "wall_s": round(time.time() - t0, 1),
                                   "gate": gate(doc, "2025-26") if doc else "unparseable output"}
        if doc:
            (dsl.COMPILED_DIR / "candidates").mkdir(exist_ok=True)
            (dsl.COMPILED_DIR / "candidates" / "fy2025_26.gemini.json").write_text(json.dumps(doc, indent=1))
    except LLMUnavailable as e:
        res["gemini_recompile"] = f"not run: {e}"
    return res


def main(sample_n: int = 12) -> dict:
    t0 = time.time()
    stale_cfg = copy.deepcopy(rules.load_config("2024-25"))
    out = {
        "edit_size": {
            "rules": {"config_lines_changed": diff_lines(ROOT / "impl_rules/config/fy2024_25.yaml",
                                                         ROOT / "impl_rules/config/fy2025_26.yaml"),
                      "code_lines_changed": 0},
            "compiled": {"json_lines_changed": diff_lines(dsl.COMPILED_DIR / "fy2024_25.json",
                                                          dsl.COMPILED_DIR / "fy2025_26.json"),
                         "code_lines_changed": 0},
            "llm_query": {"rule_text_lines_changed": diff_lines(ROOT / "sources/fy2024_25_rules.md",
                                                                ROOT / "sources/fy2025_26_rules.md"),
                          "code_lines_changed": 0},
        },
        "stale_with_fy_guard": {
            "rules": {"behaviour": "UnsupportedYear raised until fy2025_26.yaml exists (loud)"},
            "compiled": {"behaviour": "UnsupportedYear raised until compiled/fy2025_26.json exists (loud)"},
        },
        "stale_without_fy_guard": {
            "rules": run_suite(rules_with(stale_cfg)),
            "compiled": run_suite(lambda p: dsl.compute(p, dsl.load("2024-25"))),
        },
        "updated": {
            "rules": run_suite(rules.compute),
            "compiled": run_suite(dsl.compute),
        },
        "partial_update_mutations": {"rules": rules_mutations(), "compiled": compiled_mutations()},
    }
    out["revalidation_seconds"] = round(time.time() - t0, 2)
    out["llm"] = llm_part(sample_n)
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))
