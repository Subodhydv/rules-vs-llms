"""LLM extractor (Gemini) + the same deterministic validator, i.e. the hybrid parser.

The LLM only *extracts*; it never decides that the input is complete. validate() does that, and also checks
that every amount the LLM returns can be traced to a number in the user's text (hallucination guard).
"""
from __future__ import annotations

from common.llm import GeminiClient
from project_a.parser import rule_parser
from project_a.parser.validate import BOOL_FIELDS, MONEY_FIELDS, Extraction, ParseResult, validate

SYSTEM = ("You extract structured tax inputs from an Indian salaried taxpayer's free-text description. "
          "The text may be English, Hindi or Hinglish, informal, incomplete or contradictory. "
          "Never guess: use null for anything not stated. Return JSON only.")

PROMPT = """Extract these fields (all money as ANNUAL rupees; convert per-month amounts x12; 1 lakh = 100000;
1 crore = 10000000; 'k' = 1000; LPA = lakh per annum):
fy ("2024-25" or "2025-26" if stated, AY 2025-26 means FY 2024-25; else null), age (int), resident (false only if
NRI/non-resident, else null), gross_salary, basic_da (basic + DA), hra_received, rent_paid,
metro (true only for Delhi, Mumbai, Kolkata, Chennai; false for any other city incl. Noida/Gurgaon/Bengaluru;
null if no city), sec80c (sum of EPF/PF, PPF, ELSS, LIC, tuition, home-loan PRINCIPAL; 150000 if "80C maxed/full"),
sec80ccd1b (own NPS), sec80d_self_family (health insurance / medical for self, spouse, children),
sec80d_parents (health insurance / medical for parents), spouse_senior (true if spouse is 60+),
parents_senior (true if a parent is 60+, false if both below 60, null if unknown), home_loan_interest
(self-occupied house only).

Also return:
"mentioned_without_amount": list from ["home_loan", "health_insurance", "hra", "rent"] for items the user
mentions but gives no amount for;
"issues": list of {"field": <field name or "out_of_scope">, "kind": "conflict"|"ambiguous_period"|"ctc"|
"invalid"|"out_of_scope"|"ambiguous", "detail": str}. Report: two different values for one field; a salary
without "per month"/"per year" when it could be either; CTC/package given instead of gross salary; impossible
values; any non-salary income (capital gains, freelance, business, consulting, rental, interest);
a let-out (rented-out) house; two possible cities.

Description:
\"\"\"{text}\"\"\"

Return JSON: {"fy":..,"age":..,"resident":..,"gross_salary":..,"basic_da":..,"hra_received":..,"rent_paid":..,
"metro":..,"sec80c":..,"sec80ccd1b":..,"sec80d_self_family":..,"sec80d_parents":..,"spouse_senior":..,
"parents_senior":..,"home_loan_interest":..,"mentioned_without_amount":[..],"issues":[..]}"""


def extract(text: str, client: GeminiClient | None = None, variant: int = 0) -> tuple[Extraction, dict]:
    client = client or GeminiClient()
    resp = client.generate_json(PROMPT.replace("{text}", text), system=SYSTEM, variant=variant)
    meta = {"latency_ms": resp.latency_ms, "cost_usd": resp.cost_usd, "input_tokens": resp.input_tokens,
            "output_tokens": resp.output_tokens, "cached": resp.cached}
    d = resp.data if isinstance(resp.data, dict) else {}
    if resp.error or not d:
        ex = Extraction({}, set(), [{"field": "gross_salary", "kind": "invalid", "detail": "LLM output unparseable"}],
                        "llm")
        return ex, meta
    fields = {}
    for k in MONEY_FIELDS + ["age"]:
        v = d.get(k)
        fields[k] = None if v is None or v == "" else int(round(float(v)))
    for k in BOOL_FIELDS:
        v = d.get(k)
        fields[k] = v if isinstance(v, bool) else None
    if fields.get("resident") is None:
        fields.pop("resident")
    fy = d.get("fy")
    if fy:
        fields["fy"] = str(fy)
    issues = [i for i in d.get("issues", []) if isinstance(i, dict) and i.get("field")]
    return Extraction(fields, set(d.get("mentioned_without_amount") or []), issues, "llm"), meta


def parse(text: str, client: GeminiClient | None = None, default_fy: str = "2024-25",
          variant: int = 0) -> tuple[ParseResult, dict]:
    ex, meta = extract(text, client, variant)
    return validate(ex, default_fy=default_fy, text=text), meta


def parse_hybrid(text: str, client: GeminiClient | None = None, default_fy: str = "2024-25") -> tuple[ParseResult, dict]:
    """Shipping design: LLM extraction when available; if it fails, fall back to the rule extractor.
    If both extractors produce complete-but-different profiles, ask rather than pick one."""
    try:
        llm_res, meta = parse(text, client, default_fy)
    except Exception as e:  # noqa: BLE001 - LLM outage must not take the service down
        return rule_parser.parse(text, default_fy), {"fallback": f"{type(e).__name__}"}
    rule_res = rule_parser.parse(text, default_fy)
    if llm_res.status == "complete" and rule_res.status == "complete":
        a, b = llm_res.profile.to_dict(), rule_res.profile.to_dict()
        diff = [k for k in a if a[k] != b[k]]
        if diff:
            from project_a.parser.validate import QUESTIONS
            llm_res.status, llm_res.profile = "clarify", None
            llm_res.questions = [{"field": k, "question": QUESTIONS.get(k, f"Please confirm {k}."),
                                  "why": f"extractors disagree: {a[k]} vs {b[k]}"} for k in diff]
            meta["disagreement"] = diff
    return llm_res, meta
