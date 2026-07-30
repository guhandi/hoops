# Architecture

How the pipeline is built, why it's shaped this way, and where to look when something's wrong. The behavioral contract lives in the original [PRD](archive/PRD-hoops-voice-log.md) (archived); decisions that supersede it live in the [design spec](specs/2026-07-27-hoops-voice-log-design.md).

## Module map

```
src/hoops/
  cli.py         entry points: process / process-all / replay / poll / score / transcribe-fixtures
  ingest.py      inbox poller: stability rules, .icloud stubs, lock file, pending-email retry
  transcribe.py  Transcriber interface + whisper-1 backend; Word model; transcript envelope
  parse.py       PURE: word stream → calls (isolation gate, vocabulary, scratch-that, note:)
  stats.py       PURE: calls → shot rows (§7.6 schema) → session stats (§7.7 schema)
  invariants.py  PURE: I1–I6 checks on the shot table
  repair.py      LLM sequence reconstruction, only invoked on invariant failure
  narrative.py   LLM headline/recap/quote for the email, guardrailed, optional
  render.py      shot-strip PNG (matplotlib), fixture gallery
  report_html.py interactive self-contained session report — SVG charts + audio-synced movie replay; session audio embedded base64
  mailer.py      SMTP email: CID-inline strip.png, report.html attachment
  session.py     session-id derivation, folder layout, artifact read/write
  fixtures.py    fixture runner + committed transcript cache
  score.py       accuracy metrics + gate table vs fixtures/manifest.csv
  pipeline.py    orchestration: process_file() and replay_session()
scripts/
  build_db.py            rebuild disposable hoops.db from committed session text
  install_launchd.sh     schedule `hoops poll` every 300s
  com.guhan.hoops.plist  the launchd job
```

`parse.py`, `stats.py`, `invariants.py` are pure functions over data — no I/O, no clock, no network. That's deliberate: they're the load-bearing logic, so they're the most testable.

## Three debuggable layers

Every session persists three layers, each answering one question:

| Layer | Artifact | Question |
|---|---|---|
| L1 | `audio.m4a` | Ground truth — what actually happened |
| L2 | `transcript.json` | Did the ASR hear the words correctly? |
| L3 | `shots.csv` / `session.json` | Given the transcript, did the parse produce the right table? |

Triage: transcript right but shots wrong → parser/config bug (fix thresholds or aliases, then `replay`). Transcript wrong → ASR problem (prompt, vocabulary, mic distance, model). This separation is why `hoops replay` exists: the parser re-runs from stored L2 in seconds, at zero API cost, across the entire archive — and because session artifacts are committed text, `git diff sessions/` after a replay shows exactly which shots a parser change flipped.

## The parser (the part that matters most)

Input: whisper's word array with per-word `start`/`end` timestamps. The threat model is **phantom shots**: vocabulary words embedded in natural muttering ("come on, *make* it"). Defenses, in order:

1. **Isolation gating** — `isolation = min(gap_before, gap_after)` for each vocabulary token. Above `isolation_high` (0.4s): a real call. Below `isolation_low` (0.15s): continuous speech, discard. Between: ambiguous — kept out of the table but surfaced in the email flags and fed to the repair pass.
2. **Filter, don't classify** — unknown words are ignored, never fatal. A session is never rejected for containing speech the parser doesn't understand.
3. **The stop rule as a validator** — a valid session has *exactly one* run of three consecutive makes, at the very end (invariants I1 + I6). Any parse without that shape is provably wrong and gets flagged or repaired.

`scratch that` voids the most recent non-voided call. Everything after the last standalone `note` token is captured verbatim. Voided calls stay in `shots.csv` (with `voided=true`) so the record is auditable.

## Invariants

Checked on every session, forever — cheap, label-free validation on live data:

| ID | Check |
|---|---|
| I1 | Final three non-voided calls are all makes (the stop rule) |
| I2 | At least 3 calls |
| I3 | No two calls closer than 1.5s (duplicated token) |
| I4 | No gap over 120s (dropped call or long pause) |
| I5 | Every matched token is in the configured vocabulary |
| I6 | No three-make run before the final one (session would already have ended) |
| I7 | Session directory doesn't already exist (idempotency, checked in the pipeline) |

On failure the LLM repair pass gets the raw transcript plus these constraints; its output is re-validated, and if it still fails the session ships **flagged, never guessed** — `invariants_passed=false` and a ⚠️ in the email subject.

## Design principles (and what they buy)

- **Sessions are independent.** No cross-session state, no rolling baselines, no database in the capture path. Removes every class of bug where a store and a folder disagree; any session is reprocessable from its own audio alone.
- **The repo is the store.** Text committed, binaries gitignored, SQLite generated on demand by `build_db.py`. Merges can't corrupt data, diffs stay meaningful, and the pipeline physically cannot write to the DB.
- **Capture must never depend on reporting.** Data is persisted before narrative/email run; every AI or SMTP failure degrades the email (or leaves a `pending_email` marker retried next poll) — it never blocks or corrupts a session.
- **Transport is a queue, not a call.** The iCloud drop folder means a sleeping Mac produces delay, not loss — files pool and drain when the poller wakes. The poller only picks up files whose size is stable across two polls and whose mtime is >60s old (iCloud partial-sync safety), and force-downloads `.icloud` placeholder stubs.
- **Deterministic by default.** The only nondeterministic stages are repair (rare, re-validated) and narrative (cosmetic, optional). Same audio in → same table out.

## Transcription notes

whisper-1 via the OpenAI API with `response_format=verbose_json` and `timestamp_granularities=["word"]` — word timestamps are non-negotiable (the isolation gate depends on them), which rules out on-device iOS transcription and the gpt-4o-transcribe family. The bias prompt is written as **transcript-style context, not instructions** (`"brick. make. miss. splash. scratch that. note: ..."`): whisper echoes instruction-phrased prompts verbatim over quiet audio, which we observed injecting hallucinated vocabulary words — i.e. phantom shots — before the phrasing was fixed. The `Transcriber` interface is pluggable so a local `faster-whisper` backend can drop in later for cost/offline reasons.

## Failure handling

| Failure | Behavior |
|---|---|
| Transcription API down | File stays in inbox; retried each poll; alert email every 3rd consecutive failure |
| Audio < 5s | Moved to `rejected/`, no email (a misfire is not an event) |
| Audio > 20min | Processed, flagged prominently (forgot to stop) |
| Zero calls detected | Session moved to `needs_review/`, emailed with the raw transcript |
| Invariants fail after repair | Row written anyway with `invariants_passed=false`, flagged in subject |
| Duplicate session | Skipped; stray inbox copy drained |
| SMTP failure | `pending_email` marker; retried automatically on later polls |
| LLM narrative failure | Email sends without the narrative blocks |

## Schemas

**Shot row** (`shots.csv`): `session_id, session_date_local, shot_num, result, t_call_s, gap_s, streak_after, voided, isolation_s, confidence, raw_token`. Note `t_call_s` is when the word was *spoken*, ~1–2s after the shot; constant offsets cancel under differencing, so `gap_s` is valid but absolute shot time is not.

**Session** (`session.json`): `session_id, session_date_local, start_time_local, shots_to_three, makes, misses, fg_pct, longest_make_streak, longest_miss_streak, time_to_first_make_s, median_gap_s, fastest_gap_s, slowest_gap_s, session_len_s, notes, quote_of_day, profanity_count, words_per_miss, invariants_passed, ambiguous_calls, transcriber, parser_version, session_id_source`.

`shots_to_three` is the headline metric. FG% is secondary and biased upward by construction — every session ends on a hot streak.
