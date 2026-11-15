# Review log — LLM-compiled rules

The runtime only ever loads `compiled/fy<YYYY_YY>.json`. A file gets there only after these gates:

1. **Static validation** (`dsl.validate`): JSON shape, every expression parses under the whitelist (no attribute
   access, no lambdas, no imports, no calls except `min/max/slab_tax/round10`), every name is an input or an
   earlier step, every table exists, every step cites a clause ID that exists in the rule text.
2. **Test-suite gate** (`compile.gate`): all cases for that year must match the expected tax to the rupee.
3. **Line-item reconciliation**: for every case, income line items sum to total income and tax line items sum to
   tax payable (checked in `tests/test_compiled.py`).
4. **Human review checklist** (below), recorded per year.

## FY 2024-25 — `compiled/fy2024_25.json`

Provenance: produced by an LLM from `sources/fy2024_25_rules.md` alone, in the DSL format specified in
`compile.py`. During development the LLM was Claude (the coding assistant); the brief's runtime LLM is Gemini,
and `python -m project_a.impl_llm_compiled.compile --fy 2024-25` regenerates a Gemini candidate into
`compiled/candidates/` and runs the same gates. `run_all.py` reports how the unreviewed Gemini candidate scores.

| Gate | Result |
|---|---|
| Static validation | 0 problems |
| Test suite (230 cases) | 230 / 230 rupee-exact on the first draft |
| Line-item reconciliation | 0 failures across 460 regime computations |
| Safety probe (`__import__`, attribute access, lambda, list literals) | all rejected by the parser |

Human review checklist (FY 2024-25):

- [x] Slab tables match [O-SLAB] for all three age bands and [N-SLAB].
- [x] 87A old: `<= 500000`, max 12,500, residents only. 87A new: `<= 700000`, max 25,000, plus the [N-87A-MR]
      marginal relief step for income above 7 lakh.
- [x] Surcharge bands and marginal-relief base rates: old 10/15/25/37 at 50L/1Cr/2Cr/5Cr; new capped at 25%.
- [x] HRA: least of three limbs, only when both HRA and rent are positive; 50% only for the four metros.
- [x] 80D: senior limit for self applies if the taxpayer (resident, 60+) **or** the spouse is senior.
- [x] Home-loan interest capped at 2 lakh and set off only up to salary income (gross total income >= 0).
- [x] Chapter VI-A total capped at gross total income.
- [x] Rounding: 288A on total income before slabs; 288B on the final tax only.

Findings: none blocking. One readability note: the old-regime `house_property_loss` uses a three-way `min`
(interest, 2 lakh cap, salary income), which folds [O-HP]'s set-off limit into one step; it is correct but the
line item cites only [O-HP]. Accepted as is.

## FY 2025-26 — see RESULTS_A.md, Task 5 change log

## FY 2025-26 — `compiled/fy2025_26.json` (Task 5)

Provenance: recompiled by the development LLM from `sources/fy2025_26_rules.md`; regenerate with Gemini via
`python -m project_a.impl_llm_compiled.compile --fy 2025-26` (also run by `law_change.py`).

| Gate | Result |
|---|---|
| Static validation | 0 problems |
| FY 2025-26 suite (230 cases, written before the change) | 230 / 230 |
| Difference from FY 2024-25 file | new-regime table; 87A limit/maximum; marginal-relief threshold (13 JSON lines) |

Review note: the marginal-relief step holds its own copy of the 12-lakh threshold. The mutation test shows that
forgetting it leaves only 9 of 230 cases wrong and passes static validation — so the reviewer checks it
explicitly, and the release gate requires full-suite agreement, not a spot check.
