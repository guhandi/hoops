# ASR Word-Level Timestamp Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Standalone benchmark that runs six ASR backends over the golden fixtures and produces one self-contained HTML report comparing word-level timestamp quality, plus a draft ground truth and a written model recommendation.

**Architecture:** Each heavy local backend is a self-contained PEP 723 script executed via `uv run --script` in its own ephemeral env (dependency conflicts between backends are impossible by construction); whisper-1 runs in-process reusing `hoops.transcribe`. Cached `TranscriptResult` JSON files are the inter-process contract. `analyze.py` computes metrics from cached JSON (pure-stdlib math), `report.py` renders inline-SVG HTML.

**Tech Stack:** Python 3.12, uv, pytest. Backends: openai (whisper-1), faster-whisper, mlx-whisper, parakeet-mlx, whisperx (best-effort), transformers/CrisperWhisper (best-effort).

**Spec:** `docs/specs` → `docs/superpowers/specs/2026-07-28-asr-benchmark-design.md`

## Global Constraints

- Nothing under `src/hoops/` may be modified. Read-only imports from `hoops.*` are allowed in `benchmarks/` code that runs in the project env (orchestrator, whisper_api backend, analyze) — never inside PEP 723 scripts (they run in isolated envs without the repo installed).
- PEP 723 scripts must be fully self-contained: stdlib + their own declared deps only; heavy imports live inside `run()`, never at module top level (tests import the module without the deps installed).
- Report is one self-contained HTML file: inline CSS, inline SVG, **no CDN, no external requests, no JS libraries**.
- Backend failure at any stage (env resolve, import, download, OOM, timeout) = logged skip in `benchmarks/out/skips.json`; the run continues.
- Local whisper-family backends receive the production bias text via `initial_prompt`; parakeet gets none; every result records `prompt_used`.
- `resource.getrusage(...).ru_maxrss` is **bytes on macOS** (KB on Linux) — divide by 1e6 for MB and comment it.
- Transcript cache: `benchmarks/out/transcripts/{model}/{fixture_id}.json`; re-runs never re-transcribe unless `--force`.
- Never print or commit `.env` values (`OPENAI_API_KEY`, `HF_TOKEN`, `GMAIL_*`).
- Run tests with `uv run pytest tests/test_benchmark_*.py -q`; the full suite `uv run pytest` must stay green.
- Commit trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Do not add ASR backends beyond the six listed here.

## File map

| File | Responsibility |
|---|---|
| `benchmarks/transcribers/base.py` | `BWord`/`TranscriptResult` dataclasses, JSON (de)serialization, `normalize_token` |
| `benchmarks/transcribers/whisper_api.py` | in-process whisper-1 adapter over `hoops.transcribe` |
| `benchmarks/transcribers/faster_whisper_.py` | PEP 723 script, faster-whisper large-v3 int8 CPU |
| `benchmarks/transcribers/mlx_whisper_.py` | PEP 723 script, mlx-community/whisper-large-v3-mlx |
| `benchmarks/transcribers/parakeet_mlx_.py` | PEP 723 script, mlx-community/parakeet-tdt-0.6b-v2 |
| `benchmarks/transcribers/whisperx_.py` | PEP 723 script, WhisperX forced alignment (best-effort) |
| `benchmarks/transcribers/crisper_whisper_.py` | PEP 723 script, nyrahealth/CrisperWhisper (best-effort, gated) |
| `benchmarks/run_benchmark.py` | orchestrate models × fixtures, cache, skips, CLI |
| `benchmarks/analyze.py` | metrics → `out/metrics.json`, `out/draft_truth.csv` |
| `benchmarks/report.py` | metrics → `out/report.html` |
| `benchmarks/README.md` | how to run, how to add a backend |

---

### Task 1: TranscriptResult contract (`base.py`)

**Files:**
- Create: `benchmarks/transcribers/__init__.py` (empty), `benchmarks/transcribers/base.py`, `benchmarks/__init__.py` (empty)
- Test: `tests/test_benchmark_base.py`

**Interfaces:**
- Produces: `BWord(word, start, end, confidence=None)`; `TranscriptResult(model_id, fixture, words, text, runtime_s, peak_rss_mb=None, prompt_used=False)` with `.to_dict()`, `.from_dict(d)`, `.save(path)`, `.load(path)`; `normalize_token(s) -> str`. Every later task consumes these.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_benchmark_base.py
import pytest
from benchmarks.transcribers.base import BWord, TranscriptResult, normalize_token

pytestmark = pytest.mark.unit

def test_normalize_token():
    assert normalize_token(" Swish, ") == "swish"
    assert normalize_token("BRICK.") == "brick"

def test_round_trip(tmp_path):
    r = TranscriptResult(
        model_id="m", fixture="F01",
        words=[BWord("swish", 1.0, 1.4, 0.9), BWord("brick", 5.0, 5.3, None)],
        text="swish brick", runtime_s=2.5, peak_rss_mb=100.0, prompt_used=True)
    p = tmp_path / "r.json"
    r.save(p)
    r2 = TranscriptResult.load(p)
    assert r2 == r
    assert r2.words[1].confidence is None

def test_from_dict_tolerates_missing_optionals():
    r = TranscriptResult.from_dict({
        "model_id": "m", "fixture": "F01",
        "words": [{"word": "swish", "start": 1.0, "end": 1.4}],
        "text": "swish", "runtime_s": 1.0})
    assert r.peak_rss_mb is None and r.prompt_used is False
    assert r.words[0].confidence is None
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_benchmark_base.py -q` → import error.

- [ ] **Step 3: Implement**

```python
# benchmarks/transcribers/base.py
"""TranscriptResult: the JSON contract every backend writes and every analysis reads."""
from __future__ import annotations
import json
import string
from dataclasses import dataclass, field
from pathlib import Path

_PUNCT = string.punctuation + "’‘”“…"

def normalize_token(s: str) -> str:
    return s.strip().strip(_PUNCT).lower()

@dataclass(frozen=True)
class BWord:
    word: str
    start: float
    end: float
    confidence: float | None = None

