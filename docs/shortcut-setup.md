# Apple Shortcut: one-button hoops capture

Phone-side setup. ~5 minutes, done once.

This is the missing half of the pipeline: everything on the Mac (`hoops poll`, transcription, parsing, invariants, stats, email) already works against files sitting in the iCloud inbox folder. The Shortcut is just the button that gets a recording into that folder with the right name.

## Build the Shortcut

1. Shortcuts app → + → rename to "Hoops".
2. Add action **Record Audio** — Start Recording: On Tap, Finish Recording: On Tap.
3. Add action **Format Date**: Date = Current Date, Format = Custom, string `yyyyMMdd-HHmmss`.
4. Add action **Rename File**: rename *Recorded Audio* to `hoops__[Formatted Date]` (insert the Format Date variable). The `hoops__` prefix is how the poller tells this capture type apart from any others sharing the same inbox — don't drop it or change the separator.
5. Add action **Save File**: file = *Renamed File*, Service = iCloud Drive, Destination Path `/Capture/inbox/`, Ask Where To Save = OFF, Overwrite = OFF. This must be the exact path the Mac side polls (`config.yaml: inbox`) — a typo here means recordings silently never arrive.
6. Add to Home Screen (Shortcut settings → Add to Home Screen) for the one-button experience — tap the icon, no app-switching, no menus.

## Use

Tap → call shots out loud (say **swish** for a make, **brick** for a miss; "scratch that" voids the last call; "note: ..." records a note) → tap Stop. The Mac polls every 5 minutes; the report email lands a few minutes after that.

Say the call word clearly and let it sit alone for a beat — the parser only counts a call if it's isolated from surrounding speech (the isolation gate). Muttering "come on, make it" mid-sentence is exactly what it's designed to ignore.

## Vocabulary override (optional)

`swish`/`brick` is the production default (`config.yaml: vocab_default: swish_brick`). If you (or someone borrowing the Shortcut) want different call words for one recording — say, falling back to `make`/`miss` — drop a JSON sidecar next to the audio with the same stem, e.g. `hoops__20260728-063000.json` next to `hoops__20260728-063000.m4a`:

```json
{"vocabulary": "make_miss"}
```

or, for one-off custom words instead of a named set:

```json
{"vocab_map": {"make": ["bucket"], "miss": ["clank"]}}
```

A malformed sidecar (bad JSON, unknown vocabulary name, unusable `vocab_map`) routes the recording to `needs_review/` instead of silently falling back to the default — check there if a session seems to be missing.

## Verify end to end

1. Record a 30-second test with a few calls.
2. Within ~10 min: email report arrives. If not, check Mac: `tail -50 logs/poll.log`, `ls needs_review/ rejected/`.
