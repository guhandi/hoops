# Interactive HTML Session Report ("The Movie") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static session report with one self-contained interactive `report.html` (custom SVG/vanilla-JS, audio-driven "movie" replay), and slim the email to a static summary body + that single attachment.

**Architecture:** New module `src/hoops/report_html.py` owns the interactive report (data blob + SVG charts + movie JS, audio embedded as base64 data URI). `render.py`'s `render_report` becomes `render_email_body` (returns a string; kills the mailer temp-file dance). `mailer.py` attaches only `report.html`. `pipeline.py` persists the narrative to `narrative.json` and wires the new renderer into both `process_file` and `replay_session`.

**Tech Stack:** Python 3.12 stdlib (base64, json, html) + existing deps only. No Plotly, no jinja2, no new dependencies. Frontend is hand-written HTML/CSS/SVG/vanilla JS inside Python string constants.

**Spec:** `docs/specs/2026-07-30-interactive-report-design.md` — read it first.

## Global Constraints

- **No new dependencies.** `pyproject.toml` is untouched.
- `parse.py` / `stats.py` / `invariants.py` are **not modified** (pure stdlib, no I/O — load-bearing rule).
- The report must be **fully self-contained**: no `http(s)://` in any `src`/`href`; audio as `data:audio/mp4;base64,...`.
- Missing audio must **degrade gracefully** (visible "audio unavailable" state), never raise.
- All tests: `uv run pytest` (from repo root; paid API tests excluded by default).
- Gate before merge: `uv run hoops replay --all` then `git diff sessions/` — tracked parser outputs (`shots.csv`, `session.json`, transcripts) must be **byte-identical**. (`report.html`/`strip.png` are gitignored under `sessions/`.)
- Every commit message ends with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- Work on branch `feat/interactive-report` (already exists, spec committed).
- Court palette (use these exact values): hardwood `#f7ede2`, page text `#2d2a26`, ball orange `#e2711d`, make green `#1a7f37`, miss red `#c0392b`, dim grey `#999999`, card bg `#ffffff`, flag amber bg `#fff3cd`.

## Reference: existing shapes you will consume

- Shot row dict (from `build_shot_rows`, `src/hoops/stats.py:5-20`): keys `session_id, session_date_local, shot_num, result ("make"|"miss"), t_call_s, gap_s (float|None), streak_after, voided (bool), isolation_s, confidence (float|None), raw_token`.
- Stats dict (from `build_session_stats`, `src/hoops/stats.py:38-58`) keys: `session_id, session_date_local, start_time_local, shots_to_three, makes, misses, fg_pct (float|None), longest_make_streak, longest_miss_streak, time_to_first_make_s, median_gap_s, fastest_gap_s, slowest_gap_s, session_len_s, notes, quote_of_day, profanity_count, words_per_miss, invariants_passed, ambiguous_calls, transcriber, parser_version` — plus pipeline-injected `session_id_source, vocab_name, vocab_map`.
- `Word` (frozen dataclass, `src/hoops/transcribe.py:14-19`): `text, raw, start, end, confidence`.
- `Narrative` (frozen dataclass, `src/hoops/render.py:8-13`): `headline, recap, quote, quote_t_s (float|None)`.
- Flags are strings like `"I1: final three calls are not all makes"`.
- Test helpers: `tests/conftest.py:make_env(words, duration)`; existing fixtures in `tests/test_render.py` (ROWS/STATS dicts) show the row shape used by render tests.

---

### Task 1: `report_html.py` — data blob, document skeleton, stats grid, transcript, audio embed

**Files:**
- Create: `src/hoops/report_html.py`
- Test: `tests/test_report_html.py`

**Interfaces:**
- Consumes: `Narrative` from `hoops.render`; `Word` from `hoops.transcribe`; row/stats dicts as above.
- Produces: `render_interactive_report(stats: dict, rows: list[dict], narrative, flags: list[str], words, audio_path: Path | None) -> str` — the full HTML document. Also module-internal `_build_data(...) -> dict` (Tasks 2–3 extend the same module; Task 6 imports `render_interactive_report` into the pipeline). `words` is a list of `Word`; `narrative` is `Narrative | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_report_html.py`:

```python
import json, re
import pytest
from pathlib import Path
from hoops.render import Narrative
from hoops.transcribe import Word
from hoops.report_html import render_interactive_report

pytestmark = pytest.mark.unit

ROWS = [
    {"session_id": "20260727-061204", "session_date_local": "2026-07-27",
     "shot_num": 1, "result": "miss", "t_call_s": 5.0, "gap_s": None,
     "streak_after": 0, "voided": False, "isolation_s": 4.0, "confidence": None,
     "raw_token": "brick"},
    {"session_id": "20260727-061204", "session_date_local": "2026-07-27",
     "shot_num": 2, "result": "make", "t_call_s": 12.0, "gap_s": 7.0,
     "streak_after": 1, "voided": False, "isolation_s": 4.0, "confidence": None,
     "raw_token": "splash"},
    {"session_id": "20260727-061204", "session_date_local": "2026-07-27",
     "shot_num": 3, "result": "make", "t_call_s": 15.0, "gap_s": None,
     "streak_after": 0, "voided": True, "isolation_s": 0.5, "confidence": None,
     "raw_token": "splash"},
    {"session_id": "20260727-061204", "session_date_local": "2026-07-27",
     "shot_num": 4, "result": "make", "t_call_s": 20.0, "gap_s": 8.0,
     "streak_after": 2, "voided": False, "isolation_s": 4.0, "confidence": None,
     "raw_token": "swish"},
    {"session_id": "20260727-061204", "session_date_local": "2026-07-27",
     "shot_num": 5, "result": "make", "t_call_s": 26.0, "gap_s": 6.0,
     "streak_after": 3, "voided": False, "isolation_s": 4.0, "confidence": None,
     "raw_token": "splash"},
]
STATS = {"session_id": "20260727-061204", "session_date_local": "2026-07-27",
         "start_time_local": "06:12:04", "shots_to_three": 4, "makes": 3,
         "misses": 1, "fg_pct": 0.75, "longest_make_streak": 3,
         "longest_miss_streak": 1, "time_to_first_make_s": 12.0,
         "median_gap_s": 7.0, "fastest_gap_s": 6.0, "slowest_gap_s": 8.0,
         "session_len_s": 35.0, "notes": "", "quote_of_day": "ugh come on",
         "profanity_count": 1, "words_per_miss": 9.0, "invariants_passed": True,
         "ambiguous_calls": 0, "transcriber": "whisper-1",
         "parser_version": "1", "vocab_name": "swish_brick", "session_id_source": "filename"}
WORDS = [Word("brick", "brick.", 5.0, 5.3, None),
         Word("ugh", "ugh", 8.0, 8.2, None),
         Word("come", "come", 8.3, 8.5, None),
         Word("on", "on", 8.6, 8.7, None),
         Word("splash", "splash.", 12.0, 12.3, None),
         Word("splash", "splash.", 15.0, 15.3, None),
         Word("swish", "swish.", 20.0, 20.3, None),
         Word("splash", "splash.", 26.0, 26.3, None)]
NARR = Narrative("Cold start, hot finish", "Recap sentence here.", "ugh come on", 8.0)

def render(**kw):
    args = dict(stats=STATS, rows=ROWS, narrative=NARR, flags=[],
                words=WORDS, audio_path=None)
    args.update(kw)
    return render_interactive_report(**args)

def data_blob(html):
    m = re.search(r"const DATA = (.*?);\n", html, re.S)
    assert m, "DATA blob missing"
    return json.loads(m.group(1).replace("<\\/", "</"))

def test_stats_values_present():
    html = render()
    for token in ["75%", "7.0", "6.0", "8.0", "whisper-1", "swish_brick",
                  "Cold start, hot finish", "Recap sentence here.", "ugh come on",
                  "20260727-061204"]:
        assert token in html, token

def test_data_blob_matches_rows():
    d = data_blob(render())
    assert len(d["shots"]) == 5
    assert d["shots"][0] == {"n": 1, "result": "miss", "t": 5.0, "gap": None,
                             "streak": 0, "voided": False, "raw": "brick"}
    assert d["shots"][4]["streak"] == 3
    assert d["stats"]["fg_pct"] == 0.75
    assert d["has_audio"] is False

def test_words_carry_call_links():
    d = data_blob(render())
    assert len(d["words"]) == 8
    assert d["words"][0] == {"t": 5.0, "text": "brick", "call": 1}
    assert d["words"][1]["call"] == 0          # "ugh" is an aside
    assert d["words"][7]["call"] == 5

def test_audio_embedded(tmp_path):
    fake = tmp_path / "audio.m4a"
    fake.write_bytes(b"\x00\x00\x00\x18ftypM4A fake-audio")
    html = render(audio_path=fake)
    assert "data:audio/mp4;base64," in html
    assert data_blob(html)["has_audio"] is True

def test_no_audio_degrades():
    html = render(audio_path=None)
    assert "data:audio/mp4" not in html
    assert "audio unavailable" in html.lower()

def test_missing_audio_file_degrades(tmp_path):
    html = render(audio_path=tmp_path / "nope.m4a")   # path given but absent
    assert "audio unavailable" in html.lower()

def test_self_contained():
    html = render()
    assert not re.search(r"(src|href)\s*=\s*['\"]https?://", html)

def test_no_narrative_fallback():
    html = render(narrative=None)
    assert "<html" in html                      # still renders
    assert "Cold start" not in html

def test_flags_explained():
    html = render(flags=["I1: final three calls are not all makes"])
    assert "final three calls are not all makes" in html
    assert "three straight makes" in html       # plain-English explainer text

def test_script_injection_guarded():
    evil = dict(STATS, notes="</script><script>alert(1)</script>")
    html = render(stats=evil)
    assert "<script>alert(1)</script>" not in html
    data_blob(html)                             # blob still parses
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_report_html.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'hoops.report_html'`

- [ ] **Step 3: Implement the module skeleton**

Create `src/hoops/report_html.py`. Full content for this task (Tasks 2–3 replace the two placeholder section builders — they are the ONLY intentionally minimal parts, and each has its own task):