@dataclass
class TranscriptResult:
    model_id: str
    fixture: str
    words: list[BWord]
    text: str
    runtime_s: float
    peak_rss_mb: float | None = None
    prompt_used: bool = False

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id, "fixture": self.fixture,
            "words": [{"word": w.word, "start": w.start, "end": w.end,
                       "confidence": w.confidence} for w in self.words],
            "text": self.text, "runtime_s": self.runtime_s,
            "peak_rss_mb": self.peak_rss_mb, "prompt_used": self.prompt_used,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TranscriptResult":
        return cls(
            model_id=d["model_id"], fixture=d["fixture"],
            words=[BWord(w["word"], float(w["start"]), float(w["end"]),
                         w.get("confidence")) for w in d["words"]],
            text=d["text"], runtime_s=float(d["runtime_s"]),
            peak_rss_mb=d.get("peak_rss_mb"), prompt_used=bool(d.get("prompt_used", False)))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=1))

    @classmethod
    def load(cls, path: Path) -> "TranscriptResult":
        return cls.from_dict(json.loads(path.read_text()))
```

Also create empty `benchmarks/__init__.py` and `benchmarks/transcribers/__init__.py` so tests can import. Pytest likely cannot see `benchmarks` yet (`hoops` is importable because it's an installed src-layout package; `benchmarks` is not installed): add `pythonpath = ["."]` under `[tool.pytest.ini_options]` in `pyproject.toml` (merge with any existing keys — do NOT touch `src/hoops`).

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_benchmark_base.py -q` → 3 passed.
- [ ] **Step 5: Commit** — `git add benchmarks tests/test_benchmark_base.py && git commit -m "feat(bench): TranscriptResult JSON contract"`

---

### Task 2: whisper-1 in-process backend (`whisper_api.py`)

**Files:**
- Create: `benchmarks/transcribers/whisper_api.py`
- Test: `tests/test_benchmark_whisper_api.py`

**Interfaces:**
- Consumes: Task 1 types; `hoops.transcribe.WhisperApiTranscriber`, `make_envelope`, `words_from_envelope` (read-only).
- Produces: `transcribe(audio_path: Path, fixture_id: str, prompt: str) -> TranscriptResult` with `model_id="whisper-1"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_benchmark_whisper_api.py
import pytest
from pathlib import Path
from benchmarks.transcribers import whisper_api

pytestmark = pytest.mark.unit

FAKE_RESP = {
    "text": "swish brick",
    "duration": 10.0,
    "words": [{"word": " Swish,", "start": 1.0, "end": 1.4},
              {"word": "brick", "start": 5.0, "end": 5.3}],
    "segments": [{"start": 0.0, "end": 10.0, "avg_logprob": -0.1}],
}

def test_transcribe_converts_response(monkeypatch):
    class FakeT:
        model_id = "whisper-1"
        def transcribe(self, path, prompt): return FAKE_RESP
    monkeypatch.setattr(whisper_api, "WhisperApiTranscriber", lambda: FakeT())
    r = whisper_api.transcribe(Path("x.m4a"), "F01", "swish. brick.")
    assert r.model_id == "whisper-1" and r.fixture == "F01"
    assert [w.word for w in r.words] == ["Swish,", "brick"]  # raw surface, stripped
    assert r.words[0].start == 1.0 and r.words[0].confidence is not None
    assert r.prompt_used is True and r.runtime_s >= 0
```

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement**

```python
# benchmarks/transcribers/whisper_api.py
"""In-process whisper-1 backend: production parity via hoops' own transcriber + bias prompt."""
import time
from pathlib import Path
from hoops.transcribe import WhisperApiTranscriber, make_envelope, words_from_envelope
from .base import BWord, TranscriptResult

MODEL_ID = "whisper-1"

def transcribe(audio_path: Path, fixture_id: str, prompt: str) -> TranscriptResult:
    t0 = time.monotonic()
    resp = WhisperApiTranscriber().transcribe(audio_path, prompt)
    runtime = time.monotonic() - t0
    env = make_envelope(resp, MODEL_ID)
    words = [BWord(word=w.raw.strip(), start=w.start, end=w.end, confidence=w.confidence)
             for w in words_from_envelope(env)]
    return TranscriptResult(MODEL_ID, fixture_id, words, resp.get("text", ""),
                            runtime, peak_rss_mb=None, prompt_used=bool(prompt))
```

- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(bench): whisper-1 in-process backend"`

---

### Task 3: Core local backend scripts (faster-whisper, mlx-whisper, parakeet-mlx)

**Files:**
- Create: `benchmarks/transcribers/faster_whisper_.py`, `benchmarks/transcribers/mlx_whisper_.py`, `benchmarks/transcribers/parakeet_mlx_.py`
- Test: `tests/test_benchmark_scripts.py`

**Interfaces:**
- Produces: each script is CLI `uv run --script <script> AUDIO OUT_JSON [--prompt P] [--fixture F]`, writes a TranscriptResult-shaped JSON. Each module exposes (importable WITHOUT its heavy deps): `MODEL_ID: str`, `result_dict(fixture, words, text, runtime_s, prompt_used) -> dict`, `peak_rss_mb() -> float`.

Shared pattern — heavy imports only inside `run()`. Every script ends with the same `main()`/argparse block. Full code for all three:

- [ ] **Step 1: Write the failing test**

```python
# tests/test_benchmark_scripts.py
import importlib, json, re
import pytest
from pathlib import Path

pytestmark = pytest.mark.unit
SCRIPTS = ["faster_whisper_", "mlx_whisper_", "parakeet_mlx_", "whisperx_", "crisper_whisper_"]
REPO = Path(__file__).resolve().parents[1]

@pytest.mark.parametrize("name", SCRIPTS[:3])  # Task 4 extends to all 5
def test_module_imports_without_heavy_deps_and_builds_valid_result(name):
    mod = importlib.import_module(f"benchmarks.transcribers.{name}")
    d = mod.result_dict("F01", [{"word": "swish", "start": 1.0, "end": 1.4, "confidence": 0.9}],
                        "swish", 2.0, True)
    from benchmarks.transcribers.base import TranscriptResult
    r = TranscriptResult.from_dict(d)
    assert r.model_id == mod.MODEL_ID and r.fixture == "F01"
    assert r.peak_rss_mb is None or r.peak_rss_mb > 0

@pytest.mark.parametrize("name", SCRIPTS[:3])
def test_script_has_pep723_header(name):
    src = (REPO / "benchmarks" / "transcribers" / f"{name}.py").read_text()
    assert re.search(r"^# /// script$", src, re.M), "missing PEP 723 header"
    assert "dependencies" in src
```

