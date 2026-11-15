"""Task 4: measure every implementation and the parsers. Writes results/project_a_metrics.json.

Metrics per implementation:
  accuracy      rupee-exact match of BOTH regimes' final tax + the recommendation
  determinism   10 runs of the same inputs; number of distinct answers per input (1 = deterministic)
  latency       per request, p50 / p95 (ms)
  cost          USD per 1,000 requests (LLM tokens at paid-tier list price; rules have no API cost)
  traceability  % of answers in which every line item cites a clause that exists in the rule text AND the
                line items add up to total income and tax payable
"""
from __future__ import annotations

import json
import os
import statistics
import time
from pathlib import Path

from common.llm import GeminiClient, LLMUnavailable, llm_status
from project_a.impl_llm_compiled import dsl
from project_a.impl_llm_compiled.compile import compile_rules, gate
from project_a.impl_llm_query import engine as llmq
from project_a.impl_rules import engine as rules
from project_a.models import Profile, clause_ids
from project_a.parser import llm_parser, rule_parser
from project_a.parser.score import load as load_desc, score_one, summarise

ROOT = Path(__file__).parent
DATA = ROOT / "tests" / "data"


def cases(fy="2024-25"):
    return json.loads((DATA / f"cases_fy{fy.replace('-', '_')}.json").read_text())


def traceable(r, valid) -> bool:
    for reg in (r.old, r.new):
        if not reg.line_items or any(li.clause not in valid for li in reg.line_items):
            return False
        inc = sum(li.amount for li in reg.line_items if li.stage == "income")
        tax = sum(li.amount for li in reg.line_items if li.stage == "tax")
        if abs(inc - reg.total_income) > 1 or abs(tax - reg.tax_payable) > 1:
            return False
    return True


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))] if xs else None


def llm_sample(all_cases, n):
    """Stratified: one case from each category first, then fill evenly."""
    by_cat = {}
    for c in all_cases:
        by_cat.setdefault(c["category"], []).append(c)
    out, i = [], 0
    while len(out) < min(n, len(all_cases)):
        for cat in sorted(by_cat):
            if i < len(by_cat[cat]) and len(out) < n:
                out.append(by_cat[cat][i])
        i += 1
    return out


def measure(name, fn, suite, fy, repeat_inputs, repeat_fn=None) -> dict:
    valid = clause_ids(fy)
    correct = trace_ok = errors = 0
    lat, cost, failures = [], [], []
    for c in suite:
        t0 = time.perf_counter()
        try:
            r = fn(Profile.from_dict(c["profile"]))
        except LLMUnavailable:
            raise
        except Exception as e:  # noqa: BLE001 - unparseable LLM output etc. counts as wrong
            errors += 1
            failures.append({"id": c["id"], "error": str(e)[:150]})
            continue
        lat.append(r.meta.get("latency_ms", (time.perf_counter() - t0) * 1000))
        cost.append(r.meta.get("cost_usd", 0.0))
        ok = (r.old.tax_payable, r.new.tax_payable, r.recommended) == \
             (c["expected"]["old"], c["expected"]["new"], c["expected"]["recommended"])
        correct += ok
        trace_ok += traceable(r, valid)
        if not ok and len(failures) < 8:
            failures.append({"id": c["id"], "desc": c["description"],
                             "expected": [c["expected"]["old"], c["expected"]["new"]],
                             "got": [r.old.tax_payable, r.new.tax_payable]})
    distinct = []
    for c in repeat_inputs:
        answers = set()
        for k in range(10):
            try:
                r = (repeat_fn or (lambda p, k: fn(p)))(Profile.from_dict(c["profile"]), k)
                answers.add((r.old.tax_payable, r.new.tax_payable, r.recommended))
            except LLMUnavailable:
                raise
            except Exception as e:  # noqa: BLE001
                answers.add(("error", str(e)[:40]))
        distinct.append(len(answers))
    n = len(suite)
    return {"impl": name, "n": n, "correct": correct, "accuracy": correct / n if n else None,
            "errors": errors, "traceable": trace_ok / n if n else None,
            "repeat_inputs": len(repeat_inputs), "distinct_answers_per_input": distinct,
            "deterministic": all(d == 1 for d in distinct),
            "latency_ms_p50": pct(lat, 0.5), "latency_ms_p95": pct(lat, 0.95),
            "cost_per_1000_usd": (statistics.mean(cost) * 1000) if cost else 0.0,
            "failures": failures}