```python
import base64, html as _html, json
from pathlib import Path

# Plain-English explainers for invariant flags (keyed by the "I<n>" prefix).
FLAG_EXPLAIN = {
    "I1": "The session should end on three straight makes — the last three calls weren't all makes.",
    "I2": "Fewer than three calls were heard in the whole session.",
    "I3": "Two calls came impossibly close together (under the minimum gap).",
    "I4": "A silence between calls was longer than the maximum gap — a shot may have gone uncalled.",
    "I5": "A call word outside the session vocabulary slipped through.",
    "I6": "Three straight makes happened mid-session but shooting continued afterwards.",
}

CSS = """
:root { --wood:#f7ede2; --ink:#2d2a26; --ball:#e2711d; --make:#1a7f37;
        --miss:#c0392b; --dim:#999; --card:#fff; --amber:#fff3cd; }
* { box-sizing:border-box; }
body { font-family:-apple-system,Helvetica,sans-serif; background:var(--wood);
       color:var(--ink); margin:0; padding:16px; }
main { max-width:680px; margin:auto; }
section { background:var(--card); border-radius:12px; padding:16px;
          margin:12px 0; box-shadow:0 1px 3px rgba(0,0,0,.08); }
h1 { font-size:22px; margin:4px 0; }
h2 { font-size:15px; text-transform:uppercase; letter-spacing:.06em;
     color:var(--ball); margin:0 0 10px; }
.hero { font-size:64px; font-weight:800; line-height:1; }
.hero small { font-size:15px; font-weight:400; color:var(--dim); }
.badge { display:inline-block; border-radius:999px; padding:3px 10px;
         font-size:12px; font-weight:700; }
.badge.ok { background:#e6f4ea; color:var(--make); }
.badge.warn { background:var(--amber); color:#8a6d1a; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(110px,1fr));
        gap:10px; }
.stat b { display:block; font-size:20px; }
.stat span { font-size:11px; color:var(--dim); }
.make { color:var(--make); } .miss { color:var(--miss); }
.word { padding:1px 2px; border-radius:4px; }
.word.call-make { background:#e6f4ea; color:var(--make); font-weight:700; cursor:pointer; }
.word.call-miss { background:#fdecea; color:var(--miss); font-weight:700; cursor:pointer; }
.word.aside { color:var(--dim); }
.flagbox { background:var(--amber); border-radius:8px; padding:10px 12px;
           font-size:14px; margin:6px 0; }
footer { color:var(--dim); font-size:11px; text-align:center; padding:12px; }
svg { max-width:100%; height:auto; display:block; }
#tooltip { position:fixed; pointer-events:none; background:var(--ink); color:#fff;
           font-size:12px; padding:6px 9px; border-radius:6px; display:none; z-index:9; }
"""

def _fmt(v, pat="{:.1f}", dash="—"):
    return dash if v is None else pat.format(v)

def _build_data(stats, rows, narrative, flags, words, has_audio: bool) -> dict:
    shots = [{"n": r["shot_num"], "result": r["result"], "t": r["t_call_s"],
              "gap": r["gap_s"], "streak": r["streak_after"],
              "voided": r["voided"], "raw": r["raw_token"]} for r in rows]
    def call_num(w):
        for r in rows:
            if abs(w.start - r["t_call_s"]) < 0.05:
                return r["shot_num"]
        return 0
    return {"stats": stats, "shots": shots, "flags": flags,
            "words": [{"t": w.start, "text": w.text, "call": call_num(w)} for w in words],
            "narrative": ({"headline": narrative.headline, "recap": narrative.recap,
                           "quote": narrative.quote, "quote_t_s": narrative.quote_t_s}
                          if narrative else None),
            "has_audio": has_audio}

def _header(stats, narrative, flags) -> str:
    e = _html.escape
    badge = ("<span class='badge ok'>clean session</span>" if not flags
             else f"<span class='badge warn'>⚠️ {len(flags)} flag{'s' if len(flags) > 1 else ''}</span>")
    headline = e(narrative.headline) if narrative else "Morning free throws"
    return (f"<header><div>🏀 <b>{e(stats['session_date_local'])}</b> · "
            f"{e(str(stats.get('start_time_local') or ''))} {badge}</div>"
            f"<h1>{headline}</h1></header>")

def _hero(stats) -> str:
    fg = stats.get("fg_pct")
    return ("<section><div class='hero'>" + str(stats["shots_to_three"]) +
            "<small> shots to close it out</small></div>"
            f"<div><b class='make'>{stats['makes']} makes</b> · "
            f"<b class='miss'>{stats['misses']} misses</b> · "
            f"{_fmt(fg, '{:.0%}')} FG</div></section>")

def _movie_section(has_audio: bool) -> str:
    # Real court/controls arrive in Task 3.
    if not has_audio:
        return ("<section id='movie'><h2>Replay</h2>"
                "<p class='word aside'>audio unavailable for this session — "
                "no movie, but everything below still works.</p></section>")
    return "<section id='movie'><h2>Replay</h2><div id='court-slot'></div></section>"

def _charts_section(rows, stats) -> str:
    # Real SVG charts arrive in Task 2.
    return "<section id='charts'><h2>Charts</h2><div id='charts-slot'></div></section>"

def _stats_grid(stats, narrative) -> str:
    e = _html.escape
    groups = [
        ("Shooting", [("Shots", stats["shots_to_three"]), ("Makes", stats["makes"]),
                      ("Misses", stats["misses"]), ("FG%", _fmt(stats.get("fg_pct"), "{:.0%}")),
                      ("Best make run", stats["longest_make_streak"]),
                      ("Worst miss run", stats["longest_miss_streak"]),
                      ("First make", _fmt(stats.get("time_to_first_make_s"), "{:.1f}s"))]),
        ("Rhythm", [("Median gap", _fmt(stats.get("median_gap_s"), "{:.1f}s")),
                    ("Fastest gap", _fmt(stats.get("fastest_gap_s"), "{:.1f}s")),
                    ("Slowest gap", _fmt(stats.get("slowest_gap_s"), "{:.1f}s")),
                    ("Session", _fmt(stats.get("session_len_s"), "{:.0f}s")),
                    ("Started", stats.get("start_time_local") or "—")]),
        ("Fun", [("Profanity", stats.get("profanity_count", 0)),
                 ("Words per miss", _fmt(stats.get("words_per_miss"), "{:.1f}"))]),
        ("Meta", [("Transcriber", stats.get("transcriber", "—")),
                  ("Parser", stats.get("parser_version", "—")),
                  ("Vocabulary", stats.get("vocab_name", "—")),
                  ("Ambiguous", stats.get("ambiguous_calls", 0)),
                  ("Session id", stats["session_id"])]),
    ]
    out = ["<section><h2>All the stats</h2>"]
    for title, items in groups:
        cells = "".join(f"<div class='stat'><b>{e(str(v))}</b><span>{e(k)}</span></div>"
                        for k, v in items)
        out.append(f"<h3>{title}</h3><div class='grid'>{cells}</div>")
    if stats.get("quote_of_day"):
        out.append(f"<blockquote>“{e(stats['quote_of_day'])}”</blockquote>")
    if narrative:
        out.append(f"<p>{e(narrative.recap)}</p>")
    if stats.get("notes"):
        out.append(f"<p><b>Note:</b> {e(stats['notes'])}</p>")
    out.append("</section>")
    return "".join(out)

def _flags_section(flags) -> str:
    if not flags:
        return ""
    e = _html.escape
    boxes = []
    for f in flags:
        fid = f.split(":", 1)[0].strip()
        explain = FLAG_EXPLAIN.get(fid)
        extra = f"<br><span class='word aside'>{e(explain)}</span>" if explain else ""
        boxes.append(f"<div class='flagbox'><b>{e(f)}</b>{extra}</div>")
    return "<section><h2>Flags</h2>" + "".join(boxes) + "</section>"

def _transcript(words, rows) -> str:
    e = _html.escape
    by_t = {r["t_call_s"]: r for r in rows}
    spans = []
    for w in words:
        row = next((r for t, r in by_t.items() if abs(w.start - t) < 0.05), None)
        if row:
            cls = "call-make" if row["result"] == "make" else "call-miss"
            spans.append(f"<span class='word {cls}' data-t='{w.start}'>{e(w.text)}</span>")
        else:
            spans.append(f"<span class='word aside'>{e(w.text)}</span>")
    return "<section><h2>Transcript</h2><p>" + " ".join(spans) + "</p></section>"

def _audio_tag(audio_path: Path | None) -> tuple[str, bool]:
    if audio_path is None or not audio_path.exists():
        return "", False
    b64 = base64.b64encode(audio_path.read_bytes()).decode()
    return (f"<audio id='session-audio' preload='auto' "
            f"src='data:audio/mp4;base64,{b64}'></audio>", True)

JS = r"""
// Shared tooltip + transcript seek. Movie/chart engines mount in Tasks 2-3.
const tip = document.getElementById('tooltip');
function showTip(evt, html) {
  tip.innerHTML = html; tip.style.display = 'block';
  tip.style.left = Math.min(evt.clientX + 12, window.innerWidth - 160) + 'px';
  tip.style.top = (evt.clientY + 12) + 'px';
}
function hideTip() { tip.style.display = 'none'; }
function seekTo(t) {
  const a = document.getElementById('session-audio');
  if (a) { a.currentTime = Math.max(0, t - 1.0); a.play(); }
}
document.querySelectorAll('.word[data-t]').forEach(el =>
  el.addEventListener('click', () => seekTo(parseFloat(el.dataset.t))));
"""

def render_interactive_report(stats: dict, rows: list[dict], narrative,
                              flags: list[str], words,
                              audio_path: Path | None) -> str:
    audio_html, has_audio = _audio_tag(audio_path)
    data = json.dumps(_build_data(stats, rows, narrative, flags, words, has_audio)
                      ).replace("</", "<\\/")
    return "\n".join([
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>🏀 {_html.escape(stats['session_date_local'])}</title>",
        f"<style>{CSS}</style></head><body><main>",
        _header(stats, narrative, flags),
        _hero(stats),
        audio_html,
        _movie_section(has_audio),
        _charts_section(rows, stats),
        _stats_grid(stats, narrative),
        _flags_section(flags),
        _transcript(words, rows),
        f"<footer>Session {_html.escape(stats['session_id'])} · hoops</footer>",
        "</main><div id='tooltip'></div>",
        f"<script>const DATA = {data};\n</script>",
        f"<script>{JS}</script>",
        "</body></html>"])
```

