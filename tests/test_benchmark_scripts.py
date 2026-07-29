import importlib, json, re
import pytest
from pathlib import Path

pytestmark = pytest.mark.unit
SCRIPTS = ["faster_whisper_", "mlx_whisper_", "parakeet_mlx_", "whisperx_", "crisper_whisper_"]
REPO = Path(__file__).resolve().parents[1]

@pytest.mark.parametrize("name", SCRIPTS)
def test_module_imports_without_heavy_deps_and_builds_valid_result(name):
    mod = importlib.import_module(f"benchmarks.transcribers.{name}")
    d = mod.result_dict("F01", [{"word": "swish", "start": 1.0, "end": 1.4, "confidence": 0.9}],
                        "swish", 2.0, True)
    from benchmarks.transcribers.base import TranscriptResult
    r = TranscriptResult.from_dict(d)
    assert r.model_id == mod.MODEL_ID and r.fixture == "F01"
    assert r.peak_rss_mb is None or r.peak_rss_mb > 0

@pytest.mark.parametrize("name", SCRIPTS)
def test_script_has_pep723_header(name):
    src = (REPO / "benchmarks" / "transcribers" / f"{name}.py").read_text()
    assert re.search(r"^# /// script$", src, re.M), "missing PEP 723 header"
    assert "dependencies" in src
