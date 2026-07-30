# The Capture Pattern

hoops is instance #1 of a generalizable pattern: turn a spoken-word activity into
labeled data, a scored pipeline, and a report — with the score gates, not the demo,
deciding when it works. This doc abstracts what's reusable for instance #2 (any
capture domain — not necessarily voice, not necessarily basketball).

## 1. The pattern in one paragraph

Capture device (phone, mic, wearable) records raw audio into a drop folder →
a pipeline transcribes it → a vocabulary-gated parser extracts events from the
transcript → invariants sanity-check the event sequence → stats aggregate the
events → a report goes out. None of that is claimed working until it's validated
end-to-end against golden labeled datasets and score gates — see
`../methodology.md` for the binding version of this loop as hoops runs it today.

## 2. Manifest schema

Columns actually present in `fixtures/manifest.csv` (verified against its header),
one line each. "Scoring input" columns are read by `src/hoops/score.py` /
`benchmarks/analyze.py` and feed a gate; everything else is metadata for humans
running or triaging the benchmark.

| column | meaning | scoring input? |
|---|---|---|
| `filename` | audio file for this fixture | no (I/O path) |
| `fixture_id` | short id (F01, R02, D03, …) | no (join key) |
| `category` | `fixture` / `real_session` / `dev` | no |
| `status` | `recorded` / `NOT_RECORDED` | yes — gates whether the benchmark runs this row at all |
| `vocabulary` | which vocabulary set applies (`swish_brick`, `make_miss`) | yes — selects the surface→canonical map used to parse and to canonicalize labels |
| `duration_s` | audio length in seconds | no |
| `size_bytes` | audio file size | no |
| `audio_format` | container/codec (e.g. `.m4a`) | no |
| `conditions` | free-text condition tags (quiet, music, chatty, …) | no |
| `what_it_tests` | free-text — why this fixture exists | no |
| `use_for` | `GATE` (must pass), `tuning`, or `regression` | yes — only `GATE` rows enter the aggregate gate scores |
| `timing_ground_truth` | TRUE if the fixture has a metronome/beep for boundary-timing validation | yes (feeds `gap_mae`, see §4) |
| `beep_interval_s` | beep period in seconds, when `timing_ground_truth=TRUE` | yes (feeds `gap_mae`) |
| `expected_calls` | owner-labeled ground truth: space-separated **canonical** tokens (`make`/`miss`), not surface words | yes — the sequence every accuracy gate compares against |
| `expected_shot_count` | expected number of shots, independent of exact sequence | no (sanity cross-check) |
| `expect_invariants_pass` | TRUE if the expected sequence should satisfy the invariants module | yes — feeds `invariant_mismatches` |
| `contains_correction` | TRUE if the recording includes a spoken self-correction ("actually that was a brick") | no (flags fixtures needing the F08-style caution in §3) |
| `contains_note` | TRUE if the recording includes off-vocabulary commentary/chatter | no |
| `traps_planted` | bait sentences planted to probe false positives, if any | yes — feeds `phantom_on_traps` |
| `label_status` | labeling state (e.g. unlabeled, owner-reviewed) | no (process metadata) |
| `notes` | free text | no |

## 3. Labeling workflow

1. **Record** the fixture (or capture a real session).
2. **Draft**: run the benchmark/consensus step — `benchmarks/out/draft_truth.csv`
   is generated from majority agreement across transcriber backends. This is a
   starting point, not ground truth.
3. **Owner corrects** the draft against the actual audio, by ear.
4. **Canonicalize**: map the corrected surface words to canonical tokens through
   the vocabulary map, then write the result into `expected_calls`.

Two traps from hoops history, both real, both worth guarding against explicitly:

- **Surface vs. canonical mismatch.** Owner labels have arrived as capitalized,
  comma-separated surface forms — `"Brick, splash, …"` — while every scorer
  expects space-separated canonical tokens — `"miss make …"`. Canonicalization
  through the vocabulary map is a required step in the workflow, not a nicety
  you can skip when the transcript "looks obviously right." Skipping it means
  every downstream gate silently compares the wrong strings.
