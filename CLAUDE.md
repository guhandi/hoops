# hoops — morning free-throw voice log

One-button voice data capture: Apple Shortcut records shot call-outs → iCloud drop folder → Mac pipeline (whisper-1 → isolation-gated parser → invariants → stats → emailed report). Basketball is instance #1 of a generalizable capture pattern.

**Read first:** `README.md` (purpose + usage) · `docs/architecture.md` (how it works, module map, failure handling) · `docs/specs/2026-07-27-hoops-voice-log-design.md` (decisions — supersedes `docs/PRD-hoops-voice-log.md` where they conflict).

## Current status (2026-07-28)

- P0–P3 built, reviewed, merged to main. 88 tests green (`uv run pytest`).
- Dev fixtures dev01–dev04 transcribed with real whisper-1; transcripts committed in `fixtures/transcripts/`.
- The whisper bias prompt is deliberately **transcript-style, not instructions** (`transcribe.py:vocab_prompt`) — an instruction-phrased prompt got echoed over quiet audio as hallucinated vocabulary words (phantom calls). Don't regress this.
- Vocabulary (owner decision, supersedes PRD §6.3): `make`/`splash` = make, `miss`/`brick` = miss. Lives in `config.yaml`.

## Pending work

1. Owner labels `expected_calls` for dev01–dev04 in `fixtures/manifest.csv`, then `uv run hoops score` → first accuracy baseline. (dev02 is the phantom-shot stress test — label it carefully.)
2. `.env` has OPENAI_API_KEY + ANTHROPIC_API_KEY; still missing `GMAIL_APP_PASSWORD` (blocks email).
3. One real-email smoke test: `uv run hoops process fixtures/dev/dev04.m4a` (no --no-email), then delete the created `sessions/` dir.
4. `bash scripts/install_launchd.sh` to schedule `hoops poll` every 5 min.
5. Apple Shortcut: Record Audio → save to `iCloud Drive/Capture/inbox/` as `hoops__YYYYMMDD-HHMMSS.m4a` (local time).
6. Golden set F01–F10 still to be recorded (PRD §11.1); the §11.2 gates are unevaluated until then. First 14 real sessions = shadow period (eyeball transcript vs shot table).
7. Verify `config.yaml` timezone (currently America/Los_Angeles).

## Development rules

- Run tests: `uv run pytest` (paid API tests excluded by default; `-m paid` to include).
- Parser/config changes: `uv run hoops replay --all` then `git diff sessions/` — a no-op change must produce no diff; `uv run hoops score` must pass before merging (phantom shots on trap fixtures = hard failure).
- Text is committed; audio, binaries, `out/`, and `hoops.db` are gitignored. The pipeline never writes to `hoops.db` — it's rebuilt on demand by `scripts/build_db.py`.
- `parse.py` / `stats.py` / `invariants.py` stay pure stdlib, no I/O — that's the load-bearing, testable core.
