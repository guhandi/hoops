import json, shutil
import pytest
from pathlib import Path
from hoops.config import load_config
from hoops.fixtures import (read_manifest, transcript_cache_path, run_fixture, run_all)
from conftest import make_env

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[1]
GOOD = [("miss", 5.0, 5.3), ("make", 12.0, 12.3), ("make", 18.0, 18.3), ("make", 24.0, 24.3)]

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
        "filename,expected_calls,traps_planted,expect_invariants_pass,vocab,gating,expected_gaps,notes\n"
        "dev/dev01.m4a,miss make make make,,yes,,no,,smoke\n")
    return load_config(tmp_path / "config.yaml")

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

def test_run_all_writes_gallery(sandbox):
    t = FakeTranscriber(make_env(GOOD, duration=30.0))
    entries = run_all(sandbox, t, sandbox.repo_root / "fixtures")
    assert len(entries) == 1
    assert (sandbox.repo_root / "out" / "index.html").exists()
