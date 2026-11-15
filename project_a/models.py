"""Shared data model for Project A.

Every implementation takes a `Profile` and returns a `Comparison` (one `RegimeResult` per regime).
Each `RegimeResult` carries `line_items`, and every line item cites a clause ID from the rule text in
`project_a/sources/`. That is what makes an answer auditable.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

SOURCES_DIR = Path(__file__).parent / "sources"
SUPPORTED_FY = ("2024-25", "2025-26")


@dataclass
class Profile:
    """Structured input. All money is annual, in whole rupees."""
    fy: str = "2024-25"
    age: int | None = None
    resident: bool = True
    gross_salary: int | None = None          # total salary incl. basic, DA, HRA, allowances, bonus
    basic_da: int = 0                         # basic + DA (needed only for HRA)
    hra_received: int = 0
    rent_paid: int = 0
    metro: bool = False                       # Delhi / Mumbai / Kolkata / Chennai
    sec80c: int = 0
    sec80ccd1b: int = 0
    sec80d_self_family: int = 0
    sec80d_parents: int = 0
    spouse_senior: bool = False
    parents_senior: bool = False
    home_loan_interest: int = 0               # self-occupied house, interest only

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


@dataclass
class LineItem:
    """One traced step. stage="income" items sum to total_income; stage="tax" items sum to tax_payable."""
    label: str
    amount: float
    clause: str
    stage: str = "tax"


@dataclass
class RegimeResult:
    regime: str                     # "old" | "new"
    total_income: int
    tax_payable: int                # final, rounded under section 288B
    line_items: list[LineItem] = field(default_factory=list)

    def item(self, label: str) -> float:
        return sum(li.amount for li in self.line_items if li.label == label)

    def to_dict(self) -> dict:
        return {"regime": self.regime, "total_income": self.total_income, "tax_payable": self.tax_payable,
                "line_items": [asdict(li) for li in self.line_items]}


@dataclass
class Comparison:
    fy: str
    old: RegimeResult
    new: RegimeResult
    recommended: str
    explanation: str = ""
    meta: dict = field(default_factory=dict)   # tokens, latency, errors ...

    def to_dict(self) -> dict:
        return {"fy": self.fy, "old": self.old.to_dict(), "new": self.new.to_dict(),
                "recommended": self.recommended, "explanation": self.explanation}


class UnsupportedYear(Exception):
    """Raised loudly when no rules exist for the requested FY (never fall back silently)."""


def rule_text(fy: str) -> str:
    path = SOURCES_DIR / f"fy{fy.replace('-', '_')}_rules.md"
    if not path.exists():
        raise UnsupportedYear(f"No rule text for FY {fy}")
    return path.read_text()


def clause_ids(fy: str) -> set[str]:
    """All clause IDs defined in the rule text for a year."""
    return set(re.findall(r"^\[([A-Z0-9][A-Z0-9-]*)\]", rule_text(fy), flags=re.M))


def recommend(old_tax: int, new_tax: int) -> str:
    """[G-REGIME]: lower final tax wins; a tie goes to the default (new) regime."""
    return "old" if old_tax < new_tax else "new"


def explain(c: "Comparison") -> str:
    o, n = c.old.tax_payable, c.new.tax_payable
    if o == n:
        return (f"Both regimes give Rs {o:,}. Choose the new regime: it is the default under section 115BAC "
                f"and needs no deduction proofs [G-REGIME].")
    better, worse = ("old", "new") if o < n else ("new", "old")
    saving = abs(o - n)
    ded_old = sum(li.amount for li in c.old.line_items if li.stage == "income" and li.amount < 0
                  and li.clause.startswith("O-"))
    return (f"Choose the {better} regime: Rs {min(o, n):,} vs Rs {max(o, n):,} under the {worse} regime "
            f"(saving Rs {saving:,}). Old-regime exemptions and deductions total Rs {abs(int(ded_old)):,}; "
            f"the new regime gives lower slab rates and a higher standard deduction instead [G-REGIME].")
