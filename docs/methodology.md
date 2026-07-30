# Golden-Dataset Methodology

Binding practice for this repo. Applies to any capability claim in hoops (and to instance #2, whatever that ends up being).

## 1. Principles

- No capability is claimed working without a labeled dataset covering it. "It sounded right in one recording" is not evidence.
- Gates decide done, not vibes. A change is finished when `uv run hoops score` passes the relevant gates, not when the diff looks plausible.
- Precision-first for this domain: a phantom shot is a hard failure (it corrupts the stat line silently); a missed shot is a tuning problem (it's visible, and recoverable by re-listening). Optimize in that order.

## 2. The loop

```
record → label → gate → build → score → improve
```

1. **Record** the audio fixture (or capture a real session).
2. **Label**: `benchmarks/out/draft_truth.csv` is generated as a draft (consensus clustering across models), the owner corrects it against the audio, and the corrected sequence is canonicalized into `fixtures/manifest.csv`'s `expected_calls` column — space-separated canonical tokens, `make`/`miss` only.
3. **Gate**: `uv run hoops score` runs the fixture set against the current pipeline and reports pass/fail per gate.
4. **Build**: make the change (parser, vocabulary, prompt, whatever).
5. **Score**: rerun the gate.
6. **Improve**: iterate until the gates you care about pass, or the failure is filed as a known limitation (section 4).

**Label format contract:** `expected_calls` is a space-separated string of canonical tokens (`make`/`miss`). Both `src/hoops/score.py` and `benchmarks/analyze.py` call `.split()` on this column and compare the resulting sequence directly — the canonical vocabulary (not the surface words whisper actually transcribes) is what labels and scoring both operate on. Get this wrong and every gate downstream is silently comparing the wrong thing.

## 3. Current gate status (2026-07-30)

Source: `uv run hoops score`, 10 labeled fixtures.

| gate | value | threshold | result |
|---|---|---|---|
| recall | 0.565 | 0.99 | FAIL |
| precision | 1.000 | 0.99 | PASS |
| classification | 1.000 | 0.98 | PASS |
| exact_fraction | 0.000 | 0.9 | FAIL |
| gap_mae | n/a | 0.5 | PASS¹ |
| phantom_on_traps | 0 | 0 (hard) | PASS |
| invariant_mismatches | 1 | 0 (hard) | FAIL |

¹ `gap_mae` is a silent n/a-PASS, not a verified one: `score_fixture` (`src/hoops/score.py`) reads `row.get("expected_gaps")`, a manifest column that no longer exists — `timing_ground_truth`/`beep_interval_s` currently feed only the benchmark's `gap_stats`, not this score gate, and wiring them in is still pending (see `docs/pattern/README.md` §4). The gate always evaluates to `None` and passes by default, not by evidence.

Per-fixture score (expected→got): F02 8→2 · F06 15→11 · R01 12→9 · R02 11→3 · F01 14→14 (not exact) · F04 12→11 · F05 9→7 · F08 4→2 · F07 16→13 · F07b 7→7 exact.

Precision and phantom-on-traps are the load-bearing passes — the pipeline does not hallucinate shots, including on fixtures with planted trap sentences. Recall and exact-match failures are not evidence of a broken parser; they decompose into the six limitations below, each with a known cause and owner.

## 4. Limitations register

1. **Stale production transcript caches.** `fixtures/transcripts/07272026_MorningHoops.json` (R02) still holds `mess ×6`, transcribed before the bias prompt widened to six call words; a fresh whisper-1 pass on the same audio hears `miss ×5`. **Fix:** cheap API rerun — refresh the cache and rescore. Highest-leverage recall fix available.
2. **Invariant labels wrong for non-session fixtures.** Violations are on I1/I6 ("session ends with three straight makes"); most fixtures (e.g. F07b, which ends `…miss`) are deliberately partial clips, not full sessions, so `expect_invariants_pass=TRUE` is mislabeled for those rows. **Fix:** owner relabel, or scope I1/I6 out of fixture-level scoring entirely.
3. **F03/F09/F10 unrecorded.** Conversational call words, a deliberately uncalled shot, out-of-breath + trailing silence — the trickiest conditions are exactly the ones missing. **Fix:** owner records them.
4. **F02 isolation negative margin.** whisper-1 real-call isolations land 0.0–0.5 s vs. the planted bait at 0.8 s — inverted from what the isolation gate expects, so isolation alone can't separate real calls from bait on this fixture. **Fix:** revisit after labeling; may need a second signal beyond isolation.
5. **D01–D04 unlabeled.** `expected_calls` is empty for these rows. **Fix:** owner labels.
6. **`gap_mae` gate is unwired, not verified.** `score_fixture` reads `row.get("expected_gaps")`, a manifest column removed from the schema; `timing_ground_truth`/`beep_interval_s` currently only feed the benchmark's `gap_stats`, not this score gate. The gate reports `n/a` and passes by default — a silent no-op, not a verified pass. **Fix:** wire `beep_interval_s`/`timing_ground_truth` into `gap_mae` (CLAUDE.md pending item 3).

## 5. How AI sessions use this

- Capability work starts with: **which labeled fixture covers this?** If none exists, the first task is creating, recording, and labeling one — not writing the feature and hoping.
- Scores may only be claimed from actual `uv run hoops score` or benchmark output. Never estimate, extrapolate, or restate a stale number from memory — rerun it.
- If a change touches `parse.py`/`stats.py`/`invariants.py` or the vocabulary/prompt, follow the loop in section 2 before calling it done: `uv run hoops replay --all`, diff sessions, then `uv run hoops score`.

See also: `docs/decisions/001-transcriber-selection.md` (model selection evidence), `benchmarks/README.md` (benchmark harness), `docs/architecture.md` (pipeline module map).
