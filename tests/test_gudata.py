"""GuData push: payload mapping from the repo's real stats/rows shapes."""
import pytest
from hoops import PARSER_VERSION
from hoops.config import Vocabulary
from hoops.parse import parse_words
from hoops.stats import build_shot_rows, build_session_stats
from hoops.transcribe import words_from_envelope
from conftest import make_env

pytestmark = pytest.mark.unit

VOCAB = Vocabulary.from_dict("swish_brick", {"make": ["swish"], "miss": ["brick"]})
GOOD = [("okay", 0.5, 0.8), ("brick", 5.0, 5.3), ("come", 8.0, 8.2), ("on", 8.25, 8.4),
        ("swish", 12.0, 12.3), ("swish", 18.0, 18.3), ("swish", 24.0, 24.3),
        ("note", 27.0, 27.2), ("felt", 27.5, 27.7), ("good", 27.8, 28.0)]
SID = "20260728-061204"

def fixture_stats_and_rows():
    words = words_from_envelope(make_env(GOOD, duration=30.0))
    parsed = parse_words(words, VOCAB, 0.15, 0.4)
    rows = build_shot_rows(parsed.calls, SID, "2026-07-28")
    stats = build_session_stats(rows, parsed, words, session_id=SID,
        session_date_local="2026-07-28", start_time_local="06:12:04",
        session_len_s=30.0, transcriber="whisper-1",
        parser_version=PARSER_VERSION, profanity=[])
    return stats, rows

def test_build_payload_matches_contract_exactly():
    from hoops.gudata import build_payload
    stats, rows = fixture_stats_and_rows()
    payload = build_payload(stats, rows, "America/Los_Angeles", f"hoops__{SID}")
    assert payload == {
        "session": {
            "observed_at": "2026-07-28T06:12:04-07:00",
            "timezone": "America/Los_Angeles",
            "values": {
                "activity.hoops.shots_to_three": 4,
                "activity.hoops.fg_pct": 75.0,
                "activity.hoops.longest_streak": 3,
                "activity.hoops.shot_count": 4,
                "activity.hoops.session_notes": "felt good",
            },
        },
        "rows": [
            {"field": "activity.hoops.shot_result", "value": False,
             "observed_at": "2026-07-28T06:12:09-07:00"},
            {"field": "activity.hoops.shot_result", "value": True,
             "observed_at": "2026-07-28T06:12:16-07:00"},
            {"field": "activity.hoops.shot_result", "value": True,
             "observed_at": "2026-07-28T06:12:22-07:00"},
            {"field": "activity.hoops.shot_result", "value": True,
             "observed_at": "2026-07-28T06:12:28-07:00"},
        ],
        "external_id": f"hoops__{SID}",
    }

def test_empty_notes_key_omitted():
    from hoops.gudata import build_payload
    stats, rows = fixture_stats_and_rows()
    stats["notes"] = ""
    payload = build_payload(stats, rows, "America/Los_Angeles", f"hoops__{SID}")
    assert "activity.hoops.session_notes" not in payload["session"]["values"]

def test_voided_rows_excluded_and_shot_count_is_live_only():
    from hoops.gudata import build_payload
    stats, rows = fixture_stats_and_rows()
    rows.append({"session_id": SID, "session_date_local": "2026-07-28", "shot_num": 5,
                 "result": "miss", "t_call_s": 26.0, "gap_s": None, "streak_after": 3,
                 "voided": True, "isolation_s": 1.0, "confidence": 1.0, "raw_token": "brick"})
    payload = build_payload(stats, rows, "America/Los_Angeles", f"hoops__{SID}")
    assert len(payload["rows"]) == 4
    assert payload["session"]["values"]["activity.hoops.shot_count"] == 4

def test_no_live_shots_raises():
    from hoops.gudata import GuDataError, build_payload
    stats, _ = fixture_stats_and_rows()
    with pytest.raises(GuDataError):
        build_payload(stats, [], "America/Los_Angeles", "hoops__x")
