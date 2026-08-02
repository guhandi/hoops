# Decision 002: Impact detection parameters — keep current config

**Date:** 2026-08-01 · **Status:** accepted · **Input:** `scripts/sweep_thresholds.py` and `scripts/sweep_thresholds.py --full-grid` over F01/F02/F04/F06 (tuning) + F05 (music, reported only). Raw output in `out/sweep/results.json` and `out/sweep/debug_<stem>.html` (gitignored, regenerate with the commands above).

## Decision

**Keep `onset_delta: 0.4`, `min_spacing_frames: 15`, `cluster_gap_s: 2.0`** — the values already in `config.yaml` / `cloud/config.cloud.yaml`. No config change made.

At current config values, the four tuning fixtures reproduce the brief's baseline event counts **exactly** (0 deviation on all four). The full 36-combo grid (`onset_delta` × `min_spacing_frames` × `cluster_gap_s`) confirms `onset_delta=0.4` is the *unique* zero-deviation value — every other `onset_delta` in the grid (0.2, 0.3, 0.5) misses the baseline on at least one fixture. Within `onset_delta=0.4`, all 9 combinations of `min_spacing_frames ∈ {10,15,20}` × `cluster_gap_s ∈ {1.5,2.0,2.5}` produce **byte-identical** results (same event count, same pairing rate, same median latency, per fixture — verified, not just coincidentally equal means). `{15, 2.0}` — already the config values — is the middle of that 9-way tie, so the brief's mid-grid tie-break rule lands exactly where the config already sits.

## Sweep table — chosen combo (`onset_delta=0.4, min_spacing_frames=15, cluster_gap_s=2.0`)

| Fixture | n_events | baseline | Δ | median gap (s) | pairing rate | live voice calls | median latency (s) |
|---|---|---|---|---|---|---|---|
| F01_NormalSwishBrick | 17 | 17 | 0 | 5.0 | 0.571 | 14 | 1.106 |
| F04_SwishBrickQuiet | 14 | 14 | 0 | 8.9 | 0.636 | 11 | 0.913 |
| F06_SwishBrick10secBeep | 16 | 16 | 0 | 8.0 | 0.636 | 11 | 0.789 |
| F02_SwishBrickChatty | 8 | 8 | 0 | 5.5 | 1.000 | 2 | 1.802 |

Total deviation: **0**. Mean pairing rate: **0.7107**.

F02's 1.000 pairing rate is not a strong signal in isolation: F02 is the isolation-gate stress fixture (decision 001) — heavy commentary knocks all but 2 of the 8 expected calls down into the ambiguous zone before fusion ever sees them, so "100% paired" means 2-for-2, not 8-for-8. The acoustic side still found all 8 baseline event clusters; only the voice branch is starved here, by design.

## Runner-up combos

| onset_delta | min_spacing / cluster_gap | Σ|Δ| | mean pairing | notes |
|---|---|---|---|---|
| **0.4** | any of 9 combos | **0** | **0.7107** | **chosen** — exact baseline match |
| 0.3 | {10,15,20} × 2.5 | 2 | 0.7692 | F06 18 vs 16 baseline (+2); higher pairing but fails the primary (nearest-baseline) rule |
| 0.5 | {10,15,20} × any | 3 | 0.6475 | F01 14 vs 17 (−3, under-detects); worse on both rules |
| 0.3 | {10,15,20} × 2.0 | 4 | 0.7692 | same over-detection pattern as above, worse |
| 0.2 | {10,15,20} × 2.5 | 7 | 0.8277 | best raw pairing rate in the whole grid, but over-detects hardest (F06 up to 19-24 vs 16) |
| 0.3 | {10,15,20} × 1.5 | 8 | 0.7692 | |
| 0.2 | {10,15,20} × 2.0 | 12 | 0.8277 | |
| 0.2 | {10,15,20} × 1.5 | 16 | 0.8277 | worst deviation in the grid |

Per the brief's ordering (nearest baseline first, pairing rate as tie-break), `onset_delta=0.4` wins outright — it is not a close call. Note the pattern: `onset_delta=0.2` maximizes pairing rate (0.8277) precisely because it over-detects (more clusters mean fewer calls go completely unmatched), which is the failure mode the "nearest baseline" rule exists to catch — pairing rate alone would pick a threshold that manufactures phantom events.

