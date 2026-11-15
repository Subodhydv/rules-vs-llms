## 6. Final design for 100,000 users (Task 6)

```
 user text ──► [1] EXTRACT ─────────► [2] VALIDATE ──► complete? ──no──► clarifying question ──► user
               hybrid: Gemini JSON      rule: required fields,      │
               extraction; rule          conflicts, periods, CTC,    yes
               extractor as fallback     HRA/rent/city/basic,        ▼
               and cross-check           parents' age, grounding   [3] COMPUTE (rule) ── config per FY,
                                         of every amount            both regimes, line items with clause IDs
                                                                     ▼
                                                     [4] RECOMMEND + EXPLAIN (rule, template, clause-cited)
 Budget day: rule text ──► [5] hand-edit config (rule)  ┐
                           [6] LLM compiles DSL (LLM)   ├─► [7] GATE: both encodings agree on the full new
                           [8] oracle + official anchors┘        suite + mutation tests + official spot check
```

| # | Component | Label | Why (from the measurements above) |
|---|---|---|---|
| 1 | Free-text extraction | **hybrid** | {extract_why} |
| 2 | Completeness / clarifying questions | **rule** | Whether we may compute must not depend on a sampled model. The validator produced **0 unsafe guesses** on 70 descriptions and is applied to LLM output too; its grounding check rejects any amount not derivable from the user's numbers. |
| 3 | Tax computation | **rule** | {compute_why} |
| 4 | Recommendation and explanation | **rule** | Two exact numbers decide it ([G-REGIME]); a template built from the engine's line items cites clauses. An LLM rewrite would add cost and a chance of misquoting a number, for prose quality nobody asked for. |
| 5–7 | Keeping the rules current | **hybrid** | The hand-edited config absorbed FY 2025-26 with {rules_lines} config lines and 0 code, 230/230 first run. The mutation test shows the real risk: single-number slips (rebate limit, marginal-relief threshold, a missing slab) give **wrong answers with no error**. So the LLM is used once per Budget to compile an independent second encoding; the release gate requires both encodings to agree on the whole new suite. Two encodings that disagree point straight at the clause to re-read. |
| — | LLM at query time | **not shipped** | {query_why} |

**Cost and capacity at 100,000 users.** Compute is ~{rules_ms} ms of CPU per request, so the engine is free in
practice. The only paid component is extraction: {cost_line} Clarification turns add calls; caching identical
texts and skipping the LLM when the rule extractor is already complete and agrees cut that further. If the LLM
is down, the rule extractor still serves (held-out {rule_heldout}/20, and it asks rather than guesses).

**Keeping it correct through the next Budget.**
1. *Tests first.* Update the oracle and generate the new year's suite before touching any implementation; pin it
   with official worked figures (this year: the Budget speech annex table), and enter ~30 cases on the official
   calculator once it is updated.
2. *Year is explicit.* One config file per FY; an unknown FY raises `UnsupportedYear`. This turned 189/230 silent
   errors into a loud failure in Task 5.
3. *Two independent encodings must agree* (hand-edited YAML vs LLM-compiled DSL) on every case, with line items
   reconciling to the rupee.
4. *Mutation tests* in CI (forget the rebate, forget a slab, stale marginal-relief threshold) prove the suite would
   catch the classic slips.
5. *Effective-date switch, not a code deploy:* the new config ships dark and is enabled for requests whose FY is
   the new year; old years stay frozen and keep their own suites.
6. *Shadow run* the new year on real (anonymised) traffic against an independent calculation before the filing
   season, and alert on any line item that cannot be traced to a clause.
