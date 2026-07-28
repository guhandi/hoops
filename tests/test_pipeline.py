import shutil
import pytest
from pathlib import Path
from hoops.config import load_config
from hoops.pipeline import process_file, replay_session
from hoops.session import read_session_json
from conftest import make_env

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[1]
GOOD = [("okay", 0.5, 0.8), ("miss", 5.0, 5.3), ("come", 8.0, 8.2), ("on", 8.25, 8.4),
        ("make", 12.0, 12.3), ("make", 18.0, 18.3), ("make", 24.0, 24.3),
        ("note", 27.0, 27.2), ("felt", 27.5, 27.7), ("good", 27.8, 28.0)]

class FakeTranscriber:
    model_id = "fake"
    def __init__(self, env): self.env = env
    def transcribe(self, path, prompt): return self.env["response"]

@pytest.fixture
def cfg(tmp_path, monkeypatch):
    shutil.copy(REPO / "config.yaml", tmp_path / "config.yaml")
    c = load_config(tmp_path / "config.yaml")
    return c

def audio(tmp_path, name="hoops__20260727-061204.m4a"):
    src = REPO / "fixtures" / "dev" / "dev03.m4a"   # real m4a → mutagen duration works
    dst = tmp_path / name
    shutil.copy(src, dst)
    return dst

def test_happy_path(tmp_path, cfg):
    f = audio(tmp_path)
    out = process_file(f, cfg, FakeTranscriber(make_env(GOOD, duration=30.0)),
                       email=False, archive="copy")
    assert out.status == "ok" and out.sid == "20260727-061204"
    sdir = out.session_dir
    for name in ["transcript.json", "transcript.txt", "shots.csv", "session.json",
                 "strip.png", "report.html", "audio.m4a"]:
        assert (sdir / name).exists(), name
    assert out.stats["shots_to_three"] == 4 and out.stats["invariants_passed"] is True
    assert out.stats["notes"] == "felt good"
    assert out.flags == []

def test_duplicate_skipped(tmp_path, cfg):
    f = audio(tmp_path)
    t = FakeTranscriber(make_env(GOOD, duration=30.0))
    process_file(f, cfg, t, email=False, archive="copy")
    out2 = process_file(f, cfg, t, email=False, archive="copy")
    assert out2.status == "duplicate"

def test_short_audio_rejected(tmp_path, cfg):
    f = audio(tmp_path)
    out = process_file(f, cfg, FakeTranscriber(make_env(GOOD)), email=False,
                       archive="copy", min_duration_override=999999)
    assert out.status == "rejected"
    assert any((cfg.repo_root / "rejected").iterdir())

def test_truncated_audio_rejected(tmp_path, cfg):
    f = tmp_path / "hoops__20260727-070000.m4a"
    f.write_bytes(b"not an mp4 at all")
    out = process_file(f, cfg, FakeTranscriber(make_env(GOOD)), email=False, archive="copy")
    assert out.status == "rejected"

def test_zero_calls_needs_review(tmp_path, cfg):
    env = make_env([("just", 1.0, 1.2), ("talking", 1.3, 1.6)], duration=30.0)
    out = process_file(audio(tmp_path), cfg, FakeTranscriber(env), email=False, archive="copy")
    assert out.status == "needs_review"
    assert (cfg.repo_root / "needs_review").exists()

def test_invariant_failure_flagged_not_dropped(tmp_path, cfg):
    env = make_env([("make", 5.0, 5.3), ("miss", 10.0, 10.3)], duration=30.0)
    out = process_file(audio(tmp_path), cfg, FakeTranscriber(env), email=False,
                       archive="copy", repair_enabled=False)
    assert out.status == "ok"
    assert out.stats["invariants_passed"] is False and out.flags

def test_replay_rewrites_and_preserves_quote(tmp_path, cfg):
    f = audio(tmp_path)
    out = process_file(f, cfg, FakeTranscriber(make_env(GOOD, duration=30.0)),
                       email=False, archive="copy")
    stats = read_session_json(out.session_dir)
    stats["quote_of_day"] = "kept quote"
    (out.session_dir / "session.json").write_text(__import__("json").dumps(stats))
    r = replay_session(out.session_dir, cfg)
    assert r.status == "ok"
    assert read_session_json(out.session_dir)["quote_of_day"] == "kept quote"
    assert read_session_json(out.session_dir)["shots_to_three"] == 4
