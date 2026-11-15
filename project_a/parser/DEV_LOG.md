# Rule-parser development log (kept so the in-sample score is not mistaken for accuracy)

| Step | Set | Score | Notes |
|---|---|---|---|
| First run, before any tuning | dev 50 | 36 / 50 (1 unsafe guess, 10 over-asks, 3 wrong values) | Main bug: clause splitting on "." broke decimals ("1.2 lakh" -> "1" and "2 lakh"). Second bug: the assessment-year guard `(fy|ay)\s*$` matched the end of the word "pay", so "I pay 22,000 health insurance" silently dropped the amount. |
| After fixes | dev 50 | 50 / 50 | In-sample: the parser was tuned on these 50, so this number overstates real accuracy. |
| Parser frozen, then scored once | held-out 20 (written after freezing) | 16 / 20, 0 unsafe guesses, 1 wrong value | H07: parents' uninsured medical bills booked under self/family 80D instead of parents — a silent wrong answer. H08/H18 over-asked (bonus sentence, "she is 30"). H05 asked for salary instead of flagging consulting income as out of scope (safe, but the wrong question). |

The held-out figure is the honest estimate of the rule parser on unseen phrasing. `run_all.py` re-scores both sets.
