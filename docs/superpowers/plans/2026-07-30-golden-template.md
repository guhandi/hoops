# Golden-Template Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One manifest CSV holding ground truth AND machine-scored outputs, a cleaned repo tree, and documentation (playbook + refreshed CLAUDE.md/README) that makes hoops the owner's reusable example of how to build an AI-automated personal tool.

**Architecture:** `hoops score` gains an in-place manifest write-back (four machine columns, hand columns untouchable, atomic replace). Three parked robustness nits in `report_html.py` get fixed. Docs get a curated reading path: new `docs/playbook.md` centerpiece, README template section, `docs/README.md` index, `docs/archive/` for superseded material, CLAUDE.md rewritten.

**Tech Stack:** Python 3.12 stdlib only (`csv`, `os.replace`, `datetime`). No new dependencies. Markdown for docs.

**Spec:** `docs/specs/2026-07-30-golden-template-packaging-design.md` — read it first.

## Global Constraints

- **No new dependencies**; `parse.py` / `stats.py` / `invariants.py` untouched.
- Machine columns (exact names): `heard_calls`, `got_calls`, `match`, `scored_at` — appended after existing columns. `hoops score` rewrites ONLY these four, only on rows it scored; every hand column byte-identical before/after (test-enforced).
- Manifest write is atomic: temp file in `fixtures/` then `os.replace`.
- `fixtures/manifest_scored.csv` deleted; `sessions/` fully gitignored; `.playwright-mcp/` gitignored.
- All tests: `uv run pytest` from repo root. Gates before merge: full suite green, `uv run hoops replay --all` no-op, `uv run hoops score` exit code unchanged vs today (pre-existing FAILs are the repo's labeling state, not regressions).
- Every commit ends with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- Branch: `feat/golden-template` (exists; spec committed at 30fd8ee).
- Docs tone: match the repo's existing docs — first person owner voice, concrete, no marketing fluff.

## Reference: current shapes

- `read_manifest(path) -> list[dict]` (`src/hoops/fixtures.py:7-9`) — plain `csv.DictReader`.
- `FixtureScore` dataclass (`src/hoops/score.py:13-26`): fields `name, expected, got, matched, inserted, deleted, misclassified, exact, gap_mae, traps, invariants_ok_expected, invariants_ok_got`. `score_fixture(row, cfg)` returns None when `expected_calls` empty or no cached transcript; `live` calls are computed at `score.py:38` (`[c for c in parsed.calls if not c.voided]`) — each `c` has `.raw_token` and `.result`.
- `score_and_print(cfg) -> int` (`score.py:79-115`) reads `cfg.repo_root / "fixtures" / "manifest.csv"`, splits gating/info, prints table, returns 0/1.
- `tests/test_score.py` has `sandbox` fixture (tmp repo with config + transcript cache dir), `put_cache`, `row()` helpers, and a `NEW_HEADER` constant with the current 21-column header.
- Manifest hand columns (21): `filename,fixture_id,category,status,vocabulary,duration_s,size_bytes,audio_format,conditions,what_it_tests,use_for,timing_ground_truth,beep_interval_s,expected_calls,expected_shot_count,expect_invariants_pass,contains_correction,contains_note,traps_planted,label_status,notes`.

---

### Task 1: Manifest write-back in `score.py`

**Files:**
- Modify: `src/hoops/score.py`
- Delete: `fixtures/manifest_scored.csv`
- Test: `tests/test_score.py`

**Interfaces:**
- Consumes: existing `FixtureScore`, `score_fixture`, `score_and_print`, `read_manifest`.
- Produces: `FixtureScore` gains field `heard: list` (raw tokens of live calls, in order). New function `update_manifest(manifest_path: Path, scores: list[FixtureScore], scored_at: str) -> None` in `hoops.score` — scores keyed by `FixtureScore.name` == manifest `filename`. `score_and_print` calls it after scoring with `scored_at=datetime.date.today().isoformat()`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_score.py`:

```python
MACHINE_COLS = ["heard_calls", "got_calls", "match", "scored_at"]

def manifest_file(tmp_path, rows_text):
    p = tmp_path / "fixtures" / "manifest.csv"
    p.parent.mkdir(exist_ok=True)
    p.write_text(NEW_HEADER + "\n" + rows_text)
    return p

def _row_text(filename, expected_calls):
    cells = [""] * 21
    cells[0] = filename
    cells[13] = expected_calls
    cells[20] = "note, with comma"          # comma forces quoting — survives round-trip
    return ",".join(f'"{c}"' if "," in c else c for c in cells)

def test_update_manifest_writes_machine_columns(sandbox, tmp_path):
    from hoops.score import update_manifest
    put_cache(sandbox, "f01.m4a", CLEAN)
    s = score_fixture(row("f01.m4a", "miss make make make"), sandbox)
    p = manifest_file(tmp_path, _row_text("f01.m4a", "miss make make make") + "\n")
    update_manifest(p, [s], scored_at="2026-07-30")
    import csv
    rows = list(csv.DictReader(p.open()))
    assert rows[0]["heard_calls"] == "brick swish swish swish"
    assert rows[0]["got_calls"] == "miss make make make"
    assert rows[0]["match"] == "TRUE"
    assert rows[0]["scored_at"] == "2026-07-30"

def test_update_manifest_preserves_hand_columns(sandbox, tmp_path):
    from hoops.score import update_manifest
    put_cache(sandbox, "f01.m4a", CLEAN)
    s = score_fixture(row("f01.m4a", "miss make miss make"), sandbox)   # mismatch
    p = manifest_file(tmp_path, _row_text("f01.m4a", "miss make miss make") + "\n")
    import csv
    before = list(csv.DictReader(p.open()))
    update_manifest(p, [s], scored_at="2026-07-30")
    after = list(csv.DictReader(p.open()))
    hand_cols = NEW_HEADER.split(",")
    for b, a in zip(before, after):
        assert {k: b[k] for k in hand_cols} == {k: a[k] for k in hand_cols}
    assert after[0]["match"] == "FALSE"
    assert after[0]["notes"] == "note, with comma"    # quoting survived round-trip

def test_update_manifest_leaves_unscored_rows_blank(sandbox, tmp_path):
    from hoops.score import update_manifest
    put_cache(sandbox, "f01.m4a", CLEAN)
    s = score_fixture(row("f01.m4a", "miss make make make"), sandbox)
    p = manifest_file(tmp_path,
                      _row_text("f01.m4a", "miss make make make") + "\n" +
                      _row_text("f99.m4a", "") + "\n")     # never scored
    update_manifest(p, [s], scored_at="2026-07-30")
    import csv
    rows = list(csv.DictReader(p.open()))
    assert rows[1]["heard_calls"] == "" and rows[1]["scored_at"] == ""

def test_update_manifest_idempotent_columns(sandbox, tmp_path):
    from hoops.score import update_manifest
    put_cache(sandbox, "f01.m4a", CLEAN)
    s = score_fixture(row("f01.m4a", "miss make make make"), sandbox)
    p = manifest_file(tmp_path, _row_text("f01.m4a", "miss make make make") + "\n")
    update_manifest(p, [s], scored_at="2026-07-30")
    update_manifest(p, [s], scored_at="2026-07-31")       # second run
    header = p.read_text().splitlines()[0]
    assert header.count("heard_calls") == 1               # columns not duplicated
    import csv
    assert list(csv.DictReader(p.open()))[0]["scored_at"] == "2026-07-31"

def test_score_fixture_records_heard_tokens(sandbox):
    put_cache(sandbox, "f01.m4a", CLEAN)
    s = score_fixture(row("f01.m4a", "miss make make make"), sandbox)
    assert s.heard == ["brick", "swish", "swish", "swish"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_score.py -q`
Expected: 5 new tests FAIL (`ImportError: cannot import name 'update_manifest'` / `AttributeError: 'FixtureScore' object has no attribute 'heard'`); existing tests pass.

- [ ] **Step 3: Implement**

In `src/hoops/score.py`:

a. Add `heard: list` to the `FixtureScore` dataclass (after `got: list`).

b. In `score_fixture`, capture raw tokens next to `got` (line ~39):

```python
    got = [c.result for c in live]
    heard = [c.raw_token for c in live]
```
and pass `heard=heard` in the `FixtureScore(...)` constructor.

c. Add the writer (near the top, after GATES; imports: add `csv, os, tempfile` and `from datetime import date` to the existing import lines):

```python
MACHINE_COLS = ["heard_calls", "got_calls", "match", "scored_at"]

def update_manifest(manifest_path, scores, scored_at: str) -> None:
    """Write machine columns back into the manifest. Hand columns are never
    touched; only rows present in `scores` are updated; atomic replace."""
    by_name = {s.name: s for s in scores}
    with manifest_path.open(newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)
    for col in MACHINE_COLS:
        if col not in fieldnames:
            fieldnames.append(col)
    for r in rows:
        for col in MACHINE_COLS:
            r.setdefault(col, "")
        s = by_name.get(r["filename"])
        if s is None:
            continue
        r["heard_calls"] = " ".join(s.heard)
        r["got_calls"] = " ".join(s.got)
        r["match"] = "TRUE" if s.got == s.expected else "FALSE"
        r["scored_at"] = scored_at
    fd, tmp = tempfile.mkstemp(dir=manifest_path.parent, suffix=".csv")
    try:
        with os.fdopen(fd, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, manifest_path)
    except BaseException:
        os.unlink(tmp)
        raise
```

d. In `score_and_print`, after the gating/info split loop (line ~87), write back everything that was scored:

```python
    scored = gating + info
    if scored:
        update_manifest(cfg.repo_root / "fixtures" / "manifest.csv", scored,
                        scored_at=date.today().isoformat())
```

e. Delete the stray file: `rm fixtures/manifest_scored.csv` (it is untracked — no git rm needed; verify with `git status`).

Note on `match` semantics: computed from `s.got == s.expected` (same as `s.exact`) — spec says blank only for rows never scored, which falls out of the `by_name` lookup.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_score.py -q`, then full `uv run pytest -q`.
Expected: all green. Also run `uv run hoops score > /dev/null; git diff --stat fixtures/manifest.csv` — the real manifest gains the four columns with populated rows for cached fixtures; eyeball `git diff fixtures/manifest.csv` to confirm no hand-column churn (CSV re-quoting of unchanged cells counts as churn — if the diff shows quoting changes on hand columns, fix the writer to preserve them before proceeding). Revert the real-manifest change for now (`git checkout -- fixtures/manifest.csv`) — the committed population run happens in Task 6 after everything is green.

- [ ] **Step 5: Commit**

```bash
git add src/hoops/score.py tests/test_score.py
git commit -m "feat(score): write heard/got/match/scored_at back into manifest.csv

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: report_html robustness nits (three parked findings)

**Files:**
- Modify: `src/hoops/report_html.py`
- Test: `tests/test_report_html.py`

**Interfaces:**
- Consumes: existing `_gap_chart_svg`, `_build_data`, `_transcript`, `render_interactive_report`.
- Produces: module constant `CALL_MATCH_TOLERANCE_S = 0.05` and helper `_call_row_for(word, rows) -> dict | None`, used by both `_build_data` and `_transcript`. Blob escaping becomes every `<` → `\u003c`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_report_html.py`:

```python
def test_gap_bar_width_never_negative():
    rows = []
    for i in range(1, 161):                      # 160 timed shots
        rows.append({**ROWS[1], "shot_num": i, "t_call_s": float(i * 2),
                     "gap_s": 2.0, "streak_after": 0})
    html = render(rows=rows)
    assert "width='-" not in html and 'width="-' not in html

def test_blob_escapes_all_angle_brackets():
    evil = dict(STATS, notes="<!--<script>boom")
    html = render(stats=evil)
    m = re.search(r"const DATA = (.*?);\n", html, re.S)
    assert "<" not in m.group(1)                 # every < escaped in the blob
    assert json.loads(m.group(1))["stats"]["notes"] == "<!--<script>boom"

def test_shared_call_matcher_consistency():
    from hoops.report_html import _call_row_for, CALL_MATCH_TOLERANCE_S
    w = WORDS[0]                                  # brick @ 5.0 == shot 1
    assert _call_row_for(w, ROWS)["shot_num"] == 1
    off = type(w)(w.text, w.raw, w.start + CALL_MATCH_TOLERANCE_S + 0.01, w.end, None)
    assert _call_row_for(off, ROWS) is None
```

Also UPDATE the existing `data_blob` helper so both tests keep working with the new escaping (it currently un-escapes `<\/`):

```python
def data_blob(html):
    m = re.search(r"const DATA = (.*?);\n", html, re.S)
    assert m, "DATA blob missing"
    return json.loads(m.group(1))                 # < is valid JSON — no un-escaping needed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_report_html.py -q`
Expected: the three new tests FAIL (no `_call_row_for`; blob contains `<`; 160-gap render emits negative widths). Existing tests still pass (the `data_blob` change is compatible with the current `<\/` output? NO — `<\/` inside a JSON string is also valid JSON (`\/` is an escaped solidus), so `json.loads` handles today's format too; expect existing tests green).

- [ ] **Step 3: Implement**

In `src/hoops/report_html.py`:

a. Bar width floor — in `_gap_chart_svg` change:
```python
    bw = min(28, (W - 2 * pad) / len(gaps) - 4)
```
to
```python
    bw = max(1, min(28, (W - 2 * pad) / len(gaps) - 4))
```

b. Shared matcher — add near the top (after `FLAG_EXPLAIN`):
```python
CALL_MATCH_TOLERANCE_S = 0.05

def _call_row_for(word, rows):
    for r in rows:
        if abs(word.start - r["t_call_s"]) < CALL_MATCH_TOLERANCE_S:
            return r
    return None
```
Replace `_build_data`'s inner `call_num` with:
```python
    def call_num(w):
        r = _call_row_for(w, rows)
        return r["shot_num"] if r else 0
```
and `_transcript`'s per-word lookup (delete its `by_t` dict) with:
```python
    for w in words:
        row = _call_row_for(w, rows)
```

c. Escaping — in `render_interactive_report` change:
```python
    data = json.dumps(_build_data(stats, rows, narrative, flags, words, has_audio)
                      ).replace("</", "<\\/")
```
to
```python
    data = json.dumps(_build_data(stats, rows, narrative, flags, words, has_audio)
                      ).replace("<", "\\u003c")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_report_html.py -q`, then full `uv run pytest -q`. Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/hoops/report_html.py tests/test_report_html.py
git commit -m "fix(report): bar-width floor, shared call matcher, full angle-bracket blob escaping

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: gitignore + working-tree cleanup

**Files:**
- Modify: `.gitignore`
- Delete (untracked debris): `.playwright-mcp/` contents

**Interfaces:** none.

- [ ] **Step 1: Edit `.gitignore`**

Replace the four lines
```
sessions/**/audio.m4a
sessions/**/report.html
sessions/**/strip.png
sessions/**/pending_email
```
with
```
sessions/
```
(keep the surrounding comment, updating it to say per-session data is fully local-only). Add `.playwright-mcp/` under the derived/disposable block.

- [ ] **Step 2: Verify and clean**

```bash
git check-ignore sessions/2026/07/hoops__20260730-125100/shots.csv .playwright-mcp
rm -rf .playwright-mcp
git status --short   # expect: only .gitignore modified (plus .DS_Store noise), no ?? sessions/
```
`git ls-files sessions/` must print nothing (nothing tracked to remove on this lineage).

- [ ] **Step 3: Run the suite (paranoia — nothing should reference these paths)**

Run: `uv run pytest -q`. Expected: green.

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore sessions/ fully and .playwright-mcp/

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Playbook + README template section + docs index + archive

**Files:**
- Create: `docs/playbook.md`, `docs/README.md`, `docs/archive/README.md`
- Move: `docs/PRD-hoops-voice-log.md` → `docs/archive/PRD-hoops-voice-log.md`; `docs/plans/2026-07-27-hoops-voice-log.md` → `docs/archive/2026-07-27-hoops-voice-log-plan.md` (the `docs/plans/` dir disappears)
- Modify: `README.md` (add template section), `docs/specs/2026-07-27-hoops-voice-log-design.md` (two PRD links)

**Interfaces:** Produces the reading path Task 5's CLAUDE.md points at: `README.md → docs/playbook.md → docs/architecture.md → docs/methodology.md → docs/pattern/README.md`.

- [ ] **Step 1: Archive moves + link fixes**

```bash
mkdir -p docs/archive
git mv docs/PRD-hoops-voice-log.md docs/archive/PRD-hoops-voice-log.md
git mv docs/plans/2026-07-27-hoops-voice-log.md docs/archive/2026-07-27-hoops-voice-log-plan.md
```
In `docs/specs/2026-07-27-hoops-voice-log-design.md`: line 5's link `(../PRD-hoops-voice-log.md)` → `(../archive/PRD-hoops-voice-log.md)`; line ~92's tree listing text `docs/PRD-hoops-voice-log.md` → `docs/archive/PRD-hoops-voice-log.md`. Then `grep -rn "PRD-hoops\|plans/2026-07-27" --include="*.md" . | grep -v archive | grep -v superpowers/plans` must show no remaining stale references (CLAUDE.md's one is rewritten in Task 5 — leave it for that task).

- [ ] **Step 2: Write `docs/archive/README.md`**

```markdown
# Archive

Superseded documents, kept for the record. Nothing here is current.

- `PRD-hoops-voice-log.md` — the original product requirements document.
  Superseded by the dated design specs in `../specs/` (start with
  `2026-07-27-hoops-voice-log-design.md`, which names what it overrides)
  and by `CLAUDE.md` for current status and rules.
- `2026-07-27-hoops-voice-log-plan.md` — the original build plan (P0–P3).
  Executed and shipped; superseded by the dated plans in
  `../superpowers/plans/` for later features.
```

- [ ] **Step 3: Write `docs/playbook.md`**

The centerpiece. Structure and required content per section (write it in the repo's first-person owner voice; every artifact reference must be a working relative link; keep it under ~150 lines — it's a playbook, not a memoir):

```markdown
# Playbook: how to build an AI-automated personal tool

What this is: the repeatable process behind hoops, written down so tool #2
(any daily activity → captured data → automated report) follows the same
path instead of rediscovering it. Each step links to the real artifact in
this repo as the worked example.

## The loop at a glance
[8-step numbered list, one line each, matching the sections below]

## 1. Start with an owner-decision spec
[Product intent + the decisions only the owner can make (vocabulary,
protocol, stop rule, delivery channel). Working link to
specs/2026-07-27-hoops-voice-log-design.md; note the "supersedes" chain
convention — later specs name what they override instead of editing
history.]

## 2. CLAUDE.md is the working agreement, not documentation
[The AI assistant reads it every session: current status (dated), hard
rules, gates, read-first pointers. Stale CLAUDE.md = the assistant
confidently doing the wrong thing. Maintenance discipline: update it in
the same PR that changes what it describes. Link ../CLAUDE.md.]

## 3. Design before code, plan before implementation
[Each feature: brainstormed spec (docs/specs/) → implementation plan of
bite-sized TDD tasks executed with per-task review
(superpowers/plans/2026-07-30-interactive-report.md is the fullest
example — every task carries its failing test, expected failure, code,
and commit).]

## 4. Golden dataset before capability
[Record and hand-label fixtures BEFORE building the behavior
(fixtures/manifest.csv, methodology.md). Trap fixtures encode the failure
modes you fear most — chatty audio, phantom shots. The manifest carries
both ground truth (hand columns) and the latest scored outputs (machine
columns hoops score writes back).]

## 5. Gates decide done, not demos
[hoops score gate table (recall/precision/phantoms as hard build
failures), replay --all no-diff discipline for parser changes, invariants
as runtime self-checks on every real session. A feature ships when gates
pass, not when the demo looks right.]

## 6. Ship small, verify live, then shadow
[Merge only green. Watch one real end-to-end run (phone → email) before
trusting automation. Then a shadow period: N real sessions where you
eyeball the output against memory before believing the numbers.]

## 7. Record why, not just what
[decisions/ for ADRs (001-transcriber-selection.md), writeups/ for
experiments (2026-07-30-empirical-model-selection.md), showcase/ for
result dashboards. Future-you needs the reasoning, git has the code.]

## 8. Generalize from instances, not upfront
[pattern/README.md was abstracted AFTER instance #1 worked. The reusable
starter template gets designed when instance #2 exists, not before —
one data point over-fits.]
```

- [ ] **Step 4: Write `docs/README.md`**

```markdown
# docs/

Reading path: [`../README.md`](../README.md) → [`playbook.md`](playbook.md) →
[`architecture.md`](architecture.md) → [`methodology.md`](methodology.md) →
[`pattern/README.md`](pattern/README.md)

- `playbook.md` — the repeatable build process (start here)
- `architecture.md` — how the pipeline works, module map, failure handling
- `methodology.md` — golden-dataset methodology binding this repo
- `shortcut-setup.md` — phone-side Apple Shortcut setup
- `specs/` — dated design specs; later specs supersede earlier where named
- `superpowers/` — brainstormed specs + task-level implementation plans
- `decisions/` — architecture decision records
- `writeups/` — experiment writeups (e.g. transcriber model selection)
- `showcase/` — generated result dashboards
- `pattern/` — the generalizable capture pattern (for instance #2)
- `archive/` — superseded documents (original PRD, original build plan)
```

- [ ] **Step 5: Add the template section to `README.md`**

After the existing "How it works" content (read the file; place it as a new `##` section before the closing "Deeper docs" line, and update that closing line to also link `docs/playbook.md`):

```markdown
## Use this repo as a template

hoops doubles as my worked example of building an AI-automated personal
tool: spec-first design, a golden labeled dataset before capability,
score gates instead of demos, and an assistant working agreement
(CLAUDE.md) that stays truthful. The process, with links to every real
artifact here, is written down in [docs/playbook.md](docs/playbook.md).

Reading path: this README → [docs/playbook.md](docs/playbook.md) →
[docs/architecture.md](docs/architecture.md) →
[docs/methodology.md](docs/methodology.md) →
[docs/pattern/README.md](docs/pattern/README.md).
```

- [ ] **Step 6: Link check + suite**

```bash
uv run python - <<'EOF'
import re, pathlib
bad = []
for md in ["README.md", "docs/README.md", "docs/playbook.md", "docs/archive/README.md",
           "docs/specs/2026-07-27-hoops-voice-log-design.md"]:
    base = pathlib.Path(md).parent
    for m in re.finditer(r"\]\(([^)#h][^)]*)\)", pathlib.Path(md).read_text()):
        if not (base / m.group(1)).exists():
            bad.append((md, m.group(1)))
print(bad or "all links OK")
EOF
uv run pytest -q
```
Expected: `all links OK`, suite green.

- [ ] **Step 7: Commit**

```bash
git add -A docs README.md
git commit -m "docs: playbook, docs index, template section, archive superseded PRD/plan

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: CLAUDE.md rewrite

**Files:**
- Modify: `CLAUDE.md` (full replacement)

**Interfaces:** Consumes the Task 4 reading path. Content below is the complete replacement — adjust only if repo facts changed (verify each claim against the tree before committing).

- [ ] **Step 1: Replace CLAUDE.md with:**

```markdown
# hoops — morning free-throw voice log

One-button voice data capture: Apple Shortcut records shot call-outs → iCloud drop folder → Mac pipeline (whisper-1 → isolation-gated parser → invariants → stats → interactive HTML report emailed). Basketball is instance #1 of a generalizable capture pattern; this repo is also the owner's golden example of how to build an AI-automated tool — see `docs/playbook.md`.

**Read first:** `README.md` (product + template intro) · `docs/playbook.md` (the build process) · `docs/architecture.md` (module map, failure handling) · `docs/methodology.md` (golden-dataset rules — read before capability work) · `docs/shortcut-setup.md` (phone-side setup). Dated specs in `docs/specs/` supersede earlier ones where named; the original PRD lives in `docs/archive/`.

## Current status (2026-07-30)

- **V1 live and daily-use** (tag `v1.0.0`): full phone → Mac → email loop verified end-to-end 2026-07-29/30; launchd poller healthy (FDA granted). Shadow period in progress — eyeball each emailed report vs memory for the first 14 real sessions.
- Email carries a slim summary body + one self-contained interactive `report.html` (audio-synced movie replay, SVG charts — `src/hoops/report_html.py`); `narrative.json` persisted per session.
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
- Parser/config changes: `uv run hoops replay --all` must produce no diff in session parser outputs; `uv run hoops score` must pass before merging (phantom shots on trap fixtures = hard failure).
- `parse.py` / `stats.py` / `invariants.py` stay pure stdlib, no I/O — the load-bearing, testable core.
- New capability ⇒ new labeled fixture first; gates decide done. See `docs/methodology.md`.
- Fixture `.m4a` are deliberately committed; `sessions/`, `out/`, logs, and `hoops.db` are not. The pipeline never writes `hoops.db` — `scripts/build_db.py` rebuilds it on demand.
- Update this file in the same change that alters what it describes.
```

- [ ] **Step 2: Verify claims + suite**

Check each factual claim against the tree (tag exists: `git tag -l v1.0.0`; files named exist; pending-work items still true — e.g. confirm `mess` decision still open by checking `config.yaml` miss list). Run `uv run pytest -q`.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: rewrite CLAUDE.md — V1 status, single-manifest workflow, refreshed pending work

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Gates, manifest population, final review

**Files:** `fixtures/manifest.csv` (populated by running score — committed)

- [ ] **Step 1: Populate the manifest**

```bash
uv run hoops score | tail -9        # exit code may be 1 — pre-existing gate FAILs, unchanged from base
git diff fixtures/manifest.csv      # ONLY the 4 machine columns + header change; any hand-column churn = bug, stop
git add fixtures/manifest.csv
git commit -m "chore: populate manifest machine columns from first score run

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 2: Full gates**

```bash
uv run pytest -q                    # green
uv run hoops replay --all           # then verify session parser outputs unchanged (sessions/ is untracked: use checksums of shots.csv/session.json before/after)
uv run hoops score | tail -9        # same gate table as on main today
```

- [ ] **Step 3: Final whole-branch review, then finish**

Per subagent-driven-development: review package over `30fd8ee..HEAD`, most capable model, pointed at any ledger minors. Fix wave if needed. Then superpowers:finishing-a-development-branch (base: `main`).

---

## Self-review notes (already applied)

- Spec coverage: §A → Task 1 + Task 6 population; §B gitignore/debris → Task 3, three nits → Task 2; §C playbook/README/index/archive → Task 4, CLAUDE.md → Task 5; error-handling (atomic write, unscored rows) → Task 1 code + tests; verification → Task 6.
- `match` vs `exact`: same comparison; writer uses `s.got == s.expected` directly so it can't drift from the printed table.
- The `data_blob` helper change in Task 2 is backward-compatible mid-task because `\/` is a valid JSON escape — existing tests stay green at every step.
- CSV re-quoting risk (DictWriter minimal quoting may differ from the hand-authored file) is explicitly checked in Task 1 Step 4 and Task 6 Step 1 — if quoting churn appears on hand columns, the writer must switch to preserving the original lines for untouched cells rather than proceeding.
```
