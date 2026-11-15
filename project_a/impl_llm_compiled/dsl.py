"""Interpreter for LLM-compiled rules (implementation c).

The LLM's output is *data*, not code: a JSON document with lookup tables and an ordered list of named
steps. Each step has a small arithmetic expression, a clause ID and an optional line-item role. The
interpreter parses each expression with Python's `ast` module and evaluates only a whitelist of node types
(arithmetic, comparisons, boolean logic, conditional expressions, and calls to min/max/slab_tax/round10).
Nothing the LLM writes is ever passed to eval/exec, so a compiled file cannot run arbitrary code.

Document shape:
{
  "fy": "2024-25",
  "tables": {"<name>": [[lower_bound, rate], ...]},
  "regimes": {
    "old": {"steps": [{"name": str, "expr": str, "clause": str,
                       "line_item": null | {"label": str, "stage": "income"|"tax", "sign": 1|-1}}],
            "total_income": "<step name>", "tax_payable": "<step name>"},
    "new": {...}
  }
}
"""
from __future__ import annotations

import ast
import json
from functools import lru_cache
from fractions import Fraction as F
from pathlib import Path

from project_a.models import (Comparison, LineItem, Profile, RegimeResult, UnsupportedYear, clause_ids,
                              explain, recommend)

COMPILED_DIR = Path(__file__).parent / "compiled"
INPUT_FIELDS = ["age", "resident", "gross_salary", "basic_da", "hra_received", "rent_paid", "metro", "sec80c",
                "sec80ccd1b", "sec80d_self_family", "sec80d_parents", "spouse_senior", "parents_senior",
                "home_loan_interest"]
FUNCS = {"min", "max", "slab_tax", "round10"}
_ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.Call, ast.Name,
            ast.Load, ast.Constant, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd, ast.Not, ast.And,
            ast.Or, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq)


class CompiledRuleError(ValueError):
    pass


def round10(x) -> F:
    rupees = F(x) // 1
    last = rupees % 10
    return F(rupees - last + (10 if last >= 5 else 0))


def _slab_tax(income, table) -> F:
    tax = F(0)
    for i, (lower, rate) in enumerate(table):
        upper = table[i + 1][0] if i + 1 < len(table) else None
        top = income if upper is None else min(income, F(upper))
        if top > lower:
            tax += (top - F(lower)) * F(str(rate))
    return tax


@lru_cache(maxsize=4096)
def parse(expr: str) -> ast.Expression:
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise CompiledRuleError(f"syntax error in {expr!r}: {e}") from e
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise CompiledRuleError(f"disallowed construct {type(node).__name__} in {expr!r}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCS or node.keywords:
                raise CompiledRuleError(f"disallowed call in {expr!r}")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float, str, bool)):
            raise CompiledRuleError(f"disallowed constant in {expr!r}")
    return tree


def _eval(node, env, tables):
    if isinstance(node, ast.Expression):
        return _eval(node.body, env, tables)
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool) or isinstance(v, str):
            return v
        return F(str(v))
    if isinstance(node, ast.Name):
        if node.id in ("True", "False"):
            return node.id == "True"
        if node.id not in env:
            raise CompiledRuleError(f"unknown name {node.id!r}")
        return env[node.id]
    if isinstance(node, ast.BinOp):
        a, b = _eval(node.left, env, tables), _eval(node.right, env, tables)
        op = type(node.op)
        return {ast.Add: lambda: a + b, ast.Sub: lambda: a - b, ast.Mult: lambda: a * b,
                ast.Div: lambda: F(a) / F(b)}[op]()
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, env, tables)
        return {ast.USub: lambda: -v, ast.UAdd: lambda: v, ast.Not: lambda: not v}[type(node.op)]()
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(_eval(v, env, tables) for v in node.values)
        return any(_eval(v, env, tables) for v in node.values)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env, tables)
        for op, comp in zip(node.ops, node.comparators):
            right = _eval(comp, env, tables)
            ok = {ast.Lt: left < right, ast.LtE: left <= right, ast.Gt: left > right, ast.GtE: left >= right,
                  ast.Eq: left == right, ast.NotEq: left != right}[type(op)]
            if not ok:
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return _eval(node.body if _eval(node.test, env, tables) else node.orelse, env, tables)
    if isinstance(node, ast.Call):
        args = [_eval(a, env, tables) for a in node.args]
        name = node.func.id
        if name == "min":
            return min(args)
        if name == "max":
            return max(args)
        if name == "round10":
            return round10(args[0])
        if name == "slab_tax":
            if len(args) != 2 or args[1] not in tables:
                raise CompiledRuleError(f"slab_tax needs (income, '<table name>'), got {args}")
            return _slab_tax(F(args[0]), tables[args[1]])
    raise CompiledRuleError(f"cannot evaluate {ast.dump(node)}")


