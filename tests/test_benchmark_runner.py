import json, subprocess, sys
import pytest
from pathlib import Path
from benchmarks import run_benchmark as rb

pytestmark = pytest.mark.unit

STUB_OK = """\
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
import json, sys
from pathlib import Path
out = sys.argv[2]
Path(out).parent.mkdir(parents=True, exist_ok=True)
Path(out).write_text(json.dumps({"model_id": "stub", "fixture": sys.argv[sys.argv.index("--fixture")+1],
    "words": [], "text": "", "runtime_s": 0.1, "peak_rss_mb": 1.0, "prompt_used": False}))
"""
STUB_FAIL = STUB_OK.replace("Path(out).write_text", "raise RuntimeError('boom')\nPath(out).write_text")

ROW = {"filename": "F01_NormalSwishBrick.m4a", "fixture_id": "F01", "status": "recorded",
       "vocabulary": "swish_brick"}

@pytest.fixture
def env(tmp_path, monkeypatch):
    from hoops.config import load_config
    import shutil
    REPO = Path(__file__).resolve().parents[1]
    shutil.copy(REPO / "config.yaml", tmp_path / "config.yaml")
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures" / "F01_NormalSwishBrick.m4a").write_bytes(b"fake")
    return load_config(tmp_path / "config.yaml"), tmp_path / "bench_out"

def _write_stub(tmp_path, body):
    p = tmp_path / "stub_.py"
    p.write_text(body)
    return p

def test_script_backend_ok_and_cache(env, tmp_path):
    cfg, out_root = env
    rb.BACKENDS["stub"] = {"kind": "script", "script": _write_stub(tmp_path, STUB_OK)}
    try:
        assert rb.run_one("stub", ROW, cfg, out_root, force=False, timeout=60) == "ok"
        assert (out_root / "transcripts" / "stub" / "F01.json").exists()
        assert rb.run_one("stub", ROW, cfg, out_root, force=False, timeout=60) == "cached"
    finally:
        del rb.BACKENDS["stub"]

def test_script_backend_failure_is_skip(env, tmp_path):
    cfg, out_root = env
    rb.BACKENDS["stub"] = {"kind": "script", "script": _write_stub(tmp_path, STUB_FAIL)}
    try:
        assert rb.run_one("stub", ROW, cfg, out_root, force=False, timeout=60) == "skip"
        assert rb.SKIPS and rb.SKIPS[-1]["model"] == "stub" and "boom" in rb.SKIPS[-1]["reason"]
    finally:
        del rb.BACKENDS["stub"]; rb.SKIPS.clear()

def test_registry_has_all_six_backends():
    assert set(rb.BACKENDS) == {"whisper-1", "faster-whisper", "mlx-whisper",
                                "parakeet-mlx", "whisperx", "crisper-whisper"}

def test_partial_file_cleaned_on_failure(env, tmp_path):
    """Bug fix: partial file left by crashed script should be cleaned up and not cached next run."""
    cfg, out_root = env
    # Script that writes partial JSON then crashes
    STUB_PARTIAL = """\
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
import json, sys
from pathlib import Path
out = sys.argv[2]
Path(out).parent.mkdir(parents=True, exist_ok=True)
Path(out).write_text("{")  # Write invalid partial JSON
raise RuntimeError('crash after partial write')
"""
    rb.BACKENDS["stub"] = {"kind": "script", "script": _write_stub(tmp_path, STUB_PARTIAL)}
    try:
        # First run: crash after partial write
        assert rb.run_one("stub", ROW, cfg, out_root, force=False, timeout=60) == "skip"
        assert "crash after partial write" in rb.SKIPS[-1]["reason"]
        # File should have been cleaned up
        assert not (out_root / "transcripts" / "stub" / "F01.json").exists()
        # Second run: file doesn't exist, so should try again (not cached)
        rb.SKIPS.clear()
        # Replace with a working script
        rb.BACKENDS["stub"]["script"] = _write_stub(tmp_path, STUB_OK)
        result = rb.run_one("stub", ROW, cfg, out_root, force=False, timeout=60)
        assert result == "ok", "Should re-run when partial file is cleaned up"
        assert (out_root / "transcripts" / "stub" / "F01.json").exists()
    finally:
        del rb.BACKENDS["stub"]; rb.SKIPS.clear()

