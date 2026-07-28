# Finish the Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire up real email via `GMAIL_ADDRESS`, flip production vocabulary to strict swish/brick with per-recording sidecar overrides, migrate to the new golden-fixture manifest, add `--vocab` to `hoops process`, then go live: four validation emails + launchd poller + Shortcut doc.

**Architecture:** Python 3 + uv package. Pure-stdlib core (`parse.py`/`stats.py`/`invariants.py` — do not add I/O there). Pipeline orchestration in `src/hoops/pipeline.py`, config in `src/hoops/config.py`, CLI in `src/hoops/cli.py`. Spec: `docs/specs/2026-07-28-finish-pipeline-design.md`.

**Tech Stack:** Python, pytest (`uv run pytest`), whisper-1 via OpenAI API (paid tests marked `-m paid`), Gmail SMTP SSL.

## Global Constraints

- Run tests with `uv run pytest` from repo root `/Users/guhansundar/Documents/hoops`. All tests must stay green after every task.
- The whisper bias prompt (`transcribe.py:vocab_prompt`) stays transcript-style — NEVER instruction-phrased (regression risk: hallucinated vocab words over quiet audio).
- `parse.py` / `stats.py` / `invariants.py` stay pure stdlib, no I/O.
- Commit after each task; end commit messages with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Vocabulary names are exactly `swish_brick` and `make_miss` (they must match the manifest's `vocabulary` column).
- `.env` already contains `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`. Never print or commit their values.

---

### Task 1: `GMAIL_ADDRESS` env override in config

**Files:**
- Modify: `src/hoops/config.py` (load_config, ~line 42-68)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `load_config()` returns `Config.email` with `from`/`to` replaced by `os.environ["GMAIL_ADDRESS"]` when that env var is set and non-empty. `smtp_host`/`smtp_port` untouched.

- [ ] **Step 1: Write the failing test** (append to `tests/test_config.py`)

```python
def test_gmail_address_env_overrides_from_and_to(monkeypatch):
    monkeypatch.setenv("GMAIL_ADDRESS", "robot@example.com")
    cfg = load_config(REPO / "config.yaml")
    assert cfg.email["from"] == "robot@example.com"
    assert cfg.email["to"] == "robot@example.com"
    assert cfg.email["smtp_host"] == "smtp.gmail.com"

def test_no_gmail_address_env_keeps_yaml_values(monkeypatch):
    monkeypatch.delenv("GMAIL_ADDRESS", raising=False)
    cfg = load_config(REPO / "config.yaml")
    assert cfg.email["from"] == "guhandiji@gmail.com"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: `test_gmail_address_env_overrides_from_and_to` FAILS (assert on "robot@example.com").
Caution: your shell may leak the real `GMAIL_ADDRESS` via `.env` loading — pytest does not load `.env`, so `test_no_gmail_address_env_keeps_yaml_values` should pass even before the change; the monkeypatch.delenv guards it either way.

- [ ] **Step 3: Implement** — in `src/hoops/config.py`, add `import os` at top, then in `load_config` replace `email=raw["email"],` with:

```python
        email=_email_with_env_override(raw["email"]),
```

and add above `load_config`:

```python
def _email_with_env_override(email: dict) -> dict:
    addr = os.environ.get("GMAIL_ADDRESS", "").strip()
    if addr:
        return {**email, "from": addr, "to": addr}
    return dict(email)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_config.py tests/test_mailer.py -v` → all PASS, then `uv run pytest` → all green.

- [ ] **Step 5: Commit**

```bash
git add src/hoops/config.py tests/test_config.py
git commit -m "feat(config): GMAIL_ADDRESS env overrides email from/to"
```

---

### Task 2: Flip vocabulary to strict swish_brick + named make_miss

**Files:**
- Modify: `config.yaml` (vocab block, lines 6-9)
- Modify: `tests/test_config.py` (two existing tests)
- Modify: `tests/test_pipeline.py`, `tests/test_ingest.py`, `tests/test_fixtures.py`, `tests/test_score.py` (fake-envelope surface words)

**Interfaces:**
- Produces: `cfg.vocab()` → swish_brick (`{"swish": "make", "brick": "miss"}`); `cfg.vocab("make_miss")` → `{"make": "make", "miss": "miss"}`. The name `default` no longer exists.

- [ ] **Step 1: Edit `config.yaml`** — replace the vocab block with:

```yaml
vocab_default: swish_brick
vocabularies:
  swish_brick:
    make: [swish]
    miss: [brick]
  make_miss:
    make: [make]
    miss: [miss]
```

- [ ] **Step 2: Run full suite to enumerate breakage**

Run: `uv run pytest -x -q 2>&1 | tail -30` — expect failures in test_config (mapping asserts) and in any test whose fake envelope words relied on the old default (test_pipeline, test_ingest, test_fixtures, test_score sandboxes copy the real `config.yaml`).

- [ ] **Step 3: Fix `tests/test_config.py`** — update the two assertions:

```python
    assert cfg.vocab().surface_to_canonical == {"swish": "make", "brick": "miss"}
```

and in `test_named_vocab_lookup`:

```python
    assert cfg.vocab("swish_brick").name == "swish_brick"
    assert cfg.vocab("make_miss").surface_to_canonical == {"make": "make", "miss": "miss"}
    with pytest.raises(KeyError):
        cfg.vocab("default")
```

- [ ] **Step 4: Fix fake-envelope tests** — mechanical rule: in `tests/test_pipeline.py`, `tests/test_ingest.py`, `tests/test_fixtures.py`, `tests/test_score.py`, wherever a fake envelope/word list uses the surface words `"make"`/`"miss"` (e.g. `GOOD = [("miss", 5.0, 5.3), ("make", 12.0, 12.3), ...]`), replace surface `"make"` → `"swish"` and surface `"miss"` → `"brick"`. Expected **results** (canonical `"make"`/`"miss"` in `expected_calls` columns, `e1["got"]`, `shots.csv` assertions) stay UNCHANGED — swish maps to make, brick maps to miss. Old-schema manifest literals inside these tests (e.g. `"dev/dev01.m4a,miss make make make,..."`) keep canonical words in `expected_calls`. Tests that build a `Vocabulary` directly (`test_parse.py`, `test_invariants.py`, `test_repair.py`, `test_transcribe.py`) need NO changes.

- [ ] **Step 5: Run full suite**

Run: `uv run pytest` → all 88+ green. Also confirm the bias prompt: `uv run python -c "from hoops.config import load_config; from hoops.transcribe import vocab_prompt; from pathlib import Path; print(vocab_prompt(load_config(Path('config.yaml')).vocab()))"` → transcript-style string containing `swish` and `brick`, no imperative phrasing.

- [ ] **Step 6: Commit**

```bash
git add config.yaml tests/
git commit -m "feat(vocab): strict swish_brick production default, make_miss named set"
```

---

### Task 3: Persist resolved vocabulary; replay prefers the persisted mapping

**Files:**
- Modify: `src/hoops/pipeline.py` (`process_file` ~line 99-112, `replay_session` ~line 152-180)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `Vocabulary` (`src/hoops/config.py:7`) with `.name` and `.surface_to_canonical`.
- Produces: `session.json` gains keys `vocab_name: str` and `vocab_map: dict[str, str]`. `replay_session(sdir, cfg, vocab_name=None)` resolution order: explicit `vocab_name` arg → persisted `vocab_map` in session.json → `cfg.vocab(None)`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_pipeline.py`; reuse that file's existing sandbox fixture, FakeTranscriber, and audio-copy idioms — read the file first and mirror them):

```python
def test_session_json_persists_vocab_and_replay_uses_it(sandbox_cfg_and_audio, monkeypatch):
    cfg, audio = sandbox_cfg_and_audio          # adapt to the file's actual fixture name
    env = make_env([("make", 5.0, 5.3), ("miss", 12.0, 12.3)], duration=30.0)
    out = process_file(audio, cfg, FakeTranscriber(env), email=False,
                       vocab_name="make_miss", cached_env=env, repair_enabled=False)
    assert out.status == "ok"
    stats = read_session_json(out.session_dir)
    assert stats["vocab_name"] == "make_miss"
    assert stats["vocab_map"] == {"make": "make", "miss": "miss"}
    # replay with NO vocab arg must reuse the persisted make_miss mapping,
    # even though the config default is swish_brick
    r = replay_session(out.session_dir, cfg)
    assert [row["result"] for row in r.rows] == ["make", "miss"]
    assert read_session_json(out.session_dir)["vocab_name"] == "make_miss"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_pipeline.py -v -k persists_vocab`
Expected: FAIL with KeyError `'vocab_name'`.

- [ ] **Step 3: Implement** — in `process_file`, right after `stats["session_id_source"] = sid_source` (line ~109):

```python
    stats["vocab_name"] = vocab.name
    stats["vocab_map"] = vocab.surface_to_canonical
```

In `replay_session`, replace `vocab = cfg.vocab(vocab_name)` (line 154) and the later `old = read_session_json(sdir)` block with a single read up front:

```python
    try:
        old = read_session_json(sdir)
    except FileNotFoundError:
        old = {}
    if vocab_name:
        vocab = cfg.vocab(vocab_name)
    elif old.get("vocab_map"):
        vocab = Vocabulary(name=old.get("vocab_name", "persisted"),
                           surface_to_canonical=old["vocab_map"])
    else:
        vocab = cfg.vocab(None)
```

(add `Vocabulary` to the `from .config import` line), and where the old block copied `quote_of_day`/`session_id_source`, use the already-read `old` dict (drop the inner try/except). Before `write_session_json(sdir, stats)` in replay, also set `stats["vocab_name"], stats["vocab_map"] = vocab.name, vocab.surface_to_canonical`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_pipeline.py -v` then `uv run pytest` → all green.

- [ ] **Step 5: Commit**

```bash
git add src/hoops/pipeline.py tests/test_pipeline.py
git commit -m "feat(replay): persist resolved vocabulary in session.json; replay prefers it"
```

---

### Task 4: Per-recording sidecar vocabulary

**Files:**
- Modify: `src/hoops/pipeline.py` (new helpers + `process_file` head + archive block)
- Test: `tests/test_pipeline.py`, `tests/test_ingest.py`

**Interfaces:**
- Produces: for audio `X.m4a`, optional sidecar `X.json` containing `{"vocabulary": "<name>"}` or `{"vocab_map": {"make": [...], "miss": [...]}}`. Resolution order in `process_file`: explicit `vocab_name` param → sidecar → `cfg.vocab(None)`. Malformed sidecar → audio+sidecar land in `needs_review/` (flat files), `Outcome(status="needs_review")`. On success the sidecar is archived into the session dir as `vocab.json`.
- Produces: `SidecarError(ValueError)` exported from `pipeline.py`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_pipeline.py`, mirroring its sandbox idioms):

