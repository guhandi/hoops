import csv, json, os
import pytest
from pathlib import Path
from zoneinfo import ZoneInfo
from hoops.session import (session_id_for, session_dir_for, sid_date_and_time,
                           write_transcript, write_shots_csv, write_session_json,
                           read_session_json, read_envelope, find_session_dirs)
from conftest import make_env

pytestmark = pytest.mark.unit
TZ = ZoneInfo("America/Los_Angeles")

def test_sid_from_filename(tmp_path):
    f = tmp_path / "hoops__20260727-061204.m4a"; f.write_bytes(b"x")
    assert session_id_for(f, TZ) == ("20260727-061204", "filename")

def test_sid_from_mtime(tmp_path):
    f = tmp_path / "dev01.m4a"; f.write_bytes(b"x")
    ts = 1753621200.0  # fixed epoch
    os.utime(f, (ts, ts))
    sid, source = session_id_for(f, TZ)
    assert source == "mtime" and len(sid) == 15 and sid[8] == "-"

def test_session_dir_layout(tmp_path):
    d = session_dir_for(tmp_path, "20260727-061204")
    assert d == tmp_path / "2026" / "07" / "hoops__20260727-061204"

def test_sid_date_and_time():
    assert sid_date_and_time("20260727-061204") == ("2026-07-27", "06:12:04")

def test_write_and_read_roundtrip(tmp_path):
    sdir = tmp_path / "s"; sdir.mkdir()
    env = make_env([("make", 1.0, 1.3)])
    write_transcript(sdir, env)
    assert read_envelope(sdir) == env
    assert (sdir / "transcript.txt").read_text() == "make"
    rows = [{"session_id": "s", "session_date_local": "2026-07-27", "shot_num": 1,
             "result": "make", "t_call_s": 1.0, "gap_s": None, "streak_after": 1,
             "voided": False, "isolation_s": 2.0, "confidence": None, "raw_token": "make"}]
    write_shots_csv(sdir, rows)
    with (sdir / "shots.csv").open() as f:
        rec = list(csv.DictReader(f))
    assert rec[0]["result"] == "make" and rec[0]["gap_s"] == "" and rec[0]["confidence"] == ""
    write_session_json(sdir, {"session_id": "s", "makes": 1})
    assert read_session_json(sdir)["makes"] == 1

def test_find_session_dirs(tmp_path):
    a = tmp_path / "2026" / "07" / "hoops__20260727-061204"; a.mkdir(parents=True)
    (a / "transcript.json").write_text("{}")
    (tmp_path / "2026" / "07" / "empty").mkdir()
    assert find_session_dirs(tmp_path) == [a]

def test_write_transcript_annotates_recovered(tmp_path):
    from hoops.session import write_transcript
    env = {"model": "whisper-1", "response": {"text": "break. splash."},
           "gap_repair": {"spans": [
               {"gap": [111.7, 127.5], "clip": [109.7, 129.5],
                "recovered": [{"word": " splash", "start": 119.66, "end": 120.1}]}],
               "n_recovered": 1, "truncated": False, "errors": []}}
    write_transcript(tmp_path, env)
    txt = (tmp_path / "transcript.txt").read_text()
    assert txt == "break. splash.\n[gap repair recovered: splash@119.7]"

def test_write_transcript_no_gap_repair_unchanged(tmp_path):
    from hoops.session import write_transcript
    env = {"model": "whisper-1", "response": {"text": "break. splash."}}
    write_transcript(tmp_path, env)
    assert (tmp_path / "transcript.txt").read_text() == "break. splash."
