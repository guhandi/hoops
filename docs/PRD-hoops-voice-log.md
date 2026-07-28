# PRD — Morning free-throw voice log

**Status:** final, ready to build
**Audience:** Claude Code. This document is the build brief.
**One line:** One button press, call out shots by voice, get a structured shot table and an illustrated report in my inbox with no further interaction.

---

## 1. Problem

Every morning I shoot at a closet hoop until I make three in a row. It is already a consistent, self-terminating, time-stamped daily protocol — and it produces no data. Logging it by hand would kill it: hands busy, half awake, and any friction at 6am means the habit stops or the logging stops.

Voice is the only viable capture channel. The call-outs already happen naturally as part of the activity, so capture cost is effectively zero. Everything after the recording is machine work.

## 2. Why it's worth building

- **Shots-to-three-in-a-row is an unusually clean daily scalar.** Same task, same time, same equipment, taken before anything else touches the day.
- **It's a real dependent variable.** At ~40 sessions it can be regressed against prior-night sleep, HRV, alcohol, late screens.
- **The capture pattern generalizes** to reps, sets, putts, sprints. Basketball is instance #1. Generalizing is a **non-goal for v1**, but vocabulary and stop rule live in config so instance #2 is a config file, not a refactor.

## 3. Goals

| # | Goal | Measure |
|---|---|---|
| G1 | Capture costs one button press | Zero interaction between press and stop |
| G2 | Shot sequence recovered correctly | ≥98% per-call classification; ≥90% of sessions exactly correct |
| G3 | Inter-shot timing usable | Gap error ≤0.5s vs. hand annotation |
| G4 | Results arrive without asking | Email lands within 15 min of session end |
| G5 | Bad data announces itself | Every invariant failure is flagged in the email, never silent |
| G6 | Every session stands alone | A session is fully reprocessable from its own audio and nothing else |

## 4. Non-goals

- Real-time or on-device inference. Batch is fine.
- Any UI. No app, no dashboard, no web page. The inbox is the interface.
- Shot location, arc, or form — anything needing video.
- Multi-user.
- Cross-session state of any kind (see §7.2).

## 5. Context of use

6:00–7:00am. Standing, moving, sweaty, holding a ball, cold hands, not fully awake. Phone set down 3–10 feet away, possibly face-down. Background: ball impacts on wood, rim rattle, HVAC, partner asleep nearby — **so I am speaking quietly**. Sessions run 30s to ~5 min.

Assume low-volume speech at distance with percussive background noise. This drives most of what follows.

---

## 6. Input

### 6.1 Session protocol

| Element | Utterance | Required | Behavior |
|---|---|---|---|
| Shot result | `<make-word>` / `<miss-word>` | One per shot | Appends a shot row |
| Correction | "scratch that" | No | Voids the preceding call |
| Note | anything after "note:" | No | Captured verbatim to `notes` |
| End | stop the recording | Yes | — |

No preamble, no countdown. The button press is the start.

Correction handling isn't polish — a misspoken call silently corrupts the streak logic and the stop-rule invariant. The trailing note is where subjective context goes ("note: elbow stiff, three hours sleep") and is the field that makes the dataset interesting later.

### 6.2 Interstitial speech is the norm, not an edge case

The recording is **mostly not call-outs**. It is a person alone in a room muttering, cussing, and complaining, with call-outs embedded in it. Free speech is the background condition.

**Unknown words are ignored, never fatal.** Filter-don't-classify: scan every token, keep vocabulary matches, discard the rest silently. A session is never rejected for containing speech the parser doesn't understand.

**Vocabulary words inside natural speech create phantom shots.** This is the real threat. "Come on, *make* it." "I can't *make* anything today." "That was a *miss* for sure." Each injects a fake shot that corrupts the sequence, the streaks, and the stop-rule check. A naive keyword filter passes every clean fixture and then fails silently on live data.

Three mitigations, in order of importance:

1. **Isolation gating (primary).** A real call-out is an isolated utterance surrounded by silence; commentary is a continuous run at conversational pace. Word-level `start`/`end` gives this free: compute `isolation = min(gap_before, gap_after)`. Above `isolation_high` (start at 0.4s) ⇒ call. Below `isolation_low` (start at 0.15s) ⇒ commentary, discard. Between ⇒ ambiguous, route to repair. Tune both on fixtures. This single heuristic does most of the work and needs no model.
2. **Vocabulary rarity (design-time).** See §6.3.
3. **Stop-rule repair (backstop).** A phantom shot usually breaks I1 or I6, routing the session to the LLM pass.

