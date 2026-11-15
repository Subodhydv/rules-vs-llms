import pytest

from project_a.impl_rules import engine
from project_a.models import Profile, UnsupportedYear, clause_ids


def test_all_cases_fy2425(cases_2425):
    wrong = []
    for c in cases_2425:
        r = engine.compute(Profile.from_dict(c["profile"]))
        got = (r.old.tax_payable, r.new.tax_payable, r.recommended)
        exp = (c["expected"]["old"], c["expected"]["new"], c["expected"]["recommended"])
        if got != exp:
            wrong.append((c["id"], got, exp))
    assert not wrong, wrong[:5]
    assert len(cases_2425) >= 200


def test_every_rupee_traces_to_a_clause(cases_2425):
    valid = clause_ids("2024-25")
    for c in cases_2425:
        r = engine.compute(Profile.from_dict(c["profile"]))
        for reg in (r.old, r.new):
            assert all(li.clause in valid for li in reg.line_items)
            inc = sum(li.amount for li in reg.line_items if li.stage == "income")
            tax = sum(li.amount for li in reg.line_items if li.stage == "tax")
            assert abs(inc - reg.total_income) < 0.01 and abs(tax - reg.tax_payable) < 0.01


def test_unknown_year_fails_loudly():
    with pytest.raises(UnsupportedYear):
        engine.compute(Profile(fy="2030-31", age=30, gross_salary=1000000))


def test_round10():
    assert [engine.round10(x) for x in (0, 4, 5, 14, 15, 1234.99, 1235)] == [0, 0, 10, 10, 20, 1230, 1240]