def validate(doc: dict, fy: str) -> list[str]:
    """Static checks before a compiled file may run: structure, names, functions, tables, clause IDs."""
    problems = []
    if doc.get("fy") != fy:
        problems.append(f"fy is {doc.get('fy')!r}, expected {fy!r}")
    tables = doc.get("tables", {})
    valid_clauses = clause_ids(fy)
    for regime in ("old", "new"):
        r = doc.get("regimes", {}).get(regime)
        if not r:
            problems.append(f"missing regime {regime}")
            continue
        known = set(INPUT_FIELDS)
        for s in r.get("steps", []):
            try:
                tree = parse(s["expr"])
                for node in ast.walk(tree):
                    if isinstance(node, ast.Name) and node.id not in known | FUNCS | {"True", "False"}:
                        problems.append(f"{regime}.{s['name']}: unknown name {node.id!r}")
                    if (isinstance(node, ast.Call) and node.func.id == "slab_tax"):
                        for c in ast.walk(node.args[1]) if len(node.args) > 1 else []:
                            if isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value not in tables:
                                problems.append(f"{regime}.{s['name']}: unknown table {c.value!r}")
            except (CompiledRuleError, KeyError) as e:
                problems.append(f"{regime}.{s.get('name')}: {e}")
            if s.get("clause") not in valid_clauses:
                problems.append(f"{regime}.{s.get('name')}: clause {s.get('clause')!r} not in rule text")
            known.add(s["name"])
        for out in ("total_income", "tax_payable"):
            if r.get(out) not in known:
                problems.append(f"{regime}: output {out} -> {r.get(out)!r} is not a step")
    return problems


def run_regime(doc: dict, regime: str, p: Profile) -> RegimeResult:
    r = doc["regimes"][regime]
    tables = doc["tables"]
    env = {f: (getattr(p, f) if isinstance(getattr(p, f), bool) else F(getattr(p, f) or 0)) for f in INPUT_FIELDS}
    items = []
    for s in r["steps"]:
        val = _eval(parse(s["expr"]), env, tables)
        env[s["name"]] = val
        li = s.get("line_item")
        if li and val:
            items.append(LineItem(li["label"], float(val * li.get("sign", 1)), s["clause"], li["stage"]))
    return RegimeResult(regime, int(env[r["total_income"]]), int(env[r["tax_payable"]]), items)


_LOADED: dict = {}


def load(fy: str, path: Path | None = None) -> dict:
    path = path or COMPILED_DIR / f"fy{fy.replace('-', '_')}.json"
    key = (str(path), path.stat().st_mtime if path.exists() else None)
    if key in _LOADED:
        return _LOADED[key]
    if not path.exists():
        raise UnsupportedYear(f"No reviewed compiled rules for FY {fy} ({path.name} missing)")
    doc = json.loads(path.read_text())
    problems = validate(doc, fy)
    if problems:
        raise CompiledRuleError("; ".join(problems[:5]))
    _LOADED[key] = doc
    return doc


def compute(p: Profile, doc: dict | None = None) -> Comparison:
    doc = doc or load(p.fy)
    old, new = run_regime(doc, "old", p), run_regime(doc, "new", p)
    c = Comparison(p.fy, old, new, recommend(old.tax_payable, new.tax_payable))
    c.explanation = explain(c)
    return c