All of this is **additive, not gating**. Every session produces a table and an email. Low-confidence sessions ship flagged, not rejected.

### 6.3 Vocabulary

The criterion is **acoustically distinct AND semantically rare in my own muttering**. `make`/`miss` fails both: monosyllabic and M-initial so ASR confusions land *inside* the pair, and both are common words in frustrated self-talk, which makes them phantom-shot generators (§6.2).

**Decided: `swish` / `brick`.** Acoustically far apart (sibilant onset vs. plosive cluster), and neither occurs incidentally in ordinary speech. Useful accident: "ugh, brick" muttered as commentary is still a miss, so that error self-corrects.

This is **verified, not assumed** — fixture F03 records the same heavy-commentary session in `make`/`miss` for direct comparison against F02. If F03 shows phantom shots where F02 shows none, the decision is confirmed. If both are clean, the choice is a free win either way. Record the outcome in `docs/decisions/`.

Vocabulary lives in config as `{canonical_label: [accepted_surface_forms]}`, so a reversal is a config edit.

### 6.4 The commentary is data

The transcript is stored anyway (§7.1), so non-call speech is free to mine and feeds the report: quote of the day, profanity count, words-spoken-per-miss as a rough tilt index. Fun first, plausibly a real variable at 100 sessions.

### 6.5 Audio artifact

- Format: whatever Shortcuts `Record Audio` emits (m4a/AAC). No transcoding unless the transcriber requires it.
- Duration: reject <5s (misfire) and flag >20min (forgot to stop).
- **Audio is retained permanently.** It is the only ground truth, it is small, and it is the fixture corpus for every future accuracy improvement.

### 6.6 Transport — iCloud drop folder

Shortcut saves audio to `iCloud Drive/Capture/inbox/`. A job on the Mac polls every 5 minutes, processes new files, moves them into the repo.

Chosen over a synchronous POST to a Tailscale endpoint because capture then never depends on the network or a server being alive. Worst case for a dead poller is **delay, not loss** — files queue and drain when it comes back. A Mac closed for three days of travel means three sessions process on Thursday, which is fine for something never read in real time. That also dissolves the "the Mac sleeps" objection to running the poller there.

Wrapped in an `IngestSource` interface so swapping to the Google Drive API (required if the poller ever moves to Linux, which has no iCloud client) is one class.

### 6.7 Capture folder as shared substrate

This folder will later host food and workout captures. Design for that as a **naming convention, not a framework**.

```
iCloud Drive/Capture/inbox/          ← every Shortcut writes here, flat
    hoops__20260727-061204.m4a
    food__20260727-121530.m4a
```

Type is encoded in the filename prefix. One watcher, one code path, routing by prefix against a config registry. Adding "food" is a duplicated Shortcut plus a config block declaring its vocabulary and invariants — not new folders and not new plumbing. Per-type inbox folders were considered and rejected: the prefix already namespaces everything.

One Shortcut per capture type, each with its own Home Screen icon, so each stays one press. **No menu — a menu is a tap.**

Timestamps in filenames are **local time**; UTC formatting in Shortcuts is awkward and buys nothing since sessions are independent. Timezone is declared in config and `session_date_local` is derived at parse time — never by string-slicing the filename.

### 6.8 Sync gotchas the implementation must handle

- **Partial reads.** The poller can grab a file mid-sync and get a truncated m4a. Only process files whose size is unchanged across two consecutive polls *and* whose mtime is >60s old.
- **iCloud dataless placeholders.** With "Optimize Mac Storage" on, files appear as `.icloud` stubs with no content. Detect stubs and force download rather than failing.

---

## 7. Storage and output

### 7.1 Three independently debuggable layers

Each session produces a self-contained folder:

```
sessions/2026/07/hoops__20260727-061204/
    audio.m4a          L1 — ground truth, never deleted
    transcript.json    L2 — full word array, timestamps, confidences
    transcript.txt     L2 — plain text, for eyeballing
    shots.csv          L3 — one row per shot
    session.json       L3 — summary stats
    report.html        L4 — rich report
    strip.png          L4 — shot chart
```