Note: `result_dict` and `peak_rss_mb` cannot come from `base.py` (scripts run in isolated envs) — each script carries its own copy. That duplication is the price of env isolation; keep the copies byte-identical across scripts.

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement all three scripts**

```python
# benchmarks/transcribers/faster_whisper_.py
# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["faster-whisper>=1.0"]
# ///
"""faster-whisper large-v3, int8, CPU. Self-contained: run via `uv run --script`."""
import argparse, json, resource, time
from pathlib import Path

MODEL_ID = "faster-whisper-large-v3-int8"

def peak_rss_mb() -> float:
    # ru_maxrss is BYTES on macOS (KB on Linux); this benchmark targets macOS.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6

def result_dict(fixture, words, text, runtime_s, prompt_used) -> dict:
    return {"model_id": MODEL_ID, "fixture": fixture, "words": words, "text": text,
            "runtime_s": runtime_s, "peak_rss_mb": peak_rss_mb(), "prompt_used": prompt_used}

def run(audio: str, out: str, prompt: str, fixture: str) -> None:
    from faster_whisper import WhisperModel
    t0 = time.monotonic()
    model = WhisperModel("large-v3", device="cpu", compute_type="int8")
    segments, _info = model.transcribe(audio, word_timestamps=True,
                                       initial_prompt=prompt or None)
    words, texts = [], []
    for seg in segments:  # generator — iteration IS the transcription work
        texts.append(seg.text)
        for w in seg.words or []:
            words.append({"word": w.word.strip(), "start": round(w.start, 3),
                          "end": round(w.end, 3), "confidence": w.probability})
    d = result_dict(fixture, words, "".join(texts).strip(), time.monotonic() - t0, bool(prompt))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(d, indent=1))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("audio"); p.add_argument("out")
    p.add_argument("--prompt", default=""); p.add_argument("--fixture", default="")
    a = p.parse_args()
    run(a.audio, a.out, a.prompt, a.fixture)

if __name__ == "__main__":
    main()
```

```python
# benchmarks/transcribers/mlx_whisper_.py
# /// script
# requires-python = ">=3.10"
# dependencies = ["mlx-whisper>=0.4"]
# ///
"""mlx-whisper large-v3 (Apple-native). Requires ffmpeg on PATH."""
import argparse, json, resource, time
from pathlib import Path

MODEL_ID = "mlx-whisper-large-v3"

def peak_rss_mb() -> float:
    # ru_maxrss is BYTES on macOS (KB on Linux); this benchmark targets macOS.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6

def result_dict(fixture, words, text, runtime_s, prompt_used) -> dict:
    return {"model_id": MODEL_ID, "fixture": fixture, "words": words, "text": text,
            "runtime_s": runtime_s, "peak_rss_mb": peak_rss_mb(), "prompt_used": prompt_used}

def run(audio: str, out: str, prompt: str, fixture: str) -> None:
    import mlx_whisper
    t0 = time.monotonic()
    res = mlx_whisper.transcribe(audio, path_or_hf_repo="mlx-community/whisper-large-v3-mlx",
                                 word_timestamps=True, initial_prompt=prompt or None)
    words = []
    for seg in res.get("segments", []):
        for w in seg.get("words", []):
            words.append({"word": str(w["word"]).strip(), "start": round(float(w["start"]), 3),
                          "end": round(float(w["end"]), 3),
                          "confidence": w.get("probability")})
    d = result_dict(fixture, words, res.get("text", "").strip(), time.monotonic() - t0, bool(prompt))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(d, indent=1))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("audio"); p.add_argument("out")
    p.add_argument("--prompt", default=""); p.add_argument("--fixture", default="")
    a = p.parse_args()
    run(a.audio, a.out, a.prompt, a.fixture)

if __name__ == "__main__":
    main()
```

```python
# benchmarks/transcribers/parakeet_mlx_.py
# /// script
# requires-python = ">=3.10"
# dependencies = ["parakeet-mlx"]
# ///
"""Parakeet TDT 0.6B via parakeet-mlx (Apple-native RNN-T, native token timestamps).
No prompt support — prompt arg accepted and ignored, prompt_used stays False."""
import argparse, json, resource, time
from pathlib import Path

MODEL_ID = "parakeet-tdt-0.6b-mlx"

def peak_rss_mb() -> float:
    # ru_maxrss is BYTES on macOS (KB on Linux); this benchmark targets macOS.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6

def result_dict(fixture, words, text, runtime_s, prompt_used) -> dict:
    return {"model_id": MODEL_ID, "fixture": fixture, "words": words, "text": text,
            "runtime_s": runtime_s, "peak_rss_mb": peak_rss_mb(), "prompt_used": prompt_used}

def run(audio: str, out: str, prompt: str, fixture: str) -> None:
    from parakeet_mlx import from_pretrained
    t0 = time.monotonic()
    model = from_pretrained("mlx-community/parakeet-tdt-0.6b-v2")
    result = model.transcribe(audio)
    # AlignedResult: sentences -> tokens with .text/.start/.end (verify against the
    # installed parakeet-mlx version's README if attribute names changed).
    words = []
    for sent in result.sentences:
        for tok in sent.tokens:
            t = tok.text.strip()
            if t:
                words.append({"word": t, "start": round(float(tok.start), 3),
                              "end": round(float(tok.end), 3), "confidence": None})
    d = result_dict(fixture, words, result.text.strip(), time.monotonic() - t0, False)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(d, indent=1))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("audio"); p.add_argument("out")
    p.add_argument("--prompt", default=""); p.add_argument("--fixture", default="")
    a = p.parse_args()
    run(a.audio, a.out, a.prompt, a.fixture)

if __name__ == "__main__":
    main()
```

