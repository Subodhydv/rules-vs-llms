"""Score a parser on tests/data/descriptions.json."""
from __future__ import annotations

import json
from pathlib import Path

from project_a.models import Profile

DESCRIPTIONS = Path(__file__).parents[1] / "tests" / "data" / "descriptions.json"
DEFAULTS = Profile(fy="2024-25", age=None, gross_salary=None).to_dict()


def load():
    return json.loads(DESCRIPTIONS.read_text())


def expected_profile(fields: dict) -> dict:
    d = dict(DEFAULTS)
    d.update(fields)
    return d


def score_one(item: dict, result) -> dict:
    exp = item["expect"]
    out = {"id": item["id"], "style": item["style"], "expected": exp["status"], "got": result.status,
           "asked": result.ask_fields, "ok": False, "kind": ""}
    if exp["status"] == "complete":
        if result.status != "complete":
            out["kind"] = "over-asked"
            return out
        want, got = expected_profile(exp["fields"]), result.profile.to_dict()
        diffs = {k: (want[k], got[k]) for k in want if want[k] != got[k]}
        out["ok"] = not diffs
        out["kind"] = "correct" if not diffs else "wrong-field"
        out["diffs"] = diffs
    else:
        if result.status == "complete":
            out["kind"] = "GUESSED"           # the failure the brief cares most about
            return out
        missing = [f for f in exp["ask_about"] if f not in result.ask_fields]
        out["ok"] = not missing
        out["kind"] = "correct" if not missing else "asked-wrong-thing"
        out["missing"] = missing
    return out


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    comp = [r for r in rows if r["expected"] == "complete"]
    clar = [r for r in rows if r["expected"] == "clarify"]
    return {
        "n": n,
        "overall_correct": sum(r["ok"] for r in rows),
        "complete_exact": f"{sum(r['ok'] for r in comp)}/{len(comp)}",
        "clarify_correct": f"{sum(r['ok'] for r in clar)}/{len(clar)}",
        "guessed_when_should_ask": sum(r["kind"] == "GUESSED" for r in rows),
        "over_asked": sum(r["kind"] == "over-asked" for r in rows),
        "wrong_field_values": sum(r["kind"] == "wrong-field" for r in rows),
    }
