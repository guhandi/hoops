import pytest
from benchmarks.transcribers.base import BWord, TranscriptResult, normalize_token

pytestmark = pytest.mark.unit

def test_normalize_token():
    assert normalize_token(" Swish, ") == "swish"
    assert normalize_token("BRICK.") == "brick"

def test_round_trip(tmp_path):
    r = TranscriptResult(
        model_id="m", fixture="F01",
        words=[BWord("swish", 1.0, 1.4, 0.9), BWord("brick", 5.0, 5.3, None)],
        text="swish brick", runtime_s=2.5, peak_rss_mb=100.0, prompt_used=True)
    p = tmp_path / "r.json"
    r.save(p)
    r2 = TranscriptResult.load(p)
    assert r2 == r
    assert r2.words[1].confidence is None

def test_from_dict_tolerates_missing_optionals():
    r = TranscriptResult.from_dict({
        "model_id": "m", "fixture": "F01",
        "words": [{"word": "swish", "start": 1.0, "end": 1.4}],
        "text": "swish", "runtime_s": 1.0})
    assert r.peak_rss_mb is None and r.prompt_used is False
    assert r.words[0].confidence is None