Note for the implementer: parakeet-mlx emits sub-word tokens; merging tokens into words is NOT required for this task — the analyzer matches normalized whole tokens, and if parakeet's tokens split call words that will show up (honestly) as missed detections. Record reality, don't paper over it. If the library exposes word-level output trivially (check its README), prefer that.

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_benchmark_scripts.py -q`.
- [ ] **Step 5: Commit** — `git commit -m "feat(bench): core local backend scripts (faster-whisper, mlx-whisper, parakeet-mlx)"`

---

### Task 4: Best-effort backend scripts (WhisperX, CrisperWhisper)

**Files:**
- Create: `benchmarks/transcribers/whisperx_.py`, `benchmarks/transcribers/crisper_whisper_.py`
- Modify: `tests/test_benchmark_scripts.py` (change both `SCRIPTS[:3]` to `SCRIPTS`)

**Interfaces:** same contract as Task 3 (`MODEL_ID`, `result_dict`, `peak_rss_mb`, CLI).

- [ ] **Step 1: Extend the parametrized tests to all 5 scripts, run, verify the 2 new ones fail.**
- [ ] **Step 2: Implement**

```python
# benchmarks/transcribers/whisperx_.py
# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["whisperx>=3.1"]
# ///
"""WhisperX: whisper + wav2vec2 forced alignment, CPU. Best-effort backend."""
import argparse, json, resource, time
from pathlib import Path

MODEL_ID = "whisperx-large-v3-int8"

def peak_rss_mb() -> float:
    # ru_maxrss is BYTES on macOS (KB on Linux); this benchmark targets macOS.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6

def result_dict(fixture, words, text, runtime_s, prompt_used) -> dict:
    return {"model_id": MODEL_ID, "fixture": fixture, "words": words, "text": text,
            "runtime_s": runtime_s, "peak_rss_mb": peak_rss_mb(), "prompt_used": prompt_used}

def run(audio: str, out: str, prompt: str, fixture: str) -> None:
    import whisperx
    t0 = time.monotonic()
    model = whisperx.load_model("large-v3", device="cpu", compute_type="int8",
                                asr_options={"initial_prompt": prompt or None})
    wav = whisperx.load_audio(audio)
    res = model.transcribe(wav, batch_size=4)
    align_model, meta = whisperx.load_align_model(language_code=res["language"], device="cpu")
    aligned = whisperx.align(res["segments"], align_model, meta, wav, "cpu")
    words = []
    for w in aligned.get("word_segments", []):
        if "start" in w and "end" in w:  # alignment can fail per-word; drop those
            words.append({"word": str(w["word"]).strip(), "start": round(float(w["start"]), 3),
                          "end": round(float(w["end"]), 3), "confidence": w.get("score")})
    text = " ".join(s.get("text", "").strip() for s in res["segments"]).strip()
    d = result_dict(fixture, words, text, time.monotonic() - t0, bool(prompt))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(d, indent=1))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("audio"); p.add_argument("out")
    p.add_argument("--prompt", default=""); p.add_argument("--fixture", default="")
    a = p.parse_args()
    run(a.audio, a.out, a.prompt, a.fixture)

if __name__ == "__main__":
    main()
```

```python
# benchmarks/transcribers/crisper_whisper_.py
# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["transformers>=4.40,<4.47", "torch>=2.2", "accelerate", "librosa", "soundfile"]
# ///
"""CrisperWhisper (nyrahealth): verbatim transcription, retuned tokenizer for pause
attribution. GATED model — requires HF license acceptance + HF_TOKEN in env.
CPU fp32 on 8 GB RAM: slow and memory-heavy. Best-effort backend."""
import argparse, json, os, resource, time
from pathlib import Path

MODEL_ID = "crisper-whisper"

def peak_rss_mb() -> float:
    # ru_maxrss is BYTES on macOS (KB on Linux); this benchmark targets macOS.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6

def result_dict(fixture, words, text, runtime_s, prompt_used) -> dict:
    return {"model_id": MODEL_ID, "fixture": fixture, "words": words, "text": text,
            "runtime_s": runtime_s, "peak_rss_mb": peak_rss_mb(), "prompt_used": prompt_used}

def run(audio: str, out: str, prompt: str, fixture: str) -> None:
    from transformers import pipeline
    t0 = time.monotonic()
    pipe = pipeline("automatic-speech-recognition", model="nyrahealth/CrisperWhisper",
                    device="cpu", return_timestamps="word", chunk_length_s=30,
                    token=os.environ.get("HF_TOKEN"))
    res = pipe(audio)
    words = []
    for ch in res.get("chunks", []):
        s, e = ch.get("timestamp", (None, None))
        if s is not None and e is not None:
            words.append({"word": str(ch["text"]).strip(), "start": round(float(s), 3),
                          "end": round(float(e), 3), "confidence": None})
    d = result_dict(fixture, words, res.get("text", "").strip(), time.monotonic() - t0, False)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(d, indent=1))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("audio"); p.add_argument("out")
    p.add_argument("--prompt", default=""); p.add_argument("--fixture", default="")
    a = p.parse_args()
    run(a.audio, a.out, a.prompt, a.fixture)

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run tests, verify all 10 script tests pass.**
- [ ] **Step 4: Commit** — `git commit -m "feat(bench): best-effort backends (WhisperX, CrisperWhisper)"`

---

### Task 5: Orchestrator (`run_benchmark.py`)

**Files:**
- Create: `benchmarks/run_benchmark.py`
- Test: `tests/test_benchmark_runner.py`

**Interfaces:**
- Consumes: Task 1 types; `hoops.config.load_config`, `hoops.fixtures.read_manifest`, `hoops.transcribe.vocab_prompt` (read-only); Task 2 `whisper_api.transcribe`; Task 3/4 scripts by path.
- Produces: CLI `uv run python benchmarks/run_benchmark.py [--models a,b] [--fixtures F01,F06] [--force] [--timeout 600]`; `BACKENDS` registry dict; `run_one(model, row, cfg, out_root, force, timeout) -> str` returning one of `"ok" | "cached" | "skip"`; writes `out/transcripts/{model}/{fixture_id}.json` and `out/skips.json`.

