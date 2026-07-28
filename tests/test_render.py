import pytest
from hoops.render import Narrative, render_strip, render_report, render_gallery

pytestmark = pytest.mark.unit

ROWS = [
    {"shot_num": 1, "result": "miss", "t_call_s": 5.0, "voided": False},
    {"shot_num": 2, "result": "make", "t_call_s": 12.0, "voided": False},
    {"shot_num": 3, "result": "make", "t_call_s": 15.0, "voided": True},
    {"shot_num": 4, "result": "make", "t_call_s": 20.0, "voided": False},
    {"shot_num": 5, "result": "make", "t_call_s": 26.0, "voided": False},
    {"shot_num": 6, "result": "make", "t_call_s": 31.0, "voided": False},
]
STATS = {"session_id": "20260727-061204", "session_date_local": "2026-07-27",
         "shots_to_three": 5, "makes": 4, "misses": 1, "fg_pct": 0.8,
         "longest_make_streak": 4, "longest_miss_streak": 1, "median_gap_s": 6.0,
         "session_len_s": 35.0, "notes": "", "ambiguous_calls": 0}

def test_render_strip_writes_png(tmp_path):
    out = tmp_path / "strip.png"
    render_strip(ROWS, out)
    assert out.exists() and out.stat().st_size > 1000

def test_render_report_full(tmp_path):
    out = tmp_path / "report.html"
    n = Narrative("Cold start, hot finish", "Recap here.", "ugh come on", 14.2)
    render_report(STATS, ROWS, n, ["I4: gap 130s > 120s"], out, img_src="strip.png")
    html = out.read_text()
    assert "Cold start, hot finish" in html and "strip.png" in html
    assert "I4" in html and "ugh come on" in html

def test_render_report_no_narrative_no_flags(tmp_path):
    out = tmp_path / "report.html"
    render_report(STATS, ROWS, None, [], out, img_src="cid:strip")
    html = out.read_text()
    assert "cid:strip" in html and "Flags" not in html

def test_render_gallery(tmp_path):
    out = tmp_path / "index.html"
    render_gallery([{"name": "dev01", "expected": ["make"], "got": ["make", "miss"],
                     "strip_rel": "dev01/strip.png", "flags": [], "note": ""}], out)
    html = out.read_text()
    assert "dev01" in html and "mismatch" in html
