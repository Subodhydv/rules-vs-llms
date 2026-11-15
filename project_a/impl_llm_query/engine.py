"""Implementation (b): LLM at query time.

For every request the LLM receives the full rule text for the requested year plus the structured profile
and must return both regime computations as JSON with clause-cited line items. Nothing is precomputed.
"""
from __future__ import annotations

import json

from common.llm import GeminiClient, LLMResponse
from project_a.models import Comparison, LineItem, Profile, RegimeResult, explain, recommend, rule_text

SYSTEM = (
    "You are an Indian income-tax computation engine. Use ONLY the rule text provided. "
    "Compute exactly, step by step, to the rupee. Every line item must cite one clause ID from the rule text. "
    "Return JSON only."
)

SCHEMA = """{
  "old": {"line_items": [{"label": str, "amount": number, "clause": "<clause ID>", "stage": "income"|"tax"}],
          "total_income": int, "tax_payable": int},
  "new": {same shape},
  "recommended": "old" | "new",
  "explanation": str
}
Rules for line items: stage="income" items (gross salary as a positive amount, exemptions and deductions as
negative amounts, rounding adjustments) must sum to total_income; stage="tax" items (slab tax, rebate as a
negative amount, surcharge, marginal relief as a negative amount, cess, final rounding) must sum to
tax_payable. tax_payable is the final amount after section 288B rounding."""


def build_prompt(p: Profile, fy_text: str | None = None) -> str:
    text = fy_text if fy_text is not None else rule_text(p.fy)
    return (f"RULE TEXT\n=========\n{text}\n\nTAXPAYER (financial year {p.fy}; all amounts annual, in rupees)\n"
            f"========\n{json.dumps(p.to_dict(), indent=1)}\n\n"
            f"Field notes: basic_da = basic salary + DA (the 'salary' for HRA); metro = rented home in Delhi, "
            f"Mumbai, Kolkata or Chennai; home_loan_interest is for a self-occupied house.\n\n"
            f"Compute the tax under BOTH regimes and recommend one. Respond with JSON of this shape:\n{SCHEMA}")


def _regime(d: dict, name: str) -> RegimeResult:
    items = [LineItem(str(li.get("label", "")), float(li.get("amount", 0)), str(li.get("clause", "")),
                      str(li.get("stage", "tax"))) for li in d.get("line_items", [])]
    return RegimeResult(name, int(round(float(d["total_income"]))), int(round(float(d["tax_payable"]))), items)


def compute(p: Profile, client: GeminiClient | None = None, variant: int = 0,
            fy_text: str | None = None) -> Comparison:
    """Raises LLMUnavailable if no key/cache. Malformed output raises ValueError (counted as wrong)."""
    client = client or GeminiClient()
    resp: LLMResponse = client.generate_json(build_prompt(p, fy_text), system=SYSTEM, variant=variant)
    meta = {"latency_ms": resp.latency_ms, "input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens,
            "cost_usd": resp.cost_usd, "cached": resp.cached}
    if resp.error or not isinstance(resp.data, dict):
        raise ValueError(f"unparseable LLM output: {resp.error}")
    d = resp.data
    old, new = _regime(d["old"], "old"), _regime(d["new"], "new")
    rec = d.get("recommended") if d.get("recommended") in ("old", "new") else recommend(old.tax_payable,
                                                                                         new.tax_payable)
    c = Comparison(p.fy, old, new, rec, str(d.get("explanation") or ""), meta)
    if not c.explanation:
        c.explanation = explain(c)
    return c
