# Decision 003: Acoustic make/miss separability — null result, do not build the classifier

**Date:** 2026-08-01 · **Status:** accepted · **Input:** `scripts/analyze_separability.py`. Raw output in `out/separability.json` / `out/separability.html` (gitignored, regenerate with `uv run python scripts/analyze_separability.py`).

## Question

Branch B (`hoops.acoustics`) extracts spectral features per impact event — brightness, bandwidth, level, decay — independent of what the voice branch heard. If a make and a miss sound acoustically different (rim rattle vs. net swish, say), those features could seed a future audio-only classifier that cross-checks or replaces the voice call. This is that check, run on every supervised (voice-labelled, acoustically-paired) shot that exists today.

## Dataset

**40 paired shots: 18 make, 22 miss**, pooled across the 9 recorded fixtures with cached transcripts (all `fixtures/*.m4a` except the excluded one below). "Paired" means fusion (`hoops.fusion.fuse`) matched the voice call to a preceding impact cluster inside `[pair_min_s, pair_max_s] = [0.5s, 4.0s]` — the only rows this analysis can use, since unpaired calls have no acoustic features at all (see caveat below).

- **Excluded:** `F05_SwishBrickMusic.m4a` — its detection findings live in decision 002; not re-litigated here.
- **Not recorded yet:** F03, F09, F10 (per `fixtures/manifest.csv` / CLAUDE.md pending work) — not in this dataset.
- **Included, worth flagging:** the two real morning sessions (`07262026_MorningHoops.m4a` / R01, `07272026_MorningHoops.m4a` / R02) are picked up by the same `fixtures/*.m4a` glob as the synthetic F-series and are pooled in without distinction — this is real, if noisy, field data, not just scripted fixtures.

This is well short of the brief's "~100+" sanity estimate. Per-fixture pairing rates (below) are all in a normal 0.33–1.0 range, not a collapse — the shortfall is because only ~35% of live calls across the corpus end up in the fused-and-paired bucket at all (72 live calls total → 40 paired), not because any one fixture failed to pair. This is a **known, expected Task-5 property of this dataset** (isolation gating, quiet/distant audio, and 1:many call-to-event ambiguity all remove candidates before pairing), not a separability artifact — but it does mean every number below carries a small-n caveat.

### Per-fixture pairing rates + latencies

| Fixture | n_calls (live) | n_paired | pairing rate | median latency (s) |
|---|---|---|---|---|
| 07262026_MorningHoops.m4a (R01) | 9 | 3 | 0.333 | 1.273 |
| 07272026_MorningHoops.m4a (R02) | 3 | 2 | 0.667 | 0.822 |
| F00_NormalMakeMiss.m4a | 13 | 7 | 0.538 | 0.836 |
| F00_NormalMakeMiss10secBeep.m4a | 7 | 3 | 0.429 | 1.745 |
| F01_NormalSwishBrick.m4a | 14 | 8 | 0.571 | 1.106 |
| F02_SwishBrickChatty.m4a | 2 | 2 | 1.000 | 1.802 |
| F04_SwishBrickQuiet.m4a | 11 | 7 | 0.636 | 0.913 |
| F06_SwishBrick10secBeep.m4a | 11 | 7 | 0.636 | 0.789 |
| F08_SwishBrickScratchThat.m4a | 2 | 1 | 0.500 | 0.865 |
| **Total** | **72** | **40** | — | — |

F01/F02/F04/F06 pairing rates and median latencies reproduce decision 002's sweep table exactly (0.571/1.000/0.636/0.636), confirming this script's fusion path is consistent with the earlier tuning run.

## Feature separability table

Ranked by `|AUC − 0.5|` (AUC = P(feature(make) > feature(miss)), rank-based, ties count half; 0.5 = coin flip, 1.0 = perfect separation the make-high direction, 0.0 = perfect separation the miss-high direction). Cohen's d is the standardized mean difference (make − miss); by convention |d| ≈ 0.2 small, 0.5 medium, 0.8 large.

