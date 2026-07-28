# hoops — morning free-throw voice log

One-button voice data capture: Apple Shortcut records shot call-outs → iCloud drop folder → Mac pipeline (whisper-1 → isolation-gated parser → invariants → stats → emailed report). Basketball is instance #1 of a generalizable capture pattern.

**Read first:** `README.md` (purpose + usage) · `docs/architecture.md` (how it works, module map, failure handling) · `docs/shortcut-setup.md` (phone-side Apple Shortcut setup) · `docs/specs/2026-07-27-hoops-voice-log-design.md` (decisions — supersedes `docs/PRD-hoops-voice-log.md` where they conflict).

## Current status (2026-07-28)

- P0–P3 built and merged, plus this branch's work (vocab flip, per-recording sidecar, `--vocab` flag, golden-manifest migration) — 98 tests green (`uv run pytest`).
- Dev fixtures dev01–dev04 transcribed with real whisper-1; transcripts committed in `fixtures/transcripts/`.
- The whisper bias prompt is deliberately **transcript-style, not instructions** (`transcribe.py:vocab_prompt`) — an instruction-phrased prompt got echoed over quiet audio as hallucinated vocabulary words (phantom calls). Don't regress this.
- Vocabulary (owner decision, `docs/specs/2026-07-28-finish-pipeline-design.md` — supersedes the earlier make/splash line above and PRD §6.3): production default is `swish_brick` (`swish` = make, `brick` = miss); a named `make_miss` set also exists. Per-recording override via a `<same-stem>.json` sidecar next to the audio (`{"vocabulary": "make_miss"}` or `{"vocab_map": {...}}`); a malformed sidecar routes to `needs_review/` rather than silently falling back. `hoops process` also takes `--vocab NAME`. All live in `config.yaml`.

## Pending work

1. Run go-live validation (4 emails) per Task 8, then `bash scripts/install_launchd.sh` to schedule `hoops poll` every 5 min.
2. Owner labels `expected_calls` in the new golden `fixtures/manifest.csv` (dev01–dev04 are folded in as D01–D04), then `uv run hoops score` → first accuracy baseline.
3. Record fixtures F03, F09, F10 (currently `NOT_RECORDED` in the manifest — the trickiest cases: conversational call words, a deliberately uncalled shot, out-of-breath + trailing silence).
4. Evaluate the PRD §11.2 gates once F01–F10 are fully recorded and labeled.
5. First 14 real sessions = shadow period (eyeball transcript vs shot table).

## Development rules

- Run tests: `uv run pytest` (paid API tests excluded by default; `-m paid` to include).
- Parser/config changes: `uv run hoops replay --all` then `git diff sessions/` — a no-op change must produce no diff; `uv run hoops score` must pass before merging (phantom shots on trap fixtures = hard failure).
- Text is committed; audio, binaries, `out/`, and `hoops.db` are gitignored. The pipeline never writes to `hoops.db` — it's rebuilt on demand by `scripts/build_db.py`.
- `parse.py` / `stats.py` / `invariants.py` stay pure stdlib, no I/O — that's the load-bearing, testable core.
