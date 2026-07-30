# Interactive HTML session report ("the movie") + slim email — design

**Date:** 2026-07-30 · **Status:** approved for implementation
**Supersedes:** the report/email sections of earlier specs where they conflict (the plain `report.html` + attach-everything email described implicitly by the current code).

## Problem

The pipeline is live end-to-end; output is the last unrefined piece. Today each session produces a matplotlib `strip.png` and a static hand-concatenated `report.html`, and the email attaches seven files — including the raw 2.7 MB `audio.m4a` every time and `strip.png` twice (inline + attachment). The owner wants a final-version output: one polished, fun, interactive session report.

## Decisions (brainstormed 2026-07-30)

1. **Delivery: attachment + slim body.** Email clients strip JavaScript, so interactivity cannot live in the email body. The email keeps a compact static summary (headline, hero number, strip image, key stats); the interactive report travels as an attached `report.html` opened in a browser.
2. **Scope: single session only.** History/trend views are deferred until real sessions accumulate.
3. **No Plotly, no new dependencies.** Hand-rolled HTML + SVG + vanilla JS, fully self-contained (no CDN, no network references). Owner explicitly chose custom over Plotly.
4. **Movie mode.** A play button replays the session: the owner's real recorded audio is the soundtrack, and each shot triggers a make/miss animation at its exact call timestamp.
5. **Audio embedded.** The session audio is baked into `report.html` as a base64 data URI (~4 MB file). The separate `audio.m4a` email attachment is dropped, so total email size stays roughly what it is today.

## Report contents (`report.html` — one self-contained file)

1. **Header** — 🏀 date, narrative headline (fallback copy when no narrative), invariants badge: clean, or ⚠️ with each flag explained in plain English.
2. **Hero** — big `shots_to_three` number, makes–misses record, FG%.
3. **Movie** — SVG half-court with hoop and scoreboard. An HTML5 `<audio>` element (embedded m4a data URI) drives the scene via `timeupdate`: when playback crosses a shot's `t_call_s`, the ball arcs at the rim — swish animation for a make, rim-clank for a miss — the scoreboard ticks, and the raw transcribed token flashes ("SPLASH!" green / "BRICK" red). Controls: play/pause, speed 1×/2×/4× (`audio.playbackRate`), "next shot ⏭" (seek to ~1.5 s before the next call, skipping dead air), and a scrubber with shot markers. If `audio.m4a` is missing (old/replayed sessions without audio), the movie section degrades to a visible "audio unavailable" state; everything else still works.
4. **Shot timeline** — the overview plot: each shot a dot on the time axis (x = `t_call_s`), make/miss/voided styling, closing 3-make run underlined. Tap/hover → detail card (shot #, result, raw token, timestamp, `gap_s`, `streak_after`); tap also seeks the movie to that shot.
5. **Charts** — running FG% line and gap-between-shots bars, SVG with tooltips, built from the per-shot rows.
6. **Stats grid** — every `session.json` field, grouped:
   - *Shooting:* `shots_to_three, makes, misses, fg_pct, longest_make_streak, longest_miss_streak, time_to_first_make_s`
   - *Rhythm:* `median_gap_s, fastest_gap_s, slowest_gap_s, session_len_s, start_time_local`
   - *Fun:* `profanity_count, words_per_miss, quote_of_day`, narrative recap
   - *Meta:* `transcriber, parser_version, vocab_name, session_id, ambiguous_calls, notes`
7. **Transcript** — full text with call words highlighted green/red and conversational asides dimmed; call words are tap-to-seek into the movie.

Design language: court-inspired palette (hardwood, ball orange, make green, miss red), playful copy, mobile-first (the report is usually opened from iPhone Mail; layout must hold at ~390 px).

Data flows into the page as a single `<script>const DATA = {...}</script>` JSON blob. The template lives in Python (f-string / `string.Template`) — no jinja2. `parse.py` / `stats.py` / `invariants.py` remain untouched, pure-stdlib, no I/O.

## Architecture

- **New `src/hoops/report_html.py`** — `render_interactive_report(stats, rows, narrative, flags, transcript_words, audio_path) -> str`. Owns the template, the SVG chart generation, and the movie JS. If the inline string grows unwieldy, the template may live in an adjacent `report_template.html` loaded via `importlib.resources`.
- **`src/hoops/render.py`** — `render_strip` kept (email body still embeds the PNG via `cid:`). `render_report` is repurposed into `render_email_body(stats, narrative, flags, img_src) -> str` (slim summary returning a string — removes the mailer's temp-file round-trip). `render_gallery` untouched.
- **`src/hoops/mailer.py`** — body built directly from `render_email_body`; inline `cid:strip` unchanged; attachments reduced to **`report.html` only**. All other artifacts remain on disk in the session directory.
- **`src/hoops/pipeline.py`** — `process_file` persists the narrative to `narrative.json` in the session dir (fixing the existing narrative-lost-on-replay gap) and writes the interactive report. `replay_session` loads `narrative.json` when present and rebuilds the identical report.

## Error handling

- Missing/unreadable audio → movie-less degraded report, never a pipeline failure.
- Narrative absent (`None`) → fallback headline, Fun group omits recap/quote gracefully.
- The report builder must never raise for odd-but-valid sessions (zero-gap edge shots, voided shots, single-digit sessions).

## Testing

- New `tests/test_report_html.py`: every stats value present in the HTML; shot `DATA` JSON matches rows; audio data URI present when audio exists and degraded state when not; self-containment guard (no external `http(s)://` in `src`/`href`).
- Updated render/mailer tests: `render_email_body` returns a string; the email carries exactly one attachment (`report.html`); no `_email_body.html` temp file.
- Gates: `uv run pytest` green; `uv run hoops replay --all` + `git diff sessions/` shows byte-identical `shots.csv`/`session.json` (parser no-op) with only renderer-output diffs; visual verification of the movie in a real browser at desktop and ~390 px widths.
