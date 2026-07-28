# hoops — morning free-throw voice log

Voice-recorded free-throw shots flow through transcription, parsing, validation, and stats into a daily emailed report. Spec: `docs/specs/2026-07-27-hoops-voice-log-design.md`.

## Quick Start

```bash
uv sync
cp .env.example .env
# Fill .env: OPENAI_API_KEY, ANTHROPIC_API_KEY, GMAIL_APP_PASSWORD
bash scripts/install_launchd.sh
```

## Commands

- `hoops process <path> [--no-email]` — Process one audio file end to end
- `hoops process-all <fixtures_dir> [--no-email]` — Process a fixtures dir + gallery
- `hoops replay [--all | <sid>]` — Re-parse from stored transcript.json
- `hoops poll` — One-shot inbox scan (scheduled to run every 300s)
- `hoops score` — Print the gate table from fixtures/manifest.csv
- `hoops transcribe-fixtures [--only <name>]` — Refresh committed fixture transcripts (paid API call)

## Owner Checklist

Before first use:
1. Fill `.env`: OPENAI_API_KEY, ANTHROPIC_API_KEY, GMAIL_APP_PASSWORD
2. Set up Apple Shortcut: records audio to iCloud Drive/Capture/inbox/ as `hoops__YYYYMMDD-HHMMSS.m4a`
3. Record golden-set fixtures in `fixtures/`, add manifest rows with `expected_calls` label immediately after recording
4. Run `bash scripts/install_launchd.sh` to schedule `poll` (every 300s)

## Fixture Recording

After recording a fixture:
1. Save to `fixtures/` with descriptive name
2. Add row to `fixtures/manifest.csv` with `expected_calls` column (label the expected shot table rows)
3. Commit both files
4. Tag dev01–dev04 labels when convenient for tracking session difficulty

## Shadow Period

First 14 real sessions: eyeball the transcript vs. the shots table to catch parser edge cases (PRD §11.5). If you spot phantom shots or skipped calls, file the raw audio and run `hoops score` before merging parser/config changes.

## Development

- Run tests: `uv run pytest` (paid tests excluded; `-m paid` to include)
- Verify gates: `uv run hoops score` must pass before merging parser or config changes
- Parser iteration: `uv run hoops replay --all` then `git diff sessions/` — a no-op change must produce no diff
- Text is committed; audio, binaries, and `hoops.db` are gitignored