Note the `\n` after the DATA statement — the tests' `data_blob` regex relies on `const DATA = ...;\n`. The `.replace("</", "<\\/")` guards `</script>` injection through notes/tokens/transcript text inside the JSON blob (HTML-side injection is covered by `_html.escape` everywhere user text is interpolated).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_report_html.py -q`
Expected: all pass. Then `uv run pytest -q` — full suite still green (nothing else imports the new module yet).

- [ ] **Step 5: Commit**

```bash
git add src/hoops/report_html.py tests/test_report_html.py
git commit -m "feat(report): interactive report skeleton — data blob, stats grid, transcript, embedded audio

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: SVG overview charts (shot timeline, running FG%, gap bars)

**Files:**
- Modify: `src/hoops/report_html.py` (replace `_charts_section` placeholder; extend `JS`)
- Test: `tests/test_report_html.py`

**Interfaces:**
- Consumes: row dicts, `showTip`/`hideTip`/`seekTo` JS helpers from Task 1.
- Produces: `_charts_section(rows, stats) -> str` emitting three inline `<svg>` blocks with per-shot elements carrying `data-shot="<shot_num>"`; JS wires tooltips + click-to-seek on `[data-shot]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_report_html.py`:

```python
def test_timeline_has_marker_per_shot():
    html = render()
    assert html.count('class="shot-dot') == 5          # every shot incl. voided
    assert 'data-shot="2"' in html

def test_timeline_underlines_closing_run():
    html = render()
    assert 'class="close-run"' in html                 # live tail is 3 makes

def test_timeline_no_underline_without_run():
    rows = [dict(r) for r in ROWS]
    rows[4]["result"] = "miss"; rows[4]["streak_after"] = 0; rows[4]["raw_token"] = "brick"
    html = render(rows=rows)
    assert 'class="close-run"' not in html

def test_fg_chart_and_gap_bars_present():
    html = render()
    assert 'id="fg-chart"' in html and 'class="fg-line"' in html
    assert 'id="gap-chart"' in html
    assert html.count('class="gap-bar') == 3           # live shots with a gap
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_report_html.py -q`
Expected: the four new tests FAIL (placeholder `_charts_section` has none of these ids/classes); earlier tests still pass.

- [ ] **Step 3: Implement `_charts_section`**

Replace the placeholder in `src/hoops/report_html.py`:

```python
def _timeline_svg(rows, session_len) -> str:
    W, H, pad = 640, 90, 24
    dur = max(session_len or 0, max((r["t_call_s"] for r in rows), default=1), 1)
    def x(t): return pad + (W - 2 * pad) * t / dur
    parts = [f"<svg id='timeline' viewBox='0 0 {W} {H}' role='img' "
             f"aria-label='shot timeline'>",
             f"<line x1='{pad}' y1='45' x2='{W - pad}' y2='45' stroke='#ddd' stroke-width='2'/>"]
    live = [r for r in rows if not r["voided"]]
    if len(live) >= 3 and all(r["result"] == "make" for r in live[-3:]):
        parts.append(f"<line class=\"close-run\" x1='{x(live[-3]['t_call_s']):.1f}' y1='62' "
                     f"x2='{x(live[-1]['t_call_s']):.1f}' y2='62' "
                     f"stroke='var(--make)' stroke-width='4' stroke-linecap='round'/>")
    for r in rows:
        cx = f"{x(r['t_call_s']):.1f}"
        common = f"class=\"shot-dot\" data-shot=\"{r['shot_num']}\""
        if r["voided"]:
            parts.append(f"<text {common} x='{cx}' y='50' text-anchor='middle' "
                         f"fill='var(--dim)' font-size='14'>×</text>")
        elif r["result"] == "make":
            parts.append(f"<circle {common} cx='{cx}' cy='45' r='8' fill='var(--make)'/>")
        else:
            parts.append(f"<circle {common} cx='{cx}' cy='45' r='8' fill='#fff' "
                         f"stroke='var(--miss)' stroke-width='2.5'/>")
    parts.append(f"<text x='{pad}' y='{H - 4}' font-size='10' fill='var(--dim)'>0s</text>"
                 f"<text x='{W - pad}' y='{H - 4}' font-size='10' fill='var(--dim)' "
                 f"text-anchor='end'>{dur:.0f}s</text></svg>")
    return "".join(parts)

def _fg_chart_svg(rows) -> str:
    W, H, pad = 640, 120, 24
    live = [r for r in rows if not r["voided"]]
    if not live:
        return ""
    pts, makes = [], 0
    for i, r in enumerate(live, start=1):
        makes += r["result"] == "make"
        pts.append((i, makes / i))
    def x(i): return pad + (W - 2 * pad) * (i - 1) / max(len(live) - 1, 1)
    def y(p): return (H - 20) - (H - 40) * p
    line = " ".join(f"{x(i):.1f},{y(p):.1f}" for i, p in pts)
    dots = "".join(f"<circle class=\"shot-dot\" data-shot=\"{r['shot_num']}\" "
                   f"cx='{x(i):.1f}' cy='{y(p):.1f}' r='4' fill='var(--ball)'/>"
                   for (i, p), r in zip(pts, live))
    return (f"<svg id='fg-chart' viewBox='0 0 {W} {H}' role='img' aria-label='running FG%'>"
            f"<line x1='{pad}' y1='{y(0.5):.1f}' x2='{W - pad}' y2='{y(0.5):.1f}' "
            f"stroke='#eee'/><text x='{pad}' y='{y(0.5) - 4:.1f}' font-size='10' "
            f"fill='var(--dim)'>50%</text>"
            f"<polyline class='fg-line' points='{line}' fill='none' "
            f"stroke='var(--ball)' stroke-width='2.5'/>" + dots + "</svg>")

def _gap_chart_svg(rows) -> str:
    W, H, pad = 640, 110, 24
    gaps = [(r["shot_num"], r["gap_s"], r["result"]) for r in rows
            if not r["voided"] and r["gap_s"] is not None]
    if not gaps:
        return ""
    top = max(g for _, g, _ in gaps)
    bw = min(28, (W - 2 * pad) / len(gaps) - 4)
    parts = [f"<svg id='gap-chart' viewBox='0 0 {W} {H}' role='img' aria-label='gaps between shots'>"]
    for i, (n, g, result) in enumerate(gaps):
        h = (H - 30) * g / top
        bx = pad + i * ((W - 2 * pad) / len(gaps))
        color = "var(--make)" if result == "make" else "var(--miss)"
        parts.append(f"<rect class=\"gap-bar\" data-shot=\"{n}\" x='{bx:.1f}' "
                     f"y='{H - 20 - h:.1f}' width='{bw:.1f}' height='{h:.1f}' "
                     f"rx='3' fill='{color}' opacity='0.85'/>")
    parts.append(f"<text x='{pad}' y='{H - 6}' font-size='10' fill='var(--dim)'>"
                 f"gap before each shot (tallest {top:.1f}s)</text></svg>")
    return "".join(parts)

