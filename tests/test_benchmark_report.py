import pytest
from benchmarks.report import render

pytestmark = pytest.mark.unit

METRICS = {
    "models": {"whisper-1": {"boundary": {"mean": 0.2, "median": 0.1, "p95": 0.4, "max": 0.5,
                                          "n_gaps": 9},
                             "rtf": 0.3, "peak_rss_mb": 120.0, "cost_usd": 0.05,
                             "coverage": "14/14",
                             "detection": {"found": 40, "missed": 1, "extra": 2}}},
    "fixtures": {"F01": {"duration_s": 88.9, "models": {"whisper-1": {"detections": [
        {"canonical": "make", "raw": "Swish", "start": 5.0, "end": 5.4, "mid": 5.2,
         "isolation": 3.0, "consensus": True}]}}, "clusters": [], "truth": None}},
    "isolation": {"whisper-1": {"threshold": 1.2, "margin": 0.8, "real": [2.0], "bait": [0.2]}},
    "agreement": {"whisper-1|mlx-whisper": 0.05},
    "draft_truth": [{"fixture_id": "F01", "draft_expected_calls": "make miss",
                     "disagreements": ""}],
    "skips": [{"model": "crisper-whisper", "fixture": "*", "reason": "gated model"}],
    "silence": {"status": "pending F10"},
}

def test_render_self_contained_html():
    html = render(METRICS)
    assert html.startswith("<!doctype html>")
    for marker in ["Summary", "F01", "Draft ground truth", "pending F10", "crisper-whisper"]:
        assert marker in html
    low = html.lower()
    assert "<svg" in low and "cdn" not in low
    assert 'src="http' not in low and 'href="http' not in low  # no external assets