def parsers(client) -> dict:
    dev = load_desc()
    held = json.loads((DATA / "descriptions_heldout.json").read_text())
    out = {"rule": {}, "llm": {}, "hybrid": {}}
    for setname, items in (("dev50", dev), ("heldout20", held)):
        t0 = time.perf_counter()
        rows = [score_one(d, rule_parser.parse(d["text"])) for d in items]
        out["rule"][setname] = {**summarise(rows), "ms_per_item": (time.perf_counter() - t0) * 1000 / len(items),
                                "failures": [r for r in rows if not r["ok"]]}
        for kind, fn in (("llm", llm_parser.parse), ("hybrid", llm_parser.parse_hybrid)):
            if kind == "hybrid" and "status" in out["llm"][setname]:
                out[kind][setname] = out["llm"][setname]   # hybrid needs the LLM; don't report the fallback
                continue
            try:
                rows, lat, cost = [], [], []
                for d in items:
                    res, meta = fn(d["text"], client)
                    rows.append(score_one(d, res))
                    lat.append(meta.get("latency_ms", 0))
                    cost.append(meta.get("cost_usd", 0))
                out[kind][setname] = {**summarise(rows), "latency_ms_p50": pct(lat, 0.5),
                                      "cost_per_1000_usd": statistics.mean(cost) * 1000,
                                      "failures": [r for r in rows if not r["ok"]]}
            except LLMUnavailable as e:
                out[kind][setname] = {"status": f"not run: {e}"}
    # determinism of the LLM parser: 10 runs on 3 descriptions
    try:
        dist = []
        for d in [x for x in dev if x["id"] in ("D04", "D14", "D30")]:
            seen = set()
            for k in range(10):
                res, _ = llm_parser.parse(d["text"], client, variant=k)
                seen.add(json.dumps(res.profile.to_dict() if res.profile else res.ask_fields, sort_keys=True))
            dist.append(len(seen))
        out["llm"]["distinct_answers_per_input"] = dist
    except LLMUnavailable as e:
        out["llm"]["distinct_answers_per_input"] = f"not run: {e}"
    return out


def main() -> dict:
    client = GeminiClient()
    suite = cases("2024-25")
    repeat = [suite[0], suite[30], suite[120]]
    res = {"llm_status": llm_status(), "model": client.model, "suite_size": len(suite), "impls": {}}
    res["impls"]["rules"] = measure("rules", rules.compute, suite, "2024-25", repeat)
    res["impls"]["compiled"] = measure("compiled", dsl.compute, suite, "2024-25", repeat)

    n_llm = int(os.environ.get("LLM_SAMPLE_A", "40"))
    sample = llm_sample(suite, n_llm)
    try:
        res["impls"]["llm_query"] = measure(
            "llm_query", lambda p: llmq.compute(p, client), sample, "2024-25", repeat[:2],
            repeat_fn=lambda p, k: llmq.compute(p, client, variant=k + 1))
        res["impls"]["llm_query"]["note"] = f"stratified sample of {len(sample)} cases (free-tier quota)"
        # rules on the same sample, for a like-for-like comparison
        res["impls"]["rules_on_llm_sample"] = measure("rules", rules.compute, sample, "2024-25", [])
    except LLMUnavailable as e:
        res["impls"]["llm_query"] = {"impl": "llm_query", "status": f"not run: {e}"}

    try:
        doc, info = compile_rules("2024-25", client)
        g = gate(doc, "2024-25") if doc else {"static_problems": ["unparseable output"]}
        if doc:
            (dsl.COMPILED_DIR / "candidates").mkdir(exist_ok=True)
            (dsl.COMPILED_DIR / "candidates" / "fy2024_25.gemini.json").write_text(json.dumps(doc, indent=1))
        res["gemini_compile_fy2425"] = {"info": info, "gate": g}
    except LLMUnavailable as e:
        res["gemini_compile_fy2425"] = {"status": f"not run: {e}"}

    res["parsers"] = parsers(client)
    return res


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, default=str))
