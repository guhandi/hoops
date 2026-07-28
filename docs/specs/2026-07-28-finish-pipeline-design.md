# Finish the pipeline: golden fixtures, real email, one-button automation

**Date:** 2026-07-28 · **Status:** approved design, pre-implementation
**Supersedes** the vocabulary decision in CLAUDE.md ("make/splash = make, miss/brick = miss") and PRD §6.3.

## Context

P0–P3 are built and merged; 88 tests green. The owner has now (a) put `GMAIL_ADDRESS` + `GMAIL_APP_PASSWORD` in `.env`, and (b) recorded 10 golden fixtures with a rich manifest at `audio_files/fixtures-manifest.csv`. Goal of this round: everything through the live one-button flow — email wiring, fixture migration, four end-to-end validation emails, launchd poller, and Apple Shortcut instructions.

**Acceptance:** four report emails arrive in the AI Gmail inbox — F00 (make/miss vocab), F01 (swish/brick), and the two real dated sessions (2026-07-26, 2026-07-27). The owner reviews those emails and iterates from there.

## Decisions (owner, 2026-07-28)

1. `audio_files/fixtures-manifest.csv` becomes **the** fixture manifest; old `fixtures/manifest.csv` schema retires; dev01–dev04 fold in as rows.
2. Validation emails go through the production path: a new `--vocab` flag on `hoops process`, not a fixture-harness email mode.
3. Scope is everything now (launchd + Shortcut docs), not just the validation emails.
4. **Production vocabulary is strict swish/brick**, but the mapping must be flexibly overridable per recording via a metadata sidecar next to the audio file.

## 1. Vocabulary

`config.yaml`:

```yaml
vocab_default: swish_brick
vocabularies:
  swish_brick: { make: [swish], miss: [brick] }
  make_miss:   { make: [make],  miss: [miss] }
```

The old `default` (make/splash) set retires. The whisper bias prompt continues to be derived from the active vocabulary (`transcribe.py:vocab_prompt`) — keep it transcript-style, never instruction-phrased (see CLAUDE.md; do not regress).

**Vocabulary resolution order** (in `pipeline.process_file`):
1. Explicit `vocab_name` argument (CLI `--vocab`, fixture-manifest `vocabulary` column)
2. Sidecar JSON next to the audio file (see §2)
3. `config.yaml` `vocab_default`

**Replay safety:** sessions must record the *resolved word mapping* (not just the name) in the session dir (extend the existing session metadata JSON). `replay_session` uses the persisted mapping when present, falling back to current config only for legacy sessions. This keeps `hoops replay --all` a no-op across vocabulary config changes and config renames. Existing dev sessions parsed under make/splash replay identically.

## 2. Per-recording sidecar

Optional `<same-stem>.json` next to any inbox audio file, e.g. `hoops__20260728-063000.json` beside `hoops__20260728-063000.m4a`:

```json
{ "vocabulary": "make_miss" }
```

or an inline mapping for one-off sets:

```json
{ "vocab_map": { "make": ["make", "splash"], "miss": ["miss"] } }
```

- The poller/ingest moves the sidecar into the session dir together with the audio.
- Malformed sidecar → route to `needs_review/` with the audio (never guess).
- No sidecar → `vocab_default`. The Apple Shortcut does not need to write sidecars today; this is the toggle mechanism for future vocabulary changes without code edits.

## 3. Email wiring

`config.py` load applies an env override: if `GMAIL_ADDRESS` is set, it replaces both `email.from` and `email.to` from `config.yaml`. `mailer.py` is untouched — it already logs in as `email.from` using `GMAIL_APP_PASSWORD` (`mailer.py:43-45`). Without this override the SMTP login would use `guhandiji@gmail.com` (still in config.yaml) with the AI account's password and fail.

## 4. Fixture migration

- Move all 10 `.m4a` from `audio_files/` into `fixtures/`; commit them (consistent with dev01–dev04 already tracked; ~13 MB).
- The new manifest replaces `fixtures/manifest.csv` (same path, new schema). dev01–dev04 added as rows: `category=dev`, `vocabulary=make_miss`, `status=recorded`. Delete `audio_files/`.
- `fixtures.py` adapts: read `vocabulary` column (was `vocab`), skip rows where `status != recorded` or `filename` is empty (F03/F09/F10 are `NOT_RECORDED`), tolerate extra metadata columns. Existing `fixtures/transcripts/dev__*.json` caches keep working; the 10 new files transcribe once via whisper-1 and cache.
- `expected_calls` is `NEEDS_LABELING` everywhere: scoring gates (phantom-shot hard failure etc.) remain unevaluated until the owner labels. Explicitly out of scope for this round.

## 5. `--vocab` flag and the validation run

`cli.py`: `hoops process` gains `--vocab <name>`, passed through as `process_file(..., vocab_name=...)` (parameter already exists).

Acceptance run (after all tests green):

```
uv run hoops process fixtures/F00_NormalMakeMiss.m4a   --vocab make_miss
uv run hoops process fixtures/F01_NormalSwishBrick.m4a --vocab swish_brick
uv run hoops process fixtures/07262026_MorningHoops.m4a
uv run hoops process fixtures/07272026_MorningHoops.m4a
```

(R01/R02 use the swish_brick default; manifest says CONFIRM — the emails themselves are the confirmation loop.) Test `sessions/` dirs are deleted after the owner confirms receipt.

## 6. Automation

- `bash scripts/install_launchd.sh` (script and `com.guhan.hoops.plist` exist); verify with `launchctl list | grep hoops`.
- New doc `docs/shortcut-setup.md`: Record Audio → Format Date `yyyyMMdd-HHmmss` → Save File to `iCloud Drive/Capture/inbox/` as `hoops__<formatted>.m4a`. Include a test-run checklist (record 30s on phone → email arrives within ~5–10 min).
- Delete the stray `Audio Recording 2026-07-27 at 4.43.16 PM.m4a` from the inbox (wrong prefix; poller ignores it, but it's clutter).

## Error handling

Existing paths unchanged (rejected/, needs_review/, pending_email retry). New: malformed sidecar → needs_review; unknown `--vocab`/sidecar vocabulary name → hard error naming the available sets.

## Testing & verification

- New unit tests: `GMAIL_ADDRESS` env override; new-manifest parsing (skip NOT_RECORDED, `vocabulary` column); sidecar resolution order + malformed sidecar routing; `--vocab` CLI plumbing; persisted-mapping replay.
- `uv run pytest` fully green; `uv run hoops replay --all` then `git diff sessions/` must be empty (vocab persistence makes this hold despite the default flip).
- End-to-end: the four validation emails arrive and look sane; then launchd installed and one real phone-recorded session flows inbox → email untouched.

## Out of scope

Labeling `expected_calls` (owner task, enables `hoops score` baseline); recording F03/F09/F10; evaluating PRD §11.2 gates; the 14-session shadow period.
