# Rules vs LLMs — take-home (Fire AI)

Two systems, each built three ways and measured, with a defended final design.

| | Project A — Income-tax engine | Project B — Data-quality checks |
|---|---|---|
| Code | `project_a/` | `project_b/` |
| Results | `RESULTS_A.md` | `RESULTS_B.md` |
| Shared | `DECISION_MATRIX.md`, `AI_USAGE.md`, `common/llm.py` (Gemini client with cache) | |

## One command

```bash
python -m pip install -r requirements.txt
export GEMINI_API_KEY=...            # free tier (https://aistudio.google.com); optional, see below
python run_all.py                     # or: make all
```

This regenerates **every number** in `RESULTS_A.md`, `RESULTS_B.md` and `DECISION_MATRIX.md`:

1. builds the Project A test suites (230 cases per year) and runs all unit tests (`pytest`);
2. measures the three tax implementations and the parsers; runs the FY 2025-26 law-change experiment;
3. downloads a day-stratified sample of 2023 NYC 311 requests from NYC Open Data (first run only; ~110k rows,
   saved to `project_b/data/raw/`) and full-year SoQL counts;
4. profiles the data, injects the 12 problem types, measures rules / statistics / LLM review, runs the hybrid
   pipeline and the 50M-rows/day projection;
5. renders the three Markdown reports from `results/*.json`.

**Gemini quota.** A full run makes roughly 200 Gemini calls (sizes are configurable). Every response is cached
in `.llm_cache/` keyed by the exact prompt, so:
* if the free-tier daily limit stops the run part-way, the affected sections say "not run" — just run it again
  the next day and it resumes from the cache;
* once complete, commit `.llm_cache/` and `project_b/data/raw/`: anyone can then reproduce every number with
  `python run_all.py --offline`, with no key and no network.

Useful settings: `GEMINI_MODEL` (default `gemini-2.5-flash`), `GEMINI_RPM` (default 8), `LLM_MAX_CALLS`
(default 400), `LLM_SAMPLE_A` (query-time sample, default 40), `LLM_SAMPLE_B_POS` (injected rows per problem
shown to the LLM, default 8). Without a key, all non-LLM numbers are still produced and LLM cells say "not run".

## Layout

```
common/llm.py                    Gemini REST client: JSON mode, temperature 0, disk cache, rate limit, cost
project_a/
  sources/                       rule text with clause IDs (FY 2024-25, FY 2025-26) + official source list
  impl_rules/                    (a) hand-coded: one engine + one YAML per financial year
  impl_llm_query/                (b) LLM reads the rule text on every request
  impl_llm_compiled/             (c) LLM compiles rule text to a safe JSON DSL once; reviewed; runs without LLM
  parser/                        rule extractor, LLM extractor, deterministic validator / clarifying questions
  tests/                         oracle, case generator, 50 + 20 descriptions, official-calculator checklist
  evaluate.py, law_change.py     Tasks 4 and 5
project_b/
  fetch_data.py, profile_data.py data download and Task 1 profiling
  injector.py                    Task 2: 12 problem types at controlled rates with labels
  detectors/{rules,stats,llm_review}.py   Task 3: three families
  evaluate.py, pipeline.py, scale.py      Tasks 4, 5, 6
  fixture.py                     SYNTHETIC stand-in for tests/offline only (reports carry a banner if used)
docs/                            the two "max 2 pages" design write-ups (templates filled with measured numbers)
report.py, run_all.py            report rendering and the single command
```

## Before submitting

* Run `python run_all.py` once **with internet and a Gemini key**; check the top of `RESULTS_B.md` says
  `nyc_open_data` (not `SYNTHETIC_FIXTURE`) and no LLM cell says "not run".
* Enter the 30 cases in `project_a/tests/data/official_calculator_checks.csv` on the official calculator
  (https://www.incometax.gov.in/iec/foportal/income-tax-calculator), fill the `official_old/official_new`
  columns, and re-run `python run_all.py --offline` to update the count in `RESULTS_A.md`.
* Commit `.llm_cache/`, `project_b/data/raw/` and `results/`, then push to a private repo.
