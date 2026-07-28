import pytest
from hoops.config import Vocabulary
from hoops.parse import parse_words
from hoops.transcribe import words_from_envelope
from conftest import make_env

pytestmark = pytest.mark.unit
V = Vocabulary.from_dict("default", {"make": ["make", "splash"], "miss": ["miss", "brick"]})

def words(*triples):
    return words_from_envelope(make_env(list(triples)))

def parse(ws): return parse_words(ws, V, iso_low=0.15, iso_high=0.4)

def test_isolated_calls_detected():
    r = parse(words(("make", 1.0, 1.4), ("miss", 4.0, 4.4), ("splash", 8.0, 8.5)))
    assert [c.result for c in r.calls] == ["make", "miss", "make"]
    assert r.calls[0].t_s == 1.0 and r.calls[0].raw_token == "make"

def test_commentary_bait_words_discarded():
    # "come on make it" — continuous run, gaps ~0.05s → no phantom call
    r = parse(words(("come", 1.0, 1.2), ("on", 1.25, 1.4), ("make", 1.45, 1.7), ("it", 1.75, 1.9),
                    ("miss", 5.0, 5.4)))
    assert [c.result for c in r.calls] == ["miss"]

def test_midband_isolation_goes_to_ambiguous():
    # gap 0.25s both sides → between 0.15 and 0.4
    r = parse(words(("uh", 1.0, 1.2), ("make", 1.45, 1.7), ("so", 1.95, 2.1)))
    assert r.calls == []
    assert len(r.ambiguous) == 1 and r.ambiguous[0].canonical == "make"

def test_scratch_that_voids_previous_call():
    r = parse(words(("make", 1.0, 1.3), ("miss", 4.0, 4.3),
                    ("scratch", 6.0, 6.3), ("that", 6.4, 6.7), ("make", 9.0, 9.3)))
    assert [(c.result, c.voided) for c in r.calls] == [
        ("make", False), ("miss", True), ("make", False)]

def test_scratch_words_are_not_calls_or_ambiguous():
    r = parse(words(("scratch", 6.0, 6.3), ("that", 6.4, 6.7)))
    assert r.calls == [] and r.ambiguous == []

def test_note_captured_verbatim_and_excluded_from_calls():
    r = parse(words(("make", 1.0, 1.3), ("note", 5.0, 5.3),
                    ("elbow", 5.5, 5.8), ("stiff", 5.9, 6.2), ("brick", 6.3, 6.6)))
    assert [c.result for c in r.calls] == ["make"]
    assert r.note == "elbow stiff brick"

def test_no_note_returns_none():
    assert parse(words(("make", 1.0, 1.3))).note is None

def test_empty_input():
    r = parse([])
    assert r.calls == [] and r.ambiguous == [] and r.note is None

def test_isolation_computed_against_full_word_list_not_truncated():
    # Regression: "make" (1.0–1.3) immediately before "note" (1.35–1.55) with gap 0.05s
    # Gap to next word in FULL list is 0.05s, so isolation = min(inf, 0.05) = 0.05 <= 0.15 → discard
    r = parse(words(("make", 1.0, 1.3), ("note", 1.35, 1.55), ("tired", 1.6, 1.9)))
    assert r.calls == []
    assert r.note == "tired"

def test_word_far_from_note_is_accepted():
    # "make" (1.0–1.3) far from "note" (5.0–5.2) with gap 3.7s
    # isolation = min(inf, 3.7) = 3.7 >= 0.4 → call
    r = parse(words(("make", 1.0, 1.3), ("note", 5.0, 5.2), ("tired", 5.5, 5.8)))
    assert [c.result for c in r.calls] == ["make"]
    assert r.note == "tired"

def test_bare_note_with_nothing_after_returns_none():
    # Decision encoding: trailing "note" token with no content after it returns note=None
    r = parse(words(("make", 1.0, 1.3), ("note", 5.0, 5.2)))
    assert [c.result for c in r.calls] == ["make"]
    assert r.note is None
