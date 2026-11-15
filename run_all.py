"""One command that reproduces every number in RESULTS_A.md, RESULTS_B.md and DECISION_MATRIX.md.

    python run_all.py                 # full run (downloads NYC data if missing; uses Gemini if GEMINI_API_KEY set)
    python run_all.py --offline       # no network at all: cached LLM responses only, synthetic fixture if no data
    python run_all.py --skip-tests    # skip pytest

LLM responses are cached in .llm_cache/ (commit it): a second run with no key reproduces the same LLM numbers.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).parent
RES = ROOT / "results"
warnings.filterwarnings("ignore")


def step(msg):
    print(f"\n=== {msg} ===", flush=True)


def dump(name, obj):
    RES.mkdir(exist_ok=True)
    (RES / name).write_text(json.dumps(obj, indent=1, default=str))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--skip-tests", action="store_true")
    a = ap.parse_args()
    if a.offline:
        os.environ["LLM_OFFLINE"] = "1"
    t0 = time.time()

    from common.llm import llm_status
    print("LLM:", llm_status())

    step("Project A / Task 1: build the test suite")
    from project_a.tests import generate_cases, official_checks
    generate_cases.main()
    if not official_checks.CSV.exists():
        official_checks.make()

    if not a.skip_tests:
        step("Unit tests (pytest)")
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-W", "ignore", "project_a", "project_b"],
                           cwd=ROOT, capture_output=True, text=True)
        print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-500:])
        dump("tests.json", {"returncode": r.returncode, "summary": (r.stdout.strip().splitlines() or [""])[-1]})

    step("Project A / Tasks 2-4: measure the three implementations and the parsers")
    from project_a import evaluate as eval_a, law_change
    dump("project_a_metrics.json", eval_a.main())
    step("Project A / Task 5: the law changes")
    dump("project_a_law_change.json", law_change.main())
    dump("project_a_official_checks.json", official_checks.verify())

    step("Project B / data")
    from project_b import fetch_data
    if not fetch_data.RAW.exists() and not a.offline:
        try:
            fetch_data.fetch_soql_profile()
            fetch_data.fetch_sample()
        except Exception as e:  # noqa: BLE001
            print(f"  could not download NYC 311 data ({e}); falling back to the SYNTHETIC fixture")
    print("  data:", "nyc_open_data" if fetch_data.RAW.exists() else "SYNTHETIC_FIXTURE")

    step("Project B / Tasks 1-5: profile, inject, detect, hybrid")
    from project_b import evaluate as eval_b, scale
    mb = eval_b.main()
    dump("project_b_metrics.json", mb)
    step("Project B / Task 6: scale projection")
    dump("project_b_scale.json", scale.project(mb))

    step("Reports")
    import report
    report.main()
    print(f"\nDone in {time.time() - t0:.0f} s. LLM: {llm_status()}")


if __name__ == "__main__":
    main()