Behavior spec:
- Fixture rows: manifest rows where `filename` non-empty and `status == "recorded"` (same rule as `hoops.fixtures.run_all`). Audio path = `<repo>/fixtures/<filename>`; fixture key = `fixture_id` column.
- Prompt per row: `vocab_prompt(cfg.vocab(row["vocabulary"] or None))` — identical text production uses.
- whisper-1 runs in-process; script backends run `["uv", "run", "--script", str(script_path), str(audio), str(out_json), "--prompt", prompt, "--fixture", fixture_id]` with `subprocess.run(..., capture_output=True, text=True, timeout=timeout)`.
- Skip semantics: nonzero exit / timeout / exception → append `{"model", "fixture", "reason"}` (reason = last 500 chars of stderr or exception repr) to skips list, continue. **If a model's first attempted fixture fails, skip the whole model** (env-resolve failures shouldn't burn 14 timeouts); record one skip entry with fixture `"*"`.
- `.env` loaded at start (`dotenv.load_dotenv(repo_root / ".env")`) so `OPENAI_API_KEY`/`HF_TOKEN` reach subprocesses via inherited env. Missing `OPENAI_API_KEY` → whisper-1 model-level skip, not a crash.
- Cache: if out JSON exists and not `--force` → `"cached"`, no work. `--force` re-transcribes only the selected models/fixtures.
- End of run: write `out/skips.json`, print per-model counts (ok/cached/skipped) — never print env values.

- [ ] **Step 1: Write the failing tests** (use a stub PEP 723 script with no deps; no real models, no network)

```python
# tests/test_benchmark_runner.py
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
```

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement `run_benchmark.py`**