```python
def test_sidecar_named_vocab_applies(sandbox_cfg_and_audio):
    cfg, audio = sandbox_cfg_and_audio
    audio.with_suffix(".json").write_text('{"vocabulary": "make_miss"}')
    env = make_env([("make", 5.0, 5.3), ("miss", 12.0, 12.3)], duration=30.0)
    out = process_file(audio, cfg, FakeTranscriber(env), email=False,
                       cached_env=env, repair_enabled=False, archive="move")
    assert out.status == "ok"
    assert [r["result"] for r in out.rows] == ["make", "miss"]
    assert (out.session_dir / "vocab.json").exists()
    assert not audio.with_suffix(".json").exists()      # consumed

def test_sidecar_inline_map_applies(sandbox_cfg_and_audio):
    cfg, audio = sandbox_cfg_and_audio
    audio.with_suffix(".json").write_text('{"vocab_map": {"make": ["bucket"], "miss": ["clank"]}}')
    env = make_env([("bucket", 5.0, 5.3), ("clank", 12.0, 12.3)], duration=30.0)
    out = process_file(audio, cfg, FakeTranscriber(env), email=False,
                       cached_env=env, repair_enabled=False)
    assert out.status == "ok"
    assert [r["result"] for r in out.rows] == ["make", "miss"]

def test_malformed_sidecar_routes_to_needs_review(sandbox_cfg_and_audio):
    cfg, audio = sandbox_cfg_and_audio
    audio.with_suffix(".json").write_text("{not json")
    out = process_file(audio, cfg, FakeTranscriber(make_env([])), email=False,
                       archive="move")
    assert out.status == "needs_review"
    nr = cfg.repo_root / "needs_review"
    assert (nr / audio.name).exists() and (nr / audio.with_suffix(".json").name).exists()

def test_explicit_vocab_name_beats_sidecar(sandbox_cfg_and_audio):
    cfg, audio = sandbox_cfg_and_audio
    audio.with_suffix(".json").write_text('{"vocab_map": {"make": ["bucket"], "miss": ["clank"]}}')
    env = make_env([("make", 5.0, 5.3)], duration=30.0)
    out = process_file(audio, cfg, FakeTranscriber(env), email=False,
                       vocab_name="make_miss", cached_env=env, repair_enabled=False)
    assert out.status == "ok" and [r["result"] for r in out.rows] == ["make"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_pipeline.py -v -k sidecar`
