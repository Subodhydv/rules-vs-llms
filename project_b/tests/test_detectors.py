import numpy as np
import pytest

from project_b import data_io
from project_b.detectors import rules, stats
from project_b.evaluate import detection
from project_b.injector import Injector


@pytest.mark.parametrize("D", rules.ALL + stats.ALL, ids=lambda D: D.__name__)
def test_detector_catches_its_problem_and_is_quiet_on_clean(data, D):
    raw, ref, pool = data
    d = D().fit(ref)
    clean = data_io.batches(pool, 1, 1000, seed=5)[0]
    r = d.detect(clean)
    assert r.row_flags.mean() < 0.01
    inj = Injector(ref, seed=3).inject(data_io.batches(pool, 1, 1000, seed=6)[0], d.problem)
    assert detection(d.problem, d.detect(inj.df), inj) >= 0.5


def test_alerts_explain_themselves(data):
    raw, ref, pool = data
    inj = Injector(ref, seed=3).inject(data_io.batches(pool, 1, 1000, seed=6)[0], "i_zip_borough")
    r = rules.ZipBoroughRule().fit(ref).detect(inj.df)
    assert "belongs to" in r.alerts[0] and "but borough is" in r.alerts[0]
