"""Deterministic completeness / consistency checks shared by every extractor (Task 3).

An extractor (rule-based or LLM) produces an `Extraction`: field values (None = not stated), topics that were
mentioned without an amount, and issues it noticed. `validate()` turns that into either a complete Profile or a
list of clarifying questions. This layer is pure rules on purpose: deciding *whether we know enough to compute
tax* must be deterministic and auditable even when the extraction itself came from an LLM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from project_a.models import Profile, SUPPORTED_FY

MONEY_FIELDS = ["gross_salary", "basic_da", "hra_received", "rent_paid", "sec80c", "sec80ccd1b",
                "sec80d_self_family", "sec80d_parents", "home_loan_interest"]
BOOL_FIELDS = ["metro", "resident", "spouse_senior", "parents_senior"]

QUESTIONS = {
    "gross_salary": "What is your total gross salary for the year (before tax, as on Form 16), and is the figure "
                    "monthly or annual?",
    "age": "What is your age? (It changes the old-regime slabs and the 80D limits.)",
    "rent_paid": "You mentioned HRA. Do you pay rent, and how much per year?",
    "hra_received": "You pay rent. Does your salary include an HRA component? If yes, how much per year?",
    "basic_da": "To work out the HRA exemption I need your basic salary plus DA for the year. What is it?",
    "metro": "In which city is your rented home? (Delhi, Mumbai, Kolkata and Chennai get the 50% HRA limit; "
             "every other city gets 40%.)",
    "parents_senior": "Is either of your parents aged 60 or above? (The 80D limit for parents is Rs 50,000 if so, "
                      "otherwise Rs 25,000.)",
    "home_loan_interest": "How much home-loan interest do you pay in the year, and do you live in that house?",
    "sec80d_self_family": "How much health-insurance premium do you pay in the year for yourself and your family?",
    "sec80c": "How much did you invest under section 80C (EPF, PPF, ELSS, LIC, home-loan principal, ...)?",
    "out_of_scope": "This service covers salary income only. Should I compute tax on your salary alone and leave "
                    "the other income out?",
    "fy": "Which financial year is this for: 2024-25 or 2025-26?",
}


@dataclass
class Extraction:
    fields: dict = field(default_factory=dict)          # field -> value or None
    mentioned: set = field(default_factory=set)         # e.g. {"home_loan", "health_insurance", "hra", "rent"}
    issues: list = field(default_factory=list)          # {"field": str, "kind": str, "detail": str}
    source: str = "rules"


@dataclass
class ParseResult:
    status: str                                         # "complete" | "clarify"
    profile: Profile | None
    questions: list = field(default_factory=list)       # {"field": str, "question": str, "why": str}
    assumptions: list = field(default_factory=list)
    extraction: Extraction | None = None

    @property
    def ask_fields(self) -> list[str]:
        return [q["field"] for q in self.questions]


def _ask(qs, fld, why):
    if fld not in [q["field"] for q in qs]:
        qs.append({"field": fld, "question": QUESTIONS.get(fld, f"Please clarify {fld}."), "why": why})


def grounded_amounts(text: str) -> set[int]:
    """Every rupee value a text could plausibly mean (x1, x12, lakh, crore, k), used to catch hallucinations."""
    t = text.lower().replace(",", "")
    vals = set()
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(crores?|cr\b|lakhs?|lacs?|lpa|l\b|k\b|thousand|hazaa?r)?", t):
        n = float(m.group(1))
        unit = (m.group(2) or "").strip()
        mult = 1e7 if unit.startswith("cr") else 1e5 if unit[:1] == "l" else 1e3 if unit in ("k", "thousand") \
            or unit.startswith("haza") else 1
        v = int(round(n * mult))
        vals.update({v, v * 12})
    return vals


def validate(ex: Extraction, default_fy: str = "2024-25", text: str | None = None) -> ParseResult:
    f = dict(ex.fields)
    qs, assumptions = [], []

    for issue in ex.issues:
        _ask(qs, issue["field"], issue.get("detail", issue["kind"]))

    # Hallucination guard: every non-zero amount must be derivable from a number in the user's text.
    if text is not None and ex.source != "rules":
        allowed = grounded_amounts(text)
        for k in MONEY_FIELDS:
            v = f.get(k)
            if v and int(v) not in allowed and not any(abs(int(v) - a) <= 1 for a in allowed):
                if k == "sec80c" and int(v) == 150000 and re.search(r"max|full|pura|poora", text.lower()):
                    continue
                if k == "sec80ccd1b" and int(v) == 50000 and re.search(r"max|full", text.lower()):
                    continue
                if k in ("gross_salary", "sec80c") and v and _is_sum_of_mentions(int(v), allowed):
                    continue
                _ask(qs, k, f"value {v} not found in the text")

    fy = f.get("fy") or default_fy
    if fy not in SUPPORTED_FY:
        _ask(qs, "fy", f"unsupported FY {fy}")

    g = f.get("gross_salary")
    if g is None:
        _ask(qs, "gross_salary", "salary not stated")
    elif g < 0:
        _ask(qs, "gross_salary", "negative salary")
    age = f.get("age")
    if age is None:
        _ask(qs, "age", "age not stated")
    elif not (15 <= age <= 110):
        _ask(qs, "age", f"implausible age {age}")

    hra, rent, basic = f.get("hra_received"), f.get("rent_paid"), f.get("basic_da")
    hra_known_positive = (hra or 0) > 0 or ("hra" in ex.mentioned and hra is None)
    if hra_known_positive and rent is None:
        _ask(qs, "rent_paid", "HRA mentioned but rent not stated")
    if (rent or 0) > 0 and hra is None:
        _ask(qs, "hra_received", "rent stated but HRA not stated")
    if (hra or 0) > 0 and (rent or 0) > 0:
        if not basic:
            _ask(qs, "basic_da", "needed for HRA limits (b) and (c)")
        if f.get("metro") is None:
            _ask(qs, "metro", "city decides 50% vs 40%")
    if (f.get("sec80d_parents") or 0) > 0 and f.get("parents_senior") is None:
        _ask(qs, "parents_senior", "parents' age decides the 80D limit")
    if "home_loan" in ex.mentioned and f.get("home_loan_interest") is None:
        _ask(qs, "home_loan_interest", "home loan mentioned without interest amount")
    if "health_insurance" in ex.mentioned and f.get("sec80d_self_family") is None \
            and f.get("sec80d_parents") is None:
        _ask(qs, "sec80d_self_family", "health insurance mentioned without amount")

    if qs:
        return ParseResult("clarify", None, qs, assumptions, ex)

    for k in MONEY_FIELDS:
        if f.get(k) is None:
            f[k] = 0
            if k not in ("basic_da", "hra_received", "rent_paid"):
                assumptions.append(f"{k}: not mentioned, taken as Rs 0")
    for k, default in (("metro", False), ("resident", True), ("spouse_senior", False), ("parents_senior", False)):
        if f.get(k) is None:
            f[k] = default
    if not f.get("fy"):
        assumptions.append(f"financial year not stated, using the service default FY {default_fy}")
    if f.get("resident"):
        assumptions.append("resident individual (say so if you are an NRI)")
    prof = Profile(fy=fy, **{k: f[k] for k in ["age", "resident", *MONEY_FIELDS, "metro", "spouse_senior",
                                                "parents_senior"]})
    return ParseResult("complete", prof, [], assumptions, ex)


def _is_sum_of_mentions(v: int, allowed: set[int]) -> bool:
    vals = sorted(a for a in allowed if 0 < a <= v)
    s = set(vals)
    for a in vals:
        if v - a in s:
            return True
        for b in vals:
            if v - a - b in s and b != a:
                return True
    return False
