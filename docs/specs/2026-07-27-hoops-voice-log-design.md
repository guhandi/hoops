# Design — Hoops voice log

**Date:** 2026-07-27
**Status:** approved pending final review
**Base document:** [`docs/archive/PRD-hoops-voice-log.md`](../archive/PRD-hoops-voice-log.md). The PRD is the design for everything it covers. This spec records only (a) decisions that supersede the PRD, (b) decisions the PRD left open, and (c) the concrete build shape. Where this spec and the PRD conflict, this spec wins.

## 1. Scope of this build

Everything buildable now: PRD phases **P0–P3** in one pass — CLI pipeline, replay, fixture harness and gate scoring, iCloud drop-folder poller, charts, email, `launchd`, invariant flagging, `build_db.py`.

**Out of scope:** P4 aggregation (PRD gates it on ≥30 real sessions) and the Supabase sink.

## 2. Decisions superseding the PRD

### 2.1 Vocabulary (supersedes PRD §6.3's `swish`/`brick`)

Owner decision 2026-07-27:

```yaml
vocabularies:
  default:
    make: [make, splash]
    miss: [miss, brick]
```

The PRD's phantom-shot concern about `make`/`miss` (§6.2) stands. It is handled by, in order: isolation gating (primary, unchanged), the F02-style bait-word fixture measuring the actual phantom rate before gates pass, and the fact that a vocabulary swap is a one-line config edit if live data shows phantoms. The `swish`/`brick`-vs-`make`/`miss` comparison of PRD §11.4 becomes a comparison between this vocabulary and any candidate replacement, run only if F02-style fixtures show phantom shots. Record outcomes in `docs/decisions/`.

### 2.2 Standalone repo

The tool lives in `~/Documents/hoops`, its own private git repo with GitHub remote `guhandi/hoops` — not in the AI_tools monorepo. The PRD's repo-is-the-store design (§7.3) applies to this repo.

## 3. Decisions the PRD left open

### 3.1 Session ID fallback for unprefixed filenames

If the filename parses as `hoops__YYYYMMDD-HHMMSS.m4a`, the session ID comes from it. Otherwise (dev files like `dev01.m4a`), derive `YYYYMMDD-HHMMSS` from file mtime in the configured timezone. `session.json` records `session_id_source: "filename" | "mtime"`. No other filename parsing exists.

### 3.2 Fixture transcripts are committed

`fixtures/transcripts/<name>.json` caches each fixture's transcriber output, committed to git. The parse-regression suite reads only these — it runs on every commit, free, with no API key. Re-transcription happens only via an explicit `hoops transcribe-fixtures [--only <name>]`, run when the model, prompt bias, or audio changes. Without this cache the PRD's "fast, free, every commit" tier (§11.3) would not exist.

### 3.3 Manifest columns: `vocab` and `gating`

`fixtures/manifest.csv` remains the single source of truth (PRD §11.1) with columns:

```
filename, expected_calls, traps_planted, expect_invariants_pass, vocab, gating, notes
```

- `vocab`: named vocabulary from config; blank = `default`. Lets a comparison fixture use an alternate word set.
- `gating`: `yes` rows feed the §11.2 gate table and can fail the build; `no` rows are processed and shown in the gallery but never fail anything.

### 3.4 Dev fixtures

The four early recordings are committed as non-gating fixtures (`gating: no`, `vocab: default` — they were recorded with make/miss, which the default vocabulary now covers):

| File | Original name |
|---|---|
| `fixtures/dev/dev01.m4a` | Bball shot 2.m4a |
| `fixtures/dev/dev02.m4a` | Morning basketball shot.m4a |
| `fixtures/dev/dev03.m4a` | Normal make-miss 10am beep.m4a |
| `fixtures/dev/dev04.m4a` | Normal make-miss only.m4a |

Owner fills in `expected_calls` for each when convenient; blank `expected_calls` = processed in the gallery, unscored. The gating golden set (F01–F10) is recorded separately per PRD §11.1.

## 4. Build shape

### 4.1 Repo layout

