import pytest

from project_a.impl_llm_compiled import dsl
from project_a.models import Profile, clause_ids


def test_compiled_matches_suite(cases_2425):
    doc = dsl.load("2024-25")
    wrong = [c["id"] for c in cases_2425
             if (lambda r: (r.old.tax_payable, r.new.tax_payable))(dsl.compute(Profile.from_dict(c["profile"]), doc))
             != (c["expected"]["old"], c["expected"]["new"])]
    assert not wrong


def test_compiled_line_items_reconcile(cases_2425):
    valid = clause_ids("2024-25")
    for c in cases_2425[:80]:
        r = dsl.compute(Profile.from_dict(c["profile"]))
        for reg in (r.old, r.new):
            assert all(li.clause in valid for li in reg.line_items)
            assert abs(sum(li.amount for li in reg.line_items if li.stage == "tax") - reg.tax_payable) < 0.01


@pytest.mark.parametrize("expr", ['__import__("os").system("id")', "gross_salary.__class__", "(lambda: 1)()",
                                  "[1, 2]", "open('x')", "x if y else z if a else b.c"])
def test_dsl_rejects_code(expr):
    with pytest.raises(dsl.CompiledRuleError):
        dsl.parse(expr)


def test_validator_catches_bad_clause_and_name():
    doc = dsl.load("2024-25")
    bad = {**doc, "regimes": {**doc["regimes"], "new": {**doc["regimes"]["new"], "steps": [
        {"name": "x", "expr": "undefined_name + 1", "clause": "N-NOPE", "line_item": None}],
        "total_income": "x", "tax_payable": "x"}}}
    problems = dsl.validate(bad, "2024-25")
    assert any("unknown name" in p for p in problems) and any("not in rule text" in p for p in problems)
