"""Independent reference calculator used to produce expected values for the test suite.

Deliberately written differently from impl_rules/engine.py: straight-line code, hard-coded numbers,
Decimal arithmetic, no config. Two independent implementations that agree on 400+ answers, plus
hand-checked anchors (test_anchors.py) and the official calculator cross-checks, is the evidence base.

Returns a dict: {"old": {...}, "new": {...}} with total_income, tax, rebate, surcharge, relief, cess,
tax_payable (288B-rounded).
"""
from decimal import ROUND_FLOOR, Decimal as D


def _r10(x) -> int:
    x = int(D(x).to_integral_value(rounding=ROUND_FLOOR))
    q, rem = divmod(x, 10)
    return q * 10 + (10 if rem >= 5 else 0)


def _slabs(income, bounds, rates):
    """bounds = upper limits of each band except the last; rates = one per band."""
    tax, lower = D(0), 0
    for i, rate in enumerate(rates):
        upper = bounds[i] if i < len(bounds) else None
        if upper is None:
            if income > lower:
                tax += (D(income) - lower) * D(rate)
            break
        if income > lower:
            tax += (D(min(income, upper)) - lower) * D(rate)
        lower = upper
    return tax


def old_slab_tax(ti, age, resident=True):
    if resident and age is not None and age >= 80:
        return _slabs(ti, [500000, 1000000], ["0", "0.20", "0.30"])
    if resident and age is not None and age >= 60:
        return _slabs(ti, [300000, 500000, 1000000], ["0", "0.05", "0.20", "0.30"])
    return _slabs(ti, [250000, 500000, 1000000], ["0", "0.05", "0.20", "0.30"])


def new_slab_tax(ti, fy):
    if fy == "2024-25":
        return _slabs(ti, [300000, 700000, 1000000, 1200000, 1500000], ["0", "0.05", "0.10", "0.15", "0.20", "0.30"])
    if fy == "2025-26":
        return _slabs(ti, [400000, 800000, 1200000, 1600000, 2000000, 2400000],
                      ["0", "0.05", "0.10", "0.15", "0.20", "0.25", "0.30"])
    raise ValueError(fy)


def _surcharge(ti, tax, slab_fn, bands):
    """bands: list of (threshold, rate) ascending. Returns (surcharge, marginal_relief)."""
    sc_rate, base, base_rate = D(0), None, D(0)
    for idx, (thr, rate) in enumerate(bands):
        if ti > thr:
            sc_rate, base = D(rate), thr
            base_rate = D(bands[idx - 1][1]) if idx > 0 else D(0)
    if base is None:
        return D(0), D(0)
    sc = tax * sc_rate
    cap = slab_fn(base) * (1 + base_rate) + (ti - base)
    relief = max(D(0), tax + sc - cap)
    return sc, relief


def _finish(ti, tax, rebate, slab_fn, bands):
    t1 = tax - rebate
    sc, relief = _surcharge(ti, t1, slab_fn, bands)
    cess = (t1 + sc - relief) * D("0.04")
    return {"total_income": ti, "tax": float(tax), "rebate": float(rebate), "surcharge": float(sc),
            "relief": float(relief), "cess": float(cess), "tax_payable": _r10(t1 + sc - relief + cess)}


def compute(p: dict) -> dict:
    fy = p.get("fy", "2024-25")
    if fy not in ("2024-25", "2025-26"):
        raise ValueError(fy)
    age, res = p.get("age"), p.get("resident", True)
    gross = D(p["gross_salary"])
    senior = bool(res and age is not None and age >= 60)

    # ---- old regime
    hra_ex = D(0)
    if p.get("hra_received", 0) > 0 and p.get("rent_paid", 0) > 0:
        basic = D(p.get("basic_da", 0))
        a = D(p["hra_received"])
        b = max(D(0), D(p["rent_paid"]) - basic / 10)
        c = basic / 2 if p.get("metro") else basic * D("0.4")
        hra_ex = min(a, b, c)
    sal = gross - hra_ex
    sal -= min(D(50000), max(D(0), sal))
    hp = min(D(p.get("home_loan_interest", 0)), D(200000))
    gti = max(D(0), sal - min(hp, max(D(0), sal)))
    d80d_self_cap = 50000 if (senior or p.get("spouse_senior")) else 25000
    d80d_par_cap = 50000 if p.get("parents_senior") else 25000
    ded = (min(p.get("sec80c", 0), 150000) + min(p.get("sec80ccd1b", 0), 50000)
           + min(p.get("sec80d_self_family", 0), d80d_self_cap) + min(p.get("sec80d_parents", 0), d80d_par_cap))
    ti_old = _r10(gti - min(D(ded), gti))
    tax_old = old_slab_tax(ti_old, age, res)
    rebate_old = min(tax_old, D(12500)) if (res and ti_old <= 500000) else D(0)
    old = _finish(ti_old, tax_old, rebate_old, lambda x: old_slab_tax(x, age, res),
                  [(5000000, "0.10"), (10000000, "0.15"), (20000000, "0.25"), (50000000, "0.37")])

    # ---- new regime
    ti_new = _r10(gross - min(D(75000), gross))
    tax_new = new_slab_tax(ti_new, fy)
    limit, max_reb = (700000, 25000) if fy == "2024-25" else (1200000, 60000)
    rebate_new = D(0)
    if res:
        if ti_new <= limit:
            rebate_new = min(tax_new, D(max_reb))
        elif tax_new > ti_new - limit:
            rebate_new = tax_new - (ti_new - limit)
    new = _finish(ti_new, tax_new, rebate_new, lambda x: new_slab_tax(x, fy),
                  [(5000000, "0.10"), (10000000, "0.15"), (20000000, "0.25")])

    rec = "old" if old["tax_payable"] < new["tax_payable"] else "new"
    return {"old": old, "new": new, "recommended": rec}