- **Post-correction labels vs. raw-ASR sequences.** F08's owner label is 4 calls,
  because the owner's spoken self-correction ("actually, that was a brick")
  voids one — but raw ASR on the same clip correctly hears 5 call words; the
  correction phrase itself doesn't remove a word from the audio. Parser-level
  scoring (which understands corrections) is expected to hit 4; raw-detection
  scoring reads the same fixture as a miss, by design. Know which layer you're
  scoring before calling a mismatch a bug.

## 4. Gate template

Six gates, source `uv run hoops score`:

| gate | what it measures | hoops default threshold |
|---|---|---|
| `precision` | of detected calls, fraction that were real | 0.99 |
| `recall` | of expected calls, fraction detected | 0.99 |
| `exact_fraction` | fraction of fixtures with an exact sequence match | 0.90 |
| `phantom_on_traps` | detections on planted bait sentences | 0 (hard) |
| `invariant_mismatches` | fixtures where the invariants module's verdict disagrees with the label | 0 (hard) |
| `gap_mae` | mean absolute error of detected-call timing vs. beep ground truth | 0.5 s |

The principle, independent of the numbers: **pick your hard-failure direction
first.** In hoops that's phantom shots — a false positive silently corrupts the
stat line, while a missed shot is visible and recoverable by re-listening — so
`phantom_on_traps` and `invariant_mismatches` are gated at zero, hard-fail, no
threshold negotiation. Recall and exact-match can fail while you iterate;
phantoms cannot. Decide your domain's equivalent before you start scoring.

## 5. Benchmark harness shape

- **`TranscriptResult`** (`benchmarks/transcribers/base.py`) is the JSON contract
  every backend writes and every analysis step reads: `model_id`, `fixture`,
  `words` (list of `{word, start, end, confidence}`), `text`, `runtime_s`,
  `peak_rss_mb`, `prompt_used`. Any new backend just needs to produce this shape.
- **One PEP 723 script per backend**, each in its own isolated environment
  (`benchmarks/transcribers/*.py`, each with an inline `# /// script` dependency
  block) — dependency conflicts between backends are impossible by construction,
  since none of them share a Python environment.
- **Transcript cache + `skips.json`**: every transcription is cached to disk
  (`benchmarks/out/transcripts/{model}/{fixture}.json`) so re-analysis doesn't
  re-pay API/compute cost, and every failure is logged with a reason instead of
  silently dropping a model/fixture pair.
- **Consensus clustering for draft truth**: with no labels yet, majority
  agreement across backends produces `draft_truth.csv` as a labeling starting
  point (Mode B in the harness; see below).
- `benchmarks/README.md` is the reference implementation — read it before
  building a second harness from scratch.

## 6. Shadow period

Before trusting a new pipeline (or a materially changed one) with real capture:
run it alongside reality for N sessions and eyeball the outputs against what you
actually remember happening. Gates passing on recorded fixtures is necessary but
not sufficient — a shadow period catches whatever the fixture set didn't think
to cover. hoops's own plan calls for the first 14 real sessions to be shadowed
this way before the pipeline is trusted unsupervised.

## 7. Instance #2 start-here checklist

1. Define your events and their canonical outcomes (hoops: shot → `make`/`miss`).
2. Pick your call-word vocabulary; test transcription variance on it early —
   don't assume the model hears your words consistently.
3. Record 5 fixtures: the happy path, plus your scariest condition (background
   noise, overlapping speech, whatever breaks capture in your domain).
4. Write the manifest (§2) — schema first, rows as you record.
5. Transcribe with your candidate model.
6. Build the smallest parser that turns transcript into events. Resist adding
   sophistication before you have labels to justify it.
7. Generate draft truth (consensus or single-model), then label it by hand
   against the audio (§3) — don't skip canonicalization.
8. Stand up score gates (§4); decide and set your zero-tolerance gate first.
9. Benchmark alternative models/backends only once you have labels to score
   them against — comparing unlabeled outputs is just vibes with extra steps.
10. Run a shadow period (§6) before you trust the pipeline unsupervised.

See also: `../methodology.md` (the hoops-specific instance of this loop, with
current gate numbers and known limitations) and `../../benchmarks/README.md`
(the harness this section describes).