def _charts_section(rows, stats) -> str:
    return ("<section id='charts'><h2>Shot timeline</h2>"
            + _timeline_svg(rows, stats.get("session_len_s"))
            + "<h2>Running FG%</h2>" + _fg_chart_svg(rows)
            + "<h2>Rhythm</h2>" + _gap_chart_svg(rows) + "</section>")
```

Append to the `JS` constant (inside the same raw string):

```javascript
const shotByNum = Object.fromEntries(DATA.shots.map(s => [s.n, s]));
document.querySelectorAll('[data-shot]').forEach(el => {
  const s = shotByNum[parseInt(el.dataset.shot)];
  if (!s) return;
  const label = s.voided ? 'voided' : s.result.toUpperCase();
  const card = `#${s.n} ${label} — “${s.raw}” @ ${s.t.toFixed(1)}s` +
    (s.gap != null ? `<br>gap ${s.gap.toFixed(1)}s` : '') +
    (s.voided ? '' : `<br>streak ${s.streak}`);
  el.addEventListener('mousemove', evt => showTip(evt, card));
  el.addEventListener('mouseleave', hideTip);
  el.addEventListener('click', () => seekTo(s.t));
});
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_report_html.py -q`
Expected: all pass (12 tests).

- [ ] **Step 5: Commit**

```bash
git add src/hoops/report_html.py tests/test_report_html.py
git commit -m "feat(report): SVG shot timeline, running FG% and gap charts with tooltips

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Movie mode — court scene, playback controls, audio-synced animation

**Files:**
- Modify: `src/hoops/report_html.py` (replace `_movie_section` placeholder; extend `CSS` and `JS`)
- Test: `tests/test_report_html.py`

**Interfaces:**
- Consumes: `#session-audio` element (Task 1), `DATA.shots`, `seekTo`.
- Produces: `#movie` section with `#court` SVG (`#ball`, `#make-count`, `#miss-count`, `#call-flash`), controls `#play-btn`, `#speed-btn`, `#skip-btn`, `#scrubber`. All behavior driven by the audio element's clock — the movie has no timer of its own.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_report_html.py`:

```python
def _with_audio(tmp_path):
    fake = tmp_path / "audio.m4a"
    fake.write_bytes(b"\x00\x00\x00\x18ftypM4A fake-audio")
    return render(audio_path=fake)

def test_movie_ui_present_with_audio(tmp_path):
    html = _with_audio(tmp_path)
    for el_id in ["court", "ball", "play-btn", "speed-btn", "skip-btn",
                  "scrubber", "make-count", "miss-count", "call-flash"]:
        assert f"id='{el_id}'" in html or f'id="{el_id}"' in html, el_id

def test_movie_ui_absent_without_audio():
    html = render(audio_path=None)
    assert "play-btn" not in html
    assert "audio unavailable" in html.lower()

def test_scrubber_markers_per_live_shot(tmp_path):
    html = _with_audio(tmp_path)
    assert html.count("scrub-mark") >= 4               # 4 live shots
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_report_html.py -q`
Expected: the three new tests FAIL; the rest pass.

- [ ] **Step 3: Implement the movie**

Replace `_movie_section` in `src/hoops/report_html.py`:

```python
def _movie_section(has_audio: bool) -> str:
    if not has_audio:
        return ("<section id='movie'><h2>Replay</h2>"
                "<p class='word aside'>audio unavailable for this session — "
                "no movie, but everything below still works.</p></section>")
    return """<section id='movie'><h2>Replay</h2>
<svg id='court' viewBox='0 0 320 200' aria-label='replay court'>
  <rect x='0' y='0' width='320' height='200' rx='10' fill='#f2dfc9'/>
  <rect x='250' y='30' width='6' height='90' fill='#8a5a2b'/>
  <rect x='232' y='28' width='44' height='30' rx='3' fill='#fff' stroke='#8a5a2b' stroke-width='2'/>
  <ellipse id='rim' cx='236' cy='62' rx='14' ry='4' fill='none' stroke='var(--ball)' stroke-width='3'/>
  <path d='M224 64 L230 84 L242 84 L248 64' fill='none' stroke='#bbb' stroke-width='1.5'/>
  <circle id='ball' cx='60' cy='150' r='11' fill='var(--ball)' stroke='#a3540f' stroke-width='1.5'/>
  <text id='call-flash' x='160' y='120' text-anchor='middle' font-size='30'
        font-weight='800' opacity='0'></text>
  <g font-size='15' font-weight='700'>
    <text x='16' y='28' fill='var(--make)'>✓ <tspan id='make-count'>0</tspan></text>
    <text x='16' y='50' fill='var(--miss)'>✗ <tspan id='miss-count'>0</tspan></text>
  </g>
</svg>
<div id='controls'>
  <button id='play-btn'>▶ Play</button>
  <button id='speed-btn'>1×</button>
  <button id='skip-btn'>⏭ next shot</button>
  <input id='scrubber' type='range' min='0' max='100' step='0.1' value='0'>
  <div id='scrub-marks'></div>
</div></section>"""
```

Append to `CSS`:

```css
#controls { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-top:10px; }
#controls button { font-size:15px; padding:8px 14px; border:0; border-radius:8px;
                   background:var(--ball); color:#fff; font-weight:700; cursor:pointer; }
#controls button:active { transform:scale(.96); }
#scrubber { flex:1 1 160px; accent-color:var(--ball); }
#scrub-marks { position:relative; width:100%; height:8px; }
.scrub-mark { position:absolute; top:0; width:4px; height:8px; border-radius:2px; }
#ball.fly-make { animation:flyMake .9s ease-in forwards; }
#ball.fly-miss { animation:flyMiss .9s ease-in forwards; }
@keyframes flyMake { 40% { cx:180px; cy:40px; } 70% { cx:236px; cy:58px; }
                     100% { cx:236px; cy:95px; } }
@keyframes flyMiss { 40% { cx:180px; cy:40px; } 60% { cx:232px; cy:52px; }
                     100% { cx:190px; cy:170px; } }
```

(Animating `cx`/`cy` via CSS works in modern Safari/Chrome; the fallback for any browser that ignores it is simply a stationary ball — the flash + scoreboard still narrate every shot, so nothing breaks.)

Append to the `JS` constant:

