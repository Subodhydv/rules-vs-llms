import pytest

from project_b import data_io, fixture


@pytest.fixture(scope="session")
def data():
    raw = data_io.coerce(fixture.make(n=12000, seed=3))
    ref, pool = data_io.split(raw)
    return raw, ref, pool
