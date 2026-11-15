"""Build the Project A test suite (Task 1).

Writes tests/data/cases_fy2024_25.json and tests/data/cases_fy2025_26.json. Each case has a profile and
expected tax under both regimes from the independent oracle (tests/oracle.py). Cases are grouped by
category so that every threshold in the rule text has cases just below, at, and just above it.

Run: python -m project_a.tests.generate_cases
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from project_a.tests import oracle

DATA = Path(__file__).parent / "data"
SD_NEW, SD_OLD = 75000, 50000


def P(**kw):
    base = dict(age=35, resident=True, gross_salary=0, basic_da=0, hra_received=0, rent_paid=0, metro=False,
                sec80c=0, sec80ccd1b=0, sec80d_self_family=0, sec80d_parents=0, spouse_senior=False,
                parents_senior=False, home_loan_interest=0)
    base.update(kw)
    return base


def around(x, deltas=(-10, 0, 10)):
    return [x + d for d in deltas]


def build(fy: str) -> list[dict]:
    cases: list[tuple[str, str, dict]] = []

    def add(cat, desc, prof):
        cases.append((cat, desc, prof))

    # 1. New-regime slab thresholds (gross = total income + standard deduction)
    new_thr = [300000, 700000, 1000000, 1200000, 1500000] if fy == "2024-25" else \
        [400000, 800000, 1200000, 1600000, 2000000, 2400000]
    for t in new_thr:
        for ti in around(t):
            add("new_slab_edge", f"new-regime TI {ti:,} (threshold {t:,})", P(gross_salary=ti + SD_NEW))

    # 2. New-regime 87A rebate and marginal relief zone
    lim = 700000 if fy == "2024-25" else 1200000
    breakeven = 727777 if fy == "2024-25" else 1270588
    for ti in [lim - 10, lim, lim + 10, lim + 1000, lim + 10000, breakeven - 10, breakeven, breakeven + 10,
               breakeven + 1000]:
        add("new_87a_edge", f"new-regime rebate/marginal relief TI {ti:,}", P(gross_salary=ti + SD_NEW))

    # 3. Old-regime slab thresholds for each age band
    for age, thr in [(35, [250000, 500000, 1000000]), (65, [300000, 500000, 1000000]), (85, [500000, 1000000])]:
        for t in thr:
            for ti in around(t):
                add("old_slab_edge", f"old-regime age {age} TI {ti:,}", P(age=age, gross_salary=ti + SD_OLD))
    # age boundaries 59/60/79/80
    for age in (59, 60, 79, 80):
        add("age_edge", f"age {age}, salary 9 lakh", P(age=age, gross_salary=900000))

    # 4. Old-regime 87A at Rs 5,00,000
    for ti in (499990, 500000, 500010, 500004, 500005):
        add("old_87a_edge", f"old-regime rebate edge TI {ti:,} (pre-rounding)", P(gross_salary=ti + SD_OLD))

    # 5. Surcharge thresholds and marginal-relief zones (both regimes)
    for t in (5000000, 10000000, 20000000, 50000000):
        for d in (-10, 0, 10, 50000, 200000, 1000000):
            g = t + d + SD_NEW
            add("surcharge_edge", f"surcharge zone near {t:,}: new TI {t + d:,}", P(gross_salary=g))
        for d in (0, 10, 100000, 500000):
            add("surcharge_edge_old", f"surcharge zone near {t:,}: old TI {t + d:,}",
                P(gross_salary=t + d + SD_OLD, age=45))

    # 6. Rounding under 288A (income) / 288B (tax)
    for tail in (1, 4, 5, 6, 9):
        add("rounding", f"income ending in {tail}", P(gross_salary=1234560 + tail, sec80c=33333))

    # 7. Standard deduction capped by salary
    for g in (30000, 50000, 60000, 75000, 80000):
        add("std_deduction_cap", f"tiny salary {g:,}", P(gross_salary=g))

    # 8. HRA exemption — each limb binding, metro / non-metro, no rent, rent < 10% basic
    hra_cases = [
        ("limb (a) actual HRA binds, metro", dict(gross_salary=1800000, basic_da=900000, hra_received=150000, rent_paid=480000, metro=True)),
        ("limb (b) rent-10% binds, metro", dict(gross_salary=1800000, basic_da=900000, hra_received=450000, rent_paid=240000, metro=True)),
        ("limb (c) 50% basic binds, metro", dict(gross_salary=1200000, basic_da=400000, hra_received=300000, rent_paid=600000, metro=True)),
        ("limb (c) 40% basic binds, non-metro", dict(gross_salary=1200000, basic_da=400000, hra_received=300000, rent_paid=600000, metro=False)),
        ("rent below 10% of basic", dict(gross_salary=1500000, basic_da=800000, hra_received=200000, rent_paid=60000)),
        ("rent exactly 10% of basic", dict(gross_salary=1500000, basic_da=800000, hra_received=200000, rent_paid=80000)),
        ("HRA received but no rent", dict(gross_salary=1500000, basic_da=800000, hra_received=200000, rent_paid=0)),
        ("rent but no HRA in salary", dict(gross_salary=1500000, basic_da=800000, hra_received=0, rent_paid=300000)),
        ("Bengaluru = non-metro", dict(gross_salary=2400000, basic_da=1200000, hra_received=600000, rent_paid=720000, metro=False)),
        ("Mumbai = metro", dict(gross_salary=2400000, basic_da=1200000, hra_received=600000, rent_paid=720000, metro=True)),
        ("HRA + full deductions", dict(gross_salary=1600000, basic_da=640000, hra_received=320000, rent_paid=360000, metro=True, sec80c=150000, sec80ccd1b=50000, sec80d_self_family=25000)),
        ("HRA pushes old below 5L rebate", dict(gross_salary=900000, basic_da=450000, hra_received=225000, rent_paid=300000, metro=True, sec80c=150000)),
    ]
    for desc, kw in hra_cases:
        add("hra", desc, P(**kw))

    # 9. Chapter VI-A caps
    for c80 in (0, 100000, 149990, 150000, 150010, 300000):
        add("80c", f"80C {c80:,}", P(gross_salary=1100000, sec80c=c80))
    for nps in (0, 49990, 50000, 80000):
        add("80ccd1b", f"80CCD(1B) {nps:,}", P(gross_salary=1300000, sec80c=150000, sec80ccd1b=nps))
    d_cases = [
        ("self 20k, parents non-senior 20k", dict(sec80d_self_family=20000, sec80d_parents=20000)),
        ("self 40k (non-senior cap 25k)", dict(sec80d_self_family=40000)),
        ("self 40k, spouse senior (cap 50k)", dict(sec80d_self_family=40000, spouse_senior=True)),
        ("self senior 60k (cap 50k)", dict(age=62, sec80d_self_family=60000)),
        ("parents senior 45k", dict(sec80d_parents=45000, parents_senior=True)),
        ("parents senior 70k (cap 50k)", dict(sec80d_parents=70000, parents_senior=True)),
        ("parents non-senior 45k (cap 25k)", dict(sec80d_parents=45000, parents_senior=False)),
        ("max 80D 1 lakh, senior self + senior parents", dict(age=61, sec80d_self_family=55000, sec80d_parents=55000, parents_senior=True)),
        ("non-resident aged 65: self cap stays 25k", dict(age=65, resident=False, sec80d_self_family=40000)),
    ]
    for desc, kw in d_cases:
        add("80d", desc, P(gross_salary=kw.pop("gross_salary", 1400000), **kw))

    # 10. Home-loan interest (self-occupied) incl. loss larger than salary income
    for hl in (100000, 199990, 200000, 250000, 400000):
        add("home_loan", f"home-loan interest {hl:,}", P(gross_salary=1500000, home_loan_interest=hl, sec80c=150000))
    add("home_loan", "interest exceeds salary income", P(gross_salary=180000, home_loan_interest=200000))
    add("deduction_cap", "Chapter VI-A deductions exceed GTI",
        P(gross_salary=250000, sec80c=150000, sec80ccd1b=50000, sec80d_self_family=25000, home_loan_interest=50000))

    # 11. Non-residents: no 87A, below-60 slabs regardless of age
    for g, age in ((500000, 30), (550000, 30), (700000, 70), (775000, 30), (900000, 85)):
        add("non_resident", f"non-resident age {age} salary {g:,}", P(gross_salary=g, age=age, resident=False))

    # 12. Regime break-even / tie / old-better
    add("regime_choice", "heavy deductions, old better", P(gross_salary=1500000, basic_da=600000, hra_received=300000,
        rent_paid=400000, metro=True, sec80c=150000, sec80ccd1b=50000, sec80d_self_family=25000,
        sec80d_parents=50000, parents_senior=True, home_loan_interest=200000))
    add("regime_choice", "no deductions, new better", P(gross_salary=1500000))
    add("regime_choice", "both nil (tie -> new)", P(gross_salary=500000))
    for g in (1000000, 1250000, 1500000, 1750000, 2000000, 3000000):
        add("regime_choice", f"80C+80D+NPS at {g:,}", P(gross_salary=g, sec80c=150000, sec80ccd1b=50000,
            sec80d_self_family=25000))

    # 13. Seeded random realistic profiles to fill out the suite
    rng = random.Random(2024 if fy == "2024-25" else 2025)
    while len(cases) < 230:
        g = rng.choice([rng.randrange(300000, 2500000, 1000), rng.randrange(2500000, 15000000, 5000)])
        basic = int(g * rng.choice([0.4, 0.5]))
        has_rent = rng.random() < 0.5
        prof = P(
            age=rng.choice([25, 32, 41, 48, 55, 61, 67, 72, 81]),
            gross_salary=g, basic_da=basic,
            hra_received=int(basic * rng.choice([0.4, 0.5])) if has_rent else 0,
            rent_paid=rng.randrange(120000, 900000, 1000) if has_rent else 0,
            metro=rng.random() < 0.5,
            sec80c=rng.choice([0, 50000, 100000, 150000, 180000]),
            sec80ccd1b=rng.choice([0, 0, 25000, 50000]),
            sec80d_self_family=rng.choice([0, 15000, 25000, 30000]),
            sec80d_parents=rng.choice([0, 0, 20000, 40000, 55000]),
            parents_senior=rng.random() < 0.5,
            home_loan_interest=rng.choice([0, 0, 0, 120000, 200000, 260000]),
        )
        add("random", f"random profile #{len(cases)}", prof)

    out = []
    for i, (cat, desc, prof) in enumerate(cases):
        prof = dict(prof, fy=fy)
        exp = oracle.compute(prof)
        out.append({"id": f"{fy}-{i:03d}", "category": cat, "description": desc, "profile": prof,
                    "expected": {"old": exp["old"]["tax_payable"], "new": exp["new"]["tax_payable"],
                                 "old_total_income": exp["old"]["total_income"],
                                 "new_total_income": exp["new"]["total_income"],
                                 "recommended": exp["recommended"]}})
    return out


def main():
    DATA.mkdir(exist_ok=True)
    for fy in ("2024-25", "2025-26"):
        cases = build(fy)
        path = DATA / f"cases_fy{fy.replace('-', '_')}.json"
        path.write_text(json.dumps(cases, indent=1))
        cats = {}
        for c in cases:
            cats[c["category"]] = cats.get(c["category"], 0) + 1
        print(f"{path.name}: {len(cases)} cases; by category: {cats}")


if __name__ == "__main__":
    main()
