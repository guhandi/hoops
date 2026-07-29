# ASR Benchmark — Timestamp Quality Evaluation

This benchmark measures **timestamp quality** of ASR backends across recorded hoops fixtures and real sessions. It is *not* a WER (word-error-rate) benchmark.

**Design goal:** Answer "Which transcriber is best for detecting shot call-outs in real time?"

- Detection depends on boundary timing (where the word starts/ends) and isolation (gaps before/after).
- The benchmark captures call-word timing under different conditions (quiet, distance, music, speech masking, articulation stress) and compares detections across backends.
- It generates reproducible metrics and an interactive HTML report.

---

## Prerequisites

**Required:**
- `ffmpeg` on PATH (used by analyze.py for audio probing)
- `.env` file in repo root with `OPENAI_API_KEY=sk-...` (for `whisper-1` backend)
- `uv` command (see repo README for Python version / uv setup)

**Optional (for specific backends):**
- `HF_TOKEN` in `.env` if using CrisperWhisper backend and you have not yet accepted its license at https://huggingface.co/Vaibhavs10/Crisper-Whisper
  - First run will prompt you to accept the license in the HF CLI if the token is missing; subsequent runs use the cached model.

---

## Three-Step Workflow

### Step 1: Transcribe (`run_benchmark.py`)

Run selected backends over selected fixtures and cache TranscriptResult JSONs.

```bash
uv run python benchmarks/run_benchmark.py [OPTIONS]
```

**Options:**
- `--models MODEL1,MODEL2,...` — Comma-separated model names (default: all available)
  - Available: `whisper-1`, `faster-whisper`, `mlx-whisper`, `parakeet-mlx`, `whisperx`, `crisper-whisper`
- `--fixtures F01,F02,...` — Comma-separated fixture IDs (default: all recorded fixtures from manifest)
- `--force` — Re-transcribe even if a cached transcript exists
- `--timeout 600` — Timeout per fixture in seconds (default: 600)

**Output:**
- `benchmarks/out/transcripts/{model}/{fixture_id}.json` — Cached TranscriptResult for each model/fixture pair
- `benchmarks/out/skips.json` — Log of any failures (model, fixture, reason) for debugging

**Example: Quick test**
```bash
uv run python benchmarks/run_benchmark.py --models faster-whisper --fixtures F08 --timeout 900
```
F08 is the shortest fixture (33.6s). On first run, this downloads the CT2 large-v3 model (~1.5 GB).

---

### Step 2: Analyze (`analyze.py`)

Load cached transcripts, compute detection metrics, and write ground-truth for labeling.

```bash
uv run python benchmarks/analyze.py
```

**Output:**
- `benchmarks/out/metrics.json` — Per-model aggregates (boundary error stats, resource usage, coverage) and per-fixture details (detected calls, clusters, isolation thresholds)
- `benchmarks/out/draft_truth.csv` — Consensus detections across models; used to label `expected_calls` in the manifest

---

### Step 3: Report (`report.py`)

Generate an interactive HTML report.

```bash
uv run python benchmarks/report.py
```

**Output:**
- `benchmarks/out/report.html` — Opens in browser; shows per-model summary, per-fixture timelines with detected calls overlaid

---

## Understanding Skips

Some backends may fail on certain fixtures (missing library, OOM, timeout, API error, etc.).

If a backend fails on *the first fixture* and has no cached results, it is assumed broken for that model and all remaining fixtures are skipped. Otherwise, individual failures are logged in `out/skips.json` and that fixture is regenerated if you re-run with `--force` or delete the cached transcript.

Always inspect `out/skips.json` before analyzing if you see unexpected model coverage gaps.

---

## How to Add a Backend

