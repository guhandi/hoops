# Transcript gap repair — design

**Date:** 2026-08-19 · **Status:** approved, not yet implemented

## Problem

Whisper-1, decoding a full session file, silently drops call words that sit in
sparse, mostly-silent stretches of its ~30s decode windows. Session
`20260819-131500` (136s) lost **5 of 21 calls (~24%)**:

- Three mid-file "break" calls (~39.6s, ~41.0s, ~45.1s) vanished into an 18.1s
  word gap. No invariant fired for these — a dropped miss is silent data
  corruption.
- Two of the three session-ending "splash" calls (~119.7s, ~125.8s) vanished
  into a 16.6s word gap. Invariant I1 fired ("final three calls are
  [miss, miss, make]"), but the LLM repair stage correctly could not fix it —
  it can only reinterpret words that exist in the transcript, not recover
  words whisper never emitted.

Recorded result: 16 shots, 2 makes, not closed out. True session: 21 shots,
4 makes / 17 misses, closed out with splash×3.

**Diagnosis evidence** (2026-08-19, one-off re-transcriptions):

1. `transcript.json` has zero words between 111.0s and 127.5s; the parser
   faithfully converted all 16 words it received.
2. `acoustics.json` shows ball impacts at 36.6/40.6/44.3s and 117.7/125.8s;
   `fusion.json` flagged them `call_missing` — the dual-capture branch caught
   every dropped call.
3. Re-transcribing the 112s→end clip alone recovered `splash@119.7`,
   `splash@125.8`. Re-transcribing 32–49s recovered `break×3`. The calls are
   clean in the audio; fresh decode windows hear them.
4. Pinning `language="en"` on the full file produced byte-identical output —
   the "nynorsk" language auto-detection (also seen on session
   `20260803-111200`) is cosmetic, not causal.

Because the game ends on three consecutive makes, the session-ending pattern
is *always* a run of trailing makes followed by celebration and silence —
exactly the sparse-tail shape whisper drops. This failure mode is systematic,
not a fluke.

## Fix (approach A — gap-triggered second pass)

A second pass **inside the transcription stage**: detect coverage gaps in the
word timeline, re-transcribe each gap span as its own clip, merge recovered
words into the envelope before it is persisted and parsed.

```
transcribe full file ──► detect coverage gaps (pure math, free)
                              │ no gaps → done (zero cost, zero change)
                              ▼
                    clip each gap span (±pad) → whisper per clip
                              ▼
                    merge recovered words into envelope (+ provenance)
                              ▼
            write_transcript (L2 unchanged) ──► parse ──► … (untouched)
```

Everything downstream — parser, invariants, LLM repair, stats, fusion,
report — is untouched. The voice/acoustic branch independence invariant is
preserved: the acoustic branch remains the independent auditor, and fusion's
pairing rate becomes the natural verification that recovery worked.

### Rejected alternatives

- **Invariant-triggered only (I1/I2):** misses silent mid-file drops — this
  session's three lost bricks violated no invariant.
- **Fusion/acoustic-triggered:** most evidence-driven, but makes voice output
  depend on the acoustic branch (breaks branch independence) and forces a
  parse→fuse→re-transcribe→re-parse→re-fuse loop.
- **Always chunk into 30s windows:** changes behavior on every session,
  risks splitting call words at boundaries, more cost, no benefit over gap
  detection.

## Components

### 1. `src/hoops/gap_repair.py` (new)

Pure, unit-testable span math (stdlib only):

- **Gap detection:** gaps are `0 → first word start`,
  `word[i].end → word[i+1].start`, `last word end → audio duration`. A gap
  qualifies when longer than `trigger_gap_s` (default **10s**; the two misses
  in R03 were 18.1s and 16.6s; median real call spacing is ~6s).
- **Span building:** qualifying gaps padded by `pad_s` (default 2.0s),
  clamped to `[0, duration]`, count capped at `max_spans` (default 8).
  Hitting the cap adds a flag — never silent. Padded clips may overlap;
  spans are deliberately NOT merged — gaps are disjoint by construction, so
  the keep-only-inside-the-unpadded-gap rule makes cross-span duplicates
  impossible, and overlap only re-transcribes a couple of padding seconds.
- **Merge rule (hallucination guard):** only recovered words whose `start`
  falls **inside the unpadded gap** are kept. This drops boundary duplicates
  of words already in the main transcript and prompt-bleed at clip edges
  (whisper echoes vocab-prompt decoys like "scratch" over near-silence). No
  content filtering beyond that — the parser's isolation gate and fusion's
  corroboration do their normal jobs on recovered words. Word-backed edge
  margins (added 2026-08-19 after the R03 gate caught a boundary
  re-hearing): recovered words starting within `isolation.high` of a gap
  edge that abuts a transcribed word are excluded — a clip re-hearing of
  the boundary word passes the inside-gap test on timestamp drift, then
  voids the real boundary word via the parser's isolation gate (R03: clip
  brick@31.6 vs main break ending 31.5 killed both). Lossless: a real call
  that close to the boundary word could never survive isolation as a
  distinct call anyway. Head-gap starts (t=0) and tail-gap ends
  (t=duration) have no boundary word and get no margin.