```javascript
const audio = document.getElementById('session-audio');
if (audio && document.getElementById('play-btn')) {
  const live = DATA.shots.filter(s => !s.voided);
  const playBtn = document.getElementById('play-btn');
  const speedBtn = document.getElementById('speed-btn');
  const scrub = document.getElementById('scrubber');
  const ball = document.getElementById('ball');
  const flash = document.getElementById('call-flash');
  const dur = DATA.stats.session_len_s || (live.length ? live[live.length-1].t + 2 : 1);
  scrub.max = dur;
  const marks = document.getElementById('scrub-marks');
  live.forEach(s => {
    const m = document.createElement('div');
    m.className = 'scrub-mark';
    m.style.left = `calc(${(100 * s.t / dur).toFixed(2)}% - 2px)`;
    m.style.background = s.result === 'make' ? 'var(--make)' : 'var(--miss)';
    marks.appendChild(m);
  });
  const speeds = [1, 2, 4];
  let speedIdx = 0, fired = new Set();
  speedBtn.onclick = () => {
    speedIdx = (speedIdx + 1) % speeds.length;
    audio.playbackRate = speeds[speedIdx];
    speedBtn.textContent = speeds[speedIdx] + '×';
  };
  playBtn.onclick = () => audio.paused ? audio.play() : audio.pause();
  audio.onplay = () => { playBtn.textContent = '⏸ Pause'; tick(); };
  audio.onpause = () => { playBtn.textContent = '▶ Play'; };
  document.getElementById('skip-btn').onclick = () => {
    const next = live.find(s => s.t > audio.currentTime + 0.2);
    if (next) { audio.currentTime = Math.max(0, next.t - 1.5); audio.play(); }
  };
  scrub.oninput = () => { audio.currentTime = parseFloat(scrub.value); };
  function fireShot(s) {
    ball.classList.remove('fly-make', 'fly-miss');
    void ball.getBBox();                       // restart CSS animation
    ball.classList.add(s.result === 'make' ? 'fly-make' : 'fly-miss');
    flash.textContent = s.raw.toUpperCase() + (s.result === 'make' ? '!' : '');
    flash.setAttribute('fill', s.result === 'make' ? 'var(--make)' : 'var(--miss)');
    flash.style.transition = 'none'; flash.style.opacity = 1;
    setTimeout(() => { flash.style.transition = 'opacity .8s'; flash.style.opacity = 0; }, 700);
    const upto = live.filter(x => x.t <= s.t);
    document.getElementById('make-count').textContent =
      upto.filter(x => x.result === 'make').length;
    document.getElementById('miss-count').textContent =
      upto.filter(x => x.result === 'miss').length;
  }
  function sync() {
    const t = audio.currentTime;
    scrub.value = t;
    live.forEach(s => {
      if (t >= s.t && !fired.has(s.n)) { fired.add(s.n); fireShot(s); }
      if (t < s.t) fired.delete(s.n);          // rewound past it: re-arm
    });
  }
  function tick() { if (!audio.paused) { sync(); requestAnimationFrame(tick); } }
  audio.onseeked = () => {                     // keep scoreboard honest on seek
    fired = new Set(live.filter(s => s.t <= audio.currentTime).map(s => s.n));
    const upto = live.filter(s => s.t <= audio.currentTime);
    document.getElementById('make-count').textContent =
      upto.filter(x => x.result === 'make').length;
    document.getElementById('miss-count').textContent =
      upto.filter(x => x.result === 'miss').length;
    scrub.value = audio.currentTime;
  };
}
```

Uses `requestAnimationFrame` while playing (not `timeupdate`, which fires only ~4×/s and skips shots at 4× speed). `seekTo` from Task 1 already targets this same audio element, so timeline dots, chart marks, and transcript words all drive the movie.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_report_html.py -q`
Expected: all pass (15 tests).

- [ ] **Step 5: Eyeball it in a real browser (sanity, not the full check yet)**

Write a throwaway render of the ROWS/STATS fixtures with the real dev fixture audio to the scratchpad and open it:

```bash
uv run python - <<'EOF'
from pathlib import Path
import sys; sys.path.insert(0, "tests")
from test_report_html import ROWS, STATS, WORDS, NARR
from hoops.report_html import render_interactive_report
out = Path("/private/tmp/claude-501/-Users-guhansundar-Documents-hoops/33b5b5d1-fcb8-407f-98e9-a72cfa1fc5ef/scratchpad/movie_preview.html")
out.write_text(render_interactive_report(STATS, ROWS, NARR, [], WORDS,
               Path("fixtures/dev/dev03.m4a")))
print(out)
EOF
```

Open with the Playwright browser (`browser_navigate` to the printed `file://` path), click `#play-btn`, confirm the ball animates and the scoreboard ticks. Fix any JS errors surfaced in `browser_console_messages` before committing.

- [ ] **Step 6: Commit**

```bash
git add src/hoops/report_html.py tests/test_report_html.py
git commit -m "feat(report): movie mode — audio-synced court replay with controls

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: `render_email_body` — string-returning slim email body

**Files:**
- Modify: `src/hoops/render.py:50-72`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `render_email_body(stats: dict, narrative, flags: list[str], img_src: str) -> str` in `hoops.render`. `render_report(stats, rows, narrative, flags, out_html, img_src)` KEEPS working for now as a thin wrapper (pipeline still calls it until Task 6; the `rows` param was already unused).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_render.py`:

```python
def test_render_email_body_returns_string():
    from hoops.render import render_email_body
    n = Narrative("Cold start, hot finish", "Recap here.", "ugh come on", 14.2)
    body = render_email_body(STATS, n, ["I4: gap 130s > 120s"], img_src="cid:strip")
    assert isinstance(body, str)
    assert "Cold start, hot finish" in body and "cid:strip" in body and "I4" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_render.py -q`
Expected: `ImportError: cannot import name 'render_email_body'`; existing tests pass.

- [ ] **Step 3: Implement**

In `src/hoops/render.py`, change `render_report` into a wrapper around a new string-returning function. The body-building code is IDENTICAL to the current `render_report` (lines 51-71) — only the signature and the final line change:

```python
def render_email_body(stats, narrative, flags, img_src: str) -> str:
    e = _html.escape
    parts = [f"<div style='font-family:-apple-system,Helvetica,sans-serif;max-width:640px;margin:auto'>"]
    # ... lines 53-71 of the current render_report, verbatim, unchanged ...
    return "\n".join(parts)

def render_report(stats, rows, narrative, flags, out_html: Path, img_src: str) -> None:
    out_html.write_text(render_email_body(stats, narrative, flags, img_src))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_render.py tests/test_pipeline.py -q`
Expected: all pass (wrapper keeps pipeline/mailer behavior identical).

- [ ] **Step 5: Commit**

