# Public release packaging — design

**Date:** 2026-08-01 · **Status:** approved for implementation
**Goal:** hoops becomes a public, installable tool and a portfolio piece: a stranger can clone it, experience the product in 60 seconds with zero API keys, and deploy their own instance in ~15 minutes — while the repo's front door tells the end-to-end story (voice capture → cloud pipeline → data lake → interactive report) with the receipts visible.

## Decisions (owner, 2026-08-01)

1. **Real-voice fixtures stay public.** R01/R02/dev audio (unscripted sessions, mild cussing) are the golden dataset and the product's credibility — the isolation gate provably ignoring the muttering is the best demo the repo has.
2. **License: MIT.**
3. **Distribution: Modal deploy-your-own + GitHub Actions CI. No Docker** — the local mode is macOS-specific (launchd/iCloud) and a container variant would be a second deploy path to keep working for no story gain.
4. **Config personalization: env-override with placeholders** — `config.yaml` ships `you@example.com`; `GMAIL_ADDRESS` (already implemented in `config.py`) is the documented way to set your address; the owner's real address lives only in his local `.env`.

## Workstream 1 — Genericization

- `config.yaml` + `cloud/config.cloud.yaml`: `email.from`/`email.to` → `you@example.com`; comment on both pointing at the `GMAIL_ADDRESS` override; note that timezone must be edited in both files (or via the same edit documented once).
- `tests/test_config.py`: assert the placeholder (and separately assert the `GMAIL_ADDRESS` override wins — coverage already exists for the override path; extend if not).
- `.env.example`: all ten required vars, grouped with one-line comments — `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `HOOPS_UPLOAD_KEY`, `HOOPS_ENDPOINT`, `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`. Docs standardize on one `.env` (the owner's legacy `.env.r2` keeps working locally but leaves the documentation).
- `scripts/com.guhan.hoops.plist` → deleted; `scripts/install_launchd.sh` generates `com.hoops.poller.plist` at install time from the actual repo path (`sed` on a heredoc template), label `com.hoops.poller`. All doc references updated (`README.md`, `docs/architecture.md`).
- `docs/architecture.md` / `docs/shortcut-setup.md`: `.env.r2` references → `.env`.

## Workstream 2 — `docs/deploy-your-own.md` (the install)

From-zero, ~15 minutes, first-person-to-the-reader ("you"):
1. Accounts checklist with links + free-tier notes: OpenAI (API key), Anthropic (API key), Modal (free Starter, no card), Cloudflare R2 (free 10GB; token nav: R2 → Overview → Account Details → API Tokens → Manage; Account API token, Object Read & Write, bucket-scoped), Gmail app password (requires 2FA; Google Account → Security → App passwords).
2. `git clone` → `uv sync --extra cloud` → `cp .env.example .env` → fill it (incl. `openssl rand -hex 24` for `HOOPS_UPLOAD_KEY`).
3. `uv run modal setup` (browser auth) → the exact `uv run modal secret create hoops-secrets ...` command with all nine cloud-side vars.
4. `uv run modal deploy cloud/modal_app.py` → note the printed endpoint URL → curl smoke test (copy-paste command using a shipped fixture).
5. Phone: link to `docs/shortcut-setup.md` cloud section.
6. Cost table: infra $0/month (Modal credits + R2 free tier), APIs ≈ $0.01/session (whisper + narrative).
7. Troubleshooting: 401 (key mismatch), 400 (filename), no email (check Modal dashboard logs; alert-per-attempt semantics), `pull_sessions` for the dev loop.

README Setup section rewritten: "Deploy your own (cloud, ~15 min)" linking the guide; local launchd path demoted to "Local fallback mode".

## Workstream 3 — Front door

- **README hero**, in order: title + one-line pitch; badges (GitHub Actions CI status, MIT, Python 3.12+); hero visual — animated GIF of the interactive report's movie replay playing (generated from a fixture report in a headless browser; fallback: 2–3 stills of movie/timeline/stats if GIF assembly tooling is unavailable); the existing prose/pipeline diagram follows.
- **"Try it in 60 seconds — zero API keys"** section immediately after the hero: `git clone` → `uv sync` → `uv run hoops process-all fixtures --no-email` → `open out/index.html`, with one sentence explaining it runs the full parser/stats/report pipeline over the committed golden dataset (cached transcripts; no accounts, no keys). Note that `hoops score` also works key-free.
- Assets committed under `docs/assets/` (GIF + stills; generated from fixture data only — no owner sessions).
- `LICENSE` (MIT, current year, owner name), `pyproject.toml` metadata: `description`, `readme`, `license = "MIT"` (or classifier per hatchling support), `authors`, `[project.urls]` (Homepage/Repository), classifiers (Python 3.12, License MIT, Topic).

## Workstream 4 — CI + hygiene

- `.github/workflows/ci.yml`: on push/PR to main — checkout, install uv (official action), `uv sync --extra cloud`, `uv run pytest -q`. The suite is network-free by design (paid marker excluded by default), so CI needs zero secrets. Badge in README.
- Untrack committed `.DS_Store` files (`git rm --cached .DS_Store fixtures/.DS_Store`; `.gitignore` already covers them).
- Working-tree strays: delete `fixtures/manifest_scored.csv` (obsolete artifact); commit `docs/superpowers/plans/2026-07-30-zip-email-attachment.md` (part of the process record).
- Explicitly kept: CLAUDE.md's public "Pending work" list (the honest working agreement is part of the showcase); the manifest's owner TODO notes (living dataset); `hoops score`'s manifest write-back behavior (documented in README's testing section as intentional).

## Out of scope

Docker, GitHub Pages, multi-tenant/hosted service, repo rename, `gap_mae` dead-column fix (tracked as pending work item), fixture relabeling.

## Verification

- Full `uv run pytest` green locally AND the first GitHub Actions run green on push.
- Stranger-simulation: in a scratch clone (fresh dir, no `.env`), `uv sync && uv run hoops process-all fixtures --no-email` produces `out/index.html`; `bash scripts/install_launchd.sh` generates a plist with the scratch path (then immediately unloaded/removed — don't leave a poller running).
- `grep -ri "guhandiji\|guhansundar\|com.guhan" --include="*" .` over tracked files returns only historical docs (archive/specs/plans records) — none in code, config, scripts, or reader-path docs.
- README renders on GitHub with working badges, hero visual, and demo block; LICENSE detected by GitHub's license widget.
- Deploy guide dry-run: every command copy-pastes cleanly; env var list matches exactly what the code reads.