Plus one orchestration function with I/O:

- `apply_gap_repair(env, audio_path, transcriber, prompt, cfg, duration)
  -> env` — detects gaps, extracts clips, calls whisper per clip, merges,
  returns the augmented envelope. Any per-span failure skips that span and
  records it; any whole-stage failure returns the original envelope. Single
  pass — recovered words never trigger recursive re-detection.

### 2. Clip extraction

`librosa.load(path, sr=16000, mono=True, offset=span_start,
duration=span_len)` → write mono WAV to a temp file → send to whisper with
the **same vocab prompt** and `language` pinned. librosa/soundfile are
already dependencies (acoustics branch) and present in the cloud image — no
ffmpeg subprocess.

### 3. Envelope format (`transcript.json`)

`response` stays the pristine raw API response. Repair adds a sibling key:

```json
{"model": "whisper-1",
 "response": { …original, untouched… },
 "gap_repair": {
   "trigger_gap_s": 10, "pad_s": 2.0,
   "spans": [
     {"gap": [111.66, 127.48], "clip": [109.66, 129.48],
      "response": { …raw clip response… },
      "recovered": [{"word": "splash", "start": 119.66, "end": 120.10}]}
   ],
   "n_recovered": 5,
   "errors": []
 }}
```

- `words_from_envelope` merges `response.words` with all `recovered` words,
  time-sorted, **only when the `gap_repair` key exists**. Envelopes without
  the key behave exactly as today → replay byte-identity on all existing
  sessions preserved by construction.
- Recovered `Word`s carry `confidence: None` (clip responses have no usable
  segment logprobs mapped to the session timeline).
- `transcript.txt`: original `response.text`, plus one appended line when
  repair recovered anything:
  `[gap repair recovered: splash@119.7 splash@125.8]`.

### 4. Whisper language pin

`transcriber.language` config key (default `"en"`), passed to **both** the
main transcription call and clip calls. Proven byte-identical on R03's audio;
eliminates nynorsk-style language-detection drift. Replay reads cached
envelopes, so existing sessions are unaffected.

### 5. Pipeline integration (`pipeline.py`)

In `process_file`, immediately after a **fresh** transcription (never when
`cached_env` is supplied):

```python
if cfg.gap_repair.enabled:
    env = apply_gap_repair(env, path, transcriber, vocab_prompt(vocab),
                           cfg.gap_repair, duration=dur)
```

Runs before `write_transcript` — L2 ("transcript persisted before parse")
unchanged. Non-fatal like the GuData stage.

Visibility (shadow-period honesty):

- `stats["gap_repair_recovered"] = N` (0 when the stage ran and found
  nothing; absent when disabled).
- Flag string when N > 0: `"N call word(s) recovered by transcript gap
  repair"` → surfaces in report and email.
- Per-span errors and a hit `max_spans` cap also become flags.
- No shots.csv / GuData schema changes (per-shot provenance is YAGNI for
  now; fusion pairing already gives per-shot scrutiny).

### 6. Backfill: `hoops retranscribe [<sid> | --all]` (new CLI command)

Per session directory (local, populated via `pull_sessions`):

1. Read existing envelope + `audio.m4a`; **detect gaps on the existing
   envelope first (free, no API)**. `--all` skips sessions with no
   qualifying gaps or an existing `gap_repair` key; prints what it skipped.
2. Run the repair passes → rewrite `transcript.json` / `transcript.txt`.
3. `replay_session()` regenerates shots.csv, session.json, fusion, strip,
   report.
4. `--email` optionally resends the report email.

Follow-up steps stay existing tooling, documented not built: `hoops push
<sid>` for GuData, `modal run cloud/modal_app.py::push_sessions` to sync
repaired artifacts back to R2.

