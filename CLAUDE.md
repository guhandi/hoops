# hoops — morning free-throw voice log

One-button voice data capture: Apple Shortcut records shot call-outs → iCloud drop folder → Mac pipeline (whisper-1 → isolation-gated parser → invariants → stats → interactive HTML report emailed). Basketball is instance #1 of a generalizable capture pattern; this repo is also the owner's golden example of how to build an AI-automated tool — see `docs/playbook.md`.

**Read first:** `README.md` (product + template intro) · `docs/playbook.md` (the build process) · `docs/architecture.md` (module map, failure handling) · `docs/methodology.md` (golden-dataset rules — read before capability work) · `docs/shortcut-setup.md` (phone-side setup). Dated specs in `docs/specs/` supersede earlier ones where named; the original PRD lives in `docs/archive/`.

## Current status (2026-07-30)

- **V1 live and daily-use** (tag `v1.0.0`): full phone → Mac → email loop verified end-to-end 2026-07-29/30; launchd poller healthy (FDA granted). Shadow period in progress — eyeball each emailed report vs memory for the first 14 real sessions.
- Email carries a slim summary body (CID-inline strip.png) + one session-zip attachment (every session file; open `report.html` inside for the interactive report — audio-synced movie replay, SVG charts, `src/hoops/report_html.py`); `narrative.json` persisted per session.
- Vocabulary: production default `swish_brick`, widened for whisper variance (`swish`/`splash`/`make` → make, `brick`/`break`/`miss` → miss); `make_miss` also defined; per-recording sidecar override + `--vocab` flag; all in `config.yaml`. The whisper bias prompt is deliberately transcript-style, not instructions (`transcribe.py:vocab_prompt`) — don't regress this.
- `fixtures/manifest.csv` is the single fixture file: hand columns are owner-only ground truth; `hoops score` writes back `heard_calls`/`got_calls`/`match`/`scored_at` machine columns.
- Session data (`sessions/`) is fully gitignored — local-only personal data.

## Pending work

1. Refresh R01/R02 transcript caches under the current widened bias prompt; decide whether `mess` joins the miss list (whisper heard R02's "miss" as "mess" ×6 on the old prompt).
2. Wire `beep_interval_s`/`timing_ground_truth` into `score.py`'s `gap_mae` — F06's timing gate currently reports a silent n/a PASS.
3. Finish labeling `expected_calls` in `fixtures/manifest.csv` (rows still `NEEDS_LABELING`), then evaluate the accuracy gates as the first real baseline.
4. Record fixtures F03, F09, F10 (`NOT_RECORDED` — conversational call words, deliberately uncalled shot, out-of-breath + trailing silence).
5. Complete the shadow period (14 real sessions), then trust the numbers.
6. Instance #2 of the capture pattern → extract the starter template (`docs/pattern/README.md` §8 of the playbook).

## Development rules

- Run tests: `uv run pytest` (paid API tests excluded by default; `-m paid` to include).
- Parser/config changes: `uv run hoops replay --all` must leave session parser outputs byte-identical — `sessions/` isn't tracked, so snapshot it first and compare with `git diff --no-index`; `uv run hoops score` must pass before merging (phantom shots on trap fixtures = hard failure).
- `parse.py` / `stats.py` / `invariants.py` stay pure stdlib, no I/O — the load-bearing, testable core.
- New capability ⇒ new labeled fixture first; gates decide done. See `docs/methodology.md`.
- Fixture `.m4a` are deliberately committed; `sessions/`, `out/`, logs, and `hoops.db` are not. The pipeline never writes `hoops.db` — `scripts/build_db.py` rebuilds it on demand.
- Update this file in the same change that alters what it describes.
