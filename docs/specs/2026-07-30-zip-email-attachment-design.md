# Zip email attachment — design

**Date:** 2026-07-30 · **Status:** approved · **Scope:** `src/hoops/mailer.py` + tests

## Problem

The session email attaches only `report.html` (plus the inline CID `strip.png` in the
HTML body). The rest of the session's artifacts — `audio.m4a`, `transcript.txt`,
`transcript.json`, `shots.csv`, `session.json` — stay only on the Mac. The owner wants
the email to carry a complete, self-contained archive of the session.

## Decision

Replace the single `report.html` attachment with **one zip attachment containing every
file in the session directory**.

- Built in memory with stdlib `zipfile` + `io.BytesIO`, `ZIP_DEFLATED`.
- Members are namespaced under a root folder equal to the session dir name
  (`hoops__20260730-125100/report.html`, …) so extraction produces one folder.
- Attachment filename: `<session_dir.name>.zip`, MIME `application/zip`.
- Contents come from globbing the session directory's files — **no whitelist**. New
  pipeline artifacts (e.g. `narrative.json`) are included automatically with no code
  change. A whitelist was rejected because it silently drops new artifacts; the session
  dir is already the canonical "everything about this session" boundary, and nothing
  unmailable lives there.

## What stays the same

Subject line, HTML summary body, inline CID `strip.png`, SMTP send path. The
plain-text fallback line changes to point at the zip ("Extract the attached zip; open
report.html inside for the interactive report."). `report.html` is **not** duplicated
as a separate attachment (owner decision: zip only, one clean attachment).

## Size

Largest current session is ~6 MB on disk (audio dominates); zip stays well under
Gmail's 25 MB limit. No size guard needed now.

## Error handling

- Missing files simply aren't in the zip (glob semantics).
- An empty session dir yields a valid empty zip; the send still succeeds.
- Subdirectories are not expected in session dirs; only regular files are zipped.

## Testing

- Unit test on `build_email` against a temp session dir: exactly one attachment, named
  `<stem>.zip`, `application/zip`, and `zipfile.ZipFile` over the payload lists the
  expected member names under the root-folder prefix.
- `uv run pytest` green. `hoops replay --all` unaffected (mailer writes no session
  files), so no `sessions/` diff is expected.
