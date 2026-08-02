# Dual-branch capture — independent acoustics + fusion — design

**Date:** 2026-08-01 · **Status:** approved (brainstorm 2026-08-01) · **Owner:** Guhan
**Source brief:** `from_claude/claude-code-brief-dual-capture.md` (+ prototype `from_claude/impact_detect.py`, confirmed working on fixtures)

## Goal

Turn one session audio file into a shot table carrying **two independent measurements per shot**: what Guhan said happened (subjective, authoritative) and what the audio says happened (objective). The long-term payoff: voice calls **label** acoustic events, so that after enough sessions a classifier can predict outcome from audio alone. That only works if the labels are uncontaminated — hence the core rule below.

## The core architectural rule

**The two branches are computed completely independently and never inform each other.** Impact detection must not use voice-call times to decide where to look; voice parsing must not use impact times. They meet exactly once, at fusion. Any accuracy bought by coupling is fake — it contaminates the training labels with the thing they supervise.

Enforced structurally: `acoustics.py` imports nothing from `parse`/`transcribe`; `fusion.py` imports neither branch module (it consumes their *outputs* as plain data). A unit test reads the module sources and fails on forbidden imports.

This rule is why the existing `src/hoops/impacts.py` (which searches only `[t_word − 2.0s, t_word − 0.15s]` — voice-seeded by design) cannot be the data branch. **Decision: replace it** (see §5).

## Decisions made in brainstorming

- **Replace `impacts.py`**, don't run both: fusion becomes the single source of impact truth for the report; the voice-seeded detector retires in this pass.
- **Cloud after local tuning**: build as optional pipeline stages that run identically locally and on Modal; sweep thresholds and pass fixture gates locally first; add librosa/numpy to the Modal image and deploy in the same pass once gates pass.
- **Scope = layers 1–3 of the brief**: acoustics branch, fusion + report wiring, separability analysis. The provisional shot-type classifier (`classify.py`) is **deferred** until separability shows the features carry signal. Feature extraction still stores everything a future classifier needs.
- **Three-artifact layering**: `shots.csv` stays pure branch A (byte-identical whether or not sound ran — the "works without sound" guarantee, structurally). New sidecars `acoustics.json` (branch B raw) and `fusion.json` (the joined schema, including `call_missing` events, which have no `shots.csv` row to live in).

## Branch A — voice (exists, unchanged)

`transcribe.py` → `parse.py`, exactly as shipped: word timestamps, vocabulary filter, isolation gate, scratch-that corrections, `note:` capture. **No changes this round.** Its `t` is when Guhan spoke, not when the ball landed — the 1–2 s lag is the whole reason branch B exists.

## Branch B — acoustics (`src/hoops/acoustics.py`, new)

Ported from the prototype — do not redesign the approach, do tune it:

1. Load mono 22.05 kHz (`librosa.load`; m4a decode rides on the ffmpeg already present locally and in the cloud image).
2. **HPSS** (`librosa.decompose.hpss`, `margin=(1.0, 4.0)`) — harmonic (voice) vs. percussive (impacts) by spectrogram structure; single mic is fine, ICA is not applicable.
3. Onset strength on the percussive residual only, normalized to its max.
4. Peak-pick with enforced minimum spacing.
5. Cluster impacts into **shot events** (~2.0 s gap): one shot = one burst (rim, board, floor).
6. Per impact: `centroid_hz`, `bandwidth_hz`, `peak_rms`, `decay_ratio`, `time`.
7. Also emit a downsampled normalized **percussive onset envelope** (~15 Hz) — this replaces the raw loudness envelope as the report's waveform strip (voice energy filtered out, so impact markers sit on clean bumps).

All tunables live in `config.yaml` under `acoustics:` — `sr`, `hop`, `n_fft`, `hpss_margin`, `onset_delta`, `min_spacing`, `cluster_gap`, `envelope_hz`. No magic numbers in code. Deterministic; no LLM anywhere in either branch or fusion.

librosa/numpy are imported lazily inside a try/except: import failure (or any decode/processing failure) → stage skipped with a log line, sidecar absent, everything downstream degrades to voice-only. The email is never blocked.

### Empirical baseline (from the brief's prototype run — sanity gate for the port)

| Fixture | Shot events | Median gap | Impacts/event |
|---|---|---|---|
| F01 normal | 17 | 5.0 s | 1–3 |
| F04 quiet | 14 | 8.9 s | 1–3 |
| F06 beep | 16 | 8.0 s | 1–4 |
| F02 chatty | 8 | 5.5 s | 1–4 |

Centroids are bimodal: most events 2500–4000 Hz (rim, bright/metallic), a few 470–870 Hz (board, low/thuddy). A large deviation from this table means the port is wrong.

**F05 (background music) is a known problem case**: music is percussive too and HPSS won't remove it. Run F05 separately and *document* what happens in the decision doc — never tune global thresholds to accommodate it.

## Fusion (`src/hoops/fusion.py`, new)

Pure stdlib logic over two lists — parsed rows (branch A) and shot events (branch B). No audio, no branch imports.

**Pairing rule:** each voice call pairs with the nearest **preceding** cluster whose latency `t_call − t_cluster_start` falls in `[pair_min_s, pair_max_s]` (config `fusion:` block, defaults 0.5 / 4.0). Preceding, never nearest-absolute — shoot first, call second.

