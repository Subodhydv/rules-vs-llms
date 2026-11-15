"""Exercise the LLM code paths with a fake Gemini transport, so a broken parser/prompt is caught before any
real quota is spent. The fake returns what a perfect model would; accuracy is measured live, not here."""
import json

import pytest

from common import llm
from project_a.impl_llm_compiled import compile as comp, dsl
from project_a.impl_llm_query import engine as llmq
from project_a.impl_rules import engine as rules
from project_a.models import Profile
from project_a.parser import llm_parser


def gemini_envelope(obj, in_tok=1000, out_tok=500):
    return {"model": "gemini-2.5-flash", "latency_ms": 1234.0, "timestamp": "t",
            "response": {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}}],
                         "usageMetadata": {"promptTokenCount": in_tok, "candidatesTokenCount": out_tok}}}


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.delenv("LLM_OFFLINE", raising=False)
    replies = []
    monkeypatch.setattr(llm.GeminiClient, "_call", lambda self, *a, **k: gemini_envelope(replies.pop(0)))
    return replies


def test_query_time_roundtrip(fake):
    p = Profile(fy="2024-25", age=40, gross_salary=1600000, sec80c=150000)
    truth = rules.compute(p).to_dict()
    fake.append(truth)
    r = llmq.compute(p, llm.GeminiClient())
    assert (r.old.tax_payable, r.new.tax_payable) == (truth["old"]["tax_payable"], truth["new"]["tax_payable"])
    assert r.meta["cost_usd"] == pytest.approx(1000 / 1e6 * 0.30 + 500 / 1e6 * 2.50)


def test_cache_replay_keeps_latency(fake):
    p = Profile(fy="2024-25", age=40, gross_salary=900000)
    fake.append(rules.compute(p).to_dict())
    c = llm.GeminiClient()
    llmq.compute(p, c)
    r2 = llmq.compute(p, c)            # second call must come from cache: fake has no more replies
    assert r2.meta["cached"] and r2.meta["latency_ms"] == 1234.0


def test_compile_roundtrip(fake):
    fake.append(dsl.load("2024-25"))
    doc, info = comp.compile_rules("2024-25", llm.GeminiClient())
    assert comp.gate(doc, "2024-25")["correct"] == 230


def test_llm_parser_and_hallucination_guard(fake):
    fake.append({"age": 30, "gross_salary": 1200000, "sec80c": 95000, "issues": [], "mentioned_without_amount": []})
    res, _ = llm_parser.parse("12 LPA, age 30, 80C 1 lakh", llm.GeminiClient())
    assert res.status == "clarify" and "sec80c" in res.ask_fields   # 95,000 is not in the text


def test_llm_parser_complete(fake):
    fake.append({"age": 30, "gross_salary": 1200000, "sec80c": 100000, "issues": [], "mentioned_without_amount": []})
    res, _ = llm_parser.parse("12 LPA, age 30, 80C 1 lakh", llm.GeminiClient())
    assert res.status == "complete" and res.profile.sec80c == 100000