```bash
git add src/hoops/render.py tests/test_render.py
git commit -m "refactor(render): extract string-returning render_email_body

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Mailer — string body, single `report.html` attachment

**Files:**
- Modify: `src/hoops/mailer.py`
- Test: `tests/test_mailer.py`

**Interfaces:**
- Consumes: `render_email_body` from Task 4.
- Produces: `build_email(stats, session_dir, narrative, flags, cfg) -> EmailMessage` (signature unchanged) whose only file attachment is `report.html`; `ARTIFACTS` list deleted.

- [ ] **Step 1: Update the attachment test to the new contract**

In `tests/test_mailer.py`, replace `test_build_email_attachments` with:

```python
def test_build_email_single_report_attachment(tmp_path):
    cfg = load_config(REPO / "config.yaml")
    sdir = tmp_path / "hoops__20260727-061204"; sdir.mkdir()
    for name, data in [("shots.csv", b"a"), ("session.json", b"{}"),
                       ("transcript.txt", b"t"), ("strip.png", b"\x89PNG_fake"),
                       ("audio.m4a", b"m4a"), ("report.html", b"<html>interactive</html>")]:
        (sdir / name).write_bytes(data)
    msg = build_email(STATS, sdir, None, [], cfg)
    assert msg["To"] == cfg.email["to"] and "8 shots" in msg["Subject"]
    names = {p.get_filename() for p in msg.iter_attachments()}
    assert names == {"report.html"}                    # nothing else rides along
    body = msg.get_body(("html",)).get_content()
    assert "cid:strip" in body
    assert not (sdir / "_email_body.html").exists()    # temp-file dance is gone
    for part in msg.walk():
        if part.get("Content-ID") == "<strip>":
            assert part.get_content_disposition() == "inline"
            break
    else:
        pytest.fail("Related image part with Content-ID <strip> not found")

def test_build_email_survives_missing_report(tmp_path):
    cfg = load_config(REPO / "config.yaml")
    sdir = tmp_path / "hoops__20260727-061204"; sdir.mkdir()
    msg = build_email(STATS, sdir, None, [], cfg)      # bare dir: no strip, no report
    assert {p.get_filename() for p in msg.iter_attachments()} == set()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mailer.py -q`
Expected: both FAIL (old code attaches six files and writes the temp file).

- [ ] **Step 3: Implement**

In `src/hoops/mailer.py`: delete the `ARTIFACTS` list and the `mimetypes` import; change the import from `render_report` to `render_email_body`; replace the body of `build_email`:

```python
def build_email(stats: dict, session_dir: Path, narrative, flags: list[str],
                cfg: Config) -> EmailMessage:
    msg = EmailMessage()
    msg["From"], msg["To"] = cfg.email["from"], cfg.email["to"]
    msg["Subject"] = build_subject(stats, flags)
    msg.set_content("Open the attached report.html for the interactive session report.")
    msg.add_alternative(render_email_body(stats, narrative, flags, img_src="cid:strip"),
                        subtype="html")
    strip = session_dir / "strip.png"
    if strip.exists():
        msg.get_payload()[1].add_related(strip.read_bytes(), maintype="image",
                                         subtype="png", cid="<strip>",
                                         disposition="inline")
    report = session_dir / "report.html"
    if report.exists():
        msg.add_attachment(report.read_bytes(), maintype="text", subtype="html",
                           filename="report.html")
    return msg
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mailer.py tests/test_ingest.py tests/test_pipeline.py -q`
Expected: all pass (ingest/pipeline tests fake or suppress SMTP; nothing depended on the extra attachments).

- [ ] **Step 5: Commit**

```bash
git add src/hoops/mailer.py tests/test_mailer.py
git commit -m "feat(mailer): slim email — string body, report.html as sole attachment

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Pipeline wiring — narrative.json persistence, interactive report in process + replay

**Files:**
- Modify: `src/hoops/pipeline.py` (imports; `process_file` lines ~183-200; `replay_session` lines ~224-259)
- Modify: `src/hoops/render.py` (delete the `render_report` wrapper once nothing calls it)
- Test: `tests/test_pipeline.py`, `tests/test_render.py`

**Interfaces:**
- Consumes: `render_interactive_report` (Task 1-3), `Narrative` from `hoops.render`.
- Produces: sessions gain `narrative.json` (`{"headline","recap","quote","quote_t_s"}`, written only when a narrative was generated); `report.html` is now the interactive report in both `process_file` and `replay_session`. `render_report` no longer exists.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pipeline.py` (reuse that file's existing fixtures/helpers for cfg + transcriber — follow the pattern of its current `process_file` tests, e.g. copy `fixtures/dev/dev03.m4a` into `tmp_path` and pass a fake transcriber built on `conftest.make_env`; `GOOD`-style word lists appear in `tests/test_ingest.py:10`):

```python
def test_narrative_persisted_and_replay_reuses_it(tmp_path, cfg, monkeypatch):
    from hoops.render import Narrative
    from hoops.pipeline import process_file, replay_session
    n = Narrative("Ice in the veins", "One cold stretch, then done.", "come on", 9.0)
    monkeypatch.setattr("hoops.narrative.generate_narrative", lambda *a, **k: n)
    monkeypatch.setattr("hoops.mailer.send", lambda *a, **k: None)
    out = process_file(<audio path>, cfg, <fake transcriber>, email=True,
                       out_root=tmp_path / "sessions")
    sdir = out.session_dir
    saved = json.loads((sdir / "narrative.json").read_text())
    assert saved == {"headline": "Ice in the veins",
                     "recap": "One cold stretch, then done.",
                     "quote": "come on", "quote_t_s": 9.0}
    assert "Ice in the veins" in (sdir / "report.html").read_text()
    replay_session(sdir, cfg)
    assert "Ice in the veins" in (sdir / "report.html").read_text()   # not lost

def test_report_is_interactive_and_embeds_audio(tmp_path, cfg):
    from hoops.pipeline import process_file
    out = process_file(<audio path>, cfg, <fake transcriber>, email=False,
                       out_root=tmp_path / "sessions")
    html = (out.session_dir / "report.html").read_text()
    assert "const DATA =" in html
    assert "data:audio/mp4;base64," in html            # audio was archived then embedded

def test_replay_without_audio_or_narrative_degrades(tmp_path, cfg):
    from hoops.pipeline import process_file, replay_session
    out = process_file(<audio path>, cfg, <fake transcriber>, email=False,
                       out_root=tmp_path / "sessions")
    (out.session_dir / "audio.m4a").unlink()
    replay_session(out.session_dir, cfg)
    html = (out.session_dir / "report.html").read_text()
    assert "audio unavailable" in html.lower()
    assert "const DATA =" in html
```

(`<audio path>` / `<fake transcriber>` = whatever the existing tests in that file construct — mirror them exactly; do not invent a new harness.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pipeline.py -q`
Expected: the three new tests FAIL (`narrative.json` never written; report has no `const DATA =`).

