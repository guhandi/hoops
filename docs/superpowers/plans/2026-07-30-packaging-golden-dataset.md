# Packaging the Golden-Dataset Methodology — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the proven golden-dataset methodology into four in-repo documents — binding methodology doc, public deep-dive write-up, generated evidence dashboard, generalizable pattern doc — all drawing from evidence already committed.

**Architecture:** One evidence base (labeled `fixtures/manifest.csv`, `benchmarks/out/metrics.json`, `uv run hoops score` output, `docs/decisions/001-transcriber-selection.md`, committed transcripts), four documents in dependency order. Three are prose; one is a stdlib generator script producing a committed self-contained HTML page.

**Tech Stack:** Markdown, Python 3.12 stdlib (showcase generator), pytest.

**Spec:** `docs/superpowers/specs/2026-07-30-packaging-golden-dataset-methodology-design.md`

## Global Constraints

- Nothing under `src/hoops/` may be modified; no benchmark behavior changes (showcase generator + test are additive only).
- Showcase page: ONE self-contained HTML file — inline CSS, inline SVG, no CDN, no external requests, no JS libraries; generator is pure stdlib.
- All numbers in every document come from the evidence files verbatim — never invent or round beyond what the source shows. Numbers are frozen at the current evidence state (post-labeling, commit 8d71e62).
- Verbatim transcript quotes are used as-is, profanity included (owner decision).
- `uv run pytest` must stay green (160 currently).
- Commit trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## Evidence reference (single source of truth for all four tasks)

Implementers: pull numbers from here; each is verifiable in the named source.

**Gate table** (source: `uv run hoops score`, 10 labeled fixtures):
recall 0.565 FAIL (gate 0.99) · precision 1.000 PASS (gate 0.99) · classification 1.000 PASS (gate 0.98) · exact_fraction 0.000 FAIL (gate 0.9) · gap_mae n/a PASS (gate 0.5) · phantom_on_traps 0 PASS (gate 0) · invariant_mismatches 1 FAIL (gate 0, hard).

**Per-fixture score** (expected→got): F02 8→2 · F06 15→11 · R01 12→9 · R02 11→3 · F01 14→14 (not exact) · F04 12→11 · F05 9→7 · F08 4→2 · F07 16→13 · F07b 7→7 exact.

**Model comparison** (source: `benchmarks/out/metrics.json` models section):
| model | coverage | rtf_median | peak_rss_max MB | cost |
|---|---|---|---|---|
| whisper-1 | 14/14 | 0.04 | n/a (API) | $0.113 |
| mlx-whisper | 14/14 | 1.586 | 2324 | — |
| parakeet-mlx | 14/14 | 0.049 | 870 | — |
| whisperx | 14/14 (words dropped) | 0.709 | 2675 | — |
| faster-whisper | 1/14 partial | 11.349 | 1546 | — |