```
hoops/
  pyproject.toml            # uv-managed, Python 3.12
  config.yaml               # vocabularies, isolation thresholds, paths, tz, email, transcriber
  .env                      # OPENAI_API_KEY, ANTHROPIC_API_KEY, GMAIL_APP_PASSWORD (gitignored)
  src/hoops/
    cli.py                  # entry points below
    ingest.py               # IngestSource interface + iCloud folder source (stability, .icloud stubs)
    transcribe.py           # Transcriber interface + whisper-1 backend (verbose_json, word timestamps, vocab-biased prompt)
    parse.py                # pure functions: tokens → isolation gate → vocab map → voids → notes → shot rows
    stats.py                # shot table → session stats, streaks
    invariants.py           # I1–I7
    repair.py               # Anthropic Sonnet reconciliation, only on invariant failure, output re-validated
    render.py               # strip.png (matplotlib), report.html, fixture gallery out/index.html
    narrative.py            # headline/recap/quote, guardrailed per PRD §9.3
    mailer.py               # SMTP + Gmail app password, CID-attached PNG, all artifacts attached
    session.py              # session folder read/write, schemas (PRD §7.6–7.7)
    config.py               # yaml load, vocabulary registry
  scripts/build_db.py
  tests/                    # markers: unit / parse / paid
  fixtures/                 # audio + manifest.csv + transcripts/ (all committed)
  sessions/YYYY/MM/<sid>/   # text committed; audio.m4a, report.html, strip.png gitignored
  docs/archive/PRD-hoops-voice-log.md  docs/specs/  docs/decisions/
```

### 4.2 CLI surface

```
hoops process <path.m4a> [--no-email]      # one file, end to end
hoops process-all fixtures/ --no-email     # golden set + gallery → out/index.html
hoops replay [--all | <sid>]               # stage 4 onward, from stored transcript.json
hoops poll                                 # one-shot inbox scan; launchd calls this
hoops score                                # prints the §11.2 gate table from manifest.csv
hoops transcribe-fixtures [--only <name>]  # refresh committed fixture transcripts (paid)
```

### 4.3 Transcription

whisper-1 API only in this build (`response_format=verbose_json`, `timestamp_granularities[]=word`, prompt biased to the active vocabulary), behind the `Transcriber` interface so `faster-whisper` remains a later drop-in. Rationale: fewest moving parts, best-tested word timestamps, and cost is ~$0.02/session because parsing replays from stored JSON for free.

### 4.4 Parser

Pure functions over the word array; no I/O, no clock. Isolation gate uses `isolation_high=0.4s` / `isolation_low=0.15s` from config (tuned on fixtures). Tokens between thresholds go to an ambiguous list feeding both the email flags block and the repair pass. "scratch that" voids the previous non-voided call; text after "note:" is captured verbatim.

### 4.5 Poller and scheduling

`launchd` plist `~/Library/LaunchAgents/com.guhan.hoops.plist` runs `hoops poll` every 5 minutes. Poll: list `iCloud Drive/Capture/inbox/`, route by `hoops__` prefix, apply stability rules (size unchanged across two consecutive polls via a small state file, mtime >60s), force-download `.icloud` stubs, skip existing session dirs, call `process`. A lock file prevents overlapping runs. Failure behavior per PRD §12; SMTP failure leaves a `pending_email` marker in the session folder, retried next poll.

### 4.6 AI calls

Repair and narrative use the Anthropic SDK (Sonnet) per PRD §9.2–9.3 with all stated guardrails: repair output re-validated (still-failing ⇒ flag, never guess); narrative receives computed stats only, produces no numbers, no comparative or historical claims, verbatim timestamped quote, ≤3 sentences; any AI failure degrades the email, never blocks it.

### 4.7 Testing

pytest markers: `unit` (synthetic token lists), `parse` (committed fixture transcripts → shots, scored against manifest; every commit), `paid` (audio → transcript; on demand). Degenerate inputs (2s file, silent file, truncated m4a) synthesized in tests. `hoops score` prints the PRD §11.2 gate table; a phantom shot on the bait-word fixture exits non-zero. `git diff sessions/` after `hoops replay --all` is the live-data regression check (PRD §11.6).

## 5. Owner setup checklist

Everything is done by the build except:

1. Fill `.env` (template provided): `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GMAIL_APP_PASSWORD`.
2. Point the Shortcut's `Record Audio` save step at `iCloud Drive/Capture/inbox/` with filename `hoops__<local YYYYMMDD-HHMMSS>.m4a`.
3. Record the F01–F10 golden set and fill `fixtures/manifest.csv` rows as you go (PRD §11.1), plus `expected_calls` for dev01–dev04 when convenient.