| Case | Handling |
|---|---|
| Call with matching cluster | `paired`; `call_latency_s = t_call − t_start` |
| Call, no cluster in window | `impact_missing` — shot kept, voice authoritative; this is the 🤥 flag |
| Cluster, no call | `call_missing` — kept as its own fusion row, flagged (F09's real case) |
| Two calls competing for one cluster | `ambiguous` — both flagged |
| Cluster before the first call | warm-up/dropped ball — flagged, not discarded |

**Voice is authoritative for make/miss in v1.** The acoustic branch records what it saw and never overrides; disagreement is logged data, not an error.

Session-level fusion output: `pairing_rate`, median `call_latency_s`, and the latency distribution. Stable median latency across sessions validates the approach; wild variance means the window needs work.

## Artifacts per session

- `shots.csv` + parse artifacts — branch A, unchanged, byte-identical with or without sound.
- **`acoustics.json`** — `{envelope: [...], envelope_hz, events: [{t_start, t_end, n_impacts, impact_times, mean_centroid_hz, max_peak_rms, impacts: [per-impact feature dicts]}]}`. Full per-impact features always stored — aggregates alone lose what a classifier wants.
- **`fusion.json`** — per-shot rows carrying the brief's schema with source-obvious names: identity (`session_id`, `shot_num`), voice fields (`result`, `t_call_s`, `isolation_s`, `raw_token`, `voided`), acoustic fields (`t_impact_s` = paired cluster's `t_start`, `n_impacts`, `burst_duration_s` = `t_end − t_start`, `mean_centroid_hz`, `max_peak_rms`, `decay_ratio` = mean over the cluster's impacts — all null when unpaired), fusion fields (`call_latency_s`, `pairing_status`), derived (`gap_call_s`, `gap_impact_s` — impact-based gaps are the better timing measure and are stored for downstream preference later; keeping both is itself a validation signal). Plus `call_missing` event rows and the session-level pairing/latency summary.

Reprocessable: given the stored transcript JSON and the audio file, every artifact recomputes identically.

## Pipeline wiring (`pipeline.py`)

Two optional stages after parsing, mirroring today's `write_impacts` contract (never raise):

```
events = write_acoustics(sdir, audio_path)          # -> acoustics.json or None
fused  = write_fusion(sdir, rows, events, session)  # -> fusion.json or None (needs events)
```

`replay_session` gets the same wiring and removes stale sidecars (`impacts.json`, and `acoustics.json`/`fusion.json` when their stage yields None) so replayed sessions never carry outputs of a stage that didn't run.

## `impacts.py` retires (report re-wiring, `report_html.py`)

- Replay physics: ball lands at the paired cluster's `t_start`; fallback unchanged (`t_word − 0.5 s`) for `impact_missing`/no sidecar.
- 🤥 lie-detector = `pairing_status == "impact_missing"`; "Uncorroborated" stat sourced from fusion.
- Waveform strip: percussive onset envelope from `acoustics.json`; markers for **all** clusters — paired ones highlighted, unpaired (`call_missing`/warmup) visibly distinct, making ghost shots visible.
- `render_interactive_report` signature swaps `impacts=` for the new sidecar data; report remains one self-contained HTML and renders fine with zero sidecars.
- `src/hoops/impacts.py` and `tests/test_impacts.py` are deleted; nothing writes `impacts.json` anymore.

## Tuning + validation scripts

- **`scripts/sweep_thresholds.py`** — sweeps `onset_delta` × `min_spacing` × `cluster_gap` over the recorded fixtures; reports event counts / median gaps vs. the baseline table and manifest shot counts; renders a per-fixture debug HTML (shared time axis: percussive envelope, detected clusters, voice-call markers, pairing lines — pairing errors are obvious visually, invisible in tables). Chosen values + justification → `docs/decisions/002-impact-detection-params.md` (F05 findings included).
- **`scripts/analyze_separability.py`** — the single most informative deliverable: pool paired events across fixtures, group by voice label, and for each feature (`n_impacts`, `mean_centroid_hz`, `max_peak_rms`, `decay_ratio`, `burst_duration_s`) compute AUC and Cohen's d, rank by discriminative power, and render overlaid distributions as a self-contained HTML (hand-rolled SVG, no matplotlib). Honest answer → `docs/decisions/003-acoustic-separability.md`. **A null result is a valuable finding, not a failure** — it kills the classifier idea before anything is built on it.

## Dependencies + cloud

- `pyproject.toml` gains `librosa` + `numpy` (scipy transitively). No further deps without asking.
- `cloud/modal_app.py` image gains the pip installs; ffmpeg already present. Deploy + smoke E2E happen **after** local gates pass, in the same pass.

## Boundaries

- `parse.py` / `invariants.py` / `stats.py` / `transcribe.py` untouched.
- Parse artifacts byte-identical under `hoops replay --all`; `hoops score` unchanged.
- Report stays one self-contained HTML, zero external requests.
- Acoustics/fusion stages removable: delete two calls, everything degrades to voice-only.

## Non-goals

- No shot-type classifier this round (`classify.py` deferred pending separability).
- No `stats.py`/narrative changes; impact-based gaps live in `fusion.json` only for now.
- No manifest columns or score gates for timing; no changes to transcription or parsing.
- No attempt to make impact detection work under music (F05 is documented, not accommodated).

## Verification

- Unit: fusion pairing on hand-built rows/events covering all five cases; cluster logic on bare time lists; acoustics on synthetic numpy signals (click train + sine — HPSS keeps the clicks); import-independence test; sidecar-absent rendering; report self-containment test stays green.
- Integration: full acoustics+fusion run on one recorded fixture (marked `slow` if runtime warrants).
- `uv run pytest` green · `hoops replay --all` parse artifacts byte-identical · `hoops score` unchanged.
- Sweep results in the neighborhood of the baseline table; decision docs 002/003 written.
- `modal deploy` + smoke E2E; then regenerate one real session report and eyeball impact alignment on the percussive waveform.
