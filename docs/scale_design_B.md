## 6. Scale and design: 50 million rows a day, 120 customers (Task 6)

**Projection from the measured numbers** (`results/project_b_scale.json`):

| Quantity | Value |
|---|---|
| Rows per day / per customer per day | {rows_per_day} / {rows_per_customer_per_day} |
| Average / assumed peak rate (5x) | {avg_rows_per_sec} / {peak_rows_per_sec} rows/s |
| Measured hybrid throughput, one core, excl. LLM | {measured_single_core_rows_per_sec} rows/s |
| CPU core-hours per day for rules + statistics | {cpu_core_hours_per_day} |
| Cores needed at peak | {cores_needed_at_peak} |
| LLM cost per reviewed row ({llm_cost_basis}) | ${llm_usd_per_row} |
| Share of rows sent to the LLM ({llm_share_basis}) | {llm_share_of_rows} |
| **LLM cost per day, hybrid** | **${llm_usd_per_day_hybrid}** ({llm_calls_per_day_hybrid} calls) |
| LLM cost per day if every row were reviewed | ${llm_usd_per_day_if_every_row} ({llm_calls_per_day_if_every_row} calls) |
| LLM cost per month: hybrid vs every row | ${llm_usd_per_month_hybrid} vs ${llm_usd_per_month_if_every_row} |

Latency: rule and statistical checks add milliseconds per 2,000-row batch, so a batch can be gated before it
reaches a dashboard. LLM confirmations are asynchronous: the row is held in a "pending review" state, or shown with
a warning badge, until the verdict arrives (seconds), so the LLM is never on the critical path of a dashboard load.
Reviewing every row is not just expensive: at 40 rows per call it needs over a million calls a day, far beyond
free-tier and typical paid rate limits.

**What changes at this scale, and why**

1. *Schemas become configuration.* With 120 different schemas, the column contract, dtypes, date formats, lookup
   tables (ZIP→region, type→descriptor) and null-rate thresholds live in a per-customer contract file, versioned
   and reviewed like code. The LLM's best use moves to **onboarding**: proposing a mapping from a new customer's
   columns to the canonical contract, once, for a human to approve — one call per customer instead of per row.
2. *Statistics are per customer × segment.* Baselines (null rates per agency/department, category pairs, duration
   quantiles) are fitted per customer and refreshed on a schedule with drift guards, because one global baseline
   either misses spikes in small customers or floods large ones with alarms. Alert thresholds are set per
   customer to a false-alarm budget (e.g. ≤ 1 alert per million clean rows per check).
3. *Rules run in the ingestion engine, not in pandas.* At 50M rows/day the same checks move into the warehouse or
   stream processor (SQL / DuckDB / Spark expressions generated from the contract), so they scale horizontally;
   the Python here is the reference implementation and test oracle.
4. *Near-duplicate search becomes indexed.* Pairwise comparison within blocks is fine per batch; across days it
   needs blocking keys plus MinHash/LSH over a rolling window, held per customer.
5. *The LLM tier gets budgets and caching.* A per-customer daily LLM budget, the Batch API (50% cheaper, latency
   acceptable for asynchronous confirmation), caching by row-content hash (templated texts repeat constantly), and
   a cheaper model (Flash-Lite) for the confirmation prompt, with the expensive model reserved for onboarding.
6. *Quarantine semantics and feedback.* Schema failures quarantine the batch; row failures annotate rather than
   drop. Analysts' "not a problem" clicks feed back as labelled data to recalibrate the statistical thresholds —
   that, not more LLM calls, is how false alarms keep falling.
7. *PII handling changes from detection to prevention.* At scale, text fields are redacted at ingestion by the
   regex/NER tier before storage; the LLM sees only text that has already been redacted, so it never becomes a
   path for personal data to leave the platform.
