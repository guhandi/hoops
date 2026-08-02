# Report delight pass — design

**Date:** 2026-08-01 · **Status:** approved (brainstorm 2026-08-01, visual companion) · **Owner:** Guhan

## Goal

The fun of hoops lives in two places: one-button acquisition (already nailed) and the interactive HTML report. This pass makes the report subtly better on three axes Guhan named — within-session storytelling, visual/interactive polish, and physical honesty of the replay — plus one new post-processing capability he specced himself: impact-sound detection with a "was I lying" fallback.

## Decisions made in brainstorming

- **Scope:** ideas 1–5 from the visual menu (impact alignment, choreography, waveform strip, runs & chase, narrative drama) + shot-anchored transcript (layout C of three mockups). Quote-of-day wiring explicitly out.
- **Impact detector rigor:** simple heuristic + eyeball validation via the waveform strip during the shadow period. No labeled timing fixture, no new score gate this round. Guhan's spec, verbatim intent: look only 1–2 s before each call word for the loud shot sound; if missing, flag it (lie detector) and fall back to the voice as ground truth; build it as an independent post-processing step that can be added/removed from the pipeline freely.
- **Standalone stays standalone:** no external services, report remains one self-contained HTML file.

## The seven pieces

### 1. `src/hoops/impacts.py` — impact detection + envelope (new module)

The only audio-touching addition, I/O-isolated like `transcribe.py`. Decode via `ffmpeg` subprocess → WAV → stdlib `wave`; pure-stdlib DSP on PCM ints (no numpy).

- **Per call word:** search **[t_word − 2.0 s, t_word − 0.15 s]** only, for a transient peak well above the local noise floor → `impact_t_s`. No qualifying peak → `impact_t_s: null` + `no_contact: true`; the voice remains ground truth.
- **Envelope:** downsampled loudness envelope (~15 Hz, normalized 0–1) for the waveform strip.
- **Output:** optional per-session sidecar `impacts.json`: `{envelope: [...], envelope_hz: N, shots: [{shot_num, impact_t_s, no_contact}]}`.
- **Pipeline:** one optional stage call in `pipeline.py`. ffmpeg missing or decode failure → skip silently (log only), never block the email. Everything downstream degrades gracefully when the sidecar is absent — the stage is removable by deleting one call.
- **Cloud:** add ffmpeg to the Modal image in `cloud/modal_app.py`; redeploy.

### 2. Replay physics fix (`report_html.py`)

Today the ball flight *starts* at the voice timestamp — backwards from reality. New behavior: the flight **lands** at `impact_t_s`; the call word fires the confirmation flash a beat later. Fallback (no impact / no sidecar): land ~0.5 s before the word. No-contact shots get a 🤥 marker in the replay and tooltip, and an "uncorroborated calls: N" stat in the Fun group.

### 3. Make/miss choreography (`report_html.py`, pure CSS/SVG/JS)

Makes: net ripple + splash particles. Misses: rim bounce-out arc. The closing three-in-a-row: a confetti moment.

### 4. Waveform strip (`report_html.py`)

Envelope rendered behind/under the scrubber with impact markers overlaid. Doubles as the eyeball-validation view for the detector.

### 5. Runs & the chase (`stats.py`, pure stdlib, additive keys only)

Compute the run structure of the session: list of make/miss runs, count of broken two-in-a-row attempts ("almosts"), closing-run info. Timeline SVG gains run brackets, "so close ×N" annotations, and a 🏁 closeout marker.

### 6. Narrative drama (`narrative.py`)

The beat-writer payload gains the chase structure and no-contact flags as context. All hard rules unchanged: no digits, no cross-session claims, quote must be verbatim.

### 7. Shot-anchored transcript (`report_html.py`, layout C)

Transcript chunked per shot: every word said since the previous call attaches to the next shot's block, headed `#4 MAKE · 0:27 · gap 7.9s`. Words before the first shot form a "warmup" block; trailing words a "cooldown" block. Clicking a block seeks the audio.

## Boundaries

- `parse.py` / `invariants.py` untouched; `stats.py` stays pure stdlib, additive keys only.
- Parser artifacts stay byte-identical under `hoops replay --all`; stats/report artifacts change by design (capability change).
- Report: one self-contained HTML file, zero external requests.

## Non-goals

- No quote-of-day wiring, no labeled timing fixture or new score gate, no changes to transcription or parsing, no cross-session/history features.

## Verification

- Unit tests: peak-picker + envelope on synthetic PCM generated in-test via `wave`; window bounds; no-contact fallback; sidecar-absent rendering; stats runs/chase on hand-built rows; existing report self-containment test stays green.
- `uv run pytest` green; `uv run hoops score` unchanged (parser untouched).
- Regenerate one real session report (`pull_sessions`) and eyeball impact alignment against the waveform, chase annotations, and transcript blocks.
- `modal deploy cloud/modal_app.py` after the image change.
