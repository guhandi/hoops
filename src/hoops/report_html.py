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
