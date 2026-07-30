# Packaging the golden-dataset methodology — design

**Date:** 2026-07-30 · **Status:** approved (brainstorm 2026-07-30) · **Owner:** Guhan

## Goal

Package what the ASR benchmark proved — golden labeled datasets + empirical model selection + score gates = knowing when AI-built software works — into four in-repo documents drawing from one evidence base. Nothing new gets measured; this is packaging.

**Evidence base (already committed):** labeled `fixtures/manifest.csv` (10 fixtures), transcript caches (`fixtures/transcripts/`, `benchmarks/out/transcripts/`), `benchmarks/out/metrics.json`, `uv run hoops score` gate table, `docs/decisions/001-transcriber-selection.md`.

## Decisions made in brainstorming

- **All four deliverables, one spec, sequenced** (methodology → write-up → dashboard → pattern).
- **Venue: in-repo markdown + HTML** (no artifacts, no external publishing platform).
- **Write-up tone: technical deep-dive**, ~1500–2500 words, engineer audience.
- **Template form: pattern doc + checklist**, no code extraction until instance #2 exists (YAGNI).
- **Verbatim transcript quotes, profanity included** (authenticity over polish).
- **Numbers frozen** at the 8d71e62 evidence state; write-up is a dated snapshot, methodology doc is living.

## The four pieces

### 1. `docs/methodology.md` — binding golden-dataset methodology (living doc)
Principles: no capability claimed working without a labeled dataset covering it; gates decide done, not vibes; precision-first for this domain (phantom shots = hard failure). The loop: record → label (draft_truth → owner → canonicalize) → gate → build → score → improve. Current gate-status table (precision 1.000 PASS · recall 0.565 FAIL · exact 0.000 FAIL · phantom 0 PASS · invariant_mismatches 1 FAIL) and a limitations register with causes (stale production caches — R02 `mess ×6` predates widened prompt; invariant labels wrong for non-session fixtures via I1/I6; F03/F09/F10 unrecorded; F02 isolation margin −0.8 s; D01–D04 unlabeled). Ends with "how AI sessions use this": capability work starts with "which labeled fixture covers this?"; new capability ⇒ new labeled dataset first. Wired into `CLAUDE.md` ("Read first" pointer + one Development rule line).

### 2. `docs/writeups/2026-07-30-empirical-model-selection.md` — public deep-dive (snapshot)
Arc: the problem (one-button voice capture) → why golden datasets when building with AI → the fixture suite and labeling loop → six models benchmarked → per-model disqualifying evidence (mlx-whisper D02 hallucination loop quoted verbatim; parakeet-mlx R02 quiet-collapse "This make this"; whisperx zero-detection fixtures; faster-whisper RTF ≈ 11) → the decision (whisper-1, with numbers) → what the gates revealed (perfect precision, weak recall, and why) → the meta-lesson: adding capability = adding a labeled dataset. Every number traceable to `metrics.json`, score output, or a committed transcript.

### 3. `benchmarks/showcase.py` → `docs/showcase/model-selection.html` — curated dashboard
Generator script (stdlib only) reusing `benchmarks/report.py` helpers and reading `benchmarks/out/metrics.json`. Curated sections: headline decision, model comparison table, three disqualifier evidence cards, gate table, loop diagram (inline SVG). Same constraints as report.html: one self-contained file, inline CSS/SVG, zero external requests. Output committed (regenerable snapshot). One pytest mirrors the existing self-containment test.

### 4. `docs/pattern/README.md` — generalizable capture-pattern + checklist
The pattern abstracted from hoops: manifest schema spec, labeling workflow, vocabulary/canonicalization design, gate template, benchmark harness shape (PEP 723 isolated backends, TranscriptResult contract, cache + skips), shadow-period practice. Ends with an "instance #2 start-here" checklist (~10 steps from "record 5 fixtures" to "first gate table").

## Non-goals

- No new measurements, recordings, or cache refreshes (separate pending work).
- No template code extraction, no separate repo, no external hosting.
- No changes to `src/hoops/` or benchmark behavior (except the additive showcase generator + test).

## Verification

Full suite green including new showcase test; showcase page renders locally with zero external refs; CLAUDE.md references methodology.md; write-up numbers spot-checked against the evidence files.
