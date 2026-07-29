# Decision 001: Transcriber selection — stay on whisper-1

**Date:** 2026-07-29 · **Status:** accepted · **Input:** `benchmarks/` run over 14 recorded fixtures (see `benchmarks/out/report.html`, regenerate with `uv run python -m benchmarks.analyze && uv run python -m benchmarks.report`)

## Decision

**Keep whisper-1 as the production transcriber.** No local model beat it where it matters for this pipeline: no hallucination loops, full coverage of quiet real-session audio, word timestamps within ~0.3 s of the local-model consensus, negligible cost, fastest wall-clock.

## Why (headline numbers)

| Model | Coverage | Match rate¹ | Median Δ vs others² | RTF (median) | Peak RSS | Cost (14 fixtures) |
|---|---|---|---|---|---|---|
| **whisper-1** | 14/14 | 32 % | 0.17–0.30 s | **0.04** | n/a (API) | $0.11 |
| mlx-whisper | 14/14 | 29 % | 0.02–0.56 s | 1.59 | 2.3 GB | — |
| parakeet-mlx | 14/14 | 42 % | 0.14–0.56 s | 0.05 | 0.9 GB | — |
| whisperx | 14/14³ | 44 % | 0.14–0.49 s | 0.71 | 2.7 GB | — |
| faster-whisper | 1/14 (partial) | — | 0.02 s vs mlx | 11.3 | 1.5 GB | — |

¹ detections landing in a cross-model consensus cluster / total detections. Low absolute values are expected: dev/real fixtures contain conversational speech and unlabeled calls; use relatively.
² median |Δ mid-time| on shared consensus calls, per model pair. faster-whisper ↔ mlx-whisper agree to 0.02 s; whisper-1 sits ~0.3 s from the local family — well inside the parser's isolation windows.
³ whisperx *ran* on all fixtures but its forced alignment silently drops words: 0 detections on R02, D02, and F02 (27 total vs 122–184 for peers). Disqualifying for a pipeline that must not miss calls.

**The disqualifiers, per model:**

- **mlx-whisper** hallucination-looped on D02: its transcript ends in 15+ phantom `make.` repeats that whisper-1 (same audio, same bias vocabulary) does not produce. Phantom shots are this project's hard failure mode (PRD §11.2); this alone rules it out.
- **parakeet-mlx** (no bias prompt, genuinely independent) collapses on quiet out-of-breath audio: on R02 it heard 3 words ("This make this") where whisper-1 heard 10 calls. Great cross-check, not a primary.
- **whisperx**: word-dropping (above).
- **faster-whisper**: RTF ≈ 11 on this CPU — a 90 s session takes ~17 min. Impractical for the morning loop; full run deferred (see Revisit).
- **crisper-whisper**: skipped — HF `transformers` pipeline can't decode `.m4a` (`ffmpeg_read` failure, logged in `benchmarks/out/skips.json`). Would need WAV conversion to evaluate.

## Isolation threshold recommendation

**None — do not change the production gate based on this data.** The F02 trap fixture produced a **negative margin (−0.8 s)**: whisper-1's consensus-real calls show isolation 0.0–0.5 s (whisper-1 tends to emit near-contiguous word timings) while the surviving bait word sits at 0.8 s. Isolation alone does not separate real from bait on F02, pooled or per-model. Caveats: F02-only, one bait survivor, consensus-derived "real" labels (F02 is not owner-labeled yet). The production parser's combined gates (vocabulary + isolation + invariants) remain the design; revisit after F02 is labeled and F03 is recorded.

## Timing note (beep fixtures)

F06/F07b gap stats (mean |gap − beep interval| of 2.6–4.8 s) are consistent across all models — they measure the shooter's cadence drift from the metronome, not model timing error. Model-to-model timing spread on the same calls is the meaningful number (≤ 0.3 s median for whisper-1). Wiring `beep_interval_s` into `score.py`'s `gap_mae` (pending item 3) should account for this.

## The "mess" alias question (pending item 2) — resolved: no alias needed

Under the widened six-word bias prompt, whisper-1 heard R02 as `miss ×5, make ×5` — zero `mess`. No other model produced `mess` either. The old mess×6 cache predated the widened prompt; this run *is* the refresh. Recommend: do not add `mess` to the miss list.

## Revisit

1. **faster-whisper full run** (owner deferred it mid-run): `uv run python benchmarks/run_benchmark.py --models faster-whisper --timeout 3600` overnight; cache resumes automatically.
2. **crisper-whisper**: convert fixtures to WAV (or patch the script to pre-decode) if its verbatim mode is still of interest.
3. **Owner labeling**: `benchmarks/out/draft_truth.csv` rows are paste-able into `fixtures/manifest.csv` `expected_calls`; after labeling, rerun analyze for Mode A accuracy (current Mode B strict full-sequence match reads near-zero for everyone on long real fixtures — one disagreement anywhere zeroes the fixture; treat per-model match rates and the report timelines as the usable signal until labels land).
4. **F03/F09/F10** still `NOT_RECORDED`; F02/F03 are the isolation-gate stress tests.
5. **parakeet-mlx as shadow cross-check**: cheap (RTF 0.05), prompt-independent — worth running alongside shadow-period sessions to flag whisper-family shared hallucinations.
