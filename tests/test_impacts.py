import json
import shutil
import subprocess
import wave
from array import array
from pathlib import Path

import pytest

from hoops.impacts import (ENVELOPE_HZ, build_impacts, decode_pcm,
                           find_impact, loudness_envelope, write_impacts)

pytestmark = pytest.mark.unit

def _flat(n, level=0.02):
    return [level] * n

def test_find_impact_hits_peak():
    env = _flat(150)
    env[45] = 0.9                       # 15 Hz -> peak at t = 3.03s
    t = find_impact(env, 15, t_word=4.0)  # window [2.0, 3.85] covers index 30..57
    assert t is not None
    assert abs(t - (45 + 0.5) / 15) < 0.05

def test_find_impact_ignores_peak_before_window():
    env = _flat(150)
    env[10] = 0.9                       # t = 0.7s, outside [2.0, 3.85]
    assert find_impact(env, 15, t_word=4.0) is None

def test_find_impact_ignores_peak_inside_guard():
    env = _flat(150)
    env[59] = 0.9                       # t = 3.97s, inside the 0.15s guard before 4.0
    assert find_impact(env, 15, t_word=4.0) is None

def test_no_contact_when_window_is_quiet():
    assert find_impact(_flat(150), 15, t_word=4.0) is None

def test_no_contact_when_whole_window_is_loud():
    # constant loudness (music/noise) has no transient: peak barely above median
    env = _flat(150, level=0.5)
    assert find_impact(env, 15, t_word=4.0) is None

def test_window_clamped_at_session_start():
    env = _flat(30)
    env[5] = 0.9
    t = find_impact(env, 15, t_word=1.0)  # window would start at -1.0s -> clamp to 0
    assert t is not None

def test_loudness_envelope_normalized_and_sized():
    rate, hz = 16000, 15
    quiet = [100] * rate                 # 1s quiet
    loud = [20000] * (rate // hz)        # one loud block
    samples = array("h", quiet + loud)
    env = loudness_envelope(samples, rate=rate, hz=hz)
    assert max(env) == 1.0
    assert env[-1] == 1.0
    assert all(0.0 <= v <= 1.0 for v in env)
    assert len(env) == (len(samples) + rate // hz - 1) // (rate // hz)

def _rows():
    return [
        {"shot_num": 1, "t_call_s": 4.0, "voided": False},
        {"shot_num": 2, "t_call_s": 8.0, "voided": False},
        {"shot_num": 3, "t_call_s": 9.0, "voided": True},
    ]

def test_build_impacts_marks_no_contact(monkeypatch, tmp_path):
    # impact only before shot 1; shot 2 window is silent -> lie flag
    env = _flat(200)
    env[45] = 0.9
    monkeypatch.setattr("hoops.impacts.decode_pcm", lambda p, rate=16000: array("h", [1]))
    monkeypatch.setattr("hoops.impacts.loudness_envelope",
                        lambda s, rate=16000, hz=ENVELOPE_HZ: env)
    data = build_impacts(tmp_path / "a.m4a", _rows())
    shots = {s["shot_num"]: s for s in data["shots"]}
    assert shots[1]["impact_t_s"] is not None and shots[1]["no_contact"] is False
    assert shots[2]["impact_t_s"] is None and shots[2]["no_contact"] is True
    assert shots[3]["impact_t_s"] is None and shots[3]["no_contact"] is False  # voided: not a lie
    assert data["envelope_hz"] == ENVELOPE_HZ

def test_build_impacts_none_when_decode_fails(monkeypatch, tmp_path):
    monkeypatch.setattr("hoops.impacts.decode_pcm", lambda p, rate=16000: None)
    assert build_impacts(tmp_path / "a.m4a", _rows()) is None

def test_write_impacts_writes_sidecar(monkeypatch, tmp_path):
    env = _flat(200)
    env[45] = 0.9
    monkeypatch.setattr("hoops.impacts.decode_pcm", lambda p, rate=16000: array("h", [1]))
    monkeypatch.setattr("hoops.impacts.loudness_envelope",
                        lambda s, rate=16000, hz=ENVELOPE_HZ: env)
    out = write_impacts(tmp_path, tmp_path / "a.m4a", _rows())
    assert out is not None
    on_disk = json.loads((tmp_path / "impacts.json").read_text())
    assert on_disk == out

def test_write_impacts_never_raises(monkeypatch, tmp_path):
    def boom(p, rate=16000):
        raise RuntimeError("decoder exploded")
    monkeypatch.setattr("hoops.impacts.decode_pcm", boom)
    assert write_impacts(tmp_path, tmp_path / "a.m4a", _rows()) is None
    assert not (tmp_path / "impacts.json").exists()

def test_write_impacts_none_audio(tmp_path):
    assert write_impacts(tmp_path, None, _rows()) is None

@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_decode_pcm_real_ffmpeg(tmp_path):
    # ffmpeg reads WAV too; a synthetic click file proves the subprocess path.
    src = tmp_path / "click.wav"
    rate = 16000
    samples = array("h", [0] * rate + [20000] * 160 + [0] * rate)
    with wave.open(str(src), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    out = decode_pcm(src, rate=rate)
    assert out is not None and len(out) > rate
    assert max(out) > 10000

def test_decode_pcm_missing_binary(monkeypatch, tmp_path):
    monkeypatch.setattr("hoops.impacts.shutil.which", lambda n: None)
    assert decode_pcm(tmp_path / "a.m4a") is None
