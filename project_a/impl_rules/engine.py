"""Implementation (a): hand-coded rules.

One generic engine + one YAML config per financial year. The engine knows the *shape* of an Indian
salary-tax computation (exemptions -> deductions -> slabs -> rebate -> surcharge -> cess -> rounding); the
config holds every number and the clause it comes from. A Budget that only moves numbers is a config edit.

All arithmetic is exact (fractions.Fraction); rounding happens only where sections 288A/288B say so.
"""
from __future__ import annotations

from fractions import Fraction as F
from functools import lru_cache
from pathlib import Path

import yaml

from project_a.models import (Comparison, LineItem, Profile, RegimeResult, UnsupportedYear, explain,
                              recommend)

CONFIG_DIR = Path(__file__).parent / "config"


@lru_cache(maxsize=None)
def load_config(fy: str) -> dict:
    path = CONFIG_DIR / f"fy{fy.replace('-', '_')}.yaml"
    if not path.exists():
        # Fail loudly: computing FY 2025-26 with FY 2024-25 numbers is the classic silent failure.
        raise UnsupportedYear(f"No hand-coded rule config for FY {fy} ({path.name} missing)")
    cfg = yaml.safe_load(path.read_text())
    if cfg.get("fy") != fy:
        raise UnsupportedYear(f"{path.name} declares fy={cfg.get('fy')!r}, expected {fy!r}")
    return cfg


