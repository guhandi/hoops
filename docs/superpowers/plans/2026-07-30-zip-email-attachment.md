# Zip Email Attachment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The session email attaches one zip archive containing every file in the session directory, instead of a bare `report.html`.

**Architecture:** `src/hoops/mailer.py` gains a small pure-ish helper `build_session_zip(session_dir) -> bytes` that zips all regular files in the session dir (in-memory, deflated, members namespaced under the dir name). `build_email` swaps its `report.html` attachment block for this zip. Everything else — subject, HTML body, inline CID strip — is untouched.

**Tech Stack:** Python 3.12 stdlib only (`zipfile`, `io`, `email.message`). Tests via pytest, run with `uv run pytest`.

## Global Constraints

- Spec: `docs/specs/2026-07-30-zip-email-attachment-design.md`.
- Stdlib only in `mailer.py` — no new dependencies.
- Zip members namespaced under the session dir name: `hoops__<stamp>/<file>`.
- Attachment filename `<session_dir.name>.zip`, MIME `application/zip`. Zip is always attached, even when the session dir is empty (valid empty zip).
- Only regular files are zipped (no subdirectory recursion), sorted by name for determinism.
- Plain-text fallback body: `"Extract the attached zip; open report.html inside for the interactive session report."`
- All tests green via `uv run pytest` before commit.

---

### Task 1: Zip attachment in `build_email`

**Files:**
- Modify: `src/hoops/mailer.py:1-31` (imports, plain-text body, attachment block, new helper)
- Test: `tests/test_mailer.py` (rewrite the two `build_email` tests)

**Interfaces:**
- Consumes: existing `build_email(stats, session_dir, narrative, flags, cfg) -> EmailMessage` signature — unchanged.
- Produces: `build_session_zip(session_dir: Path) -> bytes` in `hoops.mailer` (zip archive bytes). Callers outside `build_email` are not expected, but the helper is module-level and directly testable.

- [ ] **Step 1: Rewrite the two attachment tests to expect the zip (failing first)**

In `tests/test_mailer.py`, add `import io, zipfile` to the imports and replace `test_build_email_single_report_attachment` and `test_build_email_survives_missing_report` with:

```python
def test_build_email_single_zip_attachment(tmp_path):
    cfg = load_config(REPO / "config.yaml")
    sdir = tmp_path / "hoops__20260727-061204"; sdir.mkdir()
    files = {"shots.csv": b"a", "session.json": b"{}", "transcript.txt": b"t",
             "strip.png": b"\x89PNG_fake", "audio.m4a": b"m4a",
             "report.html": b"<html>interactive</html>"}
    for name, data in files.items():
        (sdir / name).write_bytes(data)
    msg = build_email(STATS, sdir, None, [], cfg)
    assert msg["To"] == cfg.email["to"] and "8 shots" in msg["Subject"]
    atts = list(msg.iter_attachments())
    assert [p.get_filename() for p in atts] == [f"{sdir.name}.zip"]
    assert atts[0].get_content_type() == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(atts[0].get_payload(decode=True)))
    assert set(zf.namelist()) == {f"{sdir.name}/{n}" for n in files}
    assert zf.read(f"{sdir.name}/report.html") == files["report.html"]
    body = msg.get_body(("html",)).get_content()
    assert "cid:strip" in body
    for part in msg.walk():
        if part.get("Content-ID") == "<strip>":
            assert part.get_content_disposition() == "inline"
            break
    else:
        pytest.fail("Related image part with Content-ID <strip> not found")

def test_build_email_empty_session_dir_attaches_empty_zip(tmp_path):
    cfg = load_config(REPO / "config.yaml")
    sdir = tmp_path / "hoops__20260727-061204"; sdir.mkdir()
    msg = build_email(STATS, sdir, None, [], cfg)      # bare dir: no strip, no report
    atts = list(msg.iter_attachments())
    assert [p.get_filename() for p in atts] == [f"{sdir.name}.zip"]
    zf = zipfile.ZipFile(io.BytesIO(atts[0].get_payload(decode=True)))
    assert zf.namelist() == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_mailer.py -v`
Expected: the two new tests FAIL (attachment is still `report.html` / absent); `test_subject` still PASSES.

- [ ] **Step 3: Implement the zip attachment in `mailer.py`**

Change the import line and add the helper:

```python
import io, os, smtplib, zipfile
```

```python
def build_session_zip(session_dir: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(session_dir.iterdir()):
            if f.is_file():
                zf.write(f, arcname=f"{session_dir.name}/{f.name}")
    return buf.getvalue()
```

In `build_email`, change the plain-text body:

```python
    msg.set_content("Extract the attached zip; open report.html inside "
                    "for the interactive session report.")
```

and replace the `report.html` attachment block (the last four lines before `return msg`) with:

```python
    msg.add_attachment(build_session_zip(session_dir), maintype="application",
                       subtype="zip", filename=f"{session_dir.name}.zip")
```

The `strip.png` inline-CID block stays exactly as is.

- [ ] **Step 4: Run the mailer tests to verify they pass**

Run: `uv run pytest tests/test_mailer.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: all PASS (paid tests excluded by default). `test_ingest.py` / `test_pipeline.py` stub out `hoops.mailer.send`, so they're unaffected, but the full run confirms it.

- [ ] **Step 6: Commit**

```bash
git add src/hoops/mailer.py tests/test_mailer.py
git commit -m "feat(mailer): attach full session zip instead of bare report.html"
```

### Task 2: Docs touch-up

**Files:**
- Modify: `docs/architecture.md` (the email/attachment description), `CLAUDE.md` (the 2026-07-30 status line describing the slim email)

**Interfaces:**
- Consumes: nothing from Task 1's code — text only.
- Produces: nothing consumed by code.

- [ ] **Step 1: Update the attachment description**

In `docs/architecture.md`, find the sentence describing the email attachment (search for `report.html`) and change it to say the email carries the summary body (inline strip.png) plus a single `hoops__<stamp>.zip` attachment containing every session file (`audio.m4a`, transcripts, `shots.csv`, `session.json`, `report.html`, `strip.png`, and any future artifacts). In `CLAUDE.md`, amend the "email slimmed to summary body … + single `report.html` attachment" clause to "+ single session zip attachment (all session files, report.html inside)".

- [ ] **Step 2: Commit**

```bash
git add docs/architecture.md CLAUDE.md
git commit -m "docs: email now attaches full session zip"
```