Expected: FAIL (sidecar silently ignored — wrong results / missing vocab.json).

- [ ] **Step 3: Implement** — in `src/hoops/pipeline.py` add near the top:

```python
import json

class SidecarError(ValueError):
    pass

def _resolve_vocab(path: Path, cfg: Config, vocab_name: str | None):
    """Returns (vocab, sidecar_path | None). Raises SidecarError on a bad sidecar."""
    if vocab_name:
        return cfg.vocab(vocab_name), None
    sc = path.with_suffix(".json")
    if not sc.exists():
        return cfg.vocab(None), None
    try:
        data = json.loads(sc.read_text())
        if not isinstance(data, dict):
            raise SidecarError("sidecar is not a JSON object")
        if "vocabulary" in data:
            try:
                return cfg.vocab(str(data["vocabulary"])), sc
            except KeyError:
                raise SidecarError(f"unknown vocabulary {data['vocabulary']!r} — "
                                   f"available: {', '.join(sorted(cfg.vocabularies))}")
        if "vocab_map" in data:
            return Vocabulary.from_dict("sidecar", data["vocab_map"]), sc
        raise SidecarError("sidecar needs a 'vocabulary' or 'vocab_map' key")
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as e:
        raise e if isinstance(e, SidecarError) else SidecarError(f"unreadable sidecar: {e}")
```

