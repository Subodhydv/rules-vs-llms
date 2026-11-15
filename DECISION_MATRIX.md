# DECISION MATRIX

Generated from `results/` on 2026-11-15 10:20. Every row cites the measurement behind it. Labels: **rule**, **statistical**, **LLM**, **hybrid**.

## Project A — income-tax service

| Component | Choice | Measurement that justifies it | Auditability | Determinism | Maintenance on a Budget change |
|---|---|---|---|---|---|
| Tax computation (both regimes) | **rule** (config-driven engine) | 230/230 rupee-exact, 100% traceable, 0.13 ms, $0; LLM at query time: not measured in this run | every rupee → clause ID, line items reconcile | 10/10 identical | 4 config lines for FY 2025-26, 230/230 first run |
| Regime recommendation | **rule** | follows from two exact numbers; tie → new regime per [G-REGIME] | clause-cited | yes | none |
| Rule authoring when the law changes | **hybrid** (LLM compiles a second, independent encoding; must agree with the hand-edited config on the full suite) | compiled rules 230/230; mutation test shows single-number slips are silent without a cross-check | diff of two encodings + review log | runtime is deterministic | one LLM call per Budget + review |
| Free-text → structured fields | **hybrid** (LLM extraction, rule fallback, rule cross-check) | rules held-out 16/20 with 1 silent wrong field; LLM extraction: not measured in this run | extraction logged; numbers grounded in text | LLM part not guaranteed → validator is the gate | prompt change, no law dependency |
| Is the input complete? / clarifying questions | **rule** (`validate.py`) | 0 unsafe guesses across 70 descriptions for the rule path; the same gate is applied to LLM output | each question cites the missing/conflicting field | yes | changes only when the input schema changes |
| Hallucination guard on extracted amounts | **rule** | catches any amount not derivable from the user's numbers (test_llm_plumbing) | explicit | yes | none |
| Explanation shown to user | **rule** (template with clause IDs) | numbers come from the engine; an LLM rewrite adds cost and a risk of misquoting | full | yes | template edit |
| Expected values for tests | **rule** (independent oracle) + official anchors | Budget-speech table reproduced exactly; official calculator cross-check | full | yes | updated *before* implementations each Budget |
| FY dispatch | **rule** (fail loudly on unknown FY) | without it, stale rules give 189/230 silently wrong answers | full | yes | add one file per year |

## Project B — data-quality layer

| Check | Choice | Measurement (detection / false alarms; cost) | Auditability | Determinism | Maintenance across 120 schemas |
|---|---|---|---|---|---|
| a. Renamed / dropped column | **rule** | rule 100% / 0.00%; stat 100% / 0.00% | alert names row, field, rule | yes | per-customer config (column contract, lookup tables) |
| b. Type change | **rule** | rule 100% / 0.00%; stat 100% / 0.00% | alert names row, field, rule | yes | per-customer config (column contract, lookup tables) |
| c. Date format switch | **rule** | rule 100% / 0.00%; stat 100% / 0.00% | alert names row, field, rule | yes | per-customer config (column contract, lookup tables) |
| d. Lat/lon swapped | **rule** | rule 100% / 0.00%; stat 0% / 0.03% | alert names row, field, rule | yes | per-customer config (column contract, lookup tables) |
| e. Exact duplicates | **rule** | rule 100% / 0.00%; stat 100% / 0.00% | alert names row, field, rule | yes | per-customer config (column contract, lookup tables) |
| f. Near-duplicates | **rule** | rule 100% / 0.45%; stat 100% / 0.59% | alert names row, field, rule | yes | per-customer config (column contract, lookup tables) |
| g. Null spike (one agency) | **statistical** | rule 100% / 100.00%; stat 100% / 0.00% | alert names field + statistic | yes | per-customer baseline refit |
| h. Closed before created | **rule** | rule 100% / 0.00%; stat 100% / 0.00% | alert names row, field, rule | yes | per-customer config (column contract, lookup tables) |
| i. ZIP vs borough | **rule** | rule 100% / 0.00%; stat 92% / 0.00% | alert names row, field, rule | yes | per-customer config (column contract, lookup tables) |
| j. Type vs descriptor | **statistical** | rule 100% / 0.22%; stat 99% / 0.12% | alert names field + statistic | yes | per-customer baseline refit |
| k. Resolution vs status | **statistical** | rule 52% / 3.94%; stat 88% / 0.09% | alert names field + statistic | yes | per-customer baseline refit |
| l. Personal data in text | **rule** | rule 100% / 0.27%; stat 100% / 0.48% | alert names row, field, rule | yes | per-customer config (column contract, lookup tables) |
| Schema gate (quarantine whole batch) | **rule** | a/b caught 100% / 100% end to end, $0 | exact message | yes | one contract per customer schema |
| LLM use overall | **LLM only as confirmer / onboarding helper** | hybrid LLM cost $0.0000/M rows vs n/a/M rows to review every row | verdict + reason stored | cached by input hash | prompt per problem code |

Data source for Project B numbers: **nyc_open_data**. If this says SYNTHETIC_FIXTURE, rerun `python run_all.py` with internet access before relying on the Project B rows.