| Layer | Answers |
|---|---|
| L1 Audio | Ground truth |
| L2 Transcript | Did the ASR hear me correctly? |
| L3 Shots | Given a correct transcript, did the parse produce the right table? |

**Store the full transcriber response, not just the text.** Plain text cannot distinguish "the words were wrong" from "the words were right but the timestamps were wrong," and those have entirely different fixes. Retain per-word `word`, `start`, `end`, `confidence`, plus the model identifier.

**Consequence: the parser must run from a stored transcript.** A `replay` entry point takes `transcript.json` and skips transcription entirely.

- Iterating on alias tables, correction handling, or streak logic replays the whole archive in seconds at zero API cost.
- The test suite splits: parse accuracy (transcript JSON only — instant, free, runs every commit) vs. transcription accuracy (needs audio — slow, costs money, runs on demand).

**This is the highest-leverage structural requirement in the document. Build it in P0.**

#### Triage table

| Transcript | Shots | Diagnosis | Fix lives in |
|---|---|---|---|
| ✅ | ❌ | Parse bug | Alias table, isolation thresholds, correction logic |
| ❌ | ❌ | ASR failure | Vocabulary, prompt bias, mic distance, model |
| ❌ | ✅ | Lucky — treat as ASR failure | Same; add as a fixture |
| ✅ | ✅ | Add to golden set | — |

### 7.2 Sessions are independent

No cross-session state, no history lookup, no rolling baselines. A session is processed using nothing but its own audio file.

This removes: the dedupe table (a session already in `sessions/` is skipped by path existence), rolling-window math, schema migration paths, and the entire class of bugs where a database and a folder disagree.

It also removes three things from the report — the trend sparkline, the delta-vs-median under the hero number, and the consecutive-days-logged footer. All needed history. The email gets shorter, which is fine.

### 7.3 The repo is the store

Code, session data, and fixtures live in one **private** git repo. Git gives versioned history, offsite backup on push, sync across machines, and keeps fixtures beside the data they validate, at zero operational cost.

```
hoops/
  src/  tests/  scripts/  config.yaml  .env(gitignored)
  CLAUDE.md  STATE.md  JOURNAL.md  docs/decisions/
  fixtures/                     ← committed: 10 audio files + manifest.csv
  sessions/2026/07/<sid>/
      transcript.json .txt shots.csv session.json    ← committed
      audio.m4a report.html strip.png                ← gitignored
  hoops.db                      ← gitignored
```

**Committed: text. Gitignored: binaries and anything derived.**

### 7.4 SQLite is generated, not committed

Three reasons, and the third costs a real capability:

1. **Merges are unresolvable.** Two machines processing sessions produce two divergent binary files. Git offers "keep mine or keep theirs" and one session's data dies quietly. Text session files never conflict — two sessions are two different files.
2. **History bloats.** SQLite page shuffling defeats delta compression; every commit stores a near-full copy.
3. **Diffs go opaque.** `git diff` on a `.db` says "binary files differ" — which throws away the regression technique in §11.6.

`scripts/build_db.py` rebuilds `hoops.db` from every committed `shots.csv` and `session.json` in seconds. Query it freely, delete it whenever. A rebuilt store cannot drift from its source; an incrementally-maintained one silently can.

**The pipeline never touches the database.** Capture writes files; analysis reads the DB. One direction only. A DB problem can never block or corrupt a session, and reprocessing needs no DELETE-then-INSERT.

### 7.5 Optional sinks

Session files are the source of truth; every other store is a projection. Each sink is an independent script, run on demand, never part of the pipeline.

| Sink | Script | When |
|---|---|---|
| SQLite | `build_db.py` | Local querying. P3. |
| DuckDB | none — `SELECT * FROM 'sessions/**/shots.csv'` | Ad-hoc, any time |
| Supabase / GuData | `push_supabase.py` | P4, to join against Oura/WHOOP already in that Postgres |

Adding one later costs ~20 lines, so nothing is lost by deferring. **A sink must never become the write path for capture** — that reintroduces a network dependency into the 6am path, breaks `git diff` reprocessing, and makes sessions non-reproducible offline.

### 7.6 Shot-level schema

