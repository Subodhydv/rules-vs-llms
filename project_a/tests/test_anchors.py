"""Hand-checked anchors from official documents and by hand. If these fail, the oracle itself is wrong."""
import pytest

from project_a.tests import oracle

# Budget Speech 2025-26, Annexure to Part B: tax on income under the new regime at present (FY 2024-25) and
# proposed (FY 2025-26) slab rates, before rebate and cess.
BUDGET_2025_TABLE = [  # (income, FY24-25 slab tax, FY25-26 slab tax)
    (800000, 30000, 20000), (900000, 40000, 30000), (1000000, 50000, 40000), (1100000, 65000, 50000),
    (1200000, 80000, 60000), (1600000, 170000, 120000), (2000000, 290000, 200000), (2400000, 410000, 300000),
]


@pytest.mark.parametrize("income,t2425,t2526", BUDGET_2025_TABLE)
def test_budget_speech_table(income, t2425, t2526):
    assert oracle.new_slab_tax(income, "2024-25") == t2425
    assert oracle.new_slab_tax(income, "2025-26") == t2526


@pytest.mark.parametrize("income,benefit", [(1800000, 70000), (2500000, 110000), (5000000, 110000)])
def test_budget_speech_benefits(income, benefit):
    # Budget speech: benefit of Rs 70,000 at 18 lakh, Rs 1,10,000 at 25 lakh and at 50 lakh
    assert oracle.new_slab_tax(income, "2024-25") - oracle.new_slab_tax(income, "2025-26") == benefit


def test_salary_12_75_lakh_nil_tax_fy2526():
    # "Salaried class to pay nil income tax up to 12.75 lakh" (12 lakh + 75,000 standard deduction)
    assert oracle.compute({"fy": "2025-26", "gross_salary": 1275000, "age": 30})["new"]["tax_payable"] == 0


HAND = [
    # (profile, old, new) worked by hand, FY 2024-25
    # 10L salary, no deductions. Old: TI 9.5L -> 12,500 + 90,000 = 1,02,500 + 4% = 1,06,600.
    #   New: TI 9.25L -> 20,000 + 22,500 = 42,500 + 4% = 44,200.
    ({"gross_salary": 1000000, "age": 30}, 106600, 44200),
    # 7.75L salary: new TI 7L -> tax 20,000, rebate 20,000 -> 0. Old TI 7.25L -> 12,500+45,000=57,500+4%=59,800.
    ({"gross_salary": 775000, "age": 30}, 59800, 0),
    # New TI 7,02,000: tax 20,200; marginal relief rebate = 20,200 - 2,000 = 18,200; 2,000 + 4% = 2,080.
    #   Old TI 7,27,000: 12,500 + 20% x 2,27,000 = 57,900 + 4% = 60,216 -> 288B -> 60,220.
    ({"gross_salary": 777000, "age": 30}, 60220, 2080),
    # Old TI exactly 5L after 80C -> rebate 12,500 wipes 12,500 tax.
    #   New TI 6,25,000 -> tax 16,250, within the 7 lakh rebate -> 0.
    ({"gross_salary": 700000, "age": 30, "sec80c": 150000}, 0, 0),
]


@pytest.mark.parametrize("prof,old,new", HAND)
def test_hand_worked(prof, old, new):
    r = oracle.compute(dict(prof, fy="2024-25"))
    assert (r["old"]["tax_payable"], r["new"]["tax_payable"]) == (old, new)