**`min_spacing_frames` and `cluster_gap_s` have zero measurable effect** on event count, pairing rate, or median latency anywhere in the tested grid (10–20 frames, 1.5–2.5 s), for any `onset_delta`, on these four fixtures. Real shot impacts in this recording set are already well-separated in time (5–9 s apart) and `librosa.util.peak_pick`'s hardcoded `pre_max=post_max=30` frames (~349 ms at hop=256/sr=22050) already enforces more spacing than the swept range ever removes. All of the observed sensitivity is carried by `onset_delta` (the percussive-strength gate). This means the current `{15, 2.0}` values are not meaningfully "tuned" so much as inert on this fixture set — worth re-sweeping `min_spacing_frames`/`cluster_gap_s` if a future fixture has closely-spaced rapid-fire shots where clustering would actually matter.

## F05 (music) — reported, explicitly not tuned for

At chosen config: **11 events**, median gap 4.7 s, pairing rate **0.571** (4/7 live calls paired). No baseline exists for F05 (excluded from the brief's baseline table).

Ground truth (`fixtures/manifest.csv`) lists 9 expected calls; only **7** survive the voice branch's isolation gate under background music — 2 are lost to the same masking mechanism as F02's chatter (parser-level, not an acoustics problem).

Across the full `onset_delta` sweep, event count varies (0.2→7, 0.3→11, 0.4→11, 0.5→9; median gap 6.8/5.1/4.7/6.2 s) but **pairing rate is identical — 0.571 — at all 36 combos**, including every `min_spacing_frames`/`cluster_gap_s` variation. Whichever acoustic clusters end up inside the fusion pairing window for the 7 live calls, they pair; extra or missing clusters elsewhere in the mix never enter those windows either way. This says music-masking is a structural/coverage problem, not a threshold-sensitivity problem — no combo in this grid recovers the pairing rate, so it isn't something to chase by retuning. Flagged as a known limitation, not a bug.

## Debug HTML notes

Opened all 5 debug pages (`out/sweep/debug_*.html`); SVGs inspected via their embedded event/impact data (title attributes: impact count, centroid Hz) rather than pixels.

- **F01**: 17 clean orange clusters track well against the 14 voice-call dots. The **last** cluster (t=88.75 s of an 88.90 s fixture; 1 impact, **584 Hz**) is an order of magnitude lower-centroid than every other event (2400–3800 Hz core) — almost certainly a handling/stop-recording thump, not a shot. It's already baked into the "17" baseline (so it doesn't hurt the sanity gate), but it means the true shot-event count is 16, not 17 — worth excluding from Task 6's separability training data.
- **F04**: same tail artifact — final event at t=106.82 s of 107.75 s, 1 impact, **462 Hz**. Also a low-centroid (1136 Hz) *first* event at t=0.65 s, versus 3000+ Hz neighbors — plausibly a quiet warm-up bounce or recording-start handling noise; consistent with F04 being the whisper-quiet/distance fixture where SNR is already marginal. 6 of 14 events go unclaimed by fusion (`n_call_missing`), mostly explained by these two edge artifacts plus likely inter-shot dribble/rebound bounces, not double-counted shots.
- **F06**: 16 events line up cleanly against the beep-cadence markers. One interior low-centroid event (t=54.54 s, 375 Hz) sits mid-session, not at a recording boundary, and isn't a beep multiple (54.54 s / 10 s ≈ 5.45) — reads as a dull/off-center rebound rather than a capture artifact.
- **F02**: 8 orange clusters against only 2 live voice-call dots — expected, since F02's whole point is that heavy commentary suppresses most calls before fusion. Nothing surprising acoustically: all 8 clusters are shot-shaped (1–4 impacts, 1952–3258 Hz), squarely inside the make/miss family seen elsewhere.
- **F05 (music)**: 11 events span 786–3353 Hz, generally lower and more compressed than the other fixtures' 2400–3800 Hz core — consistent with percussive detection competing with / getting smeared by the music bed. No narrowband tonal centroid spikes that would indicate voice leaking through the HPSS split — the separation itself looks intact; it's recall (missed impacts, missed calls) that suffers under music, not false positives.

## Verification

```
uv run pytest
```
267 passed, 1 warning in 65.07s — suite untouched by this change since no source/config edits were needed.
