import numpy as np
import pytest

from project_b import data_io
from project_b.injector import PROBLEMS, Injector


@pytest.mark.parametrize("problem", list(PROBLEMS))
def test_each_problem_injects_and_labels(data, problem):
    raw, ref, pool = data
    b = data_io.batches(pool, 1, 1000, seed=1)[0]
    out = Injector(ref, seed=2).inject(b, problem)
    if PROBLEMS[problem][1] == "row":
        assert out.labels.sum() > 0
        changed = [i for i in np.flatnonzero(out.labels)]
        assert len(changed) == out.labels.sum()
    else:
        assert out.detail  # says what was done


def test_rate_is_controlled(data):
    raw, ref, pool = data
    b = data_io.batches(pool, 1, 1000, seed=1)[0]
    inj = Injector(ref, seed=2)
    assert inj.inject(b, "h_closed_before_created", rate=0.05).labels.sum() == 50
    assert inj.inject(b, "h_closed_before_created", rate=0.01).labels.sum() == 10


def test_duplicates_have_partners(data):
    raw, ref, pool = data
    b = data_io.batches(pool, 1, 500, seed=1)[0]
    out = Injector(ref, seed=2).inject(b, "e_exact_dup", rate=0.04)
    for i in np.flatnonzero(out.labels):
        j = out.partner[i]
        assert j >= 0 and (out.df.iloc[i].astype(str) == out.df.iloc[j].astype(str)).all()
