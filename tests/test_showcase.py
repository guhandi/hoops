import pytest
from pathlib import Path
from benchmarks.showcase import render_showcase

pytestmark = pytest.mark.unit

METRICS = {
    "models": {
        "whisper-1": {"rtf_median": 0.04, "cost_usd": 0.113,
                      "detections_found": 148, "detections_matched": 48, "detections_extra": 100},
        "parakeet-mlx": {"rtf_median": 0.049, "peak_rss_max": 870.0,
                         "detections_found": 122, "detections_matched": 51, "detections_extra": 71},
    },
    "fixtures": {}, "skips": [], "isolation": {"threshold": 0.04, "margin": -0.8},
    "agreement": {"whisper-1|parakeet-mlx": 0.3}, "n_fixtures_total": 14,
}

def test_showcase_self_contained():
    html = render_showcase(METRICS)
    assert html.startswith("<!doctype html>")
    for marker in ["whisper-1", "Decision", "Gate", "parakeet-mlx", "<svg"]:
        assert marker in html
    low = html.lower()
    assert "cdn" not in low
    assert 'src="http' not in low and 'href="http' not in low
