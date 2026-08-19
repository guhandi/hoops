import pytest
from pathlib import Path
from hoops.gap_repair import find_gaps, build_spans, merge_recovered, apply_gap_repair

pytestmark = pytest.mark.unit

GR_CFG = {"enabled": True, "trigger_gap_s": 10.0, "pad_s": 2.0, "max_spans": 8}

class ClipTranscriber:
    """Returns canned clip responses in call order."""
    model_id = "fake"
    def __init__(self, responses): self.responses, self.calls = list(responses), []
    def transcribe(self, path, prompt):
        self.calls.append(prompt)
        return self.responses.pop(0)

def _stub_clip(monkeypatch):
    monkeypatch.setattr("hoops.gap_repair.extract_clip",
                        lambda audio, t0, t1, dest: dest)

def _env(words):
    return {"model": "whisper-1",
            "response": {"words": [{"word": w, "start": s, "end": e}
                                   for w, s, e in words], "segments": []}}

def test_no_gaps_dense_words():
    words = [(0.5, 1.0), (6.0, 6.5), (12.0, 12.5)]
    assert find_gaps(words, 15.0, 10.0) == []

def test_interior_gap():
    words = [(5.6, 7.0), (30.1, 31.5), (49.6, 50.2)]
    assert find_gaps(words, 55.0, 10.0) == [(7.0, 30.1), (31.5, 49.6)]

def test_head_and_tail_gaps():
    words = [(20.0, 20.5), (25.0, 25.5)]
    assert find_gaps(words, 40.0, 10.0) == [(0.0, 20.0), (25.5, 40.0)]

def test_empty_transcript_is_one_full_gap():
    assert find_gaps([], 41.5, 10.0) == [(0.0, 41.5)]

def test_gap_exactly_at_threshold_does_not_trigger():
    words = [(0.0, 1.0), (11.0, 11.5)]
    assert find_gaps(words, 12.0, 10.0) == []

def test_r03_shape():
    # the two real gaps from session 20260819-131500 (word ends → next starts)
    words = [(30.1, 31.5), (49.6, 50.2), (110.96, 111.66), (127.48, 128.36)]
    gaps = find_gaps(words, 136.13, 10.0)
    assert (31.5, 49.6) in gaps and (111.66, 127.48) in gaps

def test_build_spans_pads_and_clamps():
    spans, truncated = build_spans([(1.0, 12.0), (100.0, 130.0)], 131.0, 2.0, 8)
    assert truncated is False
    assert spans == [{"gap": [1.0, 12.0], "clip": [0.0, 14.0]},
                     {"gap": [100.0, 130.0], "clip": [98.0, 131.0]}]

def test_build_spans_cap():
    gaps = [(float(i * 20), float(i * 20 + 11)) for i in range(10)]
    spans, truncated = build_spans(gaps, 500.0, 2.0, 8)
    assert len(spans) == 8 and truncated is True

def test_merge_recovered_keeps_only_inside_gap():
    clip_words = [{"word": "break", "start": 0.5, "end": 0.9},    # 110.16 — before gap
                  {"word": "splash", "start": 10.0, "end": 10.4},  # 119.66 — inside
                  {"word": "go", "start": 19.0, "end": 19.3}]      # 128.66 — after gap
    out = merge_recovered((111.66, 127.48), 109.66, clip_words)
    assert out == [{"word": "splash", "start": 119.66, "end": 120.06}]

def test_merge_recovered_empty_clip():
    assert merge_recovered((10.0, 25.0), 8.0, []) == []

# Dense words up to ~112s so ONLY the tail gap (112.4 -> 136.13) qualifies.
# (A lone word at 111s would also create a head gap — two spans, not one.)
DENSE_THEN_TAIL = [("w", float(t), float(t) + 0.4) for t in range(0, 113, 8)]

def test_apply_no_gaps_returns_env_unchanged(monkeypatch):
    _stub_clip(monkeypatch)
    env = _env([("break", 0.5, 0.9), ("splash", 8.0, 8.4)])
    t = ClipTranscriber([])
    out = apply_gap_repair(env, Path("x.m4a"), t, "p", GR_CFG, duration=12.0)
    assert out is env and t.calls == []

def test_apply_recovers_words(monkeypatch, tmp_path):
    _stub_clip(monkeypatch)
    env = _env(DENSE_THEN_TAIL)                      # tail gap 112.4 -> 136.13
    clip_resp = {"words": [{"word": "splash", "start": 9.26, "end": 9.66}]}
    t = ClipTranscriber([clip_resp])                 # clip starts 112.4-2 = 110.4
    out = apply_gap_repair(env, tmp_path / "a.m4a", t, "p", GR_CFG, duration=136.13)
    gr = out["gap_repair"]
    assert len(gr["spans"]) == 1
    assert gr["n_recovered"] == 1 and gr["errors"] == []
    rec = gr["spans"][0]["recovered"][0]
    assert rec["word"] == "splash" and abs(rec["start"] - 119.66) < 0.01
    assert out["response"] == env["response"]        # raw response pristine

def test_apply_span_failure_is_recorded_not_raised(monkeypatch, tmp_path):
    _stub_clip(monkeypatch)
    class Boom:
        def transcribe(self, path, prompt): raise RuntimeError("api down")
    env = _env(DENSE_THEN_TAIL)
    out = apply_gap_repair(env, tmp_path / "a.m4a", Boom(), "p", GR_CFG, duration=136.13)
    gr = out["gap_repair"]
    assert gr["n_recovered"] == 0 and len(gr["errors"]) == 1
    assert gr["errors"][0].startswith("span [112.4, 136.1]")

def test_apply_whole_stage_failure_returns_original(monkeypatch):
    def explode(*a, **k): raise RuntimeError("librosa gone")
    monkeypatch.setattr("hoops.gap_repair.build_spans", explode)
    env = _env(DENSE_THEN_TAIL)
    out = apply_gap_repair(env, Path("a.m4a"), ClipTranscriber([]), "p",
                           GR_CFG, duration=136.13)
    assert out["response"] == env["response"]
    assert out["gap_repair"]["n_recovered"] == 0 and out["gap_repair"]["errors"]

def test_apply_single_pass_no_recursion(monkeypatch, tmp_path):
    _stub_clip(monkeypatch)
    # clip response leaves the gap still "open" — must not re-trigger
    t = ClipTranscriber([{"words": []}])
    env = _env(DENSE_THEN_TAIL)
    apply_gap_repair(env, tmp_path / "a.m4a", t, "p", GR_CFG, duration=136.13)
    assert len(t.calls) == 1
