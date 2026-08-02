# Public Release Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stranger can clone hoops, experience the product in 60 seconds with zero API keys, and deploy their own instance in ~15 minutes — with a README that works as a portfolio front door (hero GIF, badges, honest receipts).

**Architecture:** Four workstreams as seven tasks: genericize configs/scripts, complete the env story, write the from-zero deploy guide, rebuild the README front door with generated demo assets, add LICENSE + package metadata, wire GitHub Actions CI, and clean tracked debris. No behavior changes to the pipeline itself.

**Tech Stack:** Existing repo tooling only (uv, pytest, hatchling). GitHub Actions with `astral-sh/setup-uv`. GIF assembly via Pillow (already present via matplotlib's dependency tree) — no new dependencies.

**Spec:** `docs/specs/2026-08-01-public-release-design.md` — read it first.

## Global Constraints

- No new runtime dependencies; no pipeline behavior changes (`src/hoops/` logic untouched except nothing — this release is config/docs/packaging only; `tests/test_config.py` is the only test file that changes).
- Placeholder email everywhere a stranger would copy: `you@example.com`. The owner's real address appears NOWHERE in tracked non-archive files after this branch (grep gate in Task 7).
- launchd label becomes `com.hoops.poller`; no absolute owner paths in any committed file.
- Demo assets under `docs/assets/` are generated from FIXTURE data only — never from the owner's real sessions.
- Docs speak to "you" (the deployer); README hero section ordering per spec: title/pitch → badges → hero visual → 60-seconds demo → existing story.
- All tests `uv run pytest` (network-free); commit trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`; branch `feat/public-release` (exists, spec at 0bff3ff).
- **[OWNER]**-marked steps pause for the owner. Everything else runs autonomously.

## Reference: current state consumed by tasks

- `config.yaml:31-35` and `cloud/config.cloud.yaml:31-35`: `email.from`/`to` = `guhandiji@gmail.com`; `smtp_host: smtp.gmail.com`, `smtp_port: 465` stay.
- `src/hoops/config.py:43-47`: `GMAIL_ADDRESS` env overrides both from/to — already implemented and tested (`tests/test_config.py` has an override test asserting `robot@example.com` and a no-env test asserting the owner's address at ~line 38).
- `.env.example` currently has 4 vars. Code reads ten (see Task 1 content).
- `scripts/com.guhan.hoops.plist`: hardcoded label + 4 absolute `/Users/guhansundar/...` paths. `scripts/install_launchd.sh` copies it verbatim, bootstraps, kickstarts, and verifies LastExitStatus (keep ALL that verification logic — only the plist source and label change).
- `pyproject.toml`: `[project]` has name/version/requires-python/deps only — no description/readme/license/authors/urls/classifiers. Build backend hatchling.
- README: no images/badges/license; setup section (lines ~63-77) documents only the launchd path; troubleshooting says `launchctl list com.guhan.hoops`; CLI table at ~79-88; `docs/architecture.md:33,77` references `com.guhan.hoops.plist`.
- Zero-key demo already works: `uv run hoops process-all fixtures --no-email` → `out/index.html` (cached transcripts; lazy API clients). `hoops score` is also key-free but writes machine columns into `fixtures/manifest.csv` (intentional; document, don't change).

---

### Task 1: Genericize configs + complete `.env.example`

**Files:**
- Modify: `config.yaml:31-35`, `cloud/config.cloud.yaml:31-35`, `tests/test_config.py` (~line 38 no-env test), `.env.example`

**Interfaces:** Produces the placeholder `you@example.com` that Tasks 4-5 docs reference, and the canonical ten-var `.env.example` the deploy guide walks through.

- [ ] **Step 1: Update the failing test first (TDD on config data)**

In `tests/test_config.py`, find the no-env test (`test_no_gmail_address_env_keeps_yaml_values`) and change its assertion:

```python
def test_no_gmail_address_env_keeps_yaml_values(monkeypatch):
    monkeypatch.delenv("GMAIL_ADDRESS", raising=False)
    cfg = load_config(REPO / "config.yaml")
    assert cfg.email["from"] == "you@example.com"
    assert cfg.email["to"] == "you@example.com"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_config.py -q` — expected: that test FAILS (yaml still has the real address); the `robot@example.com` override test still passes.

- [ ] **Step 3: Edit both configs**

In `config.yaml` AND `cloud/config.cloud.yaml`, replace the email block (keep smtp lines):

```yaml
email:
  from: you@example.com   # set GMAIL_ADDRESS in .env instead of editing this
  to: you@example.com     # (it overrides both from and to)
  smtp_host: smtp.gmail.com
  smtp_port: 465
```

Also update the timezone comment in BOTH files' line 1 to: `# EDIT to your timezone — in this file AND cloud/config.cloud.yaml` (in the cloud file: `# EDIT to your timezone — in this file AND config.yaml`).

- [ ] **Step 4: Replace `.env.example` entirely**

```bash
# --- LLM / transcription APIs (required) ---
OPENAI_API_KEY=            # platform.openai.com — whisper-1 transcription
ANTHROPIC_API_KEY=         # console.anthropic.com — repair + narrative

# --- Email delivery (required) ---
GMAIL_ADDRESS=             # your gmail; reports are sent from AND to this address
GMAIL_APP_PASSWORD=        # Google Account > Security > 2-Step Verification > App passwords

# --- Cloud pipeline (required for the primary deploy; see docs/deploy-your-own.md) ---
HOOPS_UPLOAD_KEY=          # shared secret for the upload endpoint: openssl rand -hex 24
HOOPS_ENDPOINT=            # printed by `modal deploy` (https://<you>--hoops-web.modal.run)
R2_ENDPOINT=               # Cloudflare R2 S3 endpoint (https://<accountid>.r2.cloudflarestorage.com)
R2_ACCESS_KEY_ID=          # R2 API token credentials (Object Read & Write, bucket-scoped)
R2_SECRET_ACCESS_KEY=
R2_BUCKET=hoops-data
```

- [ ] **Step 5: Run tests to verify green**

Run: `uv run pytest -q` — all pass (config tests now match placeholders; nothing else asserts the address — verify with `grep -rn "guhandiji" tests/` → empty).

- [ ] **Step 6: Commit**

```bash
git add config.yaml cloud/config.cloud.yaml tests/test_config.py .env.example
git commit -m "chore: placeholder email + complete .env.example for public deploys

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: launchd template — generic label, generated plist

**Files:**
- Delete: `scripts/com.guhan.hoops.plist`
- Modify: `scripts/install_launchd.sh`, `README.md` (troubleshooting line ~77), `docs/architecture.md` (two `com.guhan.hoops` references, lines ~33/77)

**Interfaces:** Produces label `com.hoops.poller` used by Task 4/5 docs.

- [ ] **Step 1: Rewrite `scripts/install_launchd.sh`**

Replace the copy-the-plist section (first ~9 lines) — KEEP the entire kickstart/verify block at the bottom unchanged except the label. New top:

```bash
#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
LABEL="com.hoops.poller"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p logs
uv sync                                    # ensures .venv/bin/hoops exists
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$REPO/.venv/bin/hoops</string>
    <string>poll</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>StartInterval</key><integer>300</integer>
  <key>StandardOutPath</key><string>$REPO/logs/poll.log</string>
  <key>StandardErrorPath</key><string>$REPO/logs/poll.log</string>
</dict>
</plist>
EOF
if [ "${DRY_RUN:-0}" = "1" ]; then
    echo "dry run: wrote $PLIST, skipping bootstrap"; exit 0
fi
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl print "gui/$(id -u)/$LABEL" | head -20
echo "installed: hoops poll every 300s, logs in logs/poll.log"
```

…then the existing kickstart/verify block with every `com.guhan.hoops` replaced by `"$LABEL"` (and the `launchctl list` check likewise). `git rm scripts/com.guhan.hoops.plist`.

- [ ] **Step 2: Verify with a dry run**

Run: `DRY_RUN=1 bash scripts/install_launchd.sh && plutil -lint ~/Library/LaunchAgents/com.hoops.poller.plist && grep -c "$(pwd)" ~/Library/LaunchAgents/com.hoops.poller.plist && rm ~/Library/LaunchAgents/com.hoops.poller.plist`
Expected: plist lints OK and contains the current repo path (4 occurrences). Do NOT bootstrap (the owner's poller is decommissioned; leave it that way).

- [ ] **Step 3: Update doc references**

- `README.md` troubleshooting: `launchctl list com.guhan.hoops` → `launchctl list com.hoops.poller`.
- `docs/architecture.md`: both `com.guhan.hoops.plist` mentions → "`install_launchd.sh` (generates `com.hoops.poller.plist` from your clone's path)"; the module-map line for the deleted plist file is removed/reworded.

- [ ] **Step 4: Run `uv run pytest -q`** (nothing should break) **and commit**

```bash
git add -A scripts README.md docs/architecture.md
git commit -m "chore: generate launchd plist at install time — generic label, no absolute paths

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: LICENSE + pyproject metadata

**Files:**
- Create: `LICENSE`
- Modify: `pyproject.toml` `[project]` table

- [ ] **Step 1: Create `LICENSE`** — standard MIT text, exactly:

```
MIT License

Copyright (c) 2026 Guhan Sundar

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 2: Extend `[project]` in `pyproject.toml`** (add below `requires-python`, keeping existing keys):

```toml
description = "One-button voice logging: record shot call-outs on your phone, get an interactive session report by email — a full capture-to-report data pipeline"
readme = "README.md"
license = { text = "MIT" }
authors = [{ name = "Guhan Sundar" }]
classifiers = [
  "License :: OSI Approved :: MIT License",
  "Programming Language :: Python :: 3.12",
  "Topic :: Multimedia :: Sound/Audio :: Speech",
]

[project.urls]
Repository = "https://github.com/guhandi/hoops"
```

(Place `[project.urls]` as its own table after `[project.scripts]`.)

- [ ] **Step 3: Verify packaging still builds and tests pass**

Run: `uv sync --extra cloud && uv run pytest -q && uv run python -c "import hoops; print('import ok')"`

- [ ] **Step 4: Commit**

```bash
git add LICENSE pyproject.toml uv.lock
git commit -m "chore: MIT license + package metadata

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: `docs/deploy-your-own.md` — the from-zero install guide

**Files:**
- Create: `docs/deploy-your-own.md`
- Modify: `docs/README.md` (add the guide to the index + reading path), `docs/shortcut-setup.md` (one line: link the guide as the prerequisite for getting the endpoint URL), `docs/architecture.md` (dev-loop paragraph: `.env.r2` → `.env`)

**Interfaces:** Consumes Task 1's `.env.example` var names + Task 2's label. Produces the guide Task 5's README links as `docs/deploy-your-own.md`.

- [ ] **Step 1: Write the guide** — second person, ~120 lines, exactly these sections with all commands concrete:

1. **What you're deploying** — 4-box diagram (phone → Modal endpoint → R2 → email), one paragraph, link to architecture.md.
2. **Accounts you need (~10 min)** — table: OpenAI (API key, platform.openai.com), Anthropic (console.anthropic.com), Modal (modal.com — free Starter, $30/mo credits, no card), Cloudflare R2 (free 10GB; exact token navigation: R2 Object Storage → Overview → Account Details → API Tokens → Manage → Create **Account API token**, Object Read & Write, scope to your bucket; note credentials shown once), Gmail app password (requires 2-Step Verification; Google Account → Security → App passwords). Create an R2 bucket named `hoops-data` (or any name — set `R2_BUCKET` to match).
3. **Configure (~3 min)** — `git clone https://github.com/guhandi/hoops && cd hoops`; `uv sync --extra cloud`; `cp .env.example .env` and fill every var (`openssl rand -hex 24` for `HOOPS_UPLOAD_KEY`; leave `HOOPS_ENDPOINT` empty until step 4); edit the timezone in `config.yaml` AND `cloud/config.cloud.yaml`.
4. **Deploy (~2 min)** —
   ```bash
   uv run modal setup        # one-time browser auth
   set -a; source .env; set +a
   uv run modal secret create hoops-secrets \
     OPENAI_API_KEY="$OPENAI_API_KEY" ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
     GMAIL_ADDRESS="$GMAIL_ADDRESS" GMAIL_APP_PASSWORD="$GMAIL_APP_PASSWORD" \
     HOOPS_UPLOAD_KEY="$HOOPS_UPLOAD_KEY" R2_ENDPOINT="$R2_ENDPOINT" \
     R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
     R2_BUCKET="$R2_BUCKET"
   uv run modal deploy cloud/modal_app.py   # prints your endpoint URL — put it in .env as HOOPS_ENDPOINT
   ```
5. **Smoke test** —
   ```bash
   curl -sS -X POST "$HOOPS_ENDPOINT/upload?name=hoops__20990101-000001.m4a" \
     -H "X-Hoops-Key: $HOOPS_UPLOAD_KEY" -H "Content-Type: application/octet-stream" \
     --data-binary @fixtures/F01_NormalSwishBrick.m4a
   ```
   Expect `{"status":"processing",...}` and an email in ~2 minutes (it will carry ⚠️ flags — the fixture deliberately violates the stop rule; that's the system working).
6. **Your phone** — link `docs/shortcut-setup.md` (cloud section).
7. **What it costs** — table: Modal $0 (credits), R2 $0 (free tier ≈ 5 years of daily sessions), APIs ≈ $0.01/session; total ≈ $0.30/month of API usage for daily use.
8. **When something breaks** — 401 = key mismatch (Shortcut header vs secret); 400 = filename contract; no email = check the Modal dashboard logs (every run is logged; a failing file alerts you by email per attempt and stays in `raw/` for replay); dev loop = `set -a; source .env; set +a; uv run modal run cloud/modal_app.py::pull_sessions`.

- [ ] **Step 2: Link it** — `docs/README.md` index gains `deploy-your-own.md — deploy your own instance in ~15 minutes` (also add it to the reading path line after playbook); `docs/shortcut-setup.md` cloud section: "Your endpoint URL comes from [deploy-your-own.md](deploy-your-own.md)."; `docs/architecture.md` dev-loop: `source .env.r2` → `source .env`.

- [ ] **Step 3: Link-check + suite** — run the repo's link-check pattern over the four touched files (all links resolve) and `uv run pytest -q`.

- [ ] **Step 4: Commit**

```bash
git add docs/deploy-your-own.md docs/README.md docs/shortcut-setup.md docs/architecture.md
git commit -m "docs: from-zero deploy-your-own guide (~15 min, all free-tier)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Demo assets — movie GIF + stills (controller-assisted)

**Files:**
- Create: `scripts/make_demo_assets.py`, `docs/assets/movie-demo.gif`, `docs/assets/report-timeline.png`, `docs/assets/report-stats.png`

**Interfaces:** Produces the asset paths Task 6's README embeds. FIXTURE DATA ONLY (F01).

- [ ] **Step 1: Write `scripts/make_demo_assets.py`** — assembles a GIF from a directory of PNG frames using Pillow (present via matplotlib):

```python
"""Assemble docs/assets/movie-demo.gif from ordered PNG frames.

Usage: uv run python scripts/make_demo_assets.py <frames_dir>
Frames are sorted by name; 600ms/frame, loops forever. Fixture data only.
"""
import sys
from pathlib import Path
from PIL import Image

def main(frames_dir: str) -> None:
    frames = [Image.open(p).convert("P", palette=Image.ADAPTIVE)
              for p in sorted(Path(frames_dir).glob("*.png"))]
    if len(frames) < 2:
        raise SystemExit(f"need >=2 frames in {frames_dir}, found {len(frames)}")
    out = Path("docs/assets/movie-demo.gif")
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(out, save_all=True, append_images=frames[1:],
                   duration=600, loop=0, optimize=True)
    print(f"wrote {out} ({out.stat().st_size // 1024} KB, {len(frames)} frames)")

if __name__ == "__main__":
    main(sys.argv[1])
```

- [ ] **Step 2 (CONTROLLER): Capture frames** — the controller renders F01's interactive report (`uv run hoops process-all fixtures --no-email` then serve `out/fixtures/F01_NormalSwishBrick/report.html` over localhost), drives the movie in the Playwright browser (click ▶, screenshot the `#movie` section element every ~1.5s for ~8 frames covering at least two shot animations + a flash), saves frames to the scratchpad, runs the assembly script, and captures the two stills (`#charts` section for report-timeline.png, the stats grid for report-stats.png) at ~800px width. Target: GIF under ~2MB (if over, halve frames or crop tighter). Fallback if animation can't be captured usably: skip the GIF, commit three stills, and Task 6 uses a still as hero.

- [ ] **Step 3: Verify + commit** — view the GIF (Read tool renders images; confirm the ball/flash visibly changes across frames), check sizes (`du -h docs/assets/*`), then:

```bash
git add scripts/make_demo_assets.py docs/assets/
git commit -m "docs: demo GIF + report stills generated from fixture F01

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: README front door

**Files:**
- Modify: `README.md` (hero block prepended; new demo section; Setup section rewritten; troubleshooting + testing notes)

**Interfaces:** Consumes Task 5 asset paths, Task 4 guide path, Task 2 label, Task 7's badge URL scheme (workflow file named `ci.yml` on repo `guhandi/hoops`).

- [ ] **Step 1: Prepend the hero** (above the current title-paragraph; the existing title line is replaced by this block):

```markdown
# 🏀 hoops — one-button voice logging, from jump shot to emailed report

[![CI](https://github.com/guhandi/hoops/actions/workflows/ci.yml/badge.svg)](https://github.com/guhandi/hoops/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](pyproject.toml)

Press one button on your phone, shoot until you make three in a row, call out each shot as it happens, stop the recording. Two minutes later an interactive session report is in your inbox — audio-synced replay, shot charts, streaks — with zero further interaction.

![Movie replay demo](docs/assets/movie-demo.gif)

*The report replays your session: your real audio drives an animated court — every call fires a make/miss animation as you hear yourself say it.*

## Try it in 60 seconds — zero API keys

```bash
git clone https://github.com/guhandi/hoops && cd hoops
uv sync
uv run hoops process-all fixtures --no-email
open out/index.html
```

That runs the full pipeline — isolation-gated parsing, invariants, stats, interactive reports — over the committed golden dataset (real recordings + cached transcripts). No accounts, no keys, nothing to configure. `uv run hoops score` prints the accuracy gate table the same way.

| ![Shot timeline](docs/assets/report-timeline.png) | ![Session stats](docs/assets/report-stats.png) |
|---|---|
```

Then keep the existing Purpose/How-it-works prose (dropping the now-duplicated old title/opening paragraph — merge, don't repeat).

- [ ] **Step 2: Rewrite Setup** — replace the launchd-only setup section with:

```markdown
## Deploy your own (~15 minutes, all free-tier)

The primary deployment is serverless: your phone POSTs recordings to a [Modal](https://modal.com) endpoint, artifacts live in Cloudflare R2, reports arrive by email. Infra cost: $0/month; API cost ≈ 1¢/session.

**[→ docs/deploy-your-own.md](docs/deploy-your-own.md)** — accounts checklist, one `.env`, two commands, smoke test, phone Shortcut.

### Local fallback mode (macOS)

No cloud required: an Apple Shortcut drops recordings in iCloud Drive and a launchd job on your Mac polls and processes them. `bash scripts/install_launchd.sh` schedules it (generates `com.hoops.poller.plist` from your clone's path). Same pipeline, slower delivery (~5-10 min). See [docs/architecture.md](docs/architecture.md) for both paths.
```

Keep `GMAIL_ADDRESS` override note; update the troubleshooting `launchctl list` label; in the Accuracy/testing section add one sentence: "`hoops score` writes its results back into `fixtures/manifest.csv` (the `heard_calls/got_calls/match/scored_at` columns) — that diff is intentional."

- [ ] **Step 3: Verify** — markdown renders (eyeball with `grep -n "](" README.md` link-check via the repo pattern; all asset/doc paths exist), `uv run pytest -q` green.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README front door — hero demo, badges, zero-key quickstart, cloud-first setup

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: CI workflow + hygiene + verification gates

**Files:**
- Create: `.github/workflows/ci.yml`
- Delete (untrack): `.DS_Store`, `fixtures/.DS_Store`; delete stray `fixtures/manifest_scored.csv` if present
- Add: `docs/superpowers/plans/2026-07-30-zip-email-attachment.md` (stray untracked process doc)

- [ ] **Step 1: Write `.github/workflows/ci.yml`**

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - run: uv sync --extra cloud
      - run: uv run pytest -q
```

- [ ] **Step 2: Hygiene**

```bash
git rm --cached .DS_Store fixtures/.DS_Store
rm -f fixtures/manifest_scored.csv
git add docs/superpowers/plans/2026-07-30-zip-email-attachment.md .github/workflows/ci.yml
```

- [ ] **Step 3: The grep gate (spec verification)**

`git grep -il "guhandiji\|guhansundar\|com\.guhan"` must return ONLY files under `docs/archive/`, `docs/specs/`, `docs/superpowers/`, `docs/writeups/`, `docs/decisions/` (historical records). Any hit in code/config/scripts/README/reader-path docs = fix before proceeding.

- [ ] **Step 4: Stranger simulation**

In a scratch dir: `git clone /Users/guhansundar/Documents/hoops /tmp/hoops-stranger && cd /tmp/hoops-stranger && git checkout feat/public-release && uv sync && uv run hoops process-all fixtures --no-email && test -f out/index.html && echo DEMO-OK` — then `DRY_RUN=1 bash scripts/install_launchd.sh` writes a plist containing `/tmp/hoops-stranger` (verify, then `rm ~/Library/LaunchAgents/com.hoops.poller.plist`), then `rm -rf /tmp/hoops-stranger`.

- [ ] **Step 5: Full suite + commit**

```bash
uv run pytest -q
git commit -m "ci: GitHub Actions test workflow; untrack OS debris

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Final whole-branch review, then finish** — per subagent-driven-development: package over `0bff3ff..HEAD`, most capable model; one fix wave max; then finishing-a-development-branch (base `main`). Post-merge the first Actions run turns the badge green — verify on GitHub.

---

## Self-review notes (already applied)

- Spec coverage: W1 → Tasks 1-2; W2 → Task 4; W3 → Tasks 3, 5, 6; W4 → Task 7. Kept-items (voice fixtures, pending-work list, score write-back) need no task — Task 6 documents the write-back; nothing removes the rest.
- The `robot@example.com` override test already exists — Task 1 only flips the no-env assertion.
- Task 5 is controller-assisted (Playwright MCP lives with the controller); its fallback (stills-as-hero) is explicit so Task 6 isn't blocked.
- Badge URL/workflow name fixed as `ci.yml` in both Task 6 and Task 7 — consistent.
- `HOOPS_ENDPOINT` intentionally NOT in the Modal secret (it's client-side only: acceptance script + docs) — the Task 4 secret command matches what `cloud/modal_app.py` actually reads.
