import json
import pytest
from hoops.narrative import generate_narrative
from conftest import make_env

pytestmark = pytest.mark.unit
STATS = {"shots_to_three": 8, "makes": 4, "misses": 4, "fg_pct": 0.5,
         "longest_make_streak": 3, "longest_miss_streak": 2, "median_gap_s": 6.0,
         "session_len_s": 60.0, "notes": ""}
ENV = make_env([("come", 1.0, 1.2), ("on", 1.3, 1.5), ("make", 5.0, 5.3)])

def _fake(monkeypatch, reply):
    class Msg:
        content = [type("T", (), {"text": reply})()]
    class Messages:
        def create(self, **kw): return Msg()
    class FakeClient:
        def __init__(self): self.messages = Messages()
    monkeypatch.setattr("hoops.narrative.anthropic.Anthropic", lambda: FakeClient())

def good_reply(quote="come on", t=1.0):
    return json.dumps({"headline": "Slow start, clean finish",
                       "recap": "A rough opening stretch. Then the rhythm arrived.",
                       "quote": quote, "quote_t_s": t})

def test_valid_narrative(monkeypatch):
    _fake(monkeypatch, good_reply())
    n = generate_narrative(STATS, ENV, "m")
    assert n.headline == "Slow start, clean finish" and n.quote == "come on"

def test_digit_in_recap_rejected(monkeypatch):
    bad = json.dumps({"headline": "ok", "recap": "Took 8 shots today.",
                      "quote": "come on", "quote_t_s": 1.0})
    _fake(monkeypatch, bad)
    assert generate_narrative(STATS, ENV, "m") is None

def test_non_verbatim_quote_rejected(monkeypatch):
    _fake(monkeypatch, good_reply(quote="lets go champ"))
    assert generate_narrative(STATS, ENV, "m") is None

def test_four_sentence_recap_rejected(monkeypatch):
    bad = json.dumps({"headline": "ok", "recap": "One. Two. Three. Four.",
                      "quote": "come on", "quote_t_s": 1.0})
    _fake(monkeypatch, bad)
    assert generate_narrative(STATS, ENV, "m") is None

def test_api_failure_returns_none(monkeypatch):
    class Boom:
        def __init__(self): raise RuntimeError("down")
    monkeypatch.setattr("hoops.narrative.anthropic.Anthropic", Boom)
    assert generate_narrative(STATS, ENV, "m") is None
