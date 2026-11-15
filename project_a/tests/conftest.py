import json
from pathlib import Path

import pytest

DATA = Path(__file__).parent / "data"


def load_cases(fy):
    return json.loads((DATA / f"cases_fy{fy.replace('-', '_')}.json").read_text())


@pytest.fixture(scope="session")
def cases_2425():
    return load_cases("2024-25")


@pytest.fixture(scope="session")
def cases_2526():
    return load_cases("2025-26")