| feature | AUC | \|AUC−0.5\| | Cohen's d | n make | n miss |
|---|---|---|---|---|---|
| decay_ratio | 0.381 | 0.119 | −0.385 | 18 | 22 |
| mean_centroid_hz | 0.540 | 0.040 | 0.181 | 18 | 22 |
| burst_duration_s | 0.519 | 0.019 | 0.056 | 18 | 22 |
| n_impacts | 0.503 | 0.003 | −0.023 | 18 | 22 |
| max_peak_rms | 0.501 | 0.001 | −0.078 | 18 | 22 |

## `impact_missing` — absence as signal

A shot's call may have no paired impact at all — the transient wasn't detected (or the pairing window missed it). This matters here specifically because a clean swish is plausibly the *quietest* possible impact (net only, no rim/backboard contact), so "no detected transient" could itself be a make signal that this AUC/Cohen's-d analysis, which only sees paired shots, cannot capture.

Across the same 9 fixtures (voided/scratch rows excluded):

| label | paired | impact_missing | total |
|---|---|---|---|
| make | 18 | 17 | 35 |
| miss | 22 | 15 | 37 |

Roughly half of every label's calls go unpaired, and the split is close to even between make (17/35 = 49%) and miss (15/37 = 41%) — a mild lean toward makes going unpaired more often, consistent with the "swish is quiet" hypothesis, but the gap is small relative to n and not a substitute for a real test. No `ambiguous`-status shots occurred in this dataset (0 across all fixtures), so that failure mode isn't a confound here.

## Caveat: the low-centroid tail events from decision 002

Decision 002 flagged one low-centroid tail event each in F01 (t=88.747s, 583.5 Hz, 1 impact) and F04 (t=106.823s, 462.0 Hz, 1 impact) as probable handling/stop-recording noise rather than real shots. Re-checked here: **neither event paired to a live call** — both land after every live call in their fixture (fusion classifies them `call_missing`, not `paired`), so they are not present in the 40-shot make/miss dataset and did not influence the table above. Recorded per the task brief's instruction to flag this either way.

## Verdict

**Nothing separates. All five features sit at AUC ≈ 0.5 (0.501–0.540) except `decay_ratio`, which shows a weak, wrong-direction-of-interest signal (AUC 0.381, i.e. misses decay *slower* than makes on average, d = −0.385 — small by Cohen's convention).** No feature reaches anywhere near the ≥0.7 AUC bar that would justify classifier work. This is a genuine null result, not a close call: four of five features round to within 0.04 of a coin flip.

**Recommendation: do not build an audio-only make/miss classifier on these features.** The acoustic branch remains valuable as an independent detector (timing, corroboration, the 🤥 no-contact flag) — that's an orthogonal, already-working use — but the spectral features captured today (impact count, centroid, peak RMS, decay ratio, burst duration) carry no discriminative signal between a made and missed shot in this dataset.

### Caveats on the null (small-n, don't over-read either direction)

- **n=40 is small** for AUC/Cohen's-d estimation, especially per-fixture-conditional effects (whisper-quiet vs. chatty vs. beep-timed). A larger corpus (after F03/F09/F10 land and pairing-rate/isolation-gate work improves the ~35% pairing yield) could still surface something decay_ratio's weak lean gestures at — but it would need to move a lot to matter.
- **Selection into "paired" is not random**: this dataset is conditioned on the shot being detected AND falling inside the fusion latency window. The `impact_missing` split above is the honest reminder that roughly half of every label's shots never enter this analysis at all, and the small make/miss imbalance there (49% vs. 41% unpaired) is a rate a classifier of transient-presence, not transient-shape, would need to explain — it is a different (and unexplored) hypothesis from "shape separates make/miss," which is what this doc answers, negatively.
- **Real-session data (R01/R02) is pooled with synthetic fixtures** without separate reporting; if a future pass wants to check whether the synthetic F-series and the real 6am recordings behave differently acoustically, they should be split out — this analysis treats them as one population per the brief's `fixtures/*.m4a` glob.

## Verification

```
uv run pytest
```
267 passed, 1 warning in 61.70s — suite untouched by this change; parse/stats/invariants stayed pure stdlib, no source edits were needed.
