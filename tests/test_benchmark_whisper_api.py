import pytest
from pathlib import Path
from benchmarks.transcribers import whisper_api

pytestmark = pytest.mark.unit

FAKE_RESP = {
    "text": "swish brick",
    "duration": 10.0,
    "words": [{"word": " Swish,", "start": 1.0, "end": 1.4},
              {"word": "brick", "start": 5.0, "end": 5.3}],
    "segments": [{"start": 0.0, "end": 10.0, "avg_logprob": -0.1}],
}

def test_transcribe_converts_response(monkeypatch):
    class FakeT:
        model_id = "whisper-1"
        def transcribe(self, path, prompt): return FAKE_RESP
    monkeypatch.setattr(whisper_api, "WhisperApiTranscriber", lambda: FakeT())
    r = whisper_api.transcribe(Path("x.m4a"), "F01", "swish. brick.")
    assert r.model_id == "whisper-1" and r.fixture == "F01"
    assert [w.word for w in r.words] == ["Swish,", "brick"]  # raw surface, stripped
    assert r.words[0].start == 1.0 and r.words[0].confidence is not None
    assert r.prompt_used is True and r.runtime_s >= 0
