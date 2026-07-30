# Picking a Transcription Model With Data, Not Vibes

I built a one-button morning free-throw log. I push a button, shoot free throws, call out "make" or "miss" after each one, and drop the phone. An Apple Shortcut records the whole thing to iCloud, a Mac-side pipeline picks it up, transcribes it, parses the call-outs into a shot sequence, checks the sequence against a few invariants (a session shouldn't end mid-shot, calls shouldn't cluster impossibly close together), computes stats, and emails me a report before I've finished my coffee. Basketball is instance #1 of a pattern I want to reuse: voice call-outs in, structured events out.

The part of this pipeline I was least sure about wasn't the parser — it's dumb string matching once you have clean words with timestamps. It was transcription. Whisper is good at English. It is not obviously good at "a winded guy standing eight feet from his phone, muttering one of six near-homophone words, sometimes over music, sometimes while narrating his own game." If it mishears "miss" as something outside my vocabulary, I silently lose a shot. If it hallucinates a "make" that was never said, my stat line lies to me and I have no way of knowing, because the whole point of the pipeline is that I don't review every morning's audio by hand.

So the real question was never "does this demo well." A single clean recording of me calling out ten shots in a quiet room proves almost nothing — every model on the market can transcribe that. The question was: across the actual range of conditions a 6am garage session produces, which model breaks, how often, and in which direction. That's not a question you can answer by listening to a demo. It's a question you answer by building a labeled dataset and running models against it.

## Why golden datasets matter more, not less, when AI writes the code

Most of this pipeline — the parser, the benchmark harness, this write-up's source material — was built with AI assistance. That's not incidental to the story; it's the reason the story matters. When an AI can produce a plausible-looking implementation in minutes, "the code looks right" stops being useful signal. It always looks right. That's what makes it dangerous: a hallucination-prone transcriber and a solid one produce transcripts that are equally readable, equally plausible, equally confidence-inspiring on a quick skim.

What doesn't get easier just because AI writes the code is knowing what "correct" means for your specific problem, and having a way to check it that doesn't depend on my judgment call at 6am. That's the leverage that's still mine to own: ground truth. A set of recordings I've personally listened to, shot by shot, and labeled as make or miss. Once that exists, "looks right" turns into a score. I can ask a specific, falsifiable question of any candidate model — recall, precision, does it invent shots that were never taken — instead of eyeballing a transcript and hoping. And critically, I can tell whether a change (a new prompt, a new model, a widened vocabulary) made things better or worse, instead of just different.

Everything that follows in this post is downstream of that one decision: label the data first, then let the data pick the model.

## The dataset

The corpus is 14 recorded audio files, spanning a conditions matrix I built specifically to stress the failure modes I was worried about: quiet-and-distant audio (the actual 6am condition — phone face-down, whisper-quiet), background music, heavy conversational commentary, two fixtures with a 10-second metronome beep for timing ground truth, and one fixture where I speak a correction mid-session. Two of the 14 are real morning sessions (R01, R02) — not staged, just me actually shooting, captured the way the pipeline will see audio in production.

Every fixture has an owner-labeled `expected_calls` field: I listened to the audio and wrote down, in canonical `make`/`miss` tokens, what actually happened, shot by shot. That label is the thing every downstream number in this post gets checked against. And one fixture, F02, has trap sentences deliberately planted in it — bait phrases built to sound like a call-out without being one, specifically to see whether the parser (or the transcriber feeding it) hallucinates a phantom shot out of ordinary chatter. In this domain, a phantom shot is the failure that matters: it corrupts the stat line and I'd have no way to notice.

## The benchmark

