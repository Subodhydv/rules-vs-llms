# Income-tax rules for salaried resident individuals — FY 2025-26 (AY 2026-27)

This is the single rule text that all three implementations are built from.
Each clause has a stable ID in square brackets. Every rupee in an answer must cite one of these IDs.
Statutory references are to the Income-tax Act, 1961 as amended by the Finance Act, 2025
(Budget of 1 February 2025). Old-regime provisions are unchanged from FY 2024-25.
Official sources are listed in `SOURCES.md`.

Scope: resident individual, salary income only (plus loss on one self-occupied house property).
Capital gains, business income, other sources, and non-salary deductions are out of scope.

---

## Part 0 — General

[G-REGIME] Section 115BAC(1A). For FY 2025-26 the new tax regime is the default. The individual may opt
out of it and be taxed under the old (normal) regime. This service computes both and recommends the one
with the lower final tax liability. If both are equal, recommend the new regime (it is the default and
requires no deduction proofs).

[G-AGE] Age categories apply to resident individuals and are determined by age at any time during the
previous year: "below 60", "senior citizen" (60 or more but below 80), "super senior citizen" (80 or more).
A non-resident individual uses the "below 60" old-regime slabs whatever the age.

[G-ROUND-INCOME] Section 288A. Total income is rounded off to the nearest multiple of ten rupees: ignore
paise; if the last digit is 5 or more, round up to the next multiple of ten, otherwise round down.

[G-ROUND-TAX] Section 288B. The final tax payable is rounded off to the nearest multiple of ten rupees in
the same way (ignore paise; last digit 5 or more rounds up, otherwise down).

---

## Part 1 — Old regime (normal provisions)

[O-HRA] Section 10(13A) read with Rule 2A. House rent allowance received is exempt to the extent of the
LEAST of:
  (a) the actual HRA received for the year;
  (b) rent actually paid for the year minus 10% of "salary";
  (c) 50% of "salary" if the rented accommodation is in Delhi, Mumbai, Kolkata or Chennai (metro),
      otherwise 40% of "salary".
"Salary" for this clause means basic salary plus dearness allowance (where DA forms part of retirement
benefits). If no rent is paid, or no HRA is received, the exemption is nil. The exemption cannot be negative.

[O-SD] Section 16(ia). Standard deduction from salary of fifty thousand rupees, or the amount of salary
(after exempt allowances) if less.

[O-HP] Section 24(b) read with section 71(3A). For one self-occupied house property the annual value is nil,
and interest on borrowed capital for its acquisition or construction is deductible up to two lakh rupees.
This produces a loss under the head "Income from house property" equal to the allowable interest, which is
set off against salary income (set-off limited to two lakh rupees). Gross total income cannot be below zero.

[O-80C] Sections 80C and 80CCE. Deduction for specified investments/payments (EPF employee contribution,
PPF, ELSS, life-insurance premium, principal repayment of home loan, tuition fees, NPS under 80CCD(1), etc.)
up to one lakh fifty thousand rupees in aggregate.

[O-80CCD1B] Section 80CCD(1B). Additional deduction for the individual's own contribution to NPS, up to
fifty thousand rupees, over and above the limit in [O-80C].

[O-80D-SELF] Section 80D. Health-insurance premium (including preventive health check-up up to Rs 5,000,
and, for an uninsured senior citizen, medical expenditure) for self, spouse and dependent children:
deductible up to twenty-five thousand rupees; the limit is fifty thousand rupees if the individual or the
spouse is a senior citizen (resident, 60 or more).

[O-80D-PARENTS] Section 80D. Health-insurance premium / eligible medical expenditure for parents:
additional deduction up to twenty-five thousand rupees; the limit is fifty thousand rupees if either parent
is a senior citizen.

[O-VIA-CAP] Section 80A(2). The aggregate of Chapter VI-A deductions ([O-80C], [O-80CCD1B], [O-80D-SELF],
[O-80D-PARENTS]) cannot exceed the gross total income.

[O-TI] Total income (old regime) = gross salary − [O-HRA] − [O-SD] − [O-HP] loss (floor at 0)
− Chapter VI-A deductions (capped by [O-VIA-CAP]), then rounded by [G-ROUND-INCOME].