def test_invalid_output_cleaned_on_exit_0(env, tmp_path):
    """Bug fix: script exiting 0 with invalid JSON should be reported as skip."""
    cfg, out_root = env
    # Script that exits 0 but writes invalid JSON
    STUB_INVALID_JSON = """\
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
import json, sys
from pathlib import Path
out = sys.argv[2]
Path(out).parent.mkdir(parents=True, exist_ok=True)
Path(out).write_text('{"not": "valid schema"}')  # Valid JSON but invalid schema
"""
    rb.BACKENDS["stub"] = {"kind": "script", "script": _write_stub(tmp_path, STUB_INVALID_JSON)}
    try:
        assert rb.run_one("stub", ROW, cfg, out_root, force=False, timeout=60) == "skip"
        assert rb.SKIPS and "model_id" in rb.SKIPS[-1]["reason"], "Should report schema validation error"
        # File should be cleaned up
        assert not (out_root / "transcripts" / "stub" / "F01.json").exists()
    finally:
        del rb.BACKENDS["stub"]; rb.SKIPS.clear()


def test_timeout_produces_distinct_skip_reason(env, tmp_path, monkeypatch):
    """Finding 1(a): a subprocess timeout must be reported with a distinct, greppable
    reason (f"timeout after {timeout}s"), not the generic repr(e) used for other
    failures — that's what lets it be told apart from an env-resolve/import failure
    both when reading skips.json and by the first-fixture abort rule."""
    cfg, out_root = env
    rb.BACKENDS["stub"] = {"kind": "script", "script": _write_stub(tmp_path, STUB_OK)}

    def fake_run(cmd, capture_output, text, timeout):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    monkeypatch.setattr(rb.subprocess, "run", fake_run)
    try:
        assert rb.run_one("stub", ROW, cfg, out_root, force=False, timeout=42) == "skip"
        assert rb.SKIPS[-1] == {"model": "stub", "fixture": "F01", "reason": "timeout after 42s"}
        assert not (out_root / "transcripts" / "stub" / "F01.json").exists()
    finally:
        del rb.BACKENDS["stub"]; rb.SKIPS.clear()


def test_run_model_does_not_abort_on_first_fixture_timeout(monkeypatch):
    """Finding 1(b): when the FIRST fixture's failure is a timeout, the model-wide
    abort must NOT fire — a timeout proves the env resolved and the model ran, so the
    remaining fixtures for that model must still be attempted."""
    rows = [{"fixture_id": "F01"}, {"fixture_id": "F02"}]
    calls = []

    def fake_run_one(model, row, cfg, out_root, force, timeout):
        calls.append(row["fixture_id"])
        if row["fixture_id"] == "F01":
            rb.SKIPS.append({"model": model, "fixture": "F01", "reason": f"timeout after {timeout}s"})
            return "skip"
        return "ok"

    monkeypatch.setattr(rb, "run_one", fake_run_one)
    try:
        counts = rb.run_model("stub", rows, cfg=None, out_root=None, force=False, timeout=42)
        assert calls == ["F01", "F02"], "second fixture must still be attempted after a first-fixture timeout"
        assert counts == {"ok": 1, "cached": 0, "skip": 1}
        # Only the timeout skip should be present -- no "first fixture failed" abort entry.
        assert rb.SKIPS == [{"model": "stub", "fixture": "F01", "reason": "timeout after 42s"}]
    finally:
        rb.SKIPS.clear()


