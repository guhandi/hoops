import math
import pytest
from hoops.transcribe import (Word, make_envelope, words_from_envelope,
                              envelope_text, envelope_duration, normalize_token,
                              vocab_prompt, WhisperApiTranscriber)
from hoops.config import Vocabulary
from conftest import make_env

pytestmark = pytest.mark.unit

def test_normalize_token():
    assert normalize_token(" Make,") == "make"
    assert normalize_token("BRICK!") == "brick"

def test_normalize_token_with_smart_quotes():
    # Test with smart quotes: left-double-quote, right-double-quote
    test_str = "“Make”"  # Left double quote + Make + right double quote
    assert normalize_token(test_str) == "make"

def test_words_from_envelope_with_segment_confidence():
    env = make_env([(" make", 1.0, 1.4), (" miss", 3.0, 3.4)])
    env["response"]["segments"] = [
        {"start": 0.0, "end": 2.0, "avg_logprob": -0.1},
        {"start": 2.0, "end": 4.0, "avg_logprob": -0.5},
    ]
    ws = words_from_envelope(env)
    assert [w.text for w in ws] == ["make", "miss"]
    assert ws[0].raw == " make" and ws[0].start == 1.0 and ws[0].end == 1.4
    assert math.isclose(ws[0].confidence, math.exp(-0.1))
    assert math.isclose(ws[1].confidence, math.exp(-0.5))

def test_words_without_segments_have_none_confidence():
    ws = words_from_envelope(make_env([("hi", 0.0, 0.2)]))
    assert ws[0].confidence is None

def test_envelope_accessors():
    env = make_env([("a", 0.0, 0.5)], duration=9.9)
    assert envelope_duration(env) == 9.9
    assert envelope_text(env) == "a"

def test_envelope_duration_zero():
    env = make_env([("a", 0.0, 0.5)], duration=0.0)
    assert envelope_duration(env) == 0.0

def test_vocab_prompt_mentions_surfaces():
    v = Vocabulary.from_dict("default", {"make": ["make", "splash"], "miss": ["miss", "brick"]})
    p = vocab_prompt(v)
    for s in ["make", "splash", "miss", "brick", "scratch that", "note"]:
        assert s in p

def test_whisper_transcriber_calls_api(monkeypatch, tmp_path):
    calls = {}
    class FakeResp:
        def model_dump(self): return {"text": "ok", "duration": 1.0, "words": []}
    class FakeTranscriptions:
        def create(self, **kw):
            calls.update(kw); return FakeResp()
    class FakeClient:
        def __init__(self): self.audio = type("A", (), {"transcriptions": FakeTranscriptions()})()
    monkeypatch.setattr("hoops.transcribe.OpenAI", lambda: FakeClient())
    f = tmp_path / "a.m4a"; f.write_bytes(b"x")
    t = WhisperApiTranscriber()
    resp = t.transcribe(f, prompt="hint")
    assert resp["text"] == "ok"
    assert calls["model"] == "whisper-1"
    assert calls["response_format"] == "verbose_json"
    assert calls["timestamp_granularities"] == ["word"]
    assert calls["prompt"] == "hint"
