# Golden-template packaging — design

**Date:** 2026-07-30 · **Status:** approved for implementation
**Goal:** hoops V1 is live and daily-usable. This work packages the repo as the owner's **golden example of how to build an AI-automated personal tool** — one manifest with all fixture data, a clean tree, and documentation that makes the build process repeatable for tool #2.

Decisions made in brainstorming (owner, 2026-07-30):
- **Form:** exemplary repo + playbook doc. This repo IS the example; a playbook makes the process repeatable. No extracted starter template yet (design it when instance #2 exists).
- **Manifest:** one file, score fills output columns in place.
- **Docs:** curated reading path + `docs/archive/` for superseded material.
- **Session data:** `sessions/` fully gitignored — daily personal data (audio, transcripts, stats) never touches GitHub. Committed fixture recordings remain the public example data.

## A. Manifest consolidation

`fixtures/manifest.csv` is the single source of truth for fixtures. Its schema gains four **machine columns**, appended after the existing columns:

| column | written by | meaning |
|---|---|---|
| `heard_calls` | `hoops score` | raw surface tokens the parser matched, lowercase, space-separated (e.g. `brick brick splash`) |
| `got_calls` | `hoops score` | canonical sequence produced (`miss miss make`), space-separated |
| `match` | `hoops score` | `TRUE`/`FALSE` — `got_calls` equals `expected_calls` (blank when the row wasn't scored: `NOT_RECORDED`, unlabeled) |
| `scored_at` | `hoops score` | ISO date of the scoring run that last wrote this row |

Rules:
- `hoops score` rewrites **only** those four columns, for the rows it actually scored; every hand-edited column is preserved byte-for-byte. A test locks this: run the writer against a fixture manifest, assert all hand columns identical before/after.
- Hand columns remain owner-only (`expected_calls`, `label_status`, …) — code never writes them.
- `fixtures/manifest_scored.csv` is **deleted**. Its content is one score run away from regenerated; nothing unique is lost (its sequences were verified to map 1:1 onto existing ground truth where labeled).
- The gate table printed to the terminal is unchanged; the CSV write-back is additive.

## B. Repo cleanup

- `.gitignore`: replace the four `sessions/**/...` lines with `sessions/`; add `.playwright-mcp/`.
- Remove stray untracked debris from the working tree (`.playwright-mcp/`, `fixtures/manifest_scored.csv` per §A).
- Fix the three robustness nits parked in the V1 final review, each with a covering test, in `src/hoops/report_html.py`:
  1. `_gap_chart_svg` bar width floored (`max(..., 1)`) so >148-shot sessions can't emit negative SVG widths.
  2. The duplicated word↔shot timestamp match (`_build_data.call_num` and `_transcript`) extracted into one shared helper (single tolerance constant).
  3. JSON blob escaping switched from `</` → `<\/` to escaping every `<` as `\u003c` (closes the script-data-double-escape corner entirely; tests' blob parsing unaffected since `<` is a valid JSON string escape).
- No other refactoring. `parse.py` / `stats.py` / `invariants.py` untouched.

## C. Golden-example documentation

**`docs/playbook.md` — the centerpiece.** The repeatable process for building an AI-automated personal tool, written from how hoops was actually built. Every step names the concrete artifact in this repo as the worked example:

1. **Idea → owner-decision spec** — write the product intent and the decisions only the owner can make (vocabulary, protocol, delivery). Example: `docs/specs/2026-07-27-hoops-voice-log-design.md`, and the superseding chain through the later specs.
2. **CLAUDE.md as the working agreement** — current status, hard development rules, gates, read-first pointers. The AI reads it every session; keeping it truthful is a maintenance discipline, not documentation.
3. **Design before code** — each feature gets a brainstormed spec (`docs/specs/`), then an implementation plan of bite-sized TDD tasks (`docs/superpowers/plans/2026-07-30-interactive-report.md` is the fullest example), executed with per-task review.
4. **Golden dataset before capability** — record/label fixtures for a behavior before building it (`fixtures/manifest.csv`, `docs/methodology.md`). Trap fixtures encode the failure modes you fear (phantom shots, chatty audio).
5. **Gates decide done, not demos** — `hoops score` accuracy/phantom gates, `hoops replay --all` no-diff discipline, invariants as runtime self-checks.
6. **Ship small, verify live** — merge only green, watch one real end-to-end run (phone → email) before trusting it; then a shadow period of eyeballing outputs.
7. **Record why, not just what** — decisions log (`docs/decisions/`), experiment writeups (`docs/writeups/2026-07-30-empirical-model-selection.md`), benchmark showcase (`docs/showcase/`).
8. **Generalize from instances, not upfront** — the capture pattern doc (`docs/pattern/README.md`) was abstracted after instance #1 worked; the starter template waits for instance #2.

**Root `README.md`** — keep the product story; add a "Use this repo as a template" section: the reading path (README → `docs/playbook.md` → `docs/architecture.md` → `docs/methodology.md` → `docs/pattern/README.md`), one paragraph on what to imitate.

**`docs/README.md`** — a ~20-line index of the docs tree: what each directory holds, what's current, what's archived.

**`docs/archive/`** — receives `docs/PRD-hoops-voice-log.md` and `docs/plans/2026-07-27-hoops-voice-log.md`, with a short `docs/archive/README.md` stating what superseded them (the dated specs; CLAUDE.md). Links elsewhere in the repo that point at moved files are updated. Everything else (specs/, superpowers/, decisions/, writeups/, showcase/, pattern/, methodology, architecture, shortcut-setup) stays in place — the trail is the example.

**`CLAUDE.md`** — rewritten fresh: V1-live status (dated), development rules (same substance: pytest, replay no-diff, score gates, pure-stdlib core, fixture-first), corrected pending work (drop the completed TCC/FDA item; keep R01/R02 transcript refresh, `gap_mae` wiring, F03/F09/F10 recording, remaining shadow-period sessions, manifest labeling), read-first pointers matching the new reading path.

## Error handling

- Score write-back is atomic: write to a temp file in `fixtures/`, then `os.replace` — a crash mid-run can't corrupt the manifest.
- Rows that can't be scored (missing audio, `NOT_RECORDED`, no label) keep their machine columns untouched from the previous run; `scored_at` is stamped only on rows actually scored.

## Testing & verification

- New tests: manifest write-back (machine columns populated; hand columns byte-identical; unscored rows untouched; atomic temp-file path exercised), the three report_html nits.
- Full `uv run pytest` green; `uv run hoops score` run once to populate the new columns (committed); `uv run hoops replay --all` no-op gate.
- Manual link-check over playbook/README/docs-index references (every named path exists).