| Column | Type | Notes |
|---|---|---|
| `session_id` | str | `YYYYMMDD-HHMMSS` local |
| `session_date_local` | date | Join key for daily data |
| `shot_num` | int | 1-indexed |
| `result` | enum | `make` \| `miss` |
| `t_call_s` | float | Seconds from recording start |
| `gap_s` | float\|null | Delta from previous call; null on shot 1 |
| `streak_after` | int | Running consecutive makes |
| `voided` | bool | Retracted by "scratch that" |
| `isolation_s` | float | min(gap_before, gap_after) — why this token was accepted |
| `confidence` | float | Transcriber confidence |
| `raw_token` | str | What was literally transcribed; keeps the mapping auditable |

**Timestamp semantics — document in the schema.** `t_call_s` is when I *said* the word, not when the ball left my hand. There is a roughly constant 1–2s lag. Constant offsets cancel under differencing, so `gap_s` is valid; absolute shot time is not. Nothing downstream may treat `t_call_s` as shot time.

### 7.7 Session-level schema

`session_id`, `session_date_local`, `start_time_local`, `shots_to_three`, `makes`, `misses`, `fg_pct`, `longest_make_streak`, `longest_miss_streak`, `time_to_first_make_s`, `median_gap_s`, `fastest_gap_s`, `slowest_gap_s`, `session_len_s`, `notes`, `quote_of_day`, `profanity_count`, `words_per_miss`, `invariants_passed`, `ambiguous_calls`, `transcriber`, `parser_version`.

`shots_to_three` is the headline. `session_len_s` answers "how long did it take to close it out." `longest_miss_streak` is the one that will sting.

### 7.8 The email report

The inbox is the only interface, so this is the entire user-facing product. Target: **glanceable in three seconds on a phone, depth available if wanted.** Tone: a beat writer filing a short recap of a very small game — fun, but it has to stay funny on day 200, which means short.

**Rendering constraint:** Gmail does not reliably render inline SVG and blocks base64 data URIs. Charts are **server-rendered PNG attached as CID** and referenced from the HTML body. The rich version ships as a separate HTML attachment.

| Block | Content |
|---|---|
| Subject | `🏀 Mon Jul 27 — 8 shots to close it out (4/8)` — fully readable from a lock-screen notification |
| Headline | One LLM-written line |
| Hero number | `8`, large. No comparison — there is no history to compare against. |
| **Shot strip** | Primary chart, PNG |
| Stat row | FG%, longest make streak, longest miss streak, session length, median gap |
| Recap | 2–3 LLM sentences |
| Quote of the day | Verbatim from transcript, with timestamp |
| Flags | Invariant failures and ambiguous calls, plainly stated. Rendered only when non-empty. |
| Footer | Session ID and processing timestamp |

**The shot strip.** Shots as circles along a horizontal time axis at their true `t_call_s` — filled = make, hollow = miss, with the closing three underlined. One chart carrying two dimensions: sequence left-to-right, and rhythm in the spacing, so hesitation is visible. Rejected: a makes-vs-misses bar chart (throws away order, which is the whole story) and a cumulative make-rate line (over-serious for an 8-shot sample).

**Attachments — every artifact in the session folder.** `shots.csv`, `session.json`, `transcript.json`, `transcript.txt`, `report.html`, `strip.png`, `audio.m4a`. Since daily audio is gitignored, **the email is its only offsite copy.** The inbox independently holds the complete dataset even if the Mac dies.

**Deliberately not in v1:** badges, streak gamification, achievements. Fun for two weeks, noise thereafter. The headline and the quote carry the whole personality budget.

---

## 8. Pipeline

```
[1] Capture      Shortcut → Record Audio → iCloud/Capture/inbox/
[2] Ingest       Poll every 5 min → stability check → skip if session dir exists
[3] Transcribe   Audio → word tokens with timestamps + confidence
[3b] Persist L2  Write transcript.json + .txt BEFORE parsing
[4] Parse        Tokens → isolation gate → vocabulary map → shot events
[5] Validate     Run invariants (§10)
[6] Repair       IF invariants fail → LLM reconciliation → re-validate
[7] Persist      Write shots.csv, session.json into the session folder
[8] Render       strip.png, report.html
[9] Report       Send email with all attachments
[10] Archive     Move audio into the session folder
```

Stage 3b is deliberately before parsing: if the parser throws, the expensive artifact is already on disk and the session is replayable.

A `replay` entry point starts at stage 4 from stored transcript JSON — one session or the whole archive.

Stage 6 is the only nondeterministic step, and only runs on failure. The default path is fully reproducible: same audio in, same table out.

---

