import json
import pytest
from hoops.config import Vocabulary
from hoops.invariants import Violation
from hoops.repair import attempt_repair, extract_json
from conftest import make_env

pytestmark = pytest.mark.unit
V = Vocabulary.from_dict("default", {"make": ["make", "splash"], "miss": ["miss", "brick"]})

def _fake_anthropic(monkeypatch, reply_text):
    class Msg:
        content = [type("T", (), {"text": reply_text})()]
    class Messages:
        def create(self, **kw): return Msg()
    class FakeClient:
        def __init__(self): self.messages = Messages()
    monkeypatch.setattr("hoops.repair.anthropic.Anthropic", lambda: FakeClient())

def test_extract_json_with_fence():
    assert extract_json("```json\n[{\"a\": 1}]\n```") == [{"a": 1}]
    assert extract_json("here: {\"b\": 2} done") == {"b": 2}

def test_repair_returns_calls(monkeypatch):
    reply = json.dumps([{"result": "miss", "t_s": 5.0, "raw_token": "miss"},
                        {"result": "make", "t_s": 12.0, "raw_token": "make"},
                        {"result": "make", "t_s": 18.0, "raw_token": "make"},
                        {"result": "make", "t_s": 24.0, "raw_token": "make"}])
    _fake_anthropic(monkeypatch, reply)
    env = make_env([("miss", 5.0, 5.3)])
    calls = attempt_repair(env, [], [Violation("I1", "x")], V, model="claude-sonnet-5")
    assert [c.result for c in calls] == ["miss", "make", "make", "make"]
    assert calls[0].t_s == 5.0 and calls[0].voided is False

def test_repair_bad_reply_returns_none(monkeypatch):
    _fake_anthropic(monkeypatch, "I cannot help with that")
    assert attempt_repair(make_env([]), [], [Violation("I1", "x")], V, "m") is None

def test_repair_api_error_returns_none(monkeypatch):
    class Boom:
        def __init__(self): raise RuntimeError("api down")
    monkeypatch.setattr("hoops.repair.anthropic.Anthropic", Boom)
    assert attempt_repair(make_env([]), [], [Violation("I1", "x")], V, "m") is None
