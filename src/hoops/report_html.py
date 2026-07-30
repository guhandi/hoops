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

CALL_MATCH_TOLERANCE_S = 0.05

def _call_row_for(word, rows):
    for r in rows:
        if abs(word.start - r["t_call_s"]) < CALL_MATCH_TOLERANCE_S:
            return r
    return None

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
#controls { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-top:10px; }
#controls button { font-size:15px; padding:8px 14px; border:0; border-radius:8px;
                   background:var(--ball); color:#fff; font-weight:700; cursor:pointer; }
#controls button:active { transform:scale(.96); }
#scrub-wrap { flex:1 1 160px; position:relative; }
#scrubber { width:100%; display:block; margin:0; accent-color:var(--ball); }
#scrub-marks { position:relative; width:100%; height:8px; }
.scrub-mark { position:absolute; top:0; width:4px; height:8px; border-radius:2px; }
#ball.fly-make { animation:flyMake .9s ease-in forwards; }
#ball.fly-miss { animation:flyMiss .9s ease-in forwards; }
@keyframes flyMake { 40% { cx:180px; cy:40px; } 70% { cx:236px; cy:58px; }
                     100% { cx:236px; cy:95px; } }
@keyframes flyMiss { 40% { cx:180px; cy:40px; } 60% { cx:232px; cy:52px; }
                     100% { cx:190px; cy:170px; } }
"""

def _fmt(v, pat="{:.1f}", dash="—"):
    return dash if v is None else pat.format(v)

def _build_data(stats, rows, narrative, flags, words, has_audio: bool) -> dict:
    shots = [{"n": r["shot_num"], "result": r["result"], "t": r["t_call_s"],
              "gap": r["gap_s"], "streak": r["streak_after"],
              "voided": r["voided"], "raw": r["raw_token"]} for r in rows]
    def call_num(w):
        r = _call_row_for(w, rows)
        return r["shot_num"] if r else 0
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
  <div id='scrub-wrap'><input id='scrubber' type='range' min='0' max='100' step='0.1' value='0'>
  <div id='scrub-marks'></div></div>
</div></section>"""

def _timeline_svg(rows, session_len) -> str:
    W, H, pad = 640, 90, 24
    dur = max(session_len or 0, max((r["t_call_s"] for r in rows), default=1), 1)
    def x(t): return pad + (W - 2 * pad) * t / dur
    parts = [f'<svg id="timeline" viewBox="0 0 {W} {H}" role="img" '
             f'aria-label="shot timeline">',
             f'<line x1="{pad}" y1="45" x2="{W - pad}" y2="45" stroke="#ddd" stroke-width="2"/>']
    live = [r for r in rows if not r["voided"]]
    if len(live) >= 3 and all(r["result"] == "make" for r in live[-3:]):
        parts.append(f'<line class="close-run" x1="{x(live[-3]["t_call_s"]):.1f}" y1="62" '
                     f'x2="{x(live[-1]["t_call_s"]):.1f}" y2="62" '
                     f'stroke="var(--make)" stroke-width="4" stroke-linecap="round"/>')
    for r in rows:
        cx = f"{x(r['t_call_s']):.1f}"
        common = f'class="shot-dot" data-shot="{r["shot_num"]}"'
        if r["voided"]:
            parts.append(f'<text {common} x="{cx}" y="50" text-anchor="middle" '
                         f'fill="var(--dim)" font-size="14">×</text>')
        elif r["result"] == "make":
            parts.append(f'<circle {common} cx="{cx}" cy="45" r="8" fill="var(--make)"/>')
        else:
            parts.append(f'<circle {common} cx="{cx}" cy="45" r="8" fill="#fff" '
                         f'stroke="var(--miss)" stroke-width="2.5"/>')
    parts.append(f'<text x="{pad}" y="{H - 4}" font-size="10" fill="var(--dim)">0s</text>'
                 f'<text x="{W - pad}" y="{H - 4}" font-size="10" fill="var(--dim)" '
                 f'text-anchor="end">{dur:.0f}s</text></svg>')
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
    dots = "".join(f'<circle class="fg-dot" data-shot="{r["shot_num"]}" '
                   f'cx="{x(i):.1f}" cy="{y(p):.1f}" r="4" fill="var(--ball)"/>'
                   for (i, p), r in zip(pts, live))
    return (f'<svg id="fg-chart" viewBox="0 0 {W} {H}" role="img" aria-label="running FG%">'
            f'<line x1="{pad}" y1="{y(0.5):.1f}" x2="{W - pad}" y2="{y(0.5):.1f}" '
            f'stroke="#eee"/><text x="{pad}" y="{y(0.5) - 4:.1f}" font-size="10" '
            f'fill="var(--dim)">50%</text>'
            f'<polyline class="fg-line" points="{line}" fill="none" '
            f'stroke="var(--ball)" stroke-width="2.5"/>' + dots + '</svg>')