- [ ] **Step 3: Implement pipeline changes**

In `src/hoops/pipeline.py`:

a. Imports: replace `from .render import render_strip, render_report` with `from .render import render_strip, Narrative`; add `from .report_html import render_interactive_report`; add `asdict` to the dataclasses import.

b. In `process_file`, replace lines 183-200 (narrative → render → archive blocks) — the archive block MOVES ABOVE the render so the report can embed the archived audio:

```python
    narrative = None
    if email:
        from .narrative import generate_narrative
        narrative = generate_narrative(stats, env, cfg.llm_model)
        if narrative:
            stats["quote_of_day"] = narrative.quote
            write_session_json(sdir, stats)
            (sdir / "narrative.json").write_text(json.dumps(asdict(narrative), indent=2))

    if archive == "move":
        shutil.move(str(path), str(sdir / "audio.m4a"))
    elif archive == "copy":
        shutil.copy(str(path), str(sdir / "audio.m4a"))
    if archive in ("move", "copy") and sidecar is not None and sidecar.exists():
        (shutil.move if archive == "move" else shutil.copy)(str(sidecar), str(sdir / "vocab.json"))

    render_strip(rows, sdir / "strip.png")
    audio_path = sdir / "audio.m4a"
    if not audio_path.exists():                     # archive="none" leaves audio in place
        audio_path = path if path.exists() else None
    (sdir / "report.html").write_text(render_interactive_report(
        stats, rows, narrative, flags, words, audio_path))
```

(The email block at former lines 202-207 stays after this, unchanged — `report.html` now exists before `build_email` attaches it.)

c. In `replay_session`, load the persisted narrative near the top (after `old = read_session_json(...)`):

```python
    narrative = None
    nfile = sdir / "narrative.json"
    if nfile.exists():
        try:
            narrative = Narrative(**json.loads(nfile.read_text()))
        except (TypeError, ValueError):
            narrative = None
```

and replace the two render lines at the bottom (formerly 256-257):

```python
    render_strip(rows, sdir / "strip.png")
    audio_path = sdir / "audio.m4a"
    (sdir / "report.html").write_text(render_interactive_report(
        stats, rows, narrative, flags, words,
        audio_path if audio_path.exists() else None))
```

d. In `src/hoops/render.py`: delete the `render_report` wrapper (Task 4 made it a 2-liner; nothing imports it now — verify with `grep -rn render_report src tests`). In `tests/test_render.py`, delete `test_render_report_full` and `test_render_report_no_narrative_no_flags` (superseded by `test_render_email_body_returns_string` and the report_html suite) and drop `render_report` from the import line.

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q`
Expected: all green. If `test_cli.py` or `test_fixtures.py` referenced `render_report`, fix those call sites the same way (they shouldn't — grep first).

- [ ] **Step 5: Commit**

```bash
git add src/hoops/pipeline.py src/hoops/render.py tests/test_pipeline.py tests/test_render.py
git commit -m "feat(pipeline): interactive report + persisted narrative in process and replay

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: End-to-end verification, docs, merge

**Files:**
- Modify: `docs/architecture.md` (module map + email description), `CLAUDE.md` (current-status line)
- No src changes expected — this task is gates.

**Interfaces:** none — verification and docs only.

- [ ] **Step 1: Parser no-op gate**

```bash
uv run hoops replay --all
git diff --stat sessions/
```
Expected: NO diff in tracked files (`shots.csv`, `session.json`, `transcript.*` are byte-identical; `report.html`/`strip.png` are gitignored). Any tracked diff = a parser regression — stop and fix before proceeding.

- [ ] **Step 2: Score gate**

Run: `uv run hoops score`
Expected: passes exactly as on `main` (this work touches no parsing).

- [ ] **Step 3: Browser verification of a real session (Playwright MCP)**

Navigate to `file:///Users/guhansundar/Documents/hoops/sessions/2026/07/hoops__20260730-125100/report.html` and verify, fixing anything broken:
1. `browser_console_messages` — zero JS errors on load.
2. Stats grid shows 20 shots, 10 makes / 10 misses, 50% FG (matches `session.json`).
3. Timeline has 20 dots; the shots 17-19 make-run underline is present; hover a dot → tooltip card.
4. Click `#play-btn` → audio plays, ball animates, scoreboard ticks at call times; `#skip-btn` jumps ahead; speed button cycles 1×/2×/4×.
5. Click a transcript call word → playback seeks near it.
6. `browser_resize` to 390×844 → screenshot: no horizontal scroll, controls usable.
7. Flags section shows I1/I6 with the plain-English explainers.

- [ ] **Step 4: Real email proof**

```bash
uv run hoops replay sessions/2026/07/hoops__20260730-125100 2>/dev/null || true
uv run python -c "
from pathlib import Path
from hoops.config import load_config
from hoops.session import read_session_json
from hoops.mailer import build_email, send
import json
sdir = Path('sessions/2026/07/hoops__20260730-125100')
cfg = load_config(Path('config.yaml'))
stats = read_session_json(sdir)
send(build_email(stats, sdir, None, [], cfg), cfg)
print('sent')
"
```
Then confirm in Gmail (guhandiji@gmail.com): slim body renders with strip image + stats, exactly one attachment (`report.html`, ~4MB), and tapping it opens the interactive report. NEVER print `.env` values while doing this.

- [ ] **Step 5: Docs**

- `docs/architecture.md`: add `report_html.py` to the module map ("interactive self-contained session report — SVG charts + audio-synced movie; audio embedded base64"); update the email description (slim HTML body + single `report.html` attachment; `narrative.json` persisted per session).
- `CLAUDE.md` current-status: one line noting the interactive report + slim email shipped (date it).

- [ ] **Step 6: Commit docs, merge, live check**

```bash
git add docs/architecture.md CLAUDE.md
git commit -m "docs: interactive report + slim email in architecture map

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git checkout main && git merge --no-ff feat/interactive-report && git branch -d feat/interactive-report
```
The launchd poller runs repo code directly — next real recording exercises the whole thing. Watch `logs/poll.log` after the next session lands.

---

## Self-review notes (already applied)

- Spec coverage: header/hero (T1), movie (T3), timeline+charts (T2), stats grid incl. Fun/Meta (T1), transcript with seek (T1+T3), flags explained (T1), slim email + single attachment (T4+T5), narrative persistence + replay (T6), degraded no-audio state (T1/T6), self-containment guard (T1), mobile check (T7).
- Audio ordering bug avoided: archive-to-session-dir moves BEFORE render in T6 so the report embeds the archived audio; `archive="none"` falls back to the inbox path; replay falls back to degraded.
- `data_blob` test regex depends on the `;\n` after the DATA statement — kept in the template on purpose.
- `render_report` survives as a wrapper through T4-T5 so the pipeline never breaks mid-plan; deleted in T6 when the last caller switches.