In `process_file`, replace `vocab = cfg.vocab(vocab_name)` (line 45) — move resolution to AFTER `sid, sid_source = session_id_for(...)` and the `base = ...` line so the error path has `sid`/`base`:

```python
    try:
        vocab, sidecar = _resolve_vocab(path, cfg, vocab_name)
    except SidecarError as e:
        nr = base / "needs_review"
        nr.mkdir(exist_ok=True)
        if archive != "none":
            op = shutil.move if archive == "move" else shutil.copy
            op(str(path), str(nr / path.name))
            sc = path.with_suffix(".json")
            if sc.exists():
                op(str(sc), str(nr / sc.name))
        return Outcome(status="needs_review", sid=sid, flags=[f"sidecar: {e}"])
```

In the success archive block (after the audio move/copy, ~line 125-128):

```python
    if archive in ("move", "copy") and sidecar is not None and sidecar.exists():
        (shutil.move if archive == "move" else shutil.copy)(str(sidecar), str(sdir / "vocab.json"))
```

Add `Vocabulary` to the config import if Task 3 didn't already. Known edge (accept, don't fix): duplicate-session hits return before sidecar archiving, leaving the sidecar in the inbox — harmless, poller ignores non-`.m4a` files.

- [ ] **Step 4: Add poller integration test** (append to `tests/test_ingest.py`, mirroring its sandbox/fake-transcriber idioms): drop `hoops__20260727-070000.m4a` (copy a dev fixture audio) plus sidecar `hoops__20260727-070000.json` = `{"vocabulary": "make_miss"}` into the sandbox inbox, prime `.poll_state.json`/mtime so `stable_files` sees it ready (copy the idiom from an existing poll test in that file), run `poll_once`, assert the session dir contains `vocab.json` and the inbox is empty of both files.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_pipeline.py tests/test_ingest.py -v` then full `uv run pytest` → green.

- [ ] **Step 6: Commit**

```bash
git add src/hoops/pipeline.py tests/test_pipeline.py tests/test_ingest.py
git commit -m "feat(pipeline): per-recording vocabulary sidecar with needs_review routing"
```

---

### Task 5: Migrate to the new golden-fixture manifest

**Files:**
- Move: `audio_files/*.m4a` → `fixtures/` (10 files); delete `audio_files/` (including its `fixtures-manifest.csv` after content is absorbed)
- Replace: `fixtures/manifest.csv` (new schema, + 4 dev rows)
- Modify: `src/hoops/fixtures.py` (`run_fixture` vocab column, `run_all` skip rule), `src/hoops/score.py` (`score_fixture`, `score_and_print` gating), `src/hoops/cli.py` (transcribe-fixtures skip rule)
- Test: `tests/test_fixtures.py`, `tests/test_score.py` (sandbox manifests → new schema)

**Interfaces:**
- Consumes: new manifest columns — `filename, fixture_id, category, status, vocabulary, duration_s, size_bytes, audio_format, conditions, what_it_tests, use_for, timing_ground_truth, beep_interval_s, expected_calls, expected_shot_count, expect_invariants_pass, contains_correction, contains_note, traps_planted, label_status, notes`.
- Produces: rows run only when `status == "recorded"` and `filename` non-empty; vocab from `vocabulary` column; gating = `use_for == "GATE"`; `expect_invariants_pass` truthy when upper() in `("TRUE", "YES")`.

- [ ] **Step 1: Move the audio and build the new manifest**

```bash
mv audio_files/*.m4a fixtures/
```

Then Write `fixtures/manifest.csv`: the full content of `audio_files/fixtures-manifest.csv` verbatim, PLUS these 4 rows appended (schema-matched; canonical make/miss words for dev fixtures):

```csv
dev/dev01.m4a,D01,dev,recorded,make_miss,,,aac,dev fixture,Bball shot 2,regression,FALSE,,,,TRUE,,,,NEEDS_LABELING,folded in from old manifest
dev/dev02.m4a,D02,dev,recorded,make_miss,,,aac,dev fixture,Morning basketball shot — phantom-shot stress test,regression,FALSE,,,,TRUE,,,,NEEDS_LABELING,label expected_calls carefully
dev/dev03.m4a,D03,dev,recorded,make_miss,,,aac,dev fixture,Normal make-miss 10am beep,regression,FALSE,,,,TRUE,,,,NEEDS_LABELING,folded in from old manifest
dev/dev04.m4a,D04,dev,recorded,make_miss,,,aac,dev fixture,Normal make-miss only,regression,FALSE,,,,TRUE,,,,NEEDS_LABELING,folded in from old manifest
```

Then `rm -rf audio_files/`.

- [ ] **Step 2: Write the failing tests** — update `tests/test_fixtures.py` sandbox manifest literal to the new schema (header above; one row):

```
dev/dev01.m4a,D01,dev,recorded,make_miss,,,aac,x,x,regression,FALSE,,make miss ...canonical expected...,,TRUE,,,,LABELED,smoke
```

(keep the same expected_calls this test already asserted, canonical words). Add a skip test:

```python
def test_run_all_skips_not_recorded_and_blank_filename(sandbox):
    (sandbox.repo_root / "fixtures" / "manifest.csv").write_text(
        NEW_HEADER + "\n"
        ",F03,fixture,NOT_RECORDED,swish_brick,,,,x,x,GATE,FALSE,,,,TRUE,,,,NOT_RECORDED,missing\n")
    entries = run_all(sandbox, FakeTranscriber(make_env([])), sandbox.repo_root / "fixtures")
    assert entries == []
```

(define `NEW_HEADER` as the full column header string at module top). Update `tests/test_score.py` sandbox manifest the same way — its gating rows get `use_for` = `GATE`, `expect_invariants_pass` = `TRUE`/`FALSE` instead of `gating=yes`, column `vocabulary` instead of `vocab`.

- [ ] **Step 3: Run to verify failures**

Run: `uv run pytest tests/test_fixtures.py tests/test_score.py -v`
Expected: FAIL — `run_fixture` reads dead `vocab` column (vocab lookup KeyError or wrong parse), `run_all` chokes/emits the NOT_RECORDED row, score gating logic reads dead `gating` column.

- [ ] **Step 4: Implement**

`src/hoops/fixtures.py` — in `run_fixture`, change `vocab_name=row.get("vocab") or None` → `vocab_name=row.get("vocabulary") or None`. In `run_all`'s loop, before the exists() check:

```python
        if not row.get("filename") or row.get("status", "recorded") != "recorded":
            continue
```

`src/hoops/score.py` — in `score_fixture`: `row.get("vocab")` → `row.get("vocabulary")`, and replace the `invariants_ok_expected=` line with:

```python
        invariants_ok_expected=row.get("expect_invariants_pass", "TRUE").strip().upper() in ("TRUE", "YES"),
```

In `score_and_print`, replace the gating classification line with:

```python
        (gating if r.get("use_for", "").strip().upper() == "GATE" else info).append(s)
```

`src/hoops/cli.py` — in the `transcribe-fixtures` loop, first line inside `for row in ...`:

```python
            if not row.get("filename") or row.get("status", "recorded") != "recorded":
                continue
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest` → all green. Then a real-manifest dry check: `uv run python -c "from hoops.fixtures import read_manifest; from pathlib import Path; rows=read_manifest(Path('fixtures/manifest.csv')); print(len(rows), [r['fixture_id'] for r in rows if r['status']=='recorded'])"` → 17 rows, 14 recorded (R01 R02 F01 F02 F04 F05 F06 F08 F07 F07b D01–D04).

- [ ] **Step 6: Commit**

```bash
git add fixtures/ src/hoops/fixtures.py src/hoops/score.py src/hoops/cli.py tests/
git rm -r --cached audio_files 2>/dev/null; true
git commit -m "feat(fixtures): golden manifest schema becomes source of truth; 10 golden recordings committed"
```

(Audio files are committed intentionally — dev01–dev04 already are; ~13 MB total.)

---

### Task 6: `--vocab` flag on `hoops process`

**Files:**
- Modify: `src/hoops/cli.py` (`build_parser` process subparser line 7-9; `main` process branch line 43-47)
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `hoops process <path> [--no-email] [--vocab NAME]`; unknown NAME → prints available sets, exit code 2.

- [ ] **Step 1: Write the failing test** (append to `tests/test_cli.py`):

```python
def test_process_accepts_vocab_flag():
    p = build_parser()
    args = p.parse_args(["process", "some.m4a", "--vocab", "make_miss"])
    assert args.vocab == "make_miss"
    assert p.parse_args(["process", "some.m4a"]).vocab is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_cli.py -v` → FAIL (`unrecognized arguments: --vocab`).

- [ ] **Step 3: Implement** — in `build_parser`, after the `--no-email` line for `process`:

```python
    sp.add_argument("--vocab", default=None,
                    help="vocabulary name from config.yaml (default: vocab_default)")
```

In `main`'s process branch, before calling `process_file`:

```python
        if args.vocab and args.vocab not in cfg.vocabularies:
            print(f"unknown vocabulary '{args.vocab}' — available: "
                  f"{', '.join(sorted(cfg.vocabularies))}")
            return 2
```

and pass `vocab_name=args.vocab` to `process_file`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_cli.py -v`, then `uv run pytest` → green. Manual check: `uv run hoops process nope.m4a --vocab bogus` → prints available sets, exit 2 (verify with `echo $?`).

- [ ] **Step 5: Commit**

```bash
git add src/hoops/cli.py tests/test_cli.py
git commit -m "feat(cli): --vocab override on hoops process"
```

---

### Task 7: Docs — Shortcut setup guide + CLAUDE.md refresh

**Files:**
- Create: `docs/shortcut-setup.md`
- Modify: `CLAUDE.md` (vocabulary line, status, pending list)

- [ ] **Step 1: Write `docs/shortcut-setup.md`** with exactly this content skeleton (flesh prose, keep all steps):

```markdown
# Apple Shortcut: one-button hoops capture

Phone-side setup. ~5 minutes, done once.

## Build the Shortcut
1. Shortcuts app → + → rename to "Hoops".
2. Add action **Record Audio** — Start Recording: On Tap, Finish Recording: On Tap.
3. Add action **Format Date**: Date = Current Date, Format = Custom, string `yyyyMMdd-HHmmss`.
4. Add action **Rename File**: rename *Recorded Audio* to `hoops__[Formatted Date]` (insert the Format Date variable).
5. Add action **Save File**: file = *Renamed File*, Service = iCloud Drive, Destination Path `/Capture/inbox/`, Ask Where To Save = OFF, Overwrite = OFF.
6. Add to Home Screen (Shortcut settings → Add to Home Screen) for the one-button experience.

## Use
Tap → call shots out loud (say **swish** for a make, **brick** for a miss; "scratch that" voids the last call; "note: ..." records a note) → tap Stop. The Mac polls every 5 minutes; the report email lands a few minutes after that.

## Vocabulary override (optional)
To use different call words for one recording, drop a JSON sidecar next to the audio with the same stem, e.g. `hoops__20260728-063000.json`:
{"vocabulary": "make_miss"}   — or —   {"vocab_map": {"make": ["bucket"], "miss": ["clank"]}}

## Verify end to end
1. Record a 30-second test with a few calls.
2. Within ~10 min: email report arrives. If not, check Mac: `tail -50 logs/poll.log`, `ls needs_review/ rejected/`.
```

- [ ] **Step 2: Update `CLAUDE.md`** — change the vocabulary bullet to: production default `swish_brick` (swish = make, brick = miss), `make_miss` named set; per-recording JSON sidecar override; decision recorded in `docs/specs/2026-07-28-finish-pipeline-design.md` (supersedes the 2026-07-28 make/splash line and PRD §6.3). Update "Pending work": remove items now done (email wiring, golden recordings, launchd if installed by Task 8), keep labeling `expected_calls` (now for the new manifest), F03/F09/F10 recording, gate evaluation, shadow period.

- [ ] **Step 3: Commit**

```bash
git add docs/shortcut-setup.md CLAUDE.md
git commit -m "docs: Shortcut one-button setup guide; CLAUDE.md reflects swish_brick decision"
```

---

### Task 8: Go-live verification (checkpoint task — human reviews outcomes)

**Files:** none created (runs commands; owner deletes test sessions after review)

- [ ] **Step 1: Full gates**

```bash
uv run pytest                    # all green
uv run hoops replay --all        # no sessions yet → prints nothing; exit 0
uv run hoops score               # "No gating fixtures with cached transcripts yet" → exit 0
```

- [ ] **Step 2: Cache golden transcripts + gallery** (paid whisper, ~25 min of audio ≈ $0.15)

```bash
uv run hoops process-all fixtures
```

Expected: 14 fixtures processed (transcripts cached under `fixtures/transcripts/`), gallery at `out/index.html`. Commit the new transcript caches:

```bash
git add fixtures/transcripts/
git commit -m "chore(fixtures): commit golden transcript caches from first whisper pass"
```

- [ ] **Step 3: The four validation emails** (the acceptance test — email ON):

```bash
uv run hoops process fixtures/F00_NormalMakeMiss.m4a   --vocab make_miss
uv run hoops process fixtures/F01_NormalSwishBrick.m4a --vocab swish_brick
uv run hoops process fixtures/07262026_MorningHoops.m4a
uv run hoops process fixtures/07272026_MorningHoops.m4a
```

Expected: each prints `<sid>: ok — sessions/...`. Four report emails arrive at the `GMAIL_ADDRESS` inbox. If a send fails, the session dir gets a `pending_email` marker — inspect the exception by rerunning send manually before blaming credentials. NOTE: these filenames lack the `hoops__` prefix, so sids come from file mtime — that's expected (`session_id_source: mtime`).

- [ ] **Step 4: Owner review gate** — STOP. Owner reviews the four emails (subject, stats sanity, strip image, narrative). Only after confirmation:

```bash
rm -rf sessions/    # test sessions; real ones start fresh
```

- [ ] **Step 5: Install the poller**

```bash
bash scripts/install_launchd.sh
launchctl list | grep com.guhan.hoops   # loaded
```

- [ ] **Step 6: Clean the inbox** — remove the stray non-matching recording (owner-approved in spec):

```bash
rm "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Capture/inbox/Audio Recording 2026-07-27 at 4.43.16 PM.m4a"
```

(`$HOME` not `~` — a quoted tilde does not expand; the path contains spaces so the quotes are required).

- [ ] **Step 7: End-to-end phone test** — owner records a real 30s session via the Shortcut (per `docs/shortcut-setup.md`); email arrives untouched within ~10 min. That closes the one-button loop.