def _gap_chart_svg(rows) -> str:
    W, H, pad = 640, 110, 24
    gaps = [(r["shot_num"], r["gap_s"], r["result"]) for r in rows
            if not r["voided"] and r["gap_s"] is not None]
    if not gaps:
        return ""
    top = max(g for _, g, _ in gaps) or 1.0
    bw = max(1, min(28, (W - 2 * pad) / len(gaps) - 4))
    parts = [f'<svg id="gap-chart" viewBox="0 0 {W} {H}" role="img" aria-label="gaps between shots">']
    for i, (n, g, result) in enumerate(gaps):
        h = (H - 30) * g / top
        bx = pad + i * ((W - 2 * pad) / len(gaps))
        color = "var(--make)" if result == "make" else "var(--miss)"
        parts.append(f'<rect class="gap-bar" data-shot="{n}" x="{bx:.1f}" '
                     f'y="{H - 20 - h:.1f}" width="{bw:.1f}" height="{h:.1f}" '
                     f'rx="3" fill="{color}" opacity="0.85"/>')
    parts.append(f'<text x="{pad}" y="{H - 6}" font-size="10" fill="var(--dim)">'
                 f'gap before each shot (tallest {top:.1f}s)</text></svg>')
    return "".join(parts)

def _charts_section(rows, stats) -> str:
    fg_svg = _fg_chart_svg(rows)
    gap_svg = _gap_chart_svg(rows)
    out = ["<section id='charts'><h2>Shot timeline</h2>"
           + _timeline_svg(rows, stats.get("session_len_s"))]
    if fg_svg:
        out.append("<h2>Running FG%</h2>" + fg_svg)
    if gap_svg:
        out.append("<h2>Rhythm</h2>" + gap_svg)
    out.append("</section>")
    return "".join(out)

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
    spans = []
    for w in words:
        row = _call_row_for(w, rows)
        if row:
            cls = "call-make" if row["result"] == "make" else "call-miss"
            spans.append(f"<span class='word {cls}' data-t='{w.start}'>{e(w.text)}</span>")
        else:
            spans.append(f"<span class='word aside'>{e(w.text)}</span>")
    return "<section><h2>Transcript</h2><p>" + " ".join(spans) + "</p></section>"

def _audio_tag(audio_path: Path | None) -> tuple[str, bool]:
    if audio_path is None or not audio_path.exists():
        return "", False
    try:
        b64 = base64.b64encode(audio_path.read_bytes()).decode()
    except OSError:
        return "", False
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
const shotByNum = Object.fromEntries(DATA.shots.map(s => [s.n, s]));
document.querySelectorAll('[data-shot]').forEach(el => {
  const s = shotByNum[parseInt(el.dataset.shot)];
  if (!s) return;
  const label = s.voided ? 'voided' : s.result.toUpperCase();
  const card = `#${s.n} ${label} — "${s.raw}" @ ${s.t.toFixed(1)}s` +
    (s.gap != null ? `<br>gap ${s.gap.toFixed(1)}s` : '') +
    (s.voided ? '' : `<br>streak ${s.streak}`);
  el.addEventListener('mousemove', evt => showTip(evt, card));
  el.addEventListener('mouseleave', hideTip);
  el.addEventListener('click', () => seekTo(s.t));
});
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
  let speedIdx = 0, fired = new Set(), flashTimer;
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
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => { flash.style.transition = 'opacity .8s'; flash.style.opacity = 0; }, 700);
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
"""

def render_interactive_report(stats: dict, rows: list[dict], narrative,
                              flags: list[str], words,
                              audio_path: Path | None) -> str:
    audio_html, has_audio = _audio_tag(audio_path)
    data = json.dumps(_build_data(stats, rows, narrative, flags, words, has_audio)
                      ).replace("<", "\\u003c")
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
