# AI usage note

## Tools and what they were used for

| Tool | Used for |
|---|---|
| Claude (Anthropic), as a coding agent | Reading the brief; checking official sources (Income Tax Department rate pages, Budget Speech 2025-26 annex, Finance (No. 2) Act 2024 / Finance Act 2025 references, Gemini pricing page, NYC Open Data API); writing the rule text, all code, the test suites and the 70 plain-language descriptions; drafting the reports' fixed prose and both design write-ups. |
| Claude, acting as the "LLM compiler" during development | Producing the first compiled-rules files (`impl_llm_compiled/compiled/*.json`) from the rule text alone, in the DSL that `compile.py` asks Gemini for. `run_all.py` also compiles with Gemini and reports how the *unreviewed* Gemini output scores. |
| Gemini (`gemini-2.5-flash`, free tier) | The runtime LLM the brief specifies: query-time tax computation (b), compilation (c), free-text extraction, and data-quality review in Project B. All calls go through `common/llm.py` and are cached in `.llm_cache/`. |

## Where the AI was wrong, and how it was caught

1. **Wrong expected values in hand-worked tests.** The assistant wrote four "hand-worked" anchor cases
   (`tests/test_anchors.py`). Two were arithmetic slips: ₹7.77 lakh under the old regime was written as ₹63,380
   (correct: ₹60,220 — TI 7,27,000 → 12,500 + 45,400 = 57,900 + 4% cess = 60,216 → 288B → 60,220), and ₹7 lakh with
   full 80C under the new regime was written as ₹20,800 (correct: nil — TI 6,25,000 is inside the ₹7 lakh rebate).
   **Caught** because the tests failed against *two* independently written implementations (the oracle and the
   engine) that agreed with each other; re-deriving by hand showed the test, not the code, was wrong.
2. **A silent parser bug.** The first rule parser skipped any amount preceded by the word "pay", because the
   guard for "AY 2026-27" was the regex `(fy|ay)\s*$` without a word boundary — "p**ay**" matched. "I pay ₹22,000
   health insurance" silently lost its 80D amount. **Caught** by the 50-description suite (first pass 36/50, see
   `project_a/parser/DEV_LOG.md`); fixed with `\b(fy|ay)`.
3. **An impossible number from the data tool.** While profiling NYC 311 through SoQL, several queries came back as
   `23,138,125` rows — more than the 3,224,723 rows created in 2023. **Caught** by sanity-checking every count
   against the year total; those queries were discarded and computed locally from the sample instead (noted in
   `project_b/data/soql_snapshot_2026-11-15.json`).
4. **Library-version assumption.** Code written for older pandas assumed `.astype(str)` turns missing values into
   the string `"nan"`; pandas 3 keeps them missing, which crashed the ZIP check. A pandas 3 `groupby().apply`
   change also dropped a column the LLM-evaluation code relied on. **Caught** by running the whole pipeline end to
   end (including a dry run with a fake Gemini transport) before any real quota was spent.

## What was checked by hand

* Every tax rate, slab, limit and threshold in `project_a/sources/` against the Income Tax Department's pages and
  the Budget 2025-26 annex table (the oracle reproduces that table exactly — `test_anchors.py`).
* The 30 official-calculator cross-checks (`official_calculator_checks.csv`) — to be entered on the official
  calculator; the count shown in `RESULTS_A.md` is whatever has actually been entered.