**Disqualifier evidence:**
- mlx-whisper, `benchmarks/out/transcripts/mlx-whisper/D02.json`, hallucination loop — transcript tail: `"make. make. make. make. make. make. make. make. make. make. make. make. make. make. make. I guess I'll stop there."` (15 phantom makes; whisper-1's transcript of the same audio has no loop).
- parakeet-mlx, `benchmarks/out/transcripts/parakeet-mlx/R02.json`, quiet-audio collapse — full text: `"This make this"` (whisper-1 heard 10 calls on the same audio).
- whisperx — 27 detections total vs 122–184 for peers; 0 detections on R02, D02, F02 (forced alignment silently drops words).
- faster-whisper — 381 s to transcribe 33.6 s of audio (F08), RTF ≈ 11 incl. model load; impractical for a morning loop.
- crisper-whisper — skipped: HF `transformers` pipeline cannot decode `.m4a` (`benchmarks/out/skips.json`).

**Cross-model timing agreement** (median |Δmid| on shared consensus calls): faster-whisper↔mlx-whisper 0.020 s · whisper-1↔local family ≈ 0.17–0.30 s.

**Benchmark Mode A** (strict full-sequence match vs owner labels, 10 fixtures): parakeet-mlx perfect 5/10 · whisper-1 3/10 (incl. F02, the trap fixture) · mlx-whisper 1/10 · whisperx 0/10 · F08 scores 0 for every backend by design (owner label is post-correction truth: 4 calls; raw ASR legitimately hears 5 call words).

**Limitations register (causes):**
1. Stale production transcript caches — `fixtures/transcripts/07272026_MorningHoops.json` (R02) still contains `mess ×6`; predates the widened bias prompt. Benchmark's fresh whisper-1 R02 hears `miss ×5`. Refreshing caches is the single highest-leverage recall fix.
2. Invariant labels wrong for non-session fixtures — violations are I1/I6 ("session ends with three straight makes"); most fixtures (and their expected sequences, e.g. F07b ends `…miss`) are not complete sessions. `expect_invariants_pass=TRUE` is mislabeled for those rows.
3. F03/F09/F10 unrecorded (conversational call words; deliberately uncalled shot; out-of-breath + trailing silence).
4. F02 isolation negative margin — whisper-1 real-call isolations 0.0–0.5 s vs bait at 0.8 s (inverted); isolation alone cannot separate real from bait on F02.
5. D01–D04 unlabeled (`expected_calls` empty).

**Decision:** stay on whisper-1 (`docs/decisions/001-transcriber-selection.md`).

---

### Task 1: `docs/methodology.md` + CLAUDE.md wiring

**Files:**
- Create: `docs/methodology.md`
- Modify: `CLAUDE.md` (two one-line additions)

**Interfaces:**
- Produces: `docs/methodology.md` — Tasks 2 and 4 reference it by path; CLAUDE.md points to it.

- [ ] **Step 1: Write `docs/methodology.md`** with exactly these sections, using the Evidence reference above for every number:
  1. **Principles** — (a) no capability is claimed working without a labeled dataset covering it; (b) gates decide done, not vibes; (c) precision-first for this domain: a phantom shot is a hard failure, a missed shot is a tuning problem.
  2. **The loop** — record → label (`benchmarks/out/draft_truth.csv` draft → owner labels → canonicalize into `fixtures/manifest.csv` `expected_calls`, space-separated `make`/`miss`) → gate (`uv run hoops score`) → build → score → improve. Note the label format contract: `score.py` and `analyze.py` both `.split()` and compare canonical sequences.
  3. **Current gate status** — the gate table verbatim, dated 2026-07-30, with the sentence: precision/phantom are the load-bearing passes; recall/exact failures decompose into the limitations below.
  4. **Limitations register** — the 5 numbered limitations with causes, each with its fix owner (cache refresh = cheap API rerun; invariant labels = owner relabel or scope I1/I6 out of fixture scoring; F03/F09/F10 = owner records; F02 margin = revisit after labeling; D01–D04 = owner labels).
  5. **How AI sessions use this** — capability work starts with "which labeled fixture covers this?"; if none exists, the first task is creating/recording/labeling one; scores may only be claimed from actual `uv run hoops score` / benchmark output, never estimated.
- [ ] **Step 2: Wire CLAUDE.md** — in the "Read first" line, append `docs/methodology.md (golden-dataset methodology — read before capability work)`. In "Development rules", add: `- New capability ⇒ new labeled fixture first; gates (uv run hoops score) decide done. See docs/methodology.md.`
- [ ] **Step 3: Verify** — `grep -c "methodology.md" CLAUDE.md` returns ≥ 2; every number in the doc matches the Evidence reference; `uv run pytest -q` still green (no code touched, sanity only).
- [ ] **Step 4: Commit** — `git add docs/methodology.md CLAUDE.md && git commit -m "docs: golden-dataset methodology — binding loop, gates, limitations"`

---

### Task 2: Public deep-dive write-up

**Files:**
- Create: `docs/writeups/2026-07-30-empirical-model-selection.md`

**Interfaces:**
- Consumes: `docs/methodology.md` (Task 1) — link to it; Evidence reference above.

- [ ] **Step 1: Write the piece**, 1500–2500 words, engineer audience, first person (Guhan's voice), with this arc — each bullet is a section, each fact from the Evidence reference:
  1. **Hook / problem** — one-button morning free-throw voice log; whisper transcribes call-outs; the question isn't "does it demo well" but "when does it break".
  2. **Why golden datasets when building with AI** — the thesis: AI writes the code, so the human's leverage is owning ground truth; a labeled dataset turns "looks right" into a score; you know what you're validating and whether you're improving.
  3. **The dataset** — 14 recorded fixtures + 2 real sessions, conditions matrix (quiet, music, chatty commentary, beep timing, corrections), owner-labeled `expected_calls`, trap sentences planted in F02.
  4. **The benchmark** — six ASR backends, isolated PEP 723 envs, same audio, cached transcripts, one HTML report. Model table verbatim.
  5. **The evidence, model by model** — the four disqualifiers with verbatim quotes (D02 loop, R02 "This make this", whisperx zero-detection fixtures, faster-whisper 381 s / 33.6 s), then the decision: whisper-1, $0.113 for the whole suite.
  6. **What the gates revealed** — gate table verbatim; the honest decomposition: perfect precision (the failure mode that matters), recall 0.565 mostly explained by stale caches (R02 `mess ×6`) and mislabeled invariant expectations — i.e., the gates found *data* bugs, not just code bugs, and that's the point.
  7. **The loop forward** — adding a capability = adding a labeled dataset; F03/F09/F10 as the named next datasets; parakeet as a cheap independent cross-check against whisper-family shared hallucinations.
  8. **Close** — restate: with golden data, both the human and the AI know when things work.
- [ ] **Step 2: Verify** — word count 1500–2500 (`wc -w`); every number spot-checked against the Evidence reference; contains the verbatim D02 tail quote and links to `docs/methodology.md`, `docs/decisions/001-transcriber-selection.md`, `benchmarks/README.md`.
- [ ] **Step 3: Commit** — `git add docs/writeups/2026-07-30-empirical-model-selection.md && git commit -m "docs: write-up — empirical model selection with golden datasets"`

---

### Task 3: Showcase dashboard generator + page

**Files:**
- Create: `benchmarks/showcase.py`, `docs/showcase/model-selection.html` (generated, committed)
- Test: `tests/test_showcase.py`

**Interfaces:**
- Consumes: `benchmarks/out/metrics.json` (must exist — it is committed? NO: it is gitignored and regenerable; the generator must fail with a clear message telling the user to run `uv run python -m benchmarks.analyze` first). Reuses `_esc` from `benchmarks/report.py` (`from benchmarks.report import _esc`; verify the helper name in report.py before importing — if it differs, use the actual name).
- Produces: `render_showcase(metrics: dict) -> str` returning the full HTML document string (decision/gate text lives in module constants); `main()` reads `benchmarks/out/metrics.json`, writes `docs/showcase/model-selection.html`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_showcase.py
import pytest
from pathlib import Path
from benchmarks.showcase import render_showcase

pytestmark = pytest.mark.unit

METRICS = {
    "models": {
        "whisper-1": {"rtf_median": 0.04, "cost_usd": 0.113,
                      "detections_found": 148, "detections_matched": 48, "detections_extra": 100},
        "parakeet-mlx": {"rtf_median": 0.049, "peak_rss_max": 870.0,
                         "detections_found": 122, "detections_matched": 51, "detections_extra": 71},
    },
    "fixtures": {}, "skips": [], "isolation": {"threshold": 0.04, "margin": -0.8},
    "agreement": {"whisper-1|parakeet-mlx": 0.3}, "n_fixtures_total": 14,
}

def test_showcase_self_contained():
    html = render_showcase(METRICS)
    assert html.startswith("<!doctype html>")
    for marker in ["whisper-1", "Decision", "Gate", "parakeet-mlx", "<svg"]:
        assert marker in html
    low = html.lower()
    assert "cdn" not in low
    assert 'src="http' not in low and 'href="http' not in low
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_showcase.py -q` → import error.
- [ ] **Step 3: Implement `benchmarks/showcase.py`** — stdlib only. Structure: module docstring; `GATES` constant holding the gate-table rows verbatim from the Evidence reference (they come from `hoops score`, not metrics.json — hardcoded snapshot is intentional, comment says so and dates it); `DISQUALIFIERS` constant with the four evidence cards (model, one-line verdict, verbatim quote/number, source file path); `render_showcase(metrics)` builds sections: (1) headline decision banner; (2) model comparison table from `metrics["models"]` (rtf_median, peak_rss_max, cost_usd, found/matched/extra) with the same "—" fallbacks report.py uses; (3) disqualifier cards from the constant; (4) gate table from `GATES`; (5) the loop diagram as a hand-written inline `<svg>` (record → label → gate → build → score → improve, six rounded rects + arrows); (6) footer linking relative paths `../decisions/001-transcriber-selection.md` and `../methodology.md`. All dynamic strings through `_esc`. `main()`: read `REPO/benchmarks/out/metrics.json` (clear `sys.exit` message naming `uv run python -m benchmarks.analyze` if missing), write `REPO/docs/showcase/model-selection.html`, print the path. Note: `render_showcase` takes only `metrics` (the decision text lives in constants), matching the test.
- [ ] **Step 4: Run tests** — `uv run pytest tests/test_showcase.py -q` → pass; full `uv run pytest -q` → green.
- [ ] **Step 5: Generate the real page** — ensure metrics exist (`uv run python -m benchmarks.analyze` if needed), then `uv run python -m benchmarks.showcase`; open `docs/showcase/model-selection.html` and confirm it renders with real numbers.
- [ ] **Step 6: Commit** — `git add benchmarks/showcase.py tests/test_showcase.py docs/showcase/model-selection.html && git commit -m "feat(bench): curated showcase dashboard — decision, evidence, gates"`

---

### Task 4: Capture-pattern doc + checklist

**Files:**
- Create: `docs/pattern/README.md`

**Interfaces:**
- Consumes: `docs/methodology.md` (Task 1) — the hoops-specific instance; this doc is the generalization.

- [ ] **Step 1: Write `docs/pattern/README.md`** — the pattern abstracted from hoops for "instance #2" (any capture-domain: voice → events → stats). Sections:
  1. **The pattern in one paragraph** — capture device → drop folder → transcribe → vocabulary-gated parse → invariants → stats → report, validated end-to-end by golden labeled datasets and score gates.
  2. **Manifest schema** — the `fixtures/manifest.csv` columns with semantics, one line each (filename, fixture_id, category, status, vocabulary, duration_s, timing_ground_truth, beep_interval_s, expected_calls [space-separated canonicals], expect_invariants_pass, traps_planted, label_status, notes; note which are scoring inputs vs metadata).
  3. **Labeling workflow** — record → benchmark/consensus produces `draft_truth.csv` → owner corrects against audio → canonicalize (surface→canonical via vocabulary) → `expected_calls`; warn about the two real traps hit in hoops: surface-vs-canonical mismatch, and post-correction labels vs raw-ASR sequences (F08).
  4. **Gate template** — precision, recall, exact_fraction, phantom_on_traps, invariant_mismatches, gap_mae; with the hoops thresholds as defaults and the principle: pick your hard-failure direction first (hoops: phantoms) and gate it at zero.
  5. **Benchmark harness shape** — TranscriptResult JSON contract; one PEP 723 script per backend in isolated envs (dependency conflicts impossible by construction); transcript cache + skips.json; consensus clustering for draft truth; pointer to `benchmarks/` as the reference implementation.
  6. **Shadow period** — run the new pipeline alongside reality for N sessions, eyeball outputs vs experience before trusting.
  7. **Instance #2 start-here checklist** — 10 numbered steps: (1) define events + canonical outcomes; (2) pick call-word vocabulary, test transcription variance early; (3) record 5 fixtures covering happy path + your scariest condition; (4) write the manifest; (5) transcribe with your candidate model; (6) build the smallest parser; (7) generate draft truth, label it; (8) stand up score gates, set the zero-tolerance one; (9) benchmark alternatives only when you have labels; (10) shadow period before trusting.
- [ ] **Step 2: Verify** — schema section names every column actually present in `fixtures/manifest.csv` header (cross-check with `head -1 fixtures/manifest.csv`); links to `docs/methodology.md` and `benchmarks/README.md` resolve.
- [ ] **Step 3: Commit** — `git add docs/pattern/README.md && git commit -m "docs: generalizable capture-pattern + instance-2 checklist"`

---

## Verification (whole plan)

- `uv run pytest -q` green (160 + new showcase test).
- `docs/showcase/model-selection.html` opens locally, renders all sections, zero external references.
- `grep -c "methodology.md" CLAUDE.md` ≥ 2.
- Spot-check: every number in all four documents traces to the Evidence reference (which traces to `metrics.json` / `hoops score` / committed transcripts).
