"""Branch B unit tests — synthetic signals only, except one 30s fixture smoke."""
import json
from pathlib import Path
import pytest
from hoops.acoustics import (cluster_times, analyze_samples, analyze_audio,
                             write_acoustics)
from hoops.config import DEFAULT_ACOUSTICS

ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.unit
def test_cluster_times_groups_bursts():
    assert cluster_times([1.0, 1.5, 2.2, 9.0, 9.1], 2.0) == [[1.0, 1.5, 2.2], [9.0, 9.1]]

@pytest.mark.unit
def test_cluster_times_empty_and_single():
    assert cluster_times([], 2.0) == []
    assert cluster_times([3.0], 2.0) == [[3.0]]

@pytest.mark.unit
def test_cluster_gap_is_between_neighbours_not_burst_start():
    # 1.0 -> 2.5 -> 4.0: each neighbour gap <= 2.0 even though span is 3.0
    assert cluster_times([1.0, 2.5, 4.0], 2.0) == [[1.0, 2.5, 4.0]]

def _click_track(sr, dur_s, click_ts):
    """Sustained low tone ('voice-ish' harmonic energy) + seeded broadband clicks."""
    import numpy as np
    rng = np.random.default_rng(0)
    n = int(sr * dur_s)
    y = 0.05 * np.sin(2 * np.pi * 220.0 * np.arange(n) / sr)
    burst = int(0.01 * sr)
    for t in click_ts:
        i = int(t * sr)
        y[i:i + burst] += rng.standard_normal(burst) * 0.8
    return y.astype("float32")

@pytest.mark.unit
def test_synthetic_clicks_survive_hpss_and_cluster():
    sr = DEFAULT_ACOUSTICS["sr"]
    # 0.45s between the first two clicks: far enough apart to clear peak_pick's
    # pre_max/post_max=30-frame (~0.35s) look-around window (a 0.2s gap gets the
    # second click's onset suppressed as a non-local-max next to the still-decaying
    # first peak), still well inside cluster_gap_s=2.0 so they cluster as one event.
    y = _click_track(sr, 8.0, click_ts=(2.0, 2.45, 5.0))
    res = analyze_samples(y, sr, DEFAULT_ACOUSTICS)
    assert len(res["events"]) == 2                       # (2.0, 2.45) cluster + 5.0
    assert abs(res["events"][0]["t_start"] - 2.0) < 0.15
    assert abs(res["events"][1]["t_start"] - 5.0) < 0.15
    assert res["events"][0]["n_impacts"] >= 2
    for e in res["events"]:
        assert set(e) >= {"t_start", "t_end", "n_impacts", "impact_times",
                          "burst_duration_s", "mean_centroid_hz", "max_peak_rms",
                          "mean_decay_ratio", "impacts"}

@pytest.mark.unit
def test_envelope_normalized_and_hz_consistent():
    sr = DEFAULT_ACOUSTICS["sr"]
    res = analyze_samples(_click_track(sr, 8.0, (2.0,)), sr, DEFAULT_ACOUSTICS)
    assert res["envelope"] and max(res["envelope"]) <= 1.0 and min(res["envelope"]) >= 0.0
    # envelope length / envelope_hz must reconstruct ~the signal duration
    assert abs(len(res["envelope"]) / res["envelope_hz"] - 8.0) < 0.5

@pytest.mark.unit
def test_analyze_audio_missing_file_returns_none(tmp_path):
    assert analyze_audio(tmp_path / "nope.m4a", DEFAULT_ACOUSTICS) is None

@pytest.mark.unit
def test_write_acoustics_none_audio_returns_none(tmp_path):
    assert write_acoustics(tmp_path, None, DEFAULT_ACOUSTICS) is None
    assert not (tmp_path / "acoustics.json").exists()

@pytest.mark.unit
def test_write_acoustics_never_raises_on_bad_params(tmp_path):
    # missing keys must not escape as KeyError
    assert write_acoustics(tmp_path, tmp_path / "nope.m4a", {}) is None

@pytest.mark.unit
def test_write_acoustics_writes_sidecar(tmp_path, monkeypatch):
    canned = {"envelope": [0.1], "envelope_hz": 14.35, "events": []}
    monkeypatch.setattr("hoops.acoustics.analyze_audio", lambda *a, **k: canned)
    out = write_acoustics(tmp_path, tmp_path / "a.m4a", DEFAULT_ACOUSTICS)
    assert out == canned
    assert json.loads((tmp_path / "acoustics.json").read_text()) == canned

def test_fixture_f01_first_30s_finds_shot_events():
    """Real-audio smoke: decode + HPSS on F01's first 30s finds >=2 events."""
    res = analyze_audio(ROOT / "fixtures" / "F01_NormalSwishBrick.m4a",
                        DEFAULT_ACOUSTICS, duration_s=30.0)
    assert res is not None
    assert len(res["events"]) >= 2
