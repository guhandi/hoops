# Apple Shortcut: one-button hoops capture

Phone-side setup. ~5 minutes, done once.

The Shortcut is the button that turns a recording into a POST straight to the cloud endpoint (current) or, in the fallback path, a file dropped in the iCloud inbox for the Mac poller to pick up.

## Build the Shortcut

1. Shortcuts app → + → rename to "Hoops".
2. Add action **Record Audio** — Start Recording: On Tap, Finish Recording: On Tap.
3. Add action **Format Date**: Date = Current Date, Format = Custom, string `yyyyMMdd-HHmmss`.
4. Add action **Rename File** (or **Set Name**, depending on iOS version): rename *Recorded Audio* to `hoops__[Formatted Date]` (insert the Format Date variable). The `hoops__` prefix is how the pipeline tells this capture type apart from any others sharing the same inbox/bucket — don't drop it or change the separator.
5. Add the upload step for whichever mode you're wiring — see below.
6. Add to Home Screen (Shortcut settings → Add to Home Screen) for the one-button experience — tap the icon, no app-switching, no menus.

## Cloud upload (current)

5. Add action **Get Contents of URL**:
   - URL: `https://<your-modal-endpoint>/upload`
   - Method: POST
   - Request Body: Form
   - Form field: `file` = the renamed recording (from step 4 above)
   - Headers: `X-Hoops-Key` = the upload secret

   The real endpoint URL and `X-Hoops-Key` value are not committed to this repo (public repo, defense in depth) — they live in the owner's local `.env.r2`.

   Tapping Stop gets an instant `{"status": "processing"}` (or `"duplicate"` on a re-tap of an already-processed recording) acknowledgment from the endpoint, and the report email lands roughly 2 minutes later — no iCloud sync wait.

## Local mode (fallback)

Kept in the repo and on the Shortcut settings for rollback if the cloud endpoint is ever unreachable. Everything on the Mac (`hoops poll`, transcription, parsing, invariants, stats, email) works against files sitting in the iCloud inbox folder — this path just needs a file to land there with the right name.

5. Add action **Save File**: file = *Renamed File*, Service = iCloud Drive, Destination Path `/Capture/inbox/`, Ask Where To Save = OFF, Overwrite = OFF. This must be the exact path the Mac side polls (`config.yaml: inbox`) — a typo here means recordings silently never arrive.

## Use

Tap → call shots out loud (say **swish** for a make, **brick** for a miss; "scratch that" voids the last call; "note: ..." records a note) → tap Stop. On the cloud path the report email lands ~2 minutes later; on the local fallback path the Mac polls every 5 minutes, so allow a few minutes longer.

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
2. Cloud path: the Shortcut should show the instant `{"status": "processing"}` ack; email report arrives within ~2 minutes. If not, check the Modal dashboard logs for the run.
3. Local fallback path: within ~10 min the email report arrives. If not, check Mac: `tail -50 logs/poll.log`, `ls needs_review/ rejected/`.