def test_run_model_aborts_on_first_fixture_non_timeout_failure(monkeypatch):
    """The abort rule is still meant for real env-resolve/import failures: a
    non-timeout failure on the first fixture must still skip the rest of the model."""
    rows = [{"fixture_id": "F01"}, {"fixture_id": "F02"}]
    calls = []

    def fake_run_one(model, row, cfg, out_root, force, timeout):
        calls.append(row["fixture_id"])
        rb.SKIPS.append({"model": model, "fixture": row["fixture_id"], "reason": "ModuleNotFoundError(...)"})
        return "skip"

    monkeypatch.setattr(rb, "run_one", fake_run_one)
    try:
        counts = rb.run_model("stub", rows, cfg=None, out_root=None, force=False, timeout=42)
        assert calls == ["F01"], "second fixture must NOT be attempted after a non-timeout first failure"
        assert counts == {"ok": 0, "cached": 0, "skip": 1}
        assert rb.SKIPS == [
            {"model": "stub", "fixture": "F01", "reason": "ModuleNotFoundError(...)"},
            {"model": "stub", "fixture": "*", "reason": "first fixture failed; skipping model"},
        ]
    finally:
        rb.SKIPS.clear()


def test_merge_skips_no_existing_file(tmp_path):
    new = [{"model": "m1", "fixture": "F01", "reason": "boom"}]
    assert rb.merge_skips(tmp_path, new) == new


def test_merge_skips_preserves_unrelated_entries_and_replaces_matching(tmp_path):
    """Finding 2: staged invocations (e.g. one per model) must not clobber each other's
    skip entries. Re-reporting a (model, fixture) pair replaces its old entry; unrelated
    entries from earlier stages survive."""
    existing = [
        {"model": "m1", "fixture": "F01", "reason": "old m1 F01 reason"},
        {"model": "m2", "fixture": "F01", "reason": "m2 F01 reason (untouched)"},
    ]
    (tmp_path / "skips.json").write_text(json.dumps(existing))
    new = [{"model": "m1", "fixture": "F01", "reason": "new m1 F01 reason"},
           {"model": "m1", "fixture": "F02", "reason": "m1 F02 reason"}]

    merged = rb.merge_skips(tmp_path, new)

    assert {"model": "m2", "fixture": "F01", "reason": "m2 F01 reason (untouched)"} in merged
    assert {"model": "m1", "fixture": "F01", "reason": "new m1 F01 reason"} in merged
    assert {"model": "m1", "fixture": "F01", "reason": "old m1 F01 reason"} not in merged
    assert {"model": "m1", "fixture": "F02", "reason": "m1 F02 reason"} in merged
    assert len(merged) == 3


def test_merge_skips_tolerates_corrupt_existing_file(tmp_path):
    (tmp_path / "skips.json").write_text("{not valid json")
    new = [{"model": "m1", "fixture": "F01", "reason": "boom"}]
    assert rb.merge_skips(tmp_path, new) == new


def test_merge_skips_tolerates_wrong_shape_existing_file(tmp_path):
    """A pre-fix skips.json could have been written as a dict; tolerate that too."""
    (tmp_path / "skips.json").write_text(json.dumps({"not": "a list"}))
    new = [{"model": "m1", "fixture": "F01", "reason": "boom"}]
    assert rb.merge_skips(tmp_path, new) == new


def test_main_warns_on_empty_fixture_filter(monkeypatch, capsys, tmp_path):
    """Finding 7: a typo'd --fixtures value matching zero manifest rows must print a
    clear warning instead of silently reporting success."""
    monkeypatch.setattr(sys, "argv", ["run_benchmark.py", "--models", "whisper-1",
                                      "--fixtures", "NO_SUCH_FIXTURE_ID"])
    monkeypatch.setattr(rb, "OUT", tmp_path / "bench_out")
    monkeypatch.setattr(rb, "run_model", lambda *a, **k: {"ok": 0, "cached": 0, "skip": 0})
    rb.main()
    out = capsys.readouterr().out
    assert "no rows matched" in out
    assert "NO_SUCH_FIXTURE_ID" in out