**Known caveat:** GuData dedupes on `external_id`, so re-pushing corrected
stats may be skipped server-side unless GuData upserts. Verifying/adding
upsert is a GuData-side task — out of scope here; the retranscribe output
reminds the operator of this.

Initial backfill targets: `20260819-131500` (R03's source) and
`20260803-111200` (same nynorsk signature; gaps to be confirmed by the free
detection step).

### 7. Config (`config.yaml`, mirrored in `cloud/config.cloud.yaml`)

```yaml
transcriber:
  model: whisper-1
  language: en          # new — pins whisper language (main + clip calls)
  gap_repair:
    enabled: true
    trigger_gap_s: 10   # word-timeline gap that triggers re-transcription
    pad_s: 2.0          # context padding around each gap span
    max_spans: 8        # per-session cost bound; hitting it adds a flag
```

Named `trigger_gap_s` to avoid collision with `limits.min_gap_s` (invariant
I3's shot-spacing floor).

## Fixture & gates (methodology: fixture first)

- Session `20260819-131500`'s audio is committed as fixture **R03**
  (`fixtures/08192026_MorningHoops.m4a`, following R01/R02's naming;
  category `real_session`), manifest row labeled by the owner.
  Evidence-derived ground truth, owner to confirm — 21 calls in time order
  (the three recovered breaks at ~39.6/41.0/45.1s slot between the calls at
  30.1s and 49.6s): surface form `break×13, splash, break×4, splash,
  splash, splash`; `expected_calls` in manifest terms
  `miss×13 make miss×4 make make make`;
  `expect_invariants_pass: TRUE` (closes out).
- **Acceptance gates:**
  1. `hoops score` on R03: `heard_calls == expected_calls`, `match=TRUE`.
  2. `uv run hoops replay --all` byte-identical on all existing sessions
     (snapshot `sessions/`, compare with `git diff --no-index`).
  3. Full offline `uv run pytest` green.
  4. Existing fixture scores unchanged (guards the language pin): re-run
     `hoops score` on currently-scored fixtures, no regressions.

## Testing

Offline (default suite, no network):

- Gap math: synthetic word lists — no gaps, head/tail gaps, adjacent gaps
  merging after padding, `max_spans` cap, empty transcript (one full-file
  gap), gap exactly at threshold.
- Merge/dedupe: recovered word inside gap kept; at padded edge dropped;
  duplicate of existing boundary word dropped; ordering stable.
- `apply_gap_repair` with a stubbed transcriber: happy path, per-span API
  failure (span skipped + recorded), whole-stage failure (original envelope
  returned), single-pass (no recursion).
- `words_from_envelope`: old envelope (no key) unchanged; augmented envelope
  merges time-sorted.
- Pipeline integration: stub transcriber returns a holed main envelope +
  clip envelopes; assert final rows contain recovered calls, stats flag set,
  L2 file contains `gap_repair` key.
- Retranscribe CLI with stubs: skip-no-gaps, skip-already-repaired, rewrite +
  replay path.

Paid (`-m paid`): E2E on R03 audio against real whisper — the acceptance
gate above.

## Error handling summary

| Failure | Behavior |
|---|---|
| Clip decode/load error | Skip span, record in `gap_repair.errors`, flag |
| Whisper API error on a clip | Same — skip span, record, flag |
| Whole-stage exception | Original envelope used, flag, pipeline proceeds |
| `max_spans` exceeded | First N spans processed, flag notes truncation |
| Report/email | Never blocked by any of the above |

## Cost

whisper-1 ≈ $0.006/min. Zero added cost on gap-free sessions; a repaired
session adds a few cents (R03 would have cost ~2 extra clips ≈ $0.004).
`max_spans` bounds the pathological case (e.g. a forgot-to-stop 20-minute
recording).

## Non-goals

- No audio-only make/miss classification (nulled per
  `docs/decisions/003-acoustic-separability.md`).
- No acoustic-informed transcription or any voice←acoustic dependency.
- No per-shot provenance column in shots.csv / GuData payload.
- No GuData server-side upsert work (tracked as a caveat, separate repo).
- No automatic R2 sync inside `retranscribe` (use existing
  `push_sessions`).

## Docs to update in the same change

- `docs/architecture.md` — transcription stage + retranscribe command.
- `CLAUDE.md` — status, and Pending work: interacts with item 1 (R01/R02
  cache refresh — retranscribe's free gap-detection can piggyback) and item
  8 (shadow-period eyeballing now includes gap-repair flags).
- `fixtures/manifest.csv` — R03 row.