With labels in hand, I ran six ASR backends — whisper-1 (OpenAI's API), faster-whisper, mlx-whisper, parakeet-mlx, whisperx, and crisper-whisper — over the same audio and compared what came back. Each backend lives in its own PEP 723 script with its own declared dependencies, so six backends' worth of conflicting ML libraries (different torch builds, mlx, ctranslate2, whatever whisperx wants) never have to coexist in one environment. Transcripts get cached to JSON per model per fixture, so re-running analysis doesn't mean re-transcribing, and the whole comparison collapses into one interactive HTML report.

Here's the model table, verbatim from the benchmark run:

| model | coverage | rtf_median | peak_rss_max MB | cost |
|---|---|---|---|---|
| whisper-1 | 14/14 | 0.04 | n/a (API) | $0.113 |
| mlx-whisper | 14/14 | 1.586 | 2324 | — |
| parakeet-mlx | 14/14 | 0.049 | 870 | — |
| whisperx | 14/14 (words dropped) | 0.709 | 2675 | — |
| faster-whisper | 1/14 partial | 11.349 | 1546 | — |

`rtf_median` is real-time factor — whisper-1 transcribes a recording in about 4% of its own duration; faster-whisper took over 11x the audio length. `crisper-whisper` doesn't even appear in the table, for a reason that turned out to be entirely mundane.

## The evidence, model by model

This is where the table stops being the interesting part.

**mlx-whisper** hallucination-looped on D02, a dev fixture I'd flagged specifically as a phantom-shot stress test. Here's its transcript tail, verbatim:

> "make. make. make. make. make. make. make. make. make. make. make. make. make. make. make. I guess I'll stop there."

Fifteen consecutive phantom "make."s. The per-word confidence on those tokens starts near-zero (0.001, then 0.003) and climbs through 0.499 and 0.715 before settling around 0.88–0.90 for the remaining ten — the model is unsure when the loop starts, then locks in and becomes confident about words that were never said. Whisper-1, run on the exact same audio with the exact same bias vocabulary, produces no loop at all; its transcript of that stretch just trails into silence and picks back up on the actual next call. Phantom shots are this project's designated hard-failure mode. One 15-word hallucination loop on a dev fixture is disqualifying on its own.

**parakeet-mlx** runs with no bias prompt at all, which makes it a genuinely independent check — and it's genuinely good, cheap, and fast. It also collapsed on R02, a real quiet out-of-breath session. Its full transcript output for that entire 89-second recording:

> "This make this"

Three words, one real call buried in there. Whisper-1, same audio, heard ten calls. That's not a rounding error — it's the model going effectively silent on exactly the acoustic condition (winded, quiet) that the pipeline has to handle every single morning.

**whisperx** doesn't hallucinate, but its forced-alignment step silently drops words: 27 total detections across the whole fixture set versus 122–184 for its peers, and zero detections on R02, D02, and F02 specifically — three of the fixtures I care most about. A word-timing pipeline that silently discards words is disqualifying for a use case where a missed call is invisible until you go looking for it.

**faster-whisper** took 381 seconds to transcribe F08, a 33.6-second fixture — a real-time factor around 11. At that rate, a 90-second morning session would take on the order of 17 minutes to transcribe. That's not a tuning problem, it's a different product.

**crisper-whisper** never got evaluated — it's skipped in `benchmarks/out/skips.json` because the Hugging Face `transformers` pipeline it depends on can't decode `.m4a` directly, and I didn't have a reason to build a WAV-conversion detour for a model that would need one more workaround before I even got a transcript to judge.

One nuance worth flagging before I get to the decision: on a strict full-sequence match against my labels (one disagreement anywhere zeroes the whole fixture), parakeet-mlx actually scores best — 5 of 10 perfect fixtures, versus 3 of 10 for whisper-1 (including F02, the trap fixture) and 1 of 10 for mlx-whisper; whisperx scores 0. That number alone would argue for parakeet. But "perfect sequence match" and "doesn't collapse into three words on a quiet real session" are different properties, and the second one is the one I can't tolerate in production. Strict-match is a useful secondary signal, not the deciding one.

Whisper-1 wins on the properties that were actually load-bearing: no hallucination, full coverage on the exact quiet-real-session condition that broke parakeet, word timestamps within roughly 0.17–0.30 seconds of the local-model consensus (well inside the parser's isolation windows — for comparison, faster-whisper and mlx-whisper agree with each other to 0.020 seconds), fastest wall clock, and $0.113 to transcribe the entire 14-fixture suite. Staying on whisper-1 was the call — recorded in `docs/decisions/001-transcriber-selection.md`.

## What the gates revealed

Choosing a transcriber didn't finish the job — it just cleared the way to run the actual pipeline against my labels and see where it stands. Gate results, from `uv run hoops score` over the 10 fixtures that are currently labeled:

| gate | value | threshold | result |
|---|---|---|---|
| recall | 0.565 | 0.99 | FAIL |
| precision | 1.000 | 0.99 | PASS |
| classification | 1.000 | 0.98 | PASS |
| exact_fraction | 0.000 | 0.9 | FAIL |
| gap_mae | n/a | 0.5 | PASS |
| phantom_on_traps | 0 | 0 | PASS |
| invariant_mismatches | 1 | 0 (hard) | FAIL |

Per-fixture, expected calls versus what the pipeline actually produced: F02 8→2, F06 15→11, R01 12→9, R02 11→3, F01 14→14 (not an exact sequence match), F04 12→11, F05 9→7, F08 4→2, F07 16→13, F07b 7→7 exact.

Read superficially, that's three failing gates and a hard-fail on invariants — not a great scoreboard. Read honestly, it's the opposite of alarming. Precision is 1.000 and phantom_on_traps is 0 — across every fixture, including F02 with its planted bait sentences, the pipeline never invents a shot. That's the gate I actually care about failing zero, and it's clean.

The recall shortfall mostly isn't a parser bug — it's a data bug, and the gates are exactly what surfaced it. R02's cached transcript still has "miss" heard as "mess" six times, because that cache predates the vocabulary widening that added "mess"-adjacent surface forms; a fresh whisper-1 pass on the same audio hears "miss" cleanly. That's most of R02's 11→3 shortfall sitting in a stale cache, not a live defect. Separately, the invariant mismatch is itself mislabeled data: the failing invariants (session-ends-with-three-makes) are checked against fixtures that were never meant to be complete sessions — F07b, for instance, is a short clip that legitimately ends on a miss, and its `expect_invariants_pass=TRUE` label is simply wrong for a fixture that isn't a full session. And `gap_mae` reporting `n/a` is its own honest gap — the wiring that would compute timing error from `beep_interval_s` isn't finished, so the timing gate can't fail *or* meaningfully pass yet; it's a silent pass, not a verified one.

That's the actual value of building the gates before trusting the pipeline: they didn't just check my code, they audited my data. A stale cache and two mislabeled rows would have quietly inflated or deflated my confidence for weeks if I'd been reading transcripts by eye instead of scoring against labels. Finding data bugs instead of code bugs isn't a consolation prize — it's the harness working exactly as intended.

## The loop forward

The pattern this sets up: adding a capability to hoops means adding a labeled dataset, not just writing code and eyeballing the output. Three fixtures are still named and waiting — F03 (call words used conversationally, the residual risk of a wide vocabulary), F09 (a shot deliberately left uncalled, testing whether the parser flags a gap instead of inventing a count), and F10 (out-of-breath articulation plus five minutes of trailing silence, testing whether the pipeline notices I forgot to stop recording). Until those are recorded and labeled, the conditions they represent are untested, full stop — no amount of code review substitutes for that.

I'll also keep parakeet-mlx around, not as a candidate to replace whisper-1, but as a cheap, prompt-independent cross-check. It's fast (RTF 0.05) and it shares none of whisper-1's bias vocabulary, which makes it a good canary for the specific failure mode that would be hardest to catch otherwise: whisper-family models sharing a hallucination because they share a prompt or training lineage. If whisper-1 and parakeet ever agree on a shot that isn't there, that's a much louder signal than either one hallucinating alone.

## Close

None of this made the pipeline smarter. What it did was make the pipeline's claims checkable. Precision at 1.000 isn't a vibe I have about the parser — it's a number that comes out of running real audio against calls I personally labeled. Recall at 0.565 isn't a mystery — it decomposes into a specific stale cache and two specific mislabeled rows, each with an owner and a fix. With golden data sitting underneath the pipeline, both I and whatever wrote the code — Claude, me, whoever touches this next — know the same thing at the same time: what's actually verified, what's still a known gap, and what it would take to close it. That's the whole trade: give up the comfort of "looks right," get a number you can trust instead.

---

Related: [`docs/methodology.md`](../methodology.md) for the binding record/label/gate/build/score/improve loop this write-up is describing in practice; [`docs/decisions/001-transcriber-selection.md`](../decisions/001-transcriber-selection.md) for the full model-selection decision record; [`benchmarks/README.md`](../../benchmarks/README.md) for how the six-backend harness itself is built.