[O-SLAB] First Schedule, Part III, Paragraph A (rates in force for FY 2025-26, unchanged). Tax on total income:
  Below 60 (and all non-residents):  0 – 2,50,000: nil; 2,50,001 – 5,00,000: 5%;
                                     5,00,001 – 10,00,000: 20%; above 10,00,000: 30%.
  Senior citizen (60 to 79):         0 – 3,00,000: nil; 3,00,001 – 5,00,000: 5%;
                                     5,00,001 – 10,00,000: 20%; above 10,00,000: 30%.
  Super senior citizen (80+):        0 – 5,00,000: nil; 5,00,001 – 10,00,000: 20%; above 10,00,000: 30%.

[O-87A] Section 87A. A resident individual whose total income does not exceed five lakh rupees gets a
rebate equal to the tax on total income or twelve thousand five hundred rupees, whichever is less.
Not available to non-residents.

[O-SURCHARGE] Finance Act, 2025, First Schedule, Part III (unchanged rates). Surcharge on income-tax (after rebate):
10% if total income exceeds 50 lakh rupees; 15% if it exceeds 1 crore; 25% if it exceeds 2 crore;
37% if it exceeds 5 crore.

[O-MR] Marginal relief on surcharge (provisos to the same Part). Where total income exceeds a surcharge
threshold (50 lakh, 1 crore, 2 crore or 5 crore), income-tax plus surcharge shall not exceed the
income-tax plus surcharge payable on a total income equal to that threshold by more than the amount by
which the total income exceeds that threshold. Apply it for the highest threshold that the income exceeds.

[O-CESS] Health and Education Cess at 4% of income-tax plus surcharge (after rebate and marginal relief).

---

## Part 2 — New regime (section 115BAC)

[N-DISALLOW] Section 115BAC(2). Under the new regime the following are NOT allowed: HRA exemption under
section 10(13A); deductions under sections 80C, 80CCD(1B), 80D (and other Chapter VI-A deductions except
80CCD(2) and 80JJAA, which are out of scope here); interest on a self-occupied house under section 24(b)
and the related set-off of loss under section 71(3A).

[N-SD] Section 16(ia), proviso inserted by the Finance (No. 2) Act, 2024. For an individual taxed under
section 115BAC(1A), the standard deduction is seventy-five thousand rupees, or the amount of salary if less.

[N-TI] Total income (new regime) = gross salary − [N-SD], then rounded by [G-ROUND-INCOME].

[N-SLAB] Section 115BAC(1A) as amended by the Finance Act, 2025. Tax on total income, same for all ages:
0 – 4,00,000: nil; 4,00,001 – 8,00,000: 5%; 8,00,001 – 12,00,000: 10%; 12,00,001 – 16,00,000: 15%;
16,00,001 – 20,00,000: 20%; 20,00,001 – 24,00,000: 25%; above 24,00,000: 30%.

[N-87A] Section 87A, proviso for income chargeable under 115BAC(1A), as amended by the Finance Act, 2025.
A resident individual whose total income does not exceed twelve lakh rupees gets a rebate equal to the tax
on total income or sixty thousand rupees, whichever is less. (The rebate does not apply to tax on
special-rate income such as capital gains; out of scope here.)

[N-87A-MR] Section 87A, further proviso (marginal relief), as amended by the Finance Act, 2025. Where such a
resident individual's total income exceeds twelve lakh rupees and the income-tax payable on it exceeds the
amount by which the total income exceeds twelve lakh rupees, the rebate equals
(income-tax payable) − (total income − 12,00,000).

[N-SURCHARGE] Surcharge under the new regime: 10% if total income exceeds 50 lakh; 15% if it exceeds 1 crore;
25% if it exceeds 2 crore. The 37% rate does not apply (maximum 25%).

[N-MR] Marginal relief on surcharge, as in [O-MR], with thresholds of 50 lakh, 1 crore and 2 crore only.

[N-CESS] Health and Education Cess at 4% of income-tax plus surcharge.

---

## Part 3 — Order of computation (both regimes)

[G-ORDER] 1) total income and its rounding; 2) tax on total income by slabs; 3) less rebate under section
87A; 4) plus surcharge (with marginal relief); 5) plus 4% cess; 6) round the result by [G-ROUND-TAX].

---

## Part 4 — What changed from FY 2024-25 (Finance Act, 2025)

[CHG-1] [N-SLAB] slabs revised (basic exemption 3 lakh -> 4 lakh; seven slabs; new 25% band from 20 to 24 lakh).
[CHG-2] [N-87A] rebate limit 7 lakh -> 12 lakh and maximum rebate 25,000 -> 60,000.
[CHG-3] [N-87A-MR] marginal-relief threshold 7 lakh -> 12 lakh.
Unchanged: standard deduction (75,000 new / 50,000 old), all old-regime provisions, surcharge, cess.
