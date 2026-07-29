import json, os, time, shutil
import pytest
from pathlib import Path
from hoops.config import load_config
from hoops.ingest import stable_files, poll_once
from conftest import make_env

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[1]
GOOD = [("brick", 5.0, 5.3), ("swish", 12.0, 12.3), ("swish", 18.0, 18.3), ("swish", 24.0, 24.3)]

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

def test_poll_once_applies_and_archives_sidecar_vocab(cfg, monkeypatch):
    class FakeTranscriber:
        model_id = "fake"
        def transcribe(self, path, prompt):
            return make_env([("make", 5.0, 5.3), ("miss", 12.0, 12.3)],
                             duration=30.0)["response"]
    # never let unit tests reach real APIs, even if keys are in the shell env
    monkeypatch.setattr("hoops.narrative.generate_narrative", lambda *a, **k: None)
    def boom(*a, **k): raise RuntimeError("no smtp in tests")
    monkeypatch.setattr("hoops.mailer.send", boom)
    f = drop(cfg, name="hoops__20260727-070000.m4a")
    sidecar = f.with_suffix(".json")
    sidecar.write_text('{"vocabulary": "make_miss"}')
    assert poll_once(cfg, FakeTranscriber()) == []      # poll 1: records size
    done = poll_once(cfg, FakeTranscriber())            # poll 2: processes
    assert done == [f]
    assert not f.exists()                               # inbox drained (audio)
    assert not sidecar.exists()                          # inbox drained (sidecar)
    sdirs = list((cfg.sessions_root).rglob("vocab.json"))
    assert len(sdirs) == 1
    assert sdirs[0].parent / "audio.m4a" in list((cfg.sessions_root).rglob("audio.m4a"))

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

def test_zero_call_consumes_inbox_and_no_retranscribe(cfg, monkeypatch):
    class ZeroCallTranscriber:
        model_id = "fake"
        def __init__(self): self.calls = 0
        def transcribe(self, path, prompt):
            self.calls += 1
            return make_env([("just", 1.0, 1.2), ("talking", 1.3, 1.6)], duration=30.0)["response"]
    t = ZeroCallTranscriber()
    sent = []
    monkeypatch.setattr("hoops.mailer.send", lambda *a, **k: sent.append(a))
    f = drop(cfg)
    assert poll_once(cfg, t) == []                       # poll 1: records size
    done = poll_once(cfg, t)                             # poll 2: zero-call -> needs_review
    assert done == [f]
    assert not f.exists()                                # inbox file consumed
    nr_dirs = list((cfg.repo_root / "needs_review").iterdir())
    assert len(nr_dirs) == 1
    assert (nr_dirs[0] / "audio.m4a").exists()
    assert t.calls == 1
    assert len(sent) == 1                                # needs_review email sent once

    done2 = poll_once(cfg, t)                             # poll 3: nothing left in inbox
    assert done2 == []
    assert t.calls == 1                                  # no re-transcription
    assert len(sent) == 1                                # no second email

def test_duplicate_repairs_stranded_session(cfg):
    sid = "20260727-061204"
    sdir = cfg.sessions_root / sid[:4] / sid[4:6] / f"hoops__{sid}"
    sdir.mkdir(parents=True)
    (sdir / "transcript.json").write_text("{}")           # session dir exists but never got audio

    class NoCallTranscriber:
        model_id = "fake"
        def transcribe(self, path, prompt):
            raise AssertionError("a duplicate session must never be re-transcribed")

    f = drop(cfg, name=f"hoops__{sid}.m4a")
    assert poll_once(cfg, NoCallTranscriber()) == []      # poll 1: records size
    done = poll_once(cfg, NoCallTranscriber())            # poll 2: duplicate -> repaired
    assert done == [f]
    assert not f.exists()                                 # inbox drained
    assert (sdir / "audio.m4a").exists()                  # stranded session adopted the audio

def _pending_email_session(cfg):
    sid = "20260727-061204"
    sdir = cfg.sessions_root / sid[:4] / sid[4:6] / f"hoops__{sid}"
    sdir.mkdir(parents=True)
    (sdir / "transcript.json").write_text("{}")
    stats = {"session_id": sid, "session_date_local": "2026-07-27", "shots_to_three": 4,
             "makes": 3, "misses": 1, "fg_pct": 0.75, "longest_make_streak": 3,
             "longest_miss_streak": 1, "median_gap_s": 6.0, "session_len_s": 30.0,
             "notes": "", "ambiguous_calls": 0, "invariants_passed": True}
    (sdir / "session.json").write_text(json.dumps(stats))
    (sdir / "strip.png").write_bytes(b"\x89PNG_fake")
    (sdir / "pending_email").touch()
    return sdir

def test_pending_email_retried_and_marker_cleared(cfg, monkeypatch):
    sdir = _pending_email_session(cfg)
    sent = []
    monkeypatch.setattr("hoops.mailer.send", lambda *a, **k: sent.append(a))
    assert poll_once(cfg, None) == []
    assert len(sent) == 1
    assert not (sdir / "pending_email").exists()

def test_pending_email_marker_kept_on_repeated_failure(cfg, monkeypatch):
    sdir = _pending_email_session(cfg)
    def boom(*a, **k): raise RuntimeError("smtp still down")
    monkeypatch.setattr("hoops.mailer.send", boom)
    assert poll_once(cfg, None) == []
    assert (sdir / "pending_email").exists()

def test_is_dataless_predicate():
    from types import SimpleNamespace
    from hoops.ingest import _is_dataless
    assert _is_dataless(SimpleNamespace(st_size=100, st_blocks=0))
    assert not _is_dataless(SimpleNamespace(st_size=100, st_blocks=8))
    assert not _is_dataless(SimpleNamespace(st_size=0, st_blocks=0))  # empty file must not brctl-loop

def test_dataless_triggers_download_and_skips(cfg, monkeypatch):
    f = drop(cfg)
    calls = []
    monkeypatch.setattr("hoops.ingest._is_dataless", lambda st: True)
    monkeypatch.setattr("hoops.ingest.subprocess.run", lambda cmd, **k: calls.append(cmd))
    ready, state = stable_files(cfg.inbox, {}, "hoops")
    assert ready == []                                   # never process a stub
    assert calls == [["brctl", "download", str(f)]]
    assert state[f.name]["size"] == f.stat().st_size     # size remembered while downloading

def test_materialized_file_no_download(cfg, monkeypatch):
    f = drop(cfg)
    calls = []
    monkeypatch.setattr("hoops.ingest.subprocess.run", lambda cmd, **k: calls.append(cmd))
    _, state = stable_files(cfg.inbox, {}, "hoops")
    ready, _ = stable_files(cfg.inbox, state, "hoops")
    assert ready == [f]                                  # normal two-poll flow intact
    assert calls == []                                   # no brctl for local files

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
