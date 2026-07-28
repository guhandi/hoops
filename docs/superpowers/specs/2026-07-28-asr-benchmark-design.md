# ASR word-level timestamp benchmark (transcriber-selection spike)

**Date:** 2026-07-28 · **Status:** approved design, pre-implementation

## Context

The hoops pipeline is live with whisper-1. Before refining transcription, the owner wants a standalone benchmark that compares ASR models on **word-level timestamp boundary accuracy and isolation separability** (not WER) over the golden fixtures, producing one self-contained HTML report plus a written model recommendation. Timestamp boundaries matter more than spelling: an alias table fixes "brik", nothing fixes a 300 ms boundary error, because the parser's isolation gate is `isolation = min(gap_before, gap_after)`.

Runs on **this Apple M2, 8 GB RAM Mac** (the original brief's GTX 1660 Ti constraint came from another context — dropped). Owner rulings (2026-07-28): simplest environment; skip any backend that's too complicated; backend set = "Core 4 + 2 attempts".

Deltas vs the original brief, from repo reality:

- The pipeline already exists — the spike stays standalone in `benchmarks/`, changes nothing under `src/hoops/`. The `TranscriptResult` JSON contract is designed for later pipeline adoption, but no pipeline refactor now.
- **F03, F09, F10 are NOT_RECORDED**: isolation separability uses F02 only; the hallucination-on-silence metric is implemented but reports "pending F10". Two beep fixtures serve the headline boundary metric: F06 and F07b (both `beep_interval_s = 10`).
- `expected_calls` is unlabeled everywhere → Mode A (cross-model consensus) is the operative mode today; Mode B activates automatically when labels land. `traps_planted` is empty — real-vs-bait in F02 comes from consensus plus owner correction of the draft truth.
- Fixture set = **all recorded rows in `fixtures/manifest.csv`** (10 top-level + 4 dev), per-fixture vocabulary from the `vocabulary` column.
- "Peak VRAM" → **peak RSS** (`resource.getrusage` inside each backend process; `ru_maxrss` is bytes on macOS).

## Backends (owner-approved)

Certain four: **whisper-1 API** (production parity — reuses `hoops.transcribe.WhisperApiTranscriber` with the production `vocab_prompt`), **faster-whisper large-v3 int8 CPU**, **mlx-whisper** (Apple-native addition), **parakeet-mlx** (TDT 0.6B, substitutes NeMo Parakeet). Best-effort, skip-with-logged-reason: **WhisperX** (CPU int8), **CrisperWhisper** (gated HF model, heavy on 8 GB; slowest on CPU). Whisper-family local backends receive the same bias text via `initial_prompt` for parity; parakeet takes no prompt (recorded per backend as `prompt_used`).

## Architecture: isolated backend subprocesses, JSON contract

WhisperX and CrisperWhisper pin incompatible transformers/torch versions, so **each local backend is a standalone PEP 723 inline-metadata script** run via `uv run --script benchmarks/transcribers/<backend>.py <audio> <out.json> [--prompt ...]`. uv resolves an isolated ephemeral env per script — one backend's pins cannot break another, and a failed resolve/import/OOM/timeout becomes a logged skip. The cached JSON file is the inter-process interface. whisper-1 runs in-process (no heavy deps).

```
benchmarks/
  transcribers/
    base.py             # TranscriptResult dataclass + JSON (de)serialization + token normalization
    whisper_api.py      # in-process adapter around hoops WhisperApiTranscriber
    faster_whisper_.py  # PEP 723 script
    mlx_whisper_.py     # PEP 723 script
    parakeet_mlx_.py    # PEP 723 script
    whisperx_.py        # PEP 723 script (best-effort)
    crisper_whisper_.py # PEP 723 script (best-effort)
  run_benchmark.py      # models × fixtures, sequential; cache out/transcripts/{model}/{fixture_id}.json; --force, --models; skips → out/skips.json
  analyze.py            # pure-stdlib metrics → out/metrics.json + out/draft_truth.csv
  report.py             # metrics.json → out/report.html (inline CSS + inline SVG, no CDN)
  README.md
```

`out/transcripts/` is committed (small text, makes analysis reproducible); `out/metrics.json`, `out/report.html`, `out/skips.json`, `out/draft_truth.csv` are gitignored (regenerated).

TranscriptResult JSON: `{model_id, fixture, words: [{word, start, end, confidence|null}], text, runtime_s, peak_rss_mb, prompt_used}`.

## Metrics (analyze.py, pure stdlib)

1. **Boundary accuracy (headline)** — F06 + F07b: `|gap between consecutive detected calls − beep_interval_s|`; mean/median/p95/max per model. Missed/extra detections corrupt gaps and honestly show up in p95/max.
2. **Isolation separability** — F02: for every token whose normalized form is in the fixture's vocabulary surface set, `isolation = min(gap_before, gap_after)` against neighboring words in the same transcript; recommend the threshold at the midpoint of the largest gap between the real and bait populations, report the separation margin. Mode A defines real = member of a majority consensus cluster, bait = vocab token in no consensus cluster.
3. **Detection** — per fixture × model: vocab tokens found vs consensus (Mode A) or `expected_calls` (Mode B); missed and extra flagged.
4. **Cross-model agreement** — tokens all models detect: pairwise `|t_A − t_B|`, median per model pair → heatmap.
5. **Hallucination on silence** — implemented; reports "pending F10" until F10 is recorded.
6. **Cost/speed** — runtime_s, real-time factor, peak RSS, whisper-1 API cost ($0.006/min, ≈ $0.09 total).

Consensus (Mode A): cluster detections across models by canonical word within a ±0.75 s window; consensus = detected by a strict majority of non-skipped models. Draft truth → `out/draft_truth.csv` in the manifest's `expected_calls` format, disagreements flagged, copy-pasteable.

## Report

Single self-contained `out/report.html`: summary table (best per column highlighted) → per-fixture timeline strips (one row per model, marks at token timestamps; ground-truth top row when present) → boundary-error distributions (F06/F07b) → isolation strip plots with the recommended-threshold line (F02) → agreement heatmap → collapsed per-fixture detail tables → draft ground truth block.

## Error handling

Backend resolve/install/import/run failure or >10 min per file → logged skip in `out/skips.json`, run continues. Missing `OPENAI_API_KEY` → whisper-1 skipped, not fatal. analyze/report run with whatever transcripts exist; partial coverage is flagged in the summary table.

## Testing & verification

- Unit tests (`tests/test_benchmark_*.py`, no paid marks): TranscriptResult round-trip; isolation math; gap-MAE math; consensus clustering incl. disagreements; draft-truth format; report renders non-empty HTML from synthetic metrics.
- `uv run pytest` stays green; nothing under `src/hoops/` changes.
- End-to-end: run benchmark → analyze → report; owner opens `report.html`.
- Final deliverable after the real run: `docs/decisions/001-transcriber-selection.md` — chosen model, the numbers, recommended isolation threshold, what to revisit (F03/F10 gaps, Mode B rerun after labeling).

## Out of scope

Pipeline refactor to the new interface; adding backends beyond the approved six (ask first); labeling `expected_calls` (owner; draft truth accelerates it); recording F03/F09/F10.
