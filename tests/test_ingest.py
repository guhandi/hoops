import json, os, time, shutil
import pytest
from pathlib import Path
from hoops.config import load_config
from hoops.ingest import stable_files, poll_once
from conftest import make_env

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[1]
GOOD = [("miss", 5.0, 5.3), ("make", 12.0, 12.3), ("make", 18.0, 18.3), ("make", 24.0, 24.3)]

def old(path):  # push mtime beyond the 60s freshness guard
    ts = time.time() - 120
    os.utime(path, (ts, ts))

@pytest.fixture
def cfg(tmp_path):
    text = (REPO / "config.yaml").read_text().replace(
        "~/Library/Mobile Documents/com~apple~CloudDocs/Capture/inbox",
        str(tmp_path / "inbox"))
    (tmp_path / "config.yaml").write_text(text)
    (tmp_path / "inbox").mkdir()
    return load_config(tmp_path / "config.yaml")

def drop(cfg, name="hoops__20260727-061204.m4a"):
    dst = cfg.inbox / name
    shutil.copy(REPO / "fixtures" / "dev" / "dev03.m4a", dst)
    old(dst)
    return dst

def test_new_file_not_ready_until_second_poll(cfg):
    f = drop(cfg)
    ready, state = stable_files(cfg.inbox, {}, "hoops")
    assert ready == []                       # first sighting: record size only
    ready, _ = stable_files(cfg.inbox, state, "hoops")
    assert ready == [f]                      # unchanged size on second poll

def test_wrong_prefix_ignored(cfg):
    (cfg.inbox / "food__x.m4a").write_bytes(b"x")
    old(cfg.inbox / "food__x.m4a")
    _, state = stable_files(cfg.inbox, {}, "hoops")
    ready, _ = stable_files(cfg.inbox, state, "hoops")
    assert ready == []

def test_fresh_mtime_not_ready(cfg):
    f = cfg.inbox / "hoops__20260727-070000.m4a"
    shutil.copy(REPO / "fixtures" / "dev" / "dev03.m4a", f)   # mtime = now
    _, state = stable_files(cfg.inbox, {}, "hoops")
    ready, _ = stable_files(cfg.inbox, state, "hoops")
    assert ready == []

def test_poll_once_processes_and_moves(cfg, monkeypatch):
    class FakeTranscriber:
        model_id = "fake"
        def transcribe(self, path, prompt): return make_env(GOOD, duration=30.0)["response"]
    # never let unit tests reach real APIs, even if keys are in the shell env
    monkeypatch.setattr("hoops.narrative.generate_narrative", lambda *a, **k: None)
    def boom(*a, **k): raise RuntimeError("no smtp in tests")
    monkeypatch.setattr("hoops.mailer.send", boom)
    f = drop(cfg)
    assert poll_once(cfg, FakeTranscriber()) == []      # poll 1: records size
    done = poll_once(cfg, FakeTranscriber())            # poll 2: processes
    assert done == [f]
    assert not f.exists()                               # moved into session folder
    sdirs = list((cfg.sessions_root).rglob("audio.m4a"))
    assert len(sdirs) == 1
    assert (sdirs[0].parent / "pending_email").exists() # email failed (no SMTP) → marker

def test_poll_lock_blocks_concurrent(cfg):
    (cfg.repo_root / ".poll.lock").write_text("999999")
    assert poll_once(cfg, None) == []

def test_corrupted_state_file_recovers(cfg):
    state_path = cfg.repo_root / ".poll_state.json"
    state_path.write_text("not json{")
    assert poll_once(cfg, None) == []            # doesn't crash the poll cycle
    new_state = json.loads(state_path.read_text())  # rewritten file is valid json
    assert new_state == {"_failures": {}}

def test_stable_files_tolerates_stat_race(cfg, monkeypatch):
    f1 = drop(cfg, name="hoops__20260727-061204.m4a")
    f2 = drop(cfg, name="hoops__20260727-071204.m4a")
    _, state = stable_files(cfg.inbox, {}, "hoops")   # poll 1: record both sizes
    orig_stat = Path.stat
    def flaky_stat(self, *a, **k):
        if self.name == f1.name:
            raise FileNotFoundError("evicted mid-scan")
        return orig_stat(self, *a, **k)
    monkeypatch.setattr(Path, "stat", flaky_stat)
    ready, new_state = stable_files(cfg.inbox, state, "hoops")
    assert ready == [f2]                              # f1's flakiness doesn't kill the cycle
    assert f1.name not in new_state

def test_alert_refires_at_multiples_of_three(cfg, monkeypatch):
    class BoomTranscriber:
        model_id = "fake"
        def transcribe(self, path, prompt): raise RuntimeError("transcription boom")
    f = drop(cfg)
    size = f.stat().st_size
    calls = []
    monkeypatch.setattr("hoops.mailer.send", lambda *a, **k: calls.append(a))
    state_path = cfg.repo_root / ".poll_state.json"
    state_path.write_text(json.dumps({f.name: {"size": size}, "_failures": {f.name: 5}}))
    done = poll_once(cfg, BoomTranscriber())
    assert done == []
    assert len(calls) == 1                            # re-armed at 6, not silent forever
    new_state = json.loads(state_path.read_text())
    assert new_state["_failures"][f.name] == 6
