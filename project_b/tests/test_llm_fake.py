"""LLM paths with a fake Gemini transport (no quota used)."""
import json

import numpy as np
import pytest

from common import llm
from project_b import data_io
from project_b.detectors.llm_review import LLMRowReviewer, LLMSchemaReviewer
from project_b.injector import Injector
from project_b.pipeline import HybridPipeline


def env(obj):
    return {"model": "gemini-2.5-flash", "latency_ms": 900.0, "timestamp": "t",
            "response": {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}}],
                         "usageMetadata": {"promptTokenCount": 4000, "candidatesTokenCount": 300}}}


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.delenv("LLM_OFFLINE", raising=False)
    replies = []
    monkeypatch.setattr(llm.GeminiClient, "_call", lambda self, *a, **k: env(replies.pop(0)))
    return replies


def test_row_reviewer_parses_flags(fake, data):
    raw, ref, pool = data
    b = data_io.batches(pool, 1, 30, seed=1)[0]
    fake.append({"flags": [{"row": 3, "codes": ["l"], "reason": "phone number"}, {"row": 999, "codes": ["d"]}]})
    out = LLMRowReviewer(llm.GeminiClient()).review(b)
    assert out == {3: {"codes": {"l"}, "reason": "phone number"}}      # unknown row 999 ignored


def test_schema_reviewer(fake, data):
    raw, ref, pool = data
    fake.append({"issues": [{"code": "a", "detail": "borough missing"}]})
    issues = LLMSchemaReviewer(llm.GeminiClient()).review(data_io.batches(pool, 1, 50, seed=1)[0])
    assert issues[0]["code"] == "a"


def test_hybrid_llm_confirms_only_candidates(fake, data):
    raw, ref, pool = data
    plan = {p: {"accept": ["rule"], "candidates": []} for p in
            ["a_schema_column", "b_type_change", "c_date_format", "d_latlon_swap", "e_exact_dup", "f_near_dup",
             "g_null_spike", "h_closed_before_created", "i_zip_borough", "j_type_descriptor",
             "k_resolution_status", "l_pii"]}
    plan["l_pii"] = {"accept": ["rule"], "candidates": ["stat"]}
    inj = Injector(ref, seed=4).inject(data_io.batches(pool, 1, 400, seed=2)[0], "l_pii", rate=0.05)
    pipe = HybridPipeline(ref, plan, llm.GeminiClient())
    # reviewer sees only stat-only candidates; confirm all of them
    stat_only = np.flatnonzero(pipe.det[("l_pii", "stat")].detect(inj.df).row_flags &
                               ~pipe.det[("l_pii", "rule")].detect(inj.df).row_flags)
    fake.append({"flags": [{"row": int(inj.df.index[i]), "codes": ["l"], "reason": "name"} for i in stat_only]})
    out = pipe.run(inj.df)
    assert out["llm_confirmed"] == len(stat_only)
    assert pipe.reviewer.calls == (1 if len(stat_only) else 0)
