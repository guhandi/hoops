# Architecture

How the pipeline is built, why it's shaped this way, and where to look when something's wrong. The behavioral contract lives in the original [PRD](archive/PRD-hoops-voice-log.md) (archived); decisions that supersede it live in the [design spec](specs/2026-07-27-hoops-voice-log-design.md) and, for the cloud ingestion path, [the cloud migration spec](specs/2026-07-31-cloud-migration-design.md).

## Module map

```
src/hoops/
  cli.py         entry points: process / process-all / replay / poll / score / transcribe-fixtures
  ingest.py      inbox poller: stability rules, .icloud stubs, lock file, pending-email retry (local fallback path)
  transcribe.py  Transcriber interface + whisper-1 backend; Word model; transcript envelope
  parse.py       PURE: word stream → calls (isolation gate, vocabulary, scratch-that, note:)
  stats.py       PURE: calls → shot rows (§7.6 schema) → session stats (§7.7 schema)
  invariants.py  PURE: I1–I6 checks on the shot table
  acoustics.py   Branch B — HPSS onset detection of ball impacts from raw audio, independent of voice/calls; acoustics.json sidecar
  fusion.py      pairs branch A calls with branch B impact events (nearest-preceding, latency-windowed); fusion.json sidecar
  repair.py      LLM sequence reconstruction, only invoked on invariant failure
  narrative.py   LLM headline/recap/quote for the email, guardrailed, optional
  render.py      shot-strip PNG (matplotlib), fixture gallery
  report_html.py interactive self-contained session report — SVG charts, audio-synced movie replay, impact-aligned replay with 🤥 no-contact flags + waveform scrubber (from acoustics.json/fusion.json sidecars); session audio embedded base64
  mailer.py      SMTP email: CID-inline strip.png, session zip attachment (all session files, report.html inside)
  session.py     session-id derivation, folder layout, artifact read/write
  fixtures.py    fixture runner + committed transcript cache
  score.py       accuracy metrics + gate table vs fixtures/manifest.csv
  pipeline.py    orchestration: process_file() and replay_session()
cloud/
  modal_app.py   Modal wiring only: image, secrets, endpoint, spawn+retries, `pull_sessions` entrypoint
  web.py         FastAPI upload endpoint app factory — auth, filename validation, size cap, dedupe (no Modal imports, fully testable)
  processor.py   stateless worker: download raw → scratch → process_file() → upload session dir → delete raw
  store.py       S3-compatible (R2) object store wrapper: put/get/list/delete
  config.cloud.yaml  scratch-space clone of config.yaml for the Modal container
scripts/
  build_db.py                rebuild disposable hoops.db from committed session text
  install_launchd.sh         generates `com.hoops.poller.plist` from your clone's path; schedules `hoops poll` every 300s (local fallback path)
  sweep_thresholds.py        grid-searches acoustics detection thresholds against fixture baselines; feeds decision 002
  analyze_separability.py    pools paired branch-A/branch-B shots to test whether acoustic features separate make/miss; feeds decision 003
```

`parse.py`, `stats.py`, `invariants.py` are pure functions over data — no I/O, no clock, no network. That's deliberate: they're the load-bearing logic, so they're the most testable.

## Ingestion

**Primary: cloud pipeline.** The phone POSTs straight to a Modal endpoint; the Mac is out of the ingestion path entirely.

```
[iPhone]  Shortcut → POST https://<modal-endpoint>/upload
          multipart hoops__<yyyyMMdd-HHmmss>.m4a + X-Hoops-Key header → instant ack
   │
   ▼
[Modal endpoint  cloud/web.py]
   auth (hmac.compare_digest) → filename vs hoops__ prefix pattern → ≤64MB size cap
   → dedupe check against R2 → PUT raw/<name> → spawn processor → ack
   │
   ▼
[R2 bucket "hoops-data"]  raw/<name> (transient) · sessions/YYYY/MM/<sid>/ · needs_review/ · rejected/
   │
   ▼
[Modal processor  cloud/processor.py]
   download raw/<name> → scratch dir → process_file() (transcribe → parse → invariants →
   stats → render → report — same core as local mode) → upload session artifacts to R2
   → delete raw/<name>
   │
   ▼
[Email]  session zip attached (report.html inside), same mailer.py as local mode
```

Endpoint contract: `401` wrong/missing `X-Hoops-Key`; `400` filename doesn't match `hoops__YYYYMMDD-HHMMSS.m4a`; `413` over the 64MB cap; `200 {"status": "duplicate"}` on a re-tap of an already-processed session (idempotent — nothing reprocessed, nothing re-emailed); `200 {"status": "processing"}` otherwise. The report email lands roughly 2 minutes after the tap.

Dev loop: the Mac never touches inbound audio, but stays the dev loop for replay/score/inspection —

```bash
set -a; source .env; set +a
uv run modal run cloud/modal_app.py::pull_sessions
```