## 9. Where AI belongs

**9.1 Transcription (always).** Requires word-level timestamps. This rules out on-device iOS transcription and OpenAI's `gpt-4o-transcribe` family, neither of which expose them. Use `whisper-1` with `response_format=verbose_json`, `timestamp_granularities[]=word`, and `prompt` biased to the vocabulary.

**9.2 Repair (conditional).** When the deterministic parse violates an invariant, hand the raw transcript plus the constraints to an LLM: the session ended when three consecutive makes occurred, calls come from this two-word vocabulary, and approximately N call-like tokens were seen. The stop rule is a strong constraint an LLM can exploit where a lookup table can't. Output is re-validated; if it still fails, flag rather than guess.

**9.3 Narrative (required).** Headline, 2–3 sentence recap, quote-of-the-day selection. This is what makes the email something I still read on day 60.

Guardrails, because this is the one place hallucination reaches my eyes daily:

- **No comparative or historical claims.** The model sees one session and nothing else, so "fastest close-out this month" is fabrication by construction. Forbid comparison outright — an unconstrained model reaches for exactly those phrasings because that's what sports recaps sound like. Statelessness makes this guardrail stricter, not looser.
- **No numbers.** The model receives stats as computed facts and may not produce any figure not given to it. All numbers in the email are template-injected.
- **Quote must be verbatim**, returned with its timestamp so it can be checked against the stored JSON.
- Cap at 3 sentences. Dry and specific over enthusiastic. Within-session dynamics — cold start, tightening rhythm, a long hesitation before the last shot — are fair game and visible in the shot table alone.
- If the call fails, the email still sends without these blocks. Reporting degrades; it never blocks.

**Explicitly not AI:** vocabulary mapping, isolation gating, streak logic, statistics, invariants. All deterministic, all unit-testable.

---

## 10. Invariants

Checked on every session. Cheap, label-free, and therefore continuous validation on live data.

| ID | Invariant | Rationale |
|---|---|---|
| I1 | Final three non-voided calls are all makes | The stop rule. Failure ⇒ a call was dropped or hallucinated. |
| I2 | `shots_to_three` ≥ 3 | Physical floor |
| I3 | No two calls closer than 1.5s | Faster than possible; indicates a duplicated token |
| I4 | No gap > 120s | Dropped call, or a pause needing review |
| I5 | Every matched token is in the configured vocabulary | Unknowns surface as `raw_token`, never coerced |
| I6 | No make-streak of 3 before the final three | The session would already have ended |
| I7 | Session directory does not already exist | Idempotency, filesystem-based |

**I1 and I6 together are the strongest tool available:** the correct sequence has *exactly one* run of three consecutive makes, at the very end. Any parse without that shape is provably wrong. Use this as the primary constraint in the repair pass.

---

## 11. Test and validation

### 11.1 Golden set — 10 fixtures

`fixtures/` holds 10 recordings and one `fixtures/manifest.csv`. The manifest is both the recording checklist and the ground truth: the owner fills in `filename`, `expected_calls` (space-separated, e.g. `miss make miss miss make make make`), `traps_planted`, and `expect_invariants_pass` as each is recorded. **Claude Code reads the manifest as the single source of truth — there are no per-fixture sidecar files.** At this size one CSV is simpler than ten YAMLs, and it stays diffable in git.

Coverage, deliberately cut from a longer list to the ten that carry the most information:

| ID | Covers |
|---|---|
| F01 | Baseline / control |
| **F02** | **Heavy commentary with planted bait words — the fixture that catches phantom shots** |
| F03 | Same, in `make`/`miss`, for the vocabulary comparison (§6.3) |
| F04 | Whisper-quiet at 10ft, face-down — the real 6am condition |
| F05 | Ball impacts over calls + background audio |
| F06 | 10-second timer beep — free timing ground truth |
| F07 | "scratch that" correction + trailing note |
| F08 | Minimum session, three makes |
| F09 | An uncalled shot — must flag, must not guess |
| F10 | Out of breath + 5 minutes of trailing silence |

**F02 is the one that matters most.** A parser can pass all nine others and still invent phantom shots from ordinary muttering, which is the failure mode that silently corrupts live sessions. Treat a phantom shot on F02 as a hard build failure.

**Degenerate inputs need no recordings.** Claude Code synthesizes them in tests: a 2-second file (misfire rejection), a silent file (zero-call path), a truncated file (partial-read handling). These exercise rejection paths and require nothing from the owner.