```python
# benchmarks/run_benchmark.py
"""Run selected ASR backends over all recorded fixtures; cache TranscriptResult JSONs.

Usage: uv run python benchmarks/run_benchmark.py [--models m1,m2] [--fixtures F01,F06]
                                                 [--force] [--timeout 600]
"""
import argparse, json, subprocess, sys
from pathlib import Path
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))  # script runs with benchmarks/ on sys.path, not repo root
SCRIPTS = REPO / "benchmarks" / "transcribers"
OUT = REPO / "benchmarks" / "out"

BACKENDS = {
    "whisper-1":       {"kind": "inproc"},
    "faster-whisper":  {"kind": "script", "script": SCRIPTS / "faster_whisper_.py"},
    "mlx-whisper":     {"kind": "script", "script": SCRIPTS / "mlx_whisper_.py"},
    "parakeet-mlx":    {"kind": "script", "script": SCRIPTS / "parakeet_mlx_.py"},
    "whisperx":        {"kind": "script", "script": SCRIPTS / "whisperx_.py"},
    "crisper-whisper": {"kind": "script", "script": SCRIPTS / "crisper_whisper_.py"},
}
SKIPS: list[dict] = []

def _prompt_for(row, cfg) -> str:
    from hoops.transcribe import vocab_prompt
    return vocab_prompt(cfg.vocab(row.get("vocabulary") or None))

def run_one(model: str, row: dict, cfg, out_root: Path, force: bool, timeout: int) -> str:
    spec = BACKENDS[model]
    fid = row["fixture_id"]
    out_json = out_root / "transcripts" / model / f"{fid}.json"
    if out_json.exists() and not force:
        return "cached"
    audio = cfg.repo_root / "fixtures" / row["filename"]
    prompt = _prompt_for(row, cfg)
    try:
        if spec["kind"] == "inproc":
            from benchmarks.transcribers.whisper_api import transcribe
            transcribe(audio, fid, prompt).save(out_json)
        else:
            cmd = ["uv", "run", "--script", str(spec["script"]), str(audio),
                   str(out_json), "--prompt", prompt, "--fixture", fid]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if proc.returncode != 0 or not out_json.exists():
                raise RuntimeError(proc.stderr[-500:] or f"exit {proc.returncode}")
        return "ok"
    except Exception as e:  # noqa: BLE001 — any backend failure is a logged skip
        SKIPS.append({"model": model, "fixture": fid, "reason": repr(e)[:500]})
        return "skip"

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--models", default=",".join(BACKENDS))
    p.add_argument("--fixtures", default="")
    p.add_argument("--force", action="store_true")
    p.add_argument("--timeout", type=int, default=600)
    a = p.parse_args()

    load_dotenv(REPO / ".env")
    from hoops.config import load_config
    from hoops.fixtures import read_manifest
    cfg = load_config(REPO / "config.yaml")
    rows = [r for r in read_manifest(REPO / "fixtures" / "manifest.csv")
            if r.get("filename") and r.get("status", "recorded") == "recorded"]
    if a.fixtures:
        want = set(a.fixtures.split(","))
        rows = [r for r in rows if r["fixture_id"] in want]

    for model in a.models.split(","):
        if model not in BACKENDS:
            print(f"unknown model {model!r}; available: {', '.join(BACKENDS)}")
            return 2
        counts = {"ok": 0, "cached": 0, "skip": 0}
        for i, row in enumerate(rows):
            status = run_one(model, row, cfg, OUT, a.force, a.timeout)
            counts[status] += 1
            print(f"{model} {row['fixture_id']}: {status}", flush=True)
            if status == "skip" and i == 0 and counts["ok"] == counts["cached"] == 0:
                SKIPS.append({"model": model, "fixture": "*",
                              "reason": "first fixture failed; skipping model"})
                break
        print(f"{model}: {counts}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "skips.json").write_text(json.dumps(SKIPS, indent=1))
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests, verify pass. Full suite `uv run pytest -q` still green.**
- [ ] **Step 5: Commit** — `git commit -m "feat(bench): orchestrator with cache, skip log, model/fixture selection"`

---

### Task 6: Metrics (`analyze.py`)

**Files:**
- Create: `benchmarks/analyze.py`
- Test: `tests/test_benchmark_analyze.py`

**Interfaces:**
- Consumes: Task 1 `TranscriptResult`, `normalize_token`; `hoops.config.load_config` + `hoops.fixtures.read_manifest` (input loading only — all metric functions are pure).
- Produces (pure functions, exact signatures):
  - `detect(words: list[BWord], surface_to_canonical: dict[str, str]) -> list[dict]` — each `{"canonical", "raw", "start", "end", "mid", "isolation"}`; `isolation = min(gap_before, gap_after)` vs neighboring words in the same transcript, `float("inf")` at edges.
  - `gap_stats(mids: list[float], interval: float) -> dict` — `{"mean", "median", "p95", "max", "n_gaps"}` of `abs(gap - interval)`; `{}` if < 2 mids.
  - `cluster(dets_by_model: dict[str, list[dict]], window: float = 0.75) -> list[dict]` — clusters `{"canonical", "mid", "models": {model: det}, "consensus": bool}`; consensus = strict majority of models in `dets_by_model`. Same-model duplicate within a window starts a new cluster.
  - `recommend_threshold(real: list[float], bait: list[float]) -> dict` — `{"threshold", "margin", "real_below", "bait_above"}`; threshold = midpoint of the largest gap between populations maximizing correct split; margin = `min(real) - max(bait)` (negative = overlap); `{}` if either side empty.
  - `pairwise_agreement(clusters: list[dict], models: list[str]) -> dict[str, float]` — key `"a|b"`, value = median `|mid_a - mid_b|` over clusters containing both.
  - `silence_words(words: list[BWord], silence_start: float) -> int` — words with `start >= silence_start`.
  - `main()` — loads all cached transcripts + manifest, assembles `out/metrics.json` and `out/draft_truth.csv`.
- Mode B: if a manifest row's `expected_calls` is non-empty and not `NEEDS_LABELING`, detection accuracy is computed against it (sequence match of canonicals); otherwise vs consensus. Draft truth rows: `fixture_id, draft_expected_calls (space-separated canonicals from consensus clusters in time order), disagreements (semicolon-joined "canonical@mid found by k/n")`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_benchmark_analyze.py
import pytest
from benchmarks.transcribers.base import BWord
from benchmarks.analyze import (detect, gap_stats, cluster, recommend_threshold,
                                pairwise_agreement, silence_words)

pytestmark = pytest.mark.unit
V = {"swish": "make", "splash": "make", "brick": "miss", "break": "miss"}

def W(word, start, end): return BWord(word, start, end, None)

def test_detect_isolation_and_edges():
    words = [W("uh", 0.0, 0.2), W("Swish,", 5.0, 5.4), W("nice", 9.0, 9.3)]
    d = detect(words, V)
    assert len(d) == 1 and d[0]["canonical"] == "make"
    assert d[0]["isolation"] == pytest.approx(3.6)  # min(4.8 before, 3.6 after)
    only = detect([W("brick", 1.0, 1.3)], V)
    assert only[0]["isolation"] == float("inf")

def test_gap_stats_ten_second_beep():
    mids = [5.0, 15.2, 24.9, 35.0]
    s = gap_stats(mids, 10.0)
    assert s["n_gaps"] == 3 and s["max"] == pytest.approx(0.3)
    assert gap_stats([5.0], 10.0) == {}

def test_cluster_consensus_majority():
    dets = {
        "a": [{"canonical": "make", "mid": 5.0}],
        "b": [{"canonical": "make", "mid": 5.3}],
        "c": [{"canonical": "make", "mid": 20.0}],
    }
    cl = cluster(dets)
    assert len(cl) == 2
    big = next(c for c in cl if len(c["models"]) == 2)
    assert big["consensus"] is True  # 2 of 3 = strict majority
    lone = next(c for c in cl if len(c["models"]) == 1)
    assert lone["consensus"] is False

def test_recommend_threshold_clean_split():
    r = recommend_threshold(real=[2.0, 3.0, 4.0], bait=[0.1, 0.2, 0.4])
    assert 0.4 < r["threshold"] < 2.0
    assert r["margin"] == pytest.approx(1.6)
    assert recommend_threshold([], [0.1]) == {}

def test_pairwise_agreement():
    cl = [{"canonical": "make", "mid": 5.0,
           "models": {"a": {"mid": 5.0}, "b": {"mid": 5.2}}, "consensus": True},
          {"canonical": "miss", "mid": 9.0,
           "models": {"a": {"mid": 9.0}, "b": {"mid": 9.4}}, "consensus": True}]
    agg = pairwise_agreement(cl, ["a", "b"])
    assert agg["a|b"] == pytest.approx(0.3)  # median of 0.2, 0.4

def test_silence_words():
    assert silence_words([W("the", 100.0, 100.3)], 90.0) == 1
    assert silence_words([W("the", 80.0, 80.3)], 90.0) == 0
```

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement the pure functions** (exact behavior pinned by the tests):

