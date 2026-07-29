# ASR Benchmark — Timestamp Quality Evaluation

This benchmark measures **timestamp quality** of ASR backends across recorded hoops fixtures and real sessions. It is *not* a WER (word-error-rate) benchmark.

**Design goal:** Answer "Which transcriber is best for detecting shot call-outs in real time?"

- Detection depends on boundary timing (where the word starts/ends) and isolation (gaps before/after).
- The benchmark captures call-word timing under different conditions (quiet, distance, music, speech masking, articulation stress) and compares detections across backends.
- It generates reproducible metrics and an interactive HTML report.

---

## Prerequisites

**Required:**
- `.env` file in repo root with `OPENAI_API_KEY=sk-...` (for `whisper-1` backend)
- `uv` command (see repo README for Python version / uv setup)

**Required for local backends (e.g., mlx-whisper):**
- `ffmpeg` on PATH (used by local transcriber scripts for audio decoding)

**Optional (for specific backends):**
- The `crisper-whisper` backend loads the gated model at https://huggingface.co/nyrahealth/CrisperWhisper. Before running it: accept the license on that model page while logged into your HF account, and set `HF_TOKEN` in `.env` to a token for that account.
  - The backend runs as a non-interactive subprocess — it cannot prompt you to accept the license. If the license hasn't been accepted or `HF_TOKEN` is missing/invalid, it just fails and gets recorded as a skip in `benchmarks/out/skips.json`.

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

If a backend fails on *the first fixture* and has no cached results, it is assumed broken for that model (env-resolve/import failure) and all remaining fixtures are skipped — *unless* that first-fixture failure was a timeout. A timeout proves the environment resolved and the model actually started running (it's just slow relative to `--timeout`), so it does not trigger the model-wide abort; the run continues to the remaining fixtures for that model. Timeout skips are logged with reason `"timeout after Ns"` so they're distinguishable from other failures in `skips.json`. Otherwise, individual failures are logged in `benchmarks/out/skips.json` and that fixture is regenerated if you re-run with `--force` or delete the cached transcript.

Running the benchmark in multiple staged invocations (e.g. one per model, or one per fixture subset) is safe: each run merges its skip entries into the existing `skips.json` rather than overwriting it, replacing only the entries for the (model, fixture) pairs it re-reports.

Always inspect `benchmarks/out/skips.json` before analyzing if you see unexpected model coverage gaps.

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
   - See `tests/test_benchmark_base.py` and the `result_dict` contract in existing backends for validation

2. **Register in `run_benchmark.py`**
   - Add entry to `BACKENDS` dict with `{"kind": "script", "script": SCRIPTS / "your_model_.py"}`

3. **Add to test suite**
   - Append your backend's module name (e.g., `"your_model_"`) to the `SCRIPTS` list in `tests/test_benchmark_scripts.py`
   - Parametrized tests will automatically validate module load and result schema

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
- `benchmarks/out/draft_truth.csv` captures consensus sequences for offline review
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

**"First fixture failed; skipping model"** in `benchmarks/out/skips.json`
- The backend is broken or misconfigured. Check the full error reason in the skip entry and debug the transcriber script.

**No metrics.json or report.html after running analyze/report**
- Check `benchmarks/out/transcripts/` is not empty. Re-run `run_benchmark.py` if needed.

**Model not showing in report despite successful transcription**
- Ensure fixtures have `status=recorded` in the manifest. The benchmark skips NOT_RECORDED fixtures.

---

## Development Notes

- Tests: `uv run pytest tests/test_benchmark*.py` (runs full benchmark suite)
- Core hoops logic is pure (no I/O in `src/hoops/parse.py`, `src/hoops/stats.py`, `src/hoops/invariants.py`); benchmark metrics helpers in `analyze.py` are pure, but its `main()` and `assemble_metrics()` do I/O
- Backends are isolated; a crash in one does not stop others
- Transcripts are JSON so they're diffs-friendly for code review and CI/CD
