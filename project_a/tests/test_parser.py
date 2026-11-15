import json
from pathlib import Path

from project_a.parser import rule_parser
from project_a.parser.score import load, score_one, summarise

HELDOUT = Path(__file__).parent / "data" / "descriptions_heldout.json"


def test_fifty_descriptions_exist_and_vary():
    items = load()
    assert len(items) == 50
    styles = {i["style"] for i in items}
    assert {"hinglish", "incomplete", "contradictory"} <= styles


def test_rule_parser_never_guesses_when_it_should_ask():
    for path_items in (load(), json.loads(HELDOUT.read_text())):
        rows = [score_one(d, rule_parser.parse(d["text"])) for d in path_items]
        assert summarise(rows)["guessed_when_should_ask"] == 0


def test_rule_parser_dev_set():
    rows = [score_one(d, rule_parser.parse(d["text"])) for d in load()]
    assert summarise(rows)["overall_correct"] == 50


def test_clarifying_question_text():
    r = rule_parser.parse("My salary is 85,000 and I'm 30.")
    assert r.status == "clarify" and "monthly or annual" in r.questions[0]["question"]