```python
# benchmarks/analyze.py  (core functions; main() assembles files)
"""Metrics over cached TranscriptResults. All metric functions are pure."""
from __future__ import annotations
import csv, json, statistics
from pathlib import Path
from benchmarks.transcribers.base import BWord, TranscriptResult, normalize_token

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "benchmarks" / "out"

def detect(words, surface_to_canonical):
    out = []
    for i, w in enumerate(words):
        canon = surface_to_canonical.get(normalize_token(w.word))
        if canon is None:
            continue
        gap_b = w.start - words[i - 1].end if i > 0 else float("inf")
        gap_a = words[i + 1].start - w.end if i < len(words) - 1 else float("inf")
        out.append({"canonical": canon, "raw": w.word, "start": w.start, "end": w.end,
                    "mid": (w.start + w.end) / 2, "isolation": min(gap_b, gap_a)})
    return out

def gap_stats(mids, interval):
    if len(mids) < 2:
        return {}
    errs = [abs((b - a) - interval) for a, b in zip(mids, mids[1:])]
    errs_sorted = sorted(errs)
    p95_idx = min(len(errs_sorted) - 1, int(round(0.95 * (len(errs_sorted) - 1))))
    return {"mean": statistics.mean(errs), "median": statistics.median(errs),
            "p95": errs_sorted[p95_idx], "max": max(errs), "n_gaps": len(errs)}

def cluster(dets_by_model, window=0.75):
    flat = sorted(((m, d) for m, ds in dets_by_model.items() for d in ds),
                  key=lambda x: x[1]["mid"])
    clusters = []
    for m, d in flat:
        home = None
        for c in reversed(clusters):
            if c["canonical"] == d["canonical"] and m not in c["models"] \
                    and abs(d["mid"] - c["mid"]) <= window:
                home = c
                break
            if d["mid"] - c["mid"] > window:
                break
        if home is None:
            clusters.append({"canonical": d["canonical"], "mid": d["mid"],
                             "models": {m: d}, "consensus": False})
        else:
            home["models"][m] = d
            home["mid"] = statistics.median(x["mid"] for x in home["models"].values())
    majority = len(dets_by_model) // 2 + 1
    for c in clusters:
        c["consensus"] = len(c["models"]) >= majority
    return sorted(clusters, key=lambda c: c["mid"])

def recommend_threshold(real, bait):
    if not real or not bait:
        return {}
    candidates = sorted(set(real + bait))
    best = None
    for lo, hi in zip(candidates, candidates[1:]):
        t = (lo + hi) / 2
        score = sum(1 for r in real if r >= t) + sum(1 for b in bait if b < t)
        if best is None or score > best[0] or (score == best[0] and (hi - lo) > best[1]):
            best = (score, hi - lo, t)
    return {"threshold": round(best[2], 3), "margin": round(min(real) - max(bait), 3),
            "real_below": sum(1 for r in real if r < best[2]),
            "bait_above": sum(1 for b in bait if b >= best[2])}

def pairwise_agreement(clusters, models):
    out = {}
    for i, a in enumerate(models):
        for b in models[i + 1:]:
            deltas = [abs(c["models"][a]["mid"] - c["models"][b]["mid"])
                      for c in clusters if a in c["models"] and b in c["models"]]
            if deltas:
                out[f"{a}|{b}"] = round(statistics.median(deltas), 3)
    return out

def silence_words(words, silence_start):
    return sum(1 for w in words if w.start >= silence_start)
```

`main()` (same file): load manifest via `hoops.fixtures.read_manifest` and vocabularies via `hoops.config.load_config(REPO / "config.yaml")`; build `surface_to_canonical` per fixture from `cfg.vocab(row["vocabulary"] or None).surface_to_canonical`; load every `out/transcripts/{model}/{fixture_id}.json` that exists; per fixture: run `detect` per model, `cluster` across models; per model: gap_stats on beep fixtures (rows where `timing_ground_truth` upper() in ("TRUE","YES"), interval = float(`beep_interval_s`)); isolation split for F02 (real = detections within `window` of a consensus cluster of same canonical, bait = the rest) → `recommend_threshold`; detection counts (found / consensus-real matched / extra); pairwise agreement over all fixtures' clusters combined; runtime/RTF (`runtime_s / float(row["duration_s"])` when duration present) and peak RSS from each TranscriptResult; whisper-1 cost = `0.006 * total_minutes`. Silence metric: no recorded fixture has a known silence region → emit `{"status": "pending F10"}`. Write `out/metrics.json` (structure: `{"models": {...per-model summary...}, "fixtures": {...per-fixture detail: per-model detections + clusters...}, "skips": [...from skips.json...], "isolation": {...}, "agreement": {...}}`) and `out/draft_truth.csv` with header `fixture_id,draft_expected_calls,disagreements`. Add one integration-style test in the same test file: build two fake models × one fake fixture of transcripts in a tmp out dir, call the assembly function with injected paths, assert metrics.json + draft_truth.csv appear and draft truth for the fixture equals the consensus sequence (make the assembly function take `out_root: Path` and `manifest_rows`/`vocabs` as parameters so it's testable without the real repo out dir; `main()` is a thin wrapper).

- [ ] **Step 4: Run tests, verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(bench): metrics — isolation, gap MAE, consensus, threshold, agreement, draft truth"`

---

### Task 7: HTML report (`report.py`)

**Files:**
- Create: `benchmarks/report.py`
- Test: `tests/test_benchmark_report.py`

**Interfaces:**
- Consumes: `out/metrics.json` structure from Task 6.
- Produces: `render(metrics: dict) -> str` (full HTML document string); `main()` reads `out/metrics.json`, writes `out/report.html`.

Sections, in order (all data from `metrics`; every chart is hand-built inline SVG — no JS, no external assets):
1. **Summary table** — one row per model: boundary MAE mean/median/p95/max, recommended threshold & margin (isolation), detection found/missed/extra, median cross-model delta, RTF, peak RSS, cost, coverage (n fixtures transcribed / n total; partial coverage flagged ⚠). Best numeric value per column gets `class="best"` (green background).
2. **Per-fixture timelines** — for each fixture: SVG, width 900, one row per model + a top ground-truth row when Mode B labels exist; x = seconds scaled to fixture duration; each detection a circle at `mid` (fill green for consensus/real, orange for non-consensus/bait); hover `<title>` with `raw @ start–end, isolation`.
3. **Boundary error distribution** (beep fixtures) — per model, a horizontal strip: dots per gap error, box for q1–q3, line at median.
4. **Isolation separation** (F02) — per model, 1-D strip: real green dots, bait orange dots, vertical line at recommended threshold, margin annotated.
5. **Agreement heatmap** — model × model table, cell background `rgba(200,0,0,alpha)` scaled by median delta, value in cell.
6. **Per-fixture detail tables** — `<details><summary>` per fixture: every detection (model, raw, canonical, start, end, isolation, in-consensus).
7. **Draft ground truth** — `<pre>` block of draft_truth.csv content, disagreements highlighted with a ⚠ line above.
8. Footer: skips list with reasons, "pending F10" note for the silence metric, generation timestamp.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_benchmark_report.py
import pytest
from benchmarks.report import render