def round10(x) -> int:
    """Sections 288A / 288B: ignore paise, then round to the nearest multiple of 10 (5 rounds up)."""
    rupees = int(F(x) // 1)
    last = rupees % 10
    return rupees - last + (10 if last >= 5 else 0)


def slab_tax(income, table) -> F:
    tax = F(0)
    for i, (lower, rate) in enumerate(table):
        upper = table[i + 1][0] if i + 1 < len(table) else None
        top = income if upper is None else min(income, upper)
        if top > lower:
            tax += (F(top) - lower) * F(rate)
    return tax


def slab_bands(income, table):
    """Yield (lower, upper, rate, tax) for each band that the income reaches (for line items)."""
    for i, (lower, rate) in enumerate(table):
        upper = table[i + 1][0] if i + 1 < len(table) else None
        top = income if upper is None else min(income, upper)
        if top > lower and F(rate) > 0:
            yield lower, upper, rate, (F(top) - lower) * F(rate)


def age_table(slabs: dict, p: Profile):
    if "all_ages" in slabs:
        return slabs["all_ages"]
    if not p.resident or p.age is None or p.age < 60:
        return slabs["below_60"]
    return slabs["super_senior"] if p.age >= 80 else slabs["senior"]


def is_senior(p: Profile) -> bool:
    return bool(p.resident and p.age is not None and p.age >= 60)


def compute_regime(p: Profile, regime: str, cfg: dict) -> RegimeResult:
    r = cfg["regimes"][regime]
    items: list[LineItem] = []

    def add(label, amount, clause, stage):
        if amount:
            items.append(LineItem(label, float(amount), clause, stage))

    gross = int(p.gross_salary or 0)
    add("gross_salary", gross, "O-TI" if regime == "old" else "N-TI", "income")

    # HRA exemption, section 10(13A) / Rule 2A
    hra_ex = 0
    if r["hra"]["enabled"] and p.hra_received > 0 and p.rent_paid > 0:
        h = r["hra"]
        pct = F(h["metro_pct"]) if p.metro else F(h["non_metro_pct"])
        hra_ex = min(F(p.hra_received), max(F(0), p.rent_paid - F(h["rent_excess_pct"]) * p.basic_da),
                     pct * p.basic_da)
        add("hra_exemption", -hra_ex, h["clause"], "income")

    # Standard deduction, section 16(ia)
    salary_after_ex = gross - hra_ex
    sd = min(F(r["standard_deduction"]["cap"]), max(F(0), salary_after_ex))
    add("standard_deduction", -sd, r["standard_deduction"]["clause"], "income")
    income_salary = salary_after_ex - sd

    # Self-occupied house property, sections 24(b) / 71(3A)
    if r["house_property"]["enabled"] and p.home_loan_interest > 0:
        hp_allowed = min(F(p.home_loan_interest), F(r["house_property"]["cap"]))
        setoff = min(hp_allowed, max(F(0), income_salary))
        add("house_property_loss", -setoff, r["house_property"]["clause"], "income")
        gti = income_salary - setoff
    else:
        gti = income_salary
    gti = max(F(0), gti)

    # Chapter VI-A deductions, capped individually and then at gross total income (80A(2))
    total_ded = F(0)
    for d in r["deductions"]:
        cap = d["cap"]
        if d.get("senior_test") == "self_or_spouse" and (is_senior(p) or p.spouse_senior):
            cap = d["senior_cap"]
        if d.get("senior_test") == "parents" and p.parents_senior:
            cap = d["senior_cap"]
        amt = min(F(getattr(p, d["field"]) or 0), F(cap))
        add(f"deduction_{d['field']}", -amt, d["clause"], "income")
        total_ded += amt
    if total_ded > gti:
        add("deduction_cap_adjustment", total_ded - gti, r["deduction_cap_clause"], "income")
        total_ded = gti

    raw_ti = gti - total_ded
    ti = round10(raw_ti)
    add("rounding_total_income", ti - raw_ti, cfg["rounding"]["income_clause"], "income")

    # Tax on slabs
    table = age_table(r["slabs"], p)
    tax = slab_tax(ti, table)
    for lower, upper, rate, t in slab_bands(ti, table):
        rng = f"{lower:,}-{upper:,}" if upper else f"above {lower:,}"
        add(f"slab_tax {float(F(rate)) * 100:g}% on {rng}", t, r["slabs"]["clause"], "tax")

    # Rebate under section 87A (residents only)
    reb = r["rebate"]
    rebate = F(0)
    if p.resident and tax > 0:
        if ti <= reb["income_limit"]:
            rebate = min(tax, F(reb["max_rebate"]))
            add("rebate_87a", -rebate, reb["clause"], "tax")
        elif reb["marginal_relief"] and tax > ti - reb["income_limit"]:
            rebate = tax - (ti - reb["income_limit"])
            add("rebate_87a_marginal_relief", -rebate, reb["relief_clause"], "tax")
    tax_after_rebate = tax - rebate

    # Surcharge with marginal relief
    sc_cfg = r["surcharge"]
    surcharge = relief = F(0)
    crossed = [(t, F(rate)) for t, rate in sc_cfg["bands"] if ti > t]
    if crossed:
        threshold, rate = crossed[-1]
        prev_rate = crossed[-2][1] if len(crossed) > 1 else F(0)
        surcharge = tax_after_rebate * rate
        limit = slab_tax(threshold, table) * (1 + prev_rate) + (ti - threshold)
        if tax_after_rebate + surcharge > limit:
            relief = tax_after_rebate + surcharge - limit
        add(f"surcharge {float(rate) * 100:g}%", surcharge, sc_cfg["clause"], "tax")
        add("surcharge_marginal_relief", -relief, sc_cfg["relief_clause"], "tax")

    cess = (tax_after_rebate + surcharge - relief) * F(r["cess"]["rate"])
    add("cess 4%", cess, r["cess"]["clause"], "tax")
    exact = tax_after_rebate + surcharge - relief + cess
    final = round10(exact)
    add("rounding_tax", final - exact, cfg["rounding"]["tax_clause"], "tax")

    if regime == "new":
        disallowed = [f for f in ("hra_received", "sec80c", "sec80ccd1b", "sec80d_self_family",
                                  "sec80d_parents", "home_loan_interest") if getattr(p, f)]
        if disallowed:
            items.append(LineItem("not_allowed_in_new_regime: " + ", ".join(disallowed), 0.0,
                                  r["disallowed_clause"], "income"))
    return RegimeResult(regime, ti, final, items)


def compute(p: Profile) -> Comparison:
    cfg = load_config(p.fy)
    old = compute_regime(p, "old", cfg)
    new = compute_regime(p, "new", cfg)
    c = Comparison(p.fy, old, new, recommend(old.tax_payable, new.tax_payable))
    c.explanation = explain(c)
    return c
