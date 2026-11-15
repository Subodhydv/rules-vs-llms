"""Task 1: cross-check at least 30 cases against the Income Tax Department's official calculator.

  python -m project_a.tests.official_checks make     -> writes tests/data/official_calculator_checks.csv
  (enter each row at https://www.incometax.gov.in/iec/foportal/income-tax-calculator , Advanced Calculator,
   Income Tax Act 1961, AY shown; type the official 'total tax liability' for each regime into the two
   official_* columns; put your initials/date in checked_by)
  python -m project_a.tests.official_checks verify   -> compares and prints a summary (also used by run_all)

The calculator wants already-derived figures (exempt HRA, deductions), so the CSV gives them precomputed from
our engine's line items; the comparison is of the final tax under each regime.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from project_a.impl_rules import engine
from project_a.models import Profile

DATA = Path(__file__).parent / "data"
CSV = DATA / "official_calculator_checks.csv"
COLS = ["case_id", "AY", "age", "residential_status", "gross_salary", "exempt_hra_10_13A",
        "interest_self_occupied_24b", "ded_80C", "ded_80CCD1B", "ded_80D", "ours_old", "ours_new",
        "official_old", "official_new", "checked_by"]


def pick() -> list[dict]:
    chosen = []
    for fy, take in (("2024-25", 24), ("2025-26", 6)):
        cases = json.loads((DATA / f"cases_fy{fy.replace('-', '_')}.json").read_text())
        by_cat = {}
        for c in cases:
            by_cat.setdefault(c["category"], []).append(c)
        i = 0
        picked = []
        while len(picked) < take:
            for cat in sorted(by_cat):
                if cat != "std_deduction_cap" and i < len(by_cat[cat]) and len(picked) < take:
                    picked.append(by_cat[cat][(i * 3) % len(by_cat[cat])])
            i += 1
        chosen += picked
    return chosen


def make():
    rows = []
    for c in pick():
        p = Profile.from_dict(c["profile"])
        r = engine.compute(p)
        it = r.old.item
        rows.append({
            "case_id": c["id"], "AY": "2025-26" if p.fy == "2024-25" else "2026-27", "age": p.age,
            "residential_status": "Resident" if p.resident else "Non-Resident", "gross_salary": p.gross_salary,
            "exempt_hra_10_13A": int(-it("hra_exemption")), "interest_self_occupied_24b": int(-it("house_property_loss")),
            "ded_80C": int(-it("deduction_sec80c")), "ded_80CCD1B": int(-it("deduction_sec80ccd1b")),
            "ded_80D": int(-it("deduction_sec80d_self_family") - it("deduction_sec80d_parents")),
            "ours_old": r.old.tax_payable, "ours_new": r.new.tax_payable,
            "official_old": "", "official_new": "", "checked_by": ""})
    DATA.mkdir(exist_ok=True)
    with CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {CSV} ({len(rows)} rows)")


def verify() -> dict:
    if not CSV.exists():
        return {"rows": 0, "checked": 0, "matched": 0, "mismatches": []}
    rows = list(csv.DictReader(CSV.open()))
    checked = [r for r in rows if r["official_old"].strip() and r["official_new"].strip()]
    mism = [r["case_id"] for r in checked
            if int(float(r["official_old"])) != int(r["ours_old"]) or int(float(r["official_new"])) != int(r["ours_new"])]
    return {"rows": len(rows), "checked": len(checked), "matched": len(checked) - len(mism), "mismatches": mism}


if __name__ == "__main__":
    (make if sys.argv[1:] == ["make"] else lambda: print(verify()))()
