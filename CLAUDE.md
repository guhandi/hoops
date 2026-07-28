# hoops — morning free-throw voice log
Voice-called shots → shot table → emailed report. Spec: docs/specs/2026-07-27-hoops-voice-log-design.md (supersedes docs/PRD-hoops-voice-log.md where they conflict).
- Run tests: `uv run pytest` (paid API tests excluded by default; `-m paid` to include)
- Parser work: iterate with `uv run hoops replay --all` then `git diff sessions/` — a no-op change must produce no diff (PRD §11.6)
- Gates: `uv run hoops score` must pass before merging parser/config changes; phantom shots on trap fixtures are a hard failure
- Text is committed; audio/binaries/db are gitignored. Never make the pipeline write to hoops.db.
