# Playbook: how to build an AI-automated personal tool

What this is: the repeatable process behind hoops, written down so tool #2
(any daily activity → captured data → automated report) follows the same
path instead of me rediscovering it. Each step links to the real artifact
in this repo as the worked example.

## The loop at a glance

1. Start with an owner-decision spec.
2. Make `CLAUDE.md` the working agreement, not documentation.
3. Design before code, plan before implementation.
4. Build the golden dataset before the capability.
5. Let gates decide done, not demos.
6. Ship small, verify live, then shadow.
7. Record why, not just what.
8. Generalize from instances, not upfront.

## 1. Start with an owner-decision spec

Before any code, I have to make the calls a model can't make for itself:
what vocabulary counts as a real call-out, what protocol ends a session,
what happens on failure, where the result gets delivered. Those aren't
implementation details — they're decisions only I can make, and if I skip
writing them down the assistant will quietly invent answers for me
somewhere in the diff.

[`specs/2026-07-27-hoops-voice-log-design.md`](specs/2026-07-27-hoops-voice-log-design.md)
is my worked example: it names exactly which PRD decisions it supersedes
instead of editing the PRD in place. That's the convention I keep — later
specs name what they override rather than silently rewriting history.
`docs/specs/` as a whole is my append-only decision log; nothing in it
gets deleted, only superseded by a newer dated file.

## 2. CLAUDE.md is the working agreement, not documentation

The AI assistant reads [`../CLAUDE.md`](../CLAUDE.md) at the start of
every session — it's not a README I write for humans, it's the context
the assistant actually builds from. I keep a dated "current status" line
in it, hard rules that don't get relitigated per task (pure-stdlib core,
gate-before-merge), and read-first pointers to the rest of the docs tree.

A stale CLAUDE.md is worse than no CLAUDE.md: the assistant will
confidently act on outdated status instead of asking me. The discipline
that keeps it honest is boring but non-negotiable — I update it in the
*same* PR that changes what it describes, not as cleanup afterward.

## 3. Design before code, plan before implementation

For each feature I write a brainstormed spec in `docs/specs/`, then an
implementation plan that breaks it into bite-sized TDD tasks I review one
at a time. [`superpowers/plans/2026-07-30-interactive-report.md`](superpowers/plans/2026-07-30-interactive-report.md)
is the fullest example in this repo — every task in it carries its own
failing test, the expected failure output, the code that makes it pass,
and a commit boundary. The plan is my unit of review, not the finished
diff; by the time all tasks are checked off, I've already reviewed the PR
task-by-task.

## 4. Golden dataset before capability

I record and hand-label fixtures *before* building the behavior that will
be scored against them. [`../fixtures/manifest.csv`](../fixtures/manifest.csv)
is my single source of truth for what each recording should produce, and
[`methodology.md`](methodology.md) is the binding loop
(record → label → gate → build → score → improve) that governs every
capability claim in this repo.

Trap fixtures are the point, not an afterthought: they encode the failure
mode I fear most (planted bait words meant to trigger phantom shots), so
the gate that matters most gets tested on purpose, not by luck. The
manifest carries both ground truth (my hand-labeled `expected_calls`) and
the latest machine output (`hoops score` writes results back into the
same file) — one file, always current, no separate scoreboard to go stale.

## 5. Gates decide done, not demos

`uv run hoops score` prints a gate table — recall, precision, phantom
shots on trap fixtures — and phantom shots on traps is a hard failure for
me, not a threshold to negotiate. `hoops replay --all` re-parses every
archived session from its stored transcript; a change that shouldn't
alter parsing must leave the replayed outputs byte-identical (I snapshot
`sessions/` beforehand and compare with `git diff --no-index` — the
folder itself isn't in git). Then `hoops score` re-scores every labeled
fixture and the gate table decides. Invariants (`src/hoops/invariants.py`)
run as runtime self-checks on every real session too, not just in test
fixtures — they flag the pipeline's own output the same way they'd flag a
fixture's.

A feature ships when the gates it's supposed to move actually move, not
when a demo run looks plausible. See [`methodology.md`](methodology.md) §1
for why I gate precision before recall in this domain.

## 6. Ship small, verify live, then shadow

I merge only what's green. Then, before I trust a change with unattended
real capture, I watch it run once end-to-end for real — phone press to
email in my inbox — because a fixture set can pass while the actual
device, network, or account wiring is still broken.

After that: a shadow period. I run the automated pipeline alongside my
own memory for N real sessions, eyeballing the output against what I
actually remember happening, before I stop checking. Gates passing on
recorded fixtures is necessary, not sufficient — see
[`pattern/README.md`](pattern/README.md) §6.

## 7. Record why, not just what

Git history carries the what; it doesn't carry the why, and future-me (or
the next AI session) will re-litigate a settled question without it.
Three places I keep this in hoops:

- `docs/decisions/` — ADRs for decisions with real alternatives
  considered, e.g. [`decisions/001-transcriber-selection.md`](decisions/001-transcriber-selection.md)
  (why I stayed on whisper-1 as the production transcriber, with the
  numbers).
- `docs/writeups/` — longer-form experiment narratives, e.g.
  [`writeups/2026-07-30-empirical-model-selection.md`](writeups/2026-07-30-empirical-model-selection.md).
- `docs/showcase/` — generated result artifacts a decision was based on,
  e.g. [`showcase/model-selection.html`](showcase/model-selection.html).

## 8. Generalize from instances, not upfront

[`pattern/README.md`](pattern/README.md) — the reusable capture pattern
(drop folder → transcribe → gated parse → invariants → stats → report) —
I wrote *after* instance #1 (basketball) worked end-to-end, not before it.
Building the abstraction first, from zero real instances, means guessing
at what varies; one data point already over-fits, and zero data points is
worse. I'll design the generalized starter template when instance #2
actually exists and I can see what's genuinely shared versus what was
basketball-specific.

---

See also: [`README.md`](README.md) for the full docs map, and
[`methodology.md`](methodology.md) for the gate loop this playbook only
summarizes.
