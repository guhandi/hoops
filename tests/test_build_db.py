import json, sqlite3, subprocess, sys
import pytest
from pathlib import Path

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[1]

def test_build_db(tmp_path):
    sdir = tmp_path / "sessions" / "2026" / "07" / "hoops__20260727-061204"
    sdir.mkdir(parents=True)
    (sdir / "shots.csv").write_text(
        "session_id,session_date_local,shot_num,result,t_call_s,gap_s,streak_after,"
        "voided,isolation_s,confidence,raw_token\n"
        "20260727-061204,2026-07-27,1,make,5.0,,1,False,2.0,,make\n")
    (sdir / "session.json").write_text(json.dumps(
        {"session_id": "20260727-061204", "session_date_local": "2026-07-27",
         "shots_to_three": 1, "makes": 1, "misses": 0}))
    db = tmp_path / "hoops.db"
    subprocess.run([sys.executable, str(REPO / "scripts" / "build_db.py"),
                    "--sessions", str(tmp_path / "sessions"), "--db", str(db)], check=True)
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM shots").fetchone()[0] == 1
    assert con.execute("SELECT makes FROM sessions").fetchone()[0] == 1
