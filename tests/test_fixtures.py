import json, shutil
import pytest
from pathlib import Path
from hoops.config import load_config
from hoops.fixtures import (read_manifest, transcript_cache_path, run_fixture, run_all)
from conftest import make_env

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[1]
GOOD = [("brick", 5.0, 5.3), ("swish", 12.0, 12.3), ("swish", 18.0, 18.3), ("swish", 24.0, 24.3)]
NEW_HEADER = ("filename,fixture_id,category,status,vocabulary,duration_s,size_bytes,"
              "audio_format,conditions,what_it_tests,use_for,timing_ground_truth,"
              "beep_interval_s,expected_calls,expected_shot_count,expect_invariants_pass,"
              "contains_correction,contains_note,traps_planted,label_status,notes")

class FakeTranscriber:
    model_id = "fake"
    def __init__(self, env): self.env = env; self.calls = 0
    def transcribe(self, path, prompt): self.calls += 1; return self.env["response"]

@pytest.fixture
def sandbox(tmp_path):
    shutil.copy(REPO / "config.yaml", tmp_path / "config.yaml")
    (tmp_path / "fixtures" / "dev").mkdir(parents=True)
    (tmp_path / "fixtures" / "transcripts").mkdir()
    shutil.copy(REPO / "fixtures" / "dev" / "dev03.m4a",
                tmp_path / "fixtures" / "dev" / "dev01.m4a")
    (tmp_path / "fixtures" / "manifest.csv").write_text(
        NEW_HEADER + "\n"
        "dev/dev01.m4a,D01,dev,recorded,,,,aac,x,x,regression,FALSE,,"
        "miss make make make,,TRUE,,,,LABELED,smoke\n")
    c = load_config(tmp_path / "config.yaml")
    c.gap_repair["enabled"] = False      # deterministic transcribe() call counts in these tests
    return c

def test_run_all_skips_not_recorded_and_blank_filename(sandbox):
    (sandbox.repo_root / "fixtures" / "manifest.csv").write_text(
        NEW_HEADER + "\n"
        ",F03,fixture,NOT_RECORDED,swish_brick,,,,x,x,GATE,FALSE,,,,TRUE,,,,NOT_RECORDED,missing\n")
    entries = run_all(sandbox, FakeTranscriber(make_env([])), sandbox.repo_root / "fixtures")
    assert entries == []

def test_cache_path():
    assert transcript_cache_path(Path("/r"), "dev/dev01.m4a") == \
        Path("/r/fixtures/transcripts/dev__dev01.json")

def test_run_fixture_writes_cache_then_reuses(sandbox):
    t = FakeTranscriber(make_env(GOOD, duration=30.0))
    row = read_manifest(sandbox.repo_root / "fixtures" / "manifest.csv")[0]
    e1 = run_fixture(row, sandbox, t, sandbox.repo_root / "out" / "fixtures")
    assert e1["got"] == ["miss", "make", "make", "make"] and t.calls == 1
    assert transcript_cache_path(sandbox.repo_root, row["filename"]).exists()
    # second run: cache hit, no new transcription
    shutil.rmtree(sandbox.repo_root / "out")
    e2 = run_fixture(row, sandbox, t, sandbox.repo_root / "out" / "fixtures")
    assert e2["got"] == e1["got"] and t.calls == 1

def test_transcribe_fixtures_cli_clears_stale_out_dir(sandbox, monkeypatch):
    import sys
    from hoops import cli
    row = read_manifest(sandbox.repo_root / "fixtures" / "manifest.csv")[0]
    out_root = sandbox.repo_root / "out" / "fixtures"
    # Simulate a prior process-all run leaving a populated out dir + cached transcript.
    t0 = FakeTranscriber(make_env(GOOD, duration=30.0))
    run_fixture(row, sandbox, t0, out_root)
    assert t0.calls == 1
    assert transcript_cache_path(sandbox.repo_root, row["filename"]).exists()

    calls = {"n": 0}
    class CountingTranscriber:
        model_id = "fake"
        def __init__(self, model, language="en"): pass
        def transcribe(self, path, prompt):
            calls["n"] += 1
            return make_env(GOOD, duration=30.0)["response"]

    monkeypatch.setattr("hoops.config.load_config", lambda *a, **k: sandbox)
    monkeypatch.setattr("hoops.transcribe.WhisperApiTranscriber", CountingTranscriber)
    monkeypatch.setattr(sys, "argv", ["hoops", "transcribe-fixtures"])
    assert cli.main() == 0
    # Without clearing the stale out dir, the I7 duplicate check would short-circuit
    # process_file before transcription and this would stay 0.
    assert calls["n"] == 1

def test_run_all_writes_gallery(sandbox):
    t = FakeTranscriber(make_env(GOOD, duration=30.0))
    entries = run_all(sandbox, t, sandbox.repo_root / "fixtures")
    assert len(entries) == 1
    assert (sandbox.repo_root / "out" / "index.html").exists()