pytestmark = pytest.mark.unit

METRICS = {
    "models": {"whisper-1": {"boundary": {"mean": 0.2, "median": 0.1, "p95": 0.4, "max": 0.5,
                                          "n_gaps": 9},
                             "rtf": 0.3, "peak_rss_mb": 120.0, "cost_usd": 0.05,
                             "coverage": "14/14",
                             "detection": {"found": 40, "missed": 1, "extra": 2}}},
    "fixtures": {"F01": {"duration_s": 88.9, "models": {"whisper-1": {"detections": [
        {"canonical": "make", "raw": "Swish", "start": 5.0, "end": 5.4, "mid": 5.2,
         "isolation": 3.0, "consensus": True}]}}, "clusters": [], "truth": None}},
    "isolation": {"whisper-1": {"threshold": 1.2, "margin": 0.8, "real": [2.0], "bait": [0.2]}},
    "agreement": {"whisper-1|mlx-whisper": 0.05},
    "draft_truth": [{"fixture_id": "F01", "draft_expected_calls": "make miss",
                     "disagreements": ""}],
    "skips": [{"model": "crisper-whisper", "fixture": "*", "reason": "gated model"}],
    "silence": {"status": "pending F10"},
}

def test_render_self_contained_html():
    html = render(METRICS)
    assert html.startswith("<!doctype html>")
    for marker in ["Summary", "F01", "Draft ground truth", "pending F10", "crisper-whisper"]:
        assert marker in html
    low = html.lower()
    assert "<svg" in low and "cdn" not in low
    assert 'src="http' not in low and 'href="http' not in low  # no external assets
```

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement `render()` + `main()`.** Structure: small helpers `_svg_timeline(fixture, data)`, `_svg_strip(values_real, values_bait, threshold)`, `_svg_gaps(errors)`, `_heat_table(agreement, models)`, `_summary_table(models)`; `render()` concatenates sections with a `<style>` block (system font stack, `.best{background:#d7f5d7}`, muted borders). Every helper returns a string; guard every section against missing/empty data (a model with no beep-fixture transcripts simply has blank boundary cells). `main()`: `metrics = json.loads((OUT / "metrics.json").read_text()); (OUT / "report.html").write_text(render(metrics))`.
- [ ] **Step 4: Run tests, verify pass; run full suite.**
- [ ] **Step 5: Commit** — `git commit -m "feat(bench): self-contained inline-SVG HTML report"`

---

### Task 8: README, gitignore, wiring check

**Files:**
- Create: `benchmarks/README.md`
- Modify: `.gitignore`

**Interfaces:** none new.

- [ ] **Step 1: `.gitignore`** — append:

```gitignore
benchmarks/out/*
!benchmarks/out/transcripts/
```

(Transcript caches are committed — small text, they make analysis reproducible; metrics/report/skips/draft truth are regenerated.)

- [ ] **Step 2: `benchmarks/README.md`** — document: purpose (timestamp quality, not WER); prerequisites (`ffmpeg` on PATH, `OPENAI_API_KEY` in `.env`, optional `HF_TOKEN` + accepted license for CrisperWhisper); the three commands (`uv run python benchmarks/run_benchmark.py`, `uv run python benchmarks/analyze.py`, `uv run python benchmarks/report.py`); flags (`--models`, `--fixtures`, `--force`, `--timeout`); how to add a backend (copy a PEP 723 script, keep `MODEL_ID`/`result_dict`/`peak_rss_mb` contract, register in `BACKENDS`, extend the script test list — and the project rule: ask the owner before adding backends); skip semantics and where to look (`out/skips.json`); Mode A vs Mode B and the draft-truth → manifest labeling loop.
- [ ] **Step 3: Wiring check (free, no API):** `uv run python benchmarks/run_benchmark.py --models faster-whisper --fixtures F08 --timeout 900` (F08 is the shortest fixture, 33.6 s; first run downloads the CT2 large-v3 model ~1.5 GB). Then `uv run python benchmarks/analyze.py` and `uv run python benchmarks/report.py`; confirm `out/report.html` opens and shows one model, one fixture. If the download is unacceptable in the task context, substitute `--models whisper-1` (needs `OPENAI_API_KEY`, costs <1¢) — either proves the plumbing.
- [ ] **Step 4: Full test suite green; commit** — `git commit -m "docs(bench): README + gitignore for benchmark outputs"`

---

### Task 9: The real run + decision doc (main session, not a subagent)

Paid API + multi-GB downloads + long CPU runtimes — the session orchestrator runs this interactively, watching `skips.json`.

- [ ] **Step 1:** `uv run python benchmarks/run_benchmark.py --models whisper-1,mlx-whisper` (fast pair first — API + Apple-native).
- [ ] **Step 2:** `uv run python benchmarks/run_benchmark.py --models faster-whisper,parakeet-mlx` then `--models whisperx,crisper-whisper` (best-effort; expect possible skips — gated HF model, dep resolution).
- [ ] **Step 3:** `analyze.py` + `report.py`; commit `benchmarks/out/transcripts/`; owner opens `out/report.html`.
- [ ] **Step 4:** Write `docs/decisions/001-transcriber-selection.md`: chosen model, headline boundary numbers per model, recommended isolation threshold (+ margin caveat from F02-only data), cost/speed table, skipped backends and why, what to revisit (F03/F10 recording, Mode B rerun after the owner corrects `draft_truth.csv` into the manifest, "mess" alias decision informed by cross-model evidence on R02).
- [ ] **Step 5:** Commit and present the recommendation + report to the owner.

---

## Verification (whole plan)

- `uv run pytest -q` — full suite green (existing 102 + new benchmark tests), no paid marks in the new tests.
- `git diff sessions/` empty; nothing under `src/hoops/` modified (`git status src/hoops` clean).
- `benchmarks/out/report.html` opens locally, renders all sections, contains no external references.
- `out/draft_truth.csv` rows are paste-able into `fixtures/manifest.csv` `expected_calls`.
- `docs/decisions/001-transcriber-selection.md` names one model with numbers behind it.