**Label immediately after recording**, while it's fresh — listen once and type the sequence into the manifest. A ten-shot session takes about a minute. Reconstructing a sequence from memory a week later is how a golden set becomes quietly wrong, which is worse than not having one.

### 11.2 Metrics and gates

| Metric | Gate |
|---|---|
| Call detection recall | ≥0.99 |
| Call detection precision | ≥0.99 |
| Classification accuracy | ≥0.98 |
| Sequence exact match | ≥0.90 |
| Timing MAE on `gap_s` | ≤0.5s |
| **Phantom shots on F02** | **Zero. Hard build failure otherwise.** |

Below gate ⇒ not shipped. The harness prints this table and runs on every parser or config change.

### 11.3 Test layers

- **Unit** — vocabulary mapping, isolation gating, correction handling, streak computation, invariants. Pure functions, synthetic token lists, no audio, fast.
- **Parse regression (fast, free, every commit)** — stored transcript JSON → shots, scored against `manifest.csv`. Never touches the transcriber.
- **Transcription regression (slow, costs money, on demand)** — audio → transcript JSON, scored against hand-labeled sequences. Run on model or vocabulary changes only.
- **Live invariants** — §10 on every real session, forever.

### 11.4 Vocabulary check

Compare F02 (`swish`/`brick`) against F03 (`make`/`miss`) on phantom-shot count under heavy commentary. That is the criterion that actually separates the candidates; a clean-session comparison would show nothing. Do this before tuning alias tables — a better word pair beats a longer alias list. Record the result in `docs/decisions/`.

### 11.5 Shadow period

First 14 real sessions: include the raw transcript in every email and eyeball the parse against it using the §7.1 triage table. Cheap human-in-the-loop validation on live data, and it grows the fixture corpus with genuinely representative recordings.

### 11.6 `git diff` as the regression test

Because session artifacts are committed text, the strongest safety net for parser work is free:

```
python -m hoops replay --all      # rewrites every shots.csv from stored transcripts
git diff --stat sessions/         # which sessions changed
git diff sessions/                # exactly which shots flipped, and how
```

Run before merging any parser or config change. A change that should be a no-op showing a diff is a bug; a change that should fix three sessions touching thirty is a bug. More informative than the metrics table, because it operates on all real sessions rather than ten curated ones.

---

## 12. Failure handling

| Failure | Behavior |
|---|---|
| Transcription API down | Retry 3× with backoff; leave file in inbox; retry next poll; email after 3 consecutive failed polls |
| Audio <5s | Move to `rejected/`, no email — a misfire is not an event |
| Audio >20min | Process, but flag prominently |
| Zero calls detected | Move to `needs_review/`, email with the raw transcript |
| Invariants fail after repair | Write the row anyway with `invariants_passed=false` and flag in the subject. Never silently drop, never silently guess. |
| Duplicate session | Skip, log, no email |
| SMTP failure | Data is already persisted; queue and retry next poll |
| LLM narrative fails | Send the email without narrative blocks |

**Governing principle: capture and persistence must never depend on reporting succeeding.** The data is the asset; the email is a view of it.

---

## 13. Tech stack

| Layer | Choice | Rationale |
|---|---|---|
| Capture | iOS Shortcuts, `Record Audio` | Native, one press, bindable to Action Button / Back Tap |
| Transport | iCloud Drive drop folder, flat inbox, type-prefixed filenames | §6.6–6.7, behind an `IngestSource` interface |
| Language | Python 3.12 | |
| Deps | `uv` | Fast, lockfile, reproducible |
| Transcription | Pluggable `Transcriber`. Default OpenAI `whisper-1`. Alternate `faster-whisper` local. | **Must return word-level timestamps** (§9.1). Local option matters for cost, privacy, offline — hence the interface. |
| Parse | Pure stdlib | Deterministic, trivially testable |
| LLM | Anthropic SDK, Sonnet | Repair + narrative |
| Store | Per-session folders in a private git repo | Text committed, binaries gitignored |
| Query | SQLite via `scripts/build_db.py`, or DuckDB over the CSV glob | Derived, gitignored, disposable |
| Charts | matplotlib → PNG | Gmail can't render inline SVG |
| Email | SMTP with Gmail app password | No API dependency in the delivery layer |
| Scheduling | `launchd` on the Mac, every 5 min | |
| Config | Single `config.yaml`: vocabulary, aliases, isolation thresholds, paths, timezone, email, transcriber | Everything tunable without touching code |
| Tests | `pytest` + committed fixtures | |

