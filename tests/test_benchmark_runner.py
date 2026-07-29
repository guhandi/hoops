import json, sys
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
