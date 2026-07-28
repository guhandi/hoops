import pytest
from hoops.config import Vocabulary
from hoops.invariants import check_invariants
from hoops.parse import Call
from hoops.stats import build_shot_rows

pytestmark = pytest.mark.unit
V = Vocabulary.from_dict("default", {"make": ["make", "splash"], "miss": ["miss", "brick"]})

def rows_from(seq, spacing=6.0, start=5.0):
    calls = [Call(result=r, raw_token=r, t_s=start + i * spacing, isolation_s=1.0,
                  confidence=0.9) for i, r in enumerate(seq)]
    return build_shot_rows(calls, "s", "2026-07-27")

def check(rows): return check_invariants(rows, min_gap_s=1.5, max_gap_s=120, vocab=V)

def test_clean_session_passes():
    assert check(rows_from(["miss", "make", "miss", "make", "make", "make"])) == []

def test_i1_not_ending_on_three_makes():
    ids = [v.id for v in check(rows_from(["make", "make", "miss"]))]
    assert "I1" in ids

def test_i2_fewer_than_three_shots():
    ids = [v.id for v in check(rows_from(["make", "make"]))]
    assert "I2" in ids

def test_i3_calls_too_close():
    rows = rows_from(["miss", "make", "make", "make"], spacing=1.0)
    assert "I3" in [v.id for v in check(rows)]

def test_i4_gap_too_long():
    rows = rows_from(["miss", "make", "make", "make"], spacing=130.0)
    assert "I4" in [v.id for v in check(rows)]

def test_i5_unknown_raw_token():
    rows = rows_from(["miss", "make", "make", "make"])
    rows[0]["raw_token"] = "swoosh"
    assert "I5" in [v.id for v in check(rows)]

def test_i6_early_triple_make():
    seq = ["make", "make", "make", "miss", "make", "make", "make"]
    assert "I6" in [v.id for v in check(rows_from(seq))]

def test_voided_rows_excluded():
    calls = [Call("make", "make", 5.0, 1.0, 0.9), Call("make", "make", 6.0, 1.0, 0.9, voided=True),
             Call("make", "make", 11.0, 1.0, 0.9), Call("make", "make", 17.0, 1.0, 0.9)]
    rows = build_shot_rows(calls, "s", "2026-07-27")
    assert check(rows) == []   # voided 1s-gap row ignored; ends on three makes