---

## 14. Phasing

| Phase | Scope | Done when |
|---|---|---|
| P0 | Walking skeleton: CLI, one audio file → transcript JSON on disk → printed shot table. Includes `replay`. | I can run it on a fixture, see a correct table, and re-run the parse without re-transcribing |
| P1 | Golden set wired in; regression harness; fixture gallery; vocabulary check; isolation thresholds tuned | §11.2 gates pass, including zero phantom shots on F02 |
| P2 | Drop folder, poller, session-folder writer, charts, email, `.gitignore`, `launchd` | A morning session produces an email with no intervention |
| P3 | Invariant flagging, shadow-mode transcript, `build_db.py` | 14 consecutive clean sessions; `git diff` after a full replay is clean |
| P4 | Aggregation. Build the DB or point DuckDB at `sessions/**/shots.csv`; join `shots_to_three` against Oura/WHOOP on `session_date_local`. | First sleep-vs-shooting scatter |

P0–P2 is the real product. P4 shouldn't start until there are ≥30 sessions — there's nothing to look at before that, and statelessness is what makes deferring it free.

---

### 14.1 Build order and the development loop

**Build in phase order, in one pass.** P0–P1 run entirely against `fixtures/` with no transport, no scheduler, and no email. Only P2 touches iCloud, `launchd`, and SMTP. Do not treat P2 as a separate later project — an unbuilt last mile means the system never runs daily, and "record a session and it just works" is the entire point.

**The core entry point takes a file path, not an event.** This is what keeps P2 thin:

```
hoops process <path.m4a>              # one file, end to end
hoops process-all fixtures/ --no-email # batch the golden set
hoops replay --all                     # re-parse from stored transcripts
```

The poller is a small wrapper that watches a folder and calls `process`. The emailer is a sink behind `--no-email`. Neither may complicate the parser, and neither is on the critical path for validating accuracy.

**Do not email during development.** `--no-email` writes `report.html` into the session folder for inspection in a browser. Send exactly one real email at the end of P2 as an SMTP smoke test.

**Fixture gallery.** `process-all` additionally emits `out/index.html`: every processed fixture on one page, showing the shot strip, the parsed sequence, the expected sequence from `manifest.csv`, and any mismatch highlighted. This is the primary working surface for P1 — threshold tuning, the vocabulary check, and report design all happen against this page.

**Fixtures may be incomplete at build time.** The owner records them in parallel with the build. Everything through P1's harness can be built against a partial set; only the §11.2 gate check requires the full ten.

## 15. Decisions already made — flip any of these deliberately

1. **iCloud drop folder over HTTP POST.** Resilience over instant notification (§6.6).
2. **Poller on the Mac.** Queued files make sleep a delay, not a failure (§6.6).
3. **One private git repo. Text committed, SQLite generated, daily audio gitignored and backed up by email** (§7.3–7.5).
4. **Sessions are fully independent.** No cross-session state anywhere (§7.2).
5. **Deterministic parse by default; LLM only on invariant failure** (§9).
6. **Transcripts persisted as full JSON; the parser runs from them alone** (§7.1).
7. **Vocabulary is `swish`/`brick`**, verified by the F02-vs-F03 comparison rather than assumed (§6.3, §11.4).
8. **All audio retained permanently** (§6.5).
9. **Flat inbox, type-prefixed filenames** — one watcher, N shortcuts (§6.7).
10. **`shots_to_three` is the headline metric.** FG% is secondary and confounded — sessions end on a hot streak by construction.

---

## 16. Known limitations

- **A shot taken but not called is unrecoverable.** No parser can invent a shot that was never spoken (fixture F17). The system's job is to flag it, not to guess. This is the floor on achievable accuracy and it is not the transcriber's fault.
- **`t_call_s` is not shot time** (§7.6).
- **FG% is biased upward** by the stop rule.

## 17. Open questions for the owner

- Is the hoop distance fixed day to day? If I move around, shot difficulty is an unlogged confound and may need a spoken distance call at session start.
- Should a missed morning produce an explicit "no session" record? Matters later for distinguishing "didn't shoot" from "logging broke."
