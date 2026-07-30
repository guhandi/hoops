import pytest
from pathlib import Path
from hoops.config import load_config
from hoops.mailer import build_subject, build_email

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[1]
STATS = {"session_id": "20260727-061204", "session_date_local": "2026-07-27",
         "shots_to_three": 8, "makes": 4, "misses": 4, "fg_pct": 0.5,
         "longest_make_streak": 3, "longest_miss_streak": 2, "median_gap_s": 6.0,
         "session_len_s": 60.0, "notes": "", "ambiguous_calls": 0}

def test_subject():
    assert build_subject(STATS, []) == "🏀 Mon Jul 27 — 8 shots to close it out (4/8)"
    assert build_subject(STATS, ["I1: bad"]).startswith("⚠️ 🏀")

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