1. **Create a PEP 723 script** at `benchmarks/transcribers/your_model_.py`
   - Must have a `# /// script` block declaring dependencies (see `faster_whisper_.py` as template)
   - Must define:
     - `MODEL_ID = "..."` — Unique identifier for this backend
     - `result_dict(fixture, words, text, runtime_s, prompt_used) -> dict` — Format the output
     - `peak_rss_mb() -> float` — Return peak resident memory in MB
     - `main()` — Parse `audio`, `out`, `--prompt`, `--fixture` arguments and call `run()`
   - Must write `out` as JSON: `{"model_id": MODEL_ID, "fixture": fixture, "words": [...], "text": "...", "runtime_s": ..., "peak_rss_mb": ..., "prompt_used": bool}`
   - See `tests/test_benchmark_transcriber*.py` for the full contract

2. **Register in `run_benchmark.py`**
   - Add entry to `BACKENDS` dict with `{"kind": "script", "script": SCRIPTS / "your_model_.py"}`

3. **Add tests**
   - Create `tests/test_benchmark_transcriber_your_model.py` testing load, run, and output validation
   - Add to the test list in CI (see `vercel.json` or project's workflow config)

4. **Ask the owner before merging**
   - Backend additions are a product decision (cost, licensing, maintenance burden)

---

## Mode A vs Mode B: Accuracy Evaluation

The benchmark supports two accuracy evaluation modes:

**Mode A: Expected-call labeling** (Ground truth)
- Owner labels `expected_calls` in `fixtures/manifest.csv` (e.g., "swish brick make brick make")
- `analyze.py` computes detections vs expected and writes match counts to metrics
- Report shows "Matched*" (recall) and "Extra" (false positives)

**Mode B: Consensus (draft truth)**
- No manual labels yet; `analyze.py` computes consensus from majority-agreement among models
- `out/draft_truth.csv` captures consensus sequences for offline review
- Owner uses draft_truth to label `expected_calls` in the manifest
- Re-run analyze/report with Mode A above

**Workflow:**
1. Run benchmark and analyze (generates draft_truth.csv)
2. Review draft_truth.csv against audio
3. Label `expected_calls` in manifest
4. Re-run analyze (now Mode A)
5. Inspect accuracy metrics in report

---

## Fixture Inventory

See `fixtures/manifest.csv` columns:
- `fixture_id`, `category` (fixture/real_session/dev), `status` (recorded/NOT_RECORDED)
- `vocabulary` — vocabulary name (swish_brick/make_miss); controls call-word detection
- `timing_ground_truth` — TRUE if fixture has 10-second beep for timing validation
- `beep_interval_s` — Beep interval if timed; used to compute boundary MAE
- `use_for` — GATE (must pass isolation/timing), tuning, or regression
- `traps_planted` — If filled, list the bait sentences for isolation validation

---

## Output Files

All outputs are regenerated on each run. Only **transcripts** are committed to git.

- `benchmarks/out/transcripts/{model}/*.json` — Cached TranscriptResults (committed)
- `benchmarks/out/metrics.json` — Metrics (regenerated)
- `benchmarks/out/skips.json` — Failures (regenerated)
- `benchmarks/out/draft_truth.csv` — Draft truth for labeling (regenerated)
- `benchmarks/out/report.html` — HTML report (regenerated)

---

## Troubleshooting

**"First fixture failed; skipping model"** in `out/skips.json`
- The backend is broken or misconfigured. Check the full error reason in the skip entry and debug the transcriber script.

**No metrics.json or report.html after running analyze/report**
- Check `out/transcripts/` is not empty. Re-run `run_benchmark.py` if needed.

**Model not showing in report despite successful transcription**
- Ensure fixtures have `status=recorded` in the manifest. The benchmark skips NOT_RECORDED fixtures.

---

## Development Notes

- Tests: `uv run pytest tests/test_benchmark*.py` (runs full benchmark suite)
- All core metric logic is pure (no I/O in parse.py / stats.py / analyze.py)
- Backends are isolated; a crash in one does not stop others
- Transcripts are JSON so they're diffs-friendly for code review and CI/CD
