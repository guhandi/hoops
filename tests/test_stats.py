import pytest
from hoops.parse import Call, ParseResult
from hoops.stats import build_shot_rows, build_session_stats
from hoops.transcribe import words_from_envelope
from conftest import make_env

pytestmark = pytest.mark.unit

def call(result, t, voided=False):
    return Call(result=result, raw_token=result, t_s=t, isolation_s=1.0,
                confidence=0.9, voided=voided)

SEQ = [call("miss", 5.0), call("make", 12.0), call("make", 18.0, voided=True),
       call("miss", 25.0), call("make", 33.0), call("make", 40.0), call("make", 46.0)]

def test_shot_rows_numbering_gaps_streaks():
    rows = build_shot_rows(SEQ, "20260727-061204", "2026-07-27")
    assert [r["shot_num"] for r in rows] == [1, 2, 3, 4, 5, 6, 7]
    assert rows[0]["gap_s"] is None and rows[1]["gap_s"] == 7.0
    assert rows[2]["voided"] is True and rows[2]["gap_s"] is None
    assert rows[3]["gap_s"] == 13.0          # 25.0 - 12.0, skipping voided
    assert [r["streak_after"] for r in rows] == [0, 1, 1, 0, 1, 2, 3]
    assert rows[0]["session_id"] == "20260727-061204"

def test_session_stats():
    rows = build_shot_rows(SEQ, "s", "2026-07-27")
    ws = words_from_envelope(make_env([("blah", i * 1.0, i * 1.0 + 0.3) for i in range(12)]))
    stats = build_session_stats(rows, ParseResult(calls=SEQ, note="tired"), ws,
        session_id="s", session_date_local="2026-07-27", start_time_local="06:12:04",
        session_len_s=50.0, transcriber="whisper-1", parser_version="1",
        profanity=["fuck"])
    assert stats["shots_to_three"] == 6           # non-voided count
    assert stats["makes"] == 4 and stats["misses"] == 2
    assert stats["fg_pct"] == pytest.approx(4 / 6)
    assert stats["longest_make_streak"] == 3
    assert stats["longest_miss_streak"] == 1
    assert stats["time_to_first_make_s"] == 12.0
    assert stats["median_gap_s"] == 7.0           # gaps: 7, 13, 8, 7, 6 → median 7
    assert stats["fastest_gap_s"] == 6.0 and stats["slowest_gap_s"] == 13.0
    assert stats["notes"] == "tired"
    assert stats["words_per_miss"] == 6.0         # 12 words / 2 misses
    assert stats["profanity_count"] == 0
    assert stats["quote_of_day"] == "" and stats["invariants_passed"] is True

def test_profanity_counted():
    rows = build_shot_rows([call("make", 1.0)] * 1, "s", "2026-07-27")
    ws = words_from_envelope(make_env([("Fuck!", 0.0, 0.3), ("ok", 1.0, 1.2)]))
    stats = build_session_stats(rows, ParseResult(), ws, session_id="s",
        session_date_local="2026-07-27", start_time_local="06:00:00",
        session_len_s=2.0, transcriber="t", parser_version="1", profanity=["fuck"])
    assert stats["profanity_count"] == 1

def test_zero_miss_words_per_miss_none():
    rows = build_shot_rows([call("make", 1.0), call("make", 4.0), call("make", 7.0)],
                           "s", "2026-07-27")
    stats = build_session_stats(rows, ParseResult(), [], session_id="s",
        session_date_local="2026-07-27", start_time_local="06:00:00",
        session_len_s=8.0, transcriber="t", parser_version="1", profanity=[])
    assert stats["words_per_miss"] is None
    assert stats["median_gap_s"] == 3.0

from hoops.stats import build_chase

def _row(n, result, t, voided=False):
    return {"shot_num": n, "result": result, "t_call_s": float(t), "voided": voided}

def test_chase_counts_broken_two_in_a_row():
    # miss, make, make, miss, make, make, miss, make, make, make -> 2 almosts, closed
    seq = ["miss", "make", "make", "miss", "make", "make", "miss",
           "make", "make", "make"]
    rows = [_row(i + 1, r, 5 * (i + 1)) for i, r in enumerate(seq)]
    chase = build_chase(rows)
    assert chase["almosts"] == 2
    assert chase["closed_out"] is True
    assert chase["runs"][0] == {"result": "miss", "start_shot": 1, "end_shot": 1,
                                "start_t": 5.0, "end_t": 5.0, "length": 1}
    assert chase["runs"][-1]["length"] == 3

def test_chase_final_two_run_is_not_an_almost():
    seq = ["make", "make"]                       # session ended without closing
    rows = [_row(i + 1, r, 5 * (i + 1)) for i, r in enumerate(seq)]
    chase = build_chase(rows)
    assert chase["almosts"] == 0
    assert chase["closed_out"] is False

def test_chase_skips_voided_rows():
    rows = [_row(1, "make", 5), _row(2, "make", 8, voided=True),
            _row(3, "miss", 12)]
    chase = build_chase(rows)
    assert [r["result"] for r in chase["runs"]] == ["make", "miss"]

def test_chase_empty():
    assert build_chase([]) == {"runs": [], "almosts": 0, "closed_out": False}

def test_session_stats_gains_chase_keys():
    # SEQ and call() are this file's existing module-level helpers
    rows = build_shot_rows(SEQ, "s", "2026-07-27")
    stats = build_session_stats(rows, ParseResult(), [], session_id="s",
        session_date_local="2026-07-27", start_time_local="06:12:04",
        session_len_s=50.0, transcriber="whisper-1", parser_version="1",
        profanity=["fuck"])
    assert stats["closed_out"] is True            # SEQ ends make, make, make
    assert stats["almost_closeouts"] == 0         # no broken 2-run: the make at
                                                  # 12.0 stands alone (18.0 voided)
    assert stats["runs"][-1]["length"] == 3
