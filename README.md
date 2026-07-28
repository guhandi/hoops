# hoops — one-button voice logging for daily basketball shots

Press one button on your phone, shoot until you make three in a row, call out each shot as it happens, stop the recording. Fifteen minutes later a structured shot table, a chart, and a short written recap are in your inbox — with zero further interaction. That's the whole product.

## Purpose

This project exists to make **data acquisition as close to free as possible** for things you do every day with your hands busy.

The concrete instance: every morning I shoot at my basketball hoop until I make three in a row. It's a consistent, self-terminating daily protocol that produces a clean scalar (*shots to three-in-a-row*) — but logging it by hand would kill the habit. Hands are busy, it's 6am, and any friction means the logging stops.

Voice is the only capture channel that costs nothing: the call-outs ("make", "miss") happen naturally as part of the activity. An Apple Shortcut bound to one Home Screen button records the audio and drops it in iCloud. Everything after that — transcription, parsing, validation, stats, charting, reporting — is machine work that runs unattended on a Mac.

At ~40 sessions the dataset becomes a real dependent variable: shots-to-three regressed against sleep, HRV, alcohol, late screens.

Basketball is instance #1. The capture pattern (one Shortcut, spoken vocabulary, a stop rule) generalizes to reps, sets, food logs, sprints — a second capture type is a config block and a duplicated Shortcut, not new code.

## How it works

```
[iPhone]  Apple Shortcut, one press
   └─ records audio → iCloud Drive/Capture/inbox/hoops__20260728-061204.m4a

[Mac]     launchd runs `hoops poll` every 5 minutes
   ├─ 1. Ingest      stability checks (iCloud partial-sync safe), dedupe
   ├─ 2. Transcribe  OpenAI whisper-1, word-level timestamps
   ├─ 3. Persist     full transcript JSON saved BEFORE parsing
   ├─ 4. Parse       isolation gating + vocabulary → shot calls (pure, deterministic)
   ├─ 5. Validate    invariants (e.g. session must end on exactly three straight makes)
   ├─ 6. Repair      only if invariants fail: LLM reconstructs the sequence, re-validated
   ├─ 7. Stats       shots-to-three, streaks, gaps, FG%
   ├─ 8. Render      shot-strip PNG + HTML report
   └─ 9. Email       report + every artifact attached (the email is the offsite backup)
```

**The spoken protocol** (all of it):

| You say | Meaning |
|---|---|
| `make` or `splash` | made shot |
| `miss` or `brick` | missed shot |
| `scratch that` | void the previous call (misspoke) |
| `note: <anything>` | free-text note captured verbatim into the dataset |

Everything else you say — muttering, cussing, commentary — is ignored by the parser (and mined for the report's quote-of-the-day). The key trick is **isolation gating**: a real call-out is an isolated word surrounded by silence; the word "make" inside "come on, make it" sits in continuous speech and is discarded. This is what keeps commentary from creating phantom shots.

**Where AI is and isn't used:** transcription (whisper-1) and two narrow LLM jobs — repairing a sequence that violates the stop rule, and writing the email's three-sentence recap (heavily guardrailed: no numbers, no invented quotes, no comparisons). Everything load-bearing — parsing, stats, validation — is deterministic, pure-stdlib Python, and unit-tested.

## Daily use

1. Tap the Shortcut. Set the phone down. Shoot, calling out each shot.
2. Make three in a row → say `note: whatever context matters` if you want → stop the recording.
3. Read the email when it arrives. That's it.

Bad sessions never disappear silently: too-short recordings are rejected, sessions with no detected calls are set aside and emailed with the raw transcript, invariant failures ship *flagged* in the subject line rather than guessed at.

## Setup (one-time)

```bash
git clone https://github.com/guhandi/hoops && cd hoops
uv sync
cp .env.example .env        # fill: OPENAI_API_KEY, ANTHROPIC_API_KEY, GMAIL_APP_PASSWORD
# edit config.yaml if needed: timezone, email address, vocabulary
bash scripts/install_launchd.sh   # schedules `hoops poll` every 5 minutes
```

Apple Shortcut: **Record Audio** → save to `iCloud Drive/Capture/inbox/` named `hoops__<YYYYMMDD-HHMMSS>.m4a` (local time). Bind it to the Action Button or a Home Screen icon so capture is one press.

## CLI

```
hoops process <path.m4a> [--no-email]      # one file, end to end
hoops process-all fixtures --no-email      # run the test-fixture set + visual gallery (out/index.html)
hoops replay [--all | <sid>]               # re-parse stored transcripts (free, no API)
hoops poll                                 # one-shot inbox scan (what launchd runs)
hoops score                                # accuracy gate table vs fixtures/manifest.csv
hoops transcribe-fixtures [--only <name>]  # refresh fixture transcripts (paid API call)
```

## Data layout

Every session is a self-contained folder — reprocessable from its own audio and nothing else:

```
sessions/2026/07/hoops__20260728-061204/
    audio.m4a          ground truth (gitignored; the email attachment is its offsite copy)
    transcript.json    full whisper response: words, timestamps, confidences
    transcript.txt     human-readable
    shots.csv          one row per shot: result, time, gap, streak, isolation, raw token
    session.json       session stats: shots_to_three, streaks, gaps, notes, flags
    report.html        the emailed report
    strip.png          shot chart: filled = make, hollow = miss, spacing = rhythm
```

The git repo **is** the store: text artifacts are committed, binaries are gitignored, and `scripts/build_db.py` rebuilds a disposable SQLite DB from the committed CSVs whenever you want to query. No live database sits in the capture path.

## Accuracy and testing

- `fixtures/` holds labeled recordings; `fixtures/manifest.csv` is the single source of truth for expected call sequences.
- `hoops score` prints the gate table (call recall/precision ≥ 0.99, sequence exact-match ≥ 0.90, **zero** phantom shots on bait-word fixtures — a hard failure).
- The parser runs from stored transcripts, so `hoops replay --all && git diff sessions/` is a free regression test over every real session ever recorded.
- `uv run pytest` — the full suite is offline and free; API-touching tests are opt-in (`-m paid`).

Deeper docs: [docs/architecture.md](docs/architecture.md) · design spec: [docs/specs/2026-07-27-hoops-voice-log-design.md](docs/specs/2026-07-27-hoops-voice-log-design.md) · original PRD: [docs/PRD-hoops-voice-log.md](docs/PRD-hoops-voice-log.md)

## Adding a second capture type later

The inbox is shared: every Shortcut writes `<type>__<timestamp>.m4a` into the same folder, and the poller routes by prefix. Adding "food" or "workout" logging is: duplicate the Shortcut with a new prefix, add a vocabulary block to `config.yaml`. One watcher, one code path.