pulls new session artifacts down from R2 into local `sessions/`, skipping files already present. The mirror command, `uv run modal run cloud/modal_app.py::push_sessions`, backfills local session folders up to the bucket (skip-if-exists, never overwrites) — used once to migrate the pre-cloud July 2026 history, and safe to re-run any time.

### Local fallback mode

Kept for rollback — run `install_launchd.sh` (generates `com.hoops.poller.plist` from your clone's path) and re-point the Shortcut at iCloud — if the cloud endpoint is ever unreachable. Both ingest paths share the same downstream pipeline core; only how a file arrives on disk differs:

```
[iPhone]  Apple Shortcut → Save File → iCloud Drive/Capture/inbox/hoops__<yyyyMMdd-HHmmss>.m4a
[Mac]     launchd runs `hoops poll` every 5 minutes → ingest.py stability checks (size stable
          across two polls, mtime >60s old, .icloud stub force-download), dedupe → process_file()
          → email
```

## Three debuggable layers

Every session persists three layers, each answering one question:

| Layer | Artifact | Question |
|---|---|---|
| L1 | `audio.m4a` | Ground truth — what actually happened |
| L2 | `transcript.json` | Did the ASR hear the words correctly? |
| L3 | `shots.csv` / `session.json` | Given the transcript, did the parse produce the right table? |

Triage: transcript right but shots wrong → parser/config bug (fix thresholds or aliases, then `replay`). Transcript wrong → ASR problem (prompt, vocabulary, mic distance, model). This separation is why `hoops replay` exists: the parser re-runs from stored L2 in seconds, at zero API cost, across the entire archive — and because session outputs are plain text (though `sessions/` itself isn't tracked in git), snapshot the folder before a replay and compare with `git diff --no-index` to see exactly which shots a parser change flipped.

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
- **The repo is the store for the golden dataset.** Fixture audio and transcripts are committed; per-session data is never committed either way — its source of truth is the R2 bucket (cloud path) or the session folder alone (local fallback), and local `sessions/` is a gitignored cache that `pull_sessions` fills from R2, not a store in its own right; SQLite is generated on demand by `build_db.py`. Merges can't corrupt data, diffs stay meaningful, and the pipeline physically cannot write to the DB.
- **Capture must never depend on reporting.** Data is persisted before narrative/email run; every AI or SMTP failure degrades the email (or leaves a `pending_email` marker retried next poll) — it never blocks or corrupts a session.
- **The Mac's disk is not the source of truth.** R2 is — every session artifact lands in the bucket under `sessions/YYYY/MM/<sid>/` regardless of which Mac (or none) is awake; `pull_sessions` is a cache-fill, not a requirement. In local fallback mode, transport is a queue, not a call: the iCloud drop folder means a sleeping Mac produces delay, not loss — files pool and drain when the poller wakes. The poller only picks up files whose size is stable across two polls and whose mtime is >60s old (iCloud partial-sync safety), and force-downloads `.icloud` placeholder stubs.
- **Deterministic by default.** The only nondeterministic stages are repair (rare, re-validated) and narrative (cosmetic, optional). Same audio in → same table out.

## Transcription notes

whisper-1 via the OpenAI API with `response_format=verbose_json` and `timestamp_granularities=["word"]` — word timestamps are non-negotiable (the isolation gate depends on them), which rules out on-device iOS transcription and the gpt-4o-transcribe family. The bias prompt is written as **transcript-style context, not instructions** (`"brick. make. miss. splash. scratch that. note: ..."`): whisper echoes instruction-phrased prompts verbatim over quiet audio, which we observed injecting hallucinated vocabulary words — i.e. phantom shots — before the phrasing was fixed. The `Transcriber` interface is pluggable so a local `faster-whisper` backend can drop in later for cost/offline reasons.

## Failure handling

**Cloud (primary):**

| Failure | Behavior |
|---|---|
| Wrong/missing upload key | Endpoint returns `401`; nothing written to R2 |
| Malformed filename | Endpoint returns `400`; nothing written to R2 |
| Recording over 64MB | Endpoint returns `413`; nothing written to R2 |
| Duplicate sid re-tap | Endpoint returns `200 {"status": "duplicate"}`; idempotent, nothing reprocessed |
| Processor failure (any exception) | A best-effort alert email fires on *every* raised attempt, then Modal re-raises and retries (up to 3× more, exponential backoff) — so a permanently failing file can send up to 4 alert emails (one per attempt) before Modal gives up, while a transient failure may send one alert and then succeed on a later retry with no further email |
| Total failure after retries exhausted | `raw/<name>` is retained in the bucket (never deleted on failure) for manual replay; every attempt — success or failure — is visible in the Modal dashboard logs |
| Audio < 5s / > 20min, zero calls, invariants fail, LLM narrative failure | Same behavior as local mode below — this logic lives in the shared `process_file()` core, not the cloud wiring |

**Local fallback:**

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
