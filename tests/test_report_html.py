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

def test_unreadable_audio_degrades(tmp_path, monkeypatch):
    fake = tmp_path / "audio.m4a"
    fake.write_bytes(b"\x00\x00\x00\x18ftypM4A fake-audio")
    from pathlib import Path as _P
    def boom(self):
        if self.name == "audio.m4a":
            raise OSError("dataless stub")
        return _orig(self)
    _orig = _P.read_bytes
    monkeypatch.setattr(_P, "read_bytes", boom)
    html = render(audio_path=fake)
    assert "audio unavailable" in html.lower()
    assert "data:audio/mp4" not in html

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

def test_gap_chart_zero_gap_does_not_crash():
    rows = [dict(ROWS[0]), dict(ROWS[1])]
    rows[1]["gap_s"] = 0.0
    html = render(rows=rows)
    assert 'id="gap-chart"' in html

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
    assert "id='play-btn'" not in html          # controls absent (JS may mention the id)
    assert "audio unavailable" in html.lower()

def test_scrubber_markers_per_live_shot(tmp_path):
    html = _with_audio(tmp_path)
    assert html.count("scrub-mark") >= 4               # 4 live shots

def test_empty_charts_hide_headers():
    rows = [dict(r) for r in ROWS]
    for r in rows:
        r["voided"] = True
        r["gap_s"] = None
    html = render(rows=rows)
    assert "<h2>Running FG%</h2>" not in html
    assert "<h2>Rhythm</h2>" not in html
    assert 'id="fg-chart"' not in html
    assert 'id="gap-chart"' not in html
    assert "<html" in html                             # still renders, doesn't crash
