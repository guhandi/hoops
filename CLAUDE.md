# hoops — morning free-throw voice log

One-button voice data capture: Apple Shortcut records shot call-outs → iCloud drop folder → Mac pipeline (whisper-1 → isolation-gated parser → invariants → stats → emailed report). Basketball is instance #1 of a generalizable capture pattern.

**Read first:** `README.md` (purpose + usage) · `docs/architecture.md` (how it works, module map, failure handling) · `docs/shortcut-setup.md` (phone-side Apple Shortcut setup) · `docs/specs/2026-07-27-hoops-voice-log-design.md` (decisions — supersedes `docs/PRD-hoops-voice-log.md` where they conflict) · `docs/methodology.md` (golden-dataset methodology — read before capability work).

## Current status (2026-07-28)

- P0–P3 built and merged, plus this branch's work (vocab flip, per-recording sidecar, `--vocab` flag, golden-manifest migration) — tests green via `uv run pytest`.
- Dev fixtures dev01–dev04 transcribed with real whisper-1; transcripts committed in `fixtures/transcripts/`.
- The whisper bias prompt is deliberately **transcript-style, not instructions** (`transcribe.py:vocab_prompt`) — an instruction-phrased prompt got echoed over quiet audio as hallucinated vocabulary words (phantom calls). Don't regress this.
- Vocabulary (owner decision, `docs/specs/2026-07-28-finish-pipeline-design.md` — supersedes the earlier make/splash line above and PRD §6.3): production default `swish_brick` was widened 2026-07-28 for whisper transcription variance — `swish`/`splash`/`make` → make, `brick`/`break`/`miss` → miss; a named `make_miss` set (`make`→make, `miss`→miss) also exists. Per-recording override via a `<same-stem>.json` sidecar next to the audio (`{"vocabulary": "make_miss"}` or `{"vocab_map": {...}}`, now validated — a `vocab_map` must have exactly `make`/`miss` keys each mapped to a non-empty list of surface-form strings, or it routes to `needs_review/`); `hoops process` also takes `--vocab NAME`. All live in `config.yaml`.
- Interactive HTML session report shipped (2026-07-30): `report_html.py` generates self-contained replay with SVG charts + audio-synced movie mode and embedded audio; email slimmed to summary body (CID-inline strip.png) + single session-zip attachment (every session file, `report.html` inside); `narrative.json` persisted per session for replay reuse.

## Pending work

1. Grant Full Disk Access to `/Users/guhansundar/miniconda3/bin/python3.12` so the launchd poller can read `~/Documents` and iCloud Drive — every run currently dies with a TCC `PermissionError`. Verify with `launchctl list com.guhan.hoops` (status must be `0`) and a clean `logs/poll.log`, then do a real phone end-to-end test.
2. Before labeling R01/R02: refresh their transcript caches under the current (widened, six-call-word) bias prompt and decide whether `mess` joins the miss list — whisper heard R02's "miss" as "mess" ×6, and the cached transcript predates the widened prompt.
3. Wire `beep_interval_s`/`timing_ground_truth` into `score.py`'s `gap_mae` — the old `expected_gaps` column is gone from the manifest schema, so F06's timing gate currently reports a silent n/a PASS.
4. Owner labels `expected_calls` in `fixtures/manifest.csv` (dev01–dev04 are folded in as D01–D04, R01/R02 per item 2 above), then `uv run hoops score` → first accuracy baseline.
5. Record fixtures F03, F09, F10 (currently `NOT_RECORDED` in the manifest — the trickiest cases: conversational call words, a deliberately uncalled shot, out-of-breath + trailing silence).
6. Evaluate the PRD §11.2 gates once F01–F10 are fully recorded and labeled.
7. First 14 real sessions = shadow period (eyeball transcript vs shot table).
8. Phantom-shot check vs dev02 once labels exist — the bias prompt now carries six call words, widening the surface area for hallucinated vocabulary.

## Development rules

- Run tests: `uv run pytest` (paid API tests excluded by default; `-m paid` to include).
- Parser/config changes: `uv run hoops replay --all` then `git diff sessions/` — a no-op change must produce no diff; `uv run hoops score` must pass before merging (phantom shots on trap fixtures = hard failure).
- Text is committed; session audio, binaries, `out/`, and `hoops.db` are gitignored (fixture `.m4a` are deliberately committed). The pipeline never writes to `hoops.db` — it's rebuilt on demand by `scripts/build_db.py`.
- `parse.py` / `stats.py` / `invariants.py` stay pure stdlib, no I/O — that's the load-bearing, testable core.
- New capability ⇒ new labeled fixture first; gates (uv run hoops score) decide done. See docs/methodology.md.
