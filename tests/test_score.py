import json, shutil
import pytest
from pathlib import Path
from hoops.config import load_config
from hoops.score import score_fixture, aggregate
from hoops.fixtures import transcript_cache_path
from conftest import make_env

pytestmark = pytest.mark.parse
REPO = Path(__file__).resolve().parents[1]

@pytest.fixture
def sandbox(tmp_path):
    shutil.copy(REPO / "config.yaml", tmp_path / "config.yaml")
    (tmp_path / "fixtures" / "transcripts").mkdir(parents=True)
    return load_config(tmp_path / "config.yaml")

def put_cache(cfg, filename, words):
    p = transcript_cache_path(cfg.repo_root, filename)
    p.write_text(json.dumps(make_env(words, duration=60.0)))

def row(filename, expected, traps="", gating="yes", gaps=""):
    return {"filename": filename, "expected_calls": expected, "traps_planted": traps,
            "expect_invariants_pass": "yes", "vocab": "", "gating": gating,
            "expected_gaps": gaps, "notes": ""}

CLEAN = [("miss", 5.0, 5.3), ("make", 12.0, 12.3), ("make", 18.0, 18.3), ("make", 24.0, 24.3)]

def test_exact_match(sandbox):
    put_cache(sandbox, "f01.m4a", CLEAN)
    s = score_fixture(row("f01.m4a", "miss make make make"), sandbox)
    assert s.exact and s.matched == 4 and s.inserted == 0 and s.deleted == 0

def test_phantom_detected_on_trap_fixture(sandbox):
    words = CLEAN + [("brick", 30.0, 30.3)]     # extra isolated call = phantom
    put_cache(sandbox, "f02.m4a", words)
    s = score_fixture(row("f02.m4a", "miss make make make", traps="3"), sandbox)
    assert s.traps and s.inserted == 1 and not s.exact

def test_gap_mae(sandbox):
    put_cache(sandbox, "f06.m4a", CLEAN)
    s = score_fixture(row("f06.m4a", "miss make make make", gaps="7.0 6.0 6.0"), sandbox)
    assert s.gap_mae == pytest.approx(0.0)

def test_invariant_mismatch_detected(sandbox):
    words = [("miss", 5.0, 5.3), ("make", 12.0, 12.3)]      # only 2 live calls -> invariants fail
    put_cache(sandbox, "f10.m4a", words)
    s = score_fixture(row("f10.m4a", "miss make"), sandbox)  # row() hardcodes expect_invariants_pass=yes
    assert s.invariants_ok_expected is True and s.invariants_ok_got is False
    agg = aggregate([s])
    assert agg["invariant_mismatches"] == 1

def test_score_and_print_fails_on_invariant_mismatch(sandbox, capsys):
    from hoops.score import score_and_print
    words = [("miss", 5.0, 5.3), ("make", 12.0, 12.3)]
    put_cache(sandbox, "f10.m4a", words)
    (sandbox.repo_root / "fixtures" / "manifest.csv").write_text(
        "filename,expected_calls,traps_planted,expect_invariants_pass,vocab,gating,expected_gaps,notes\n"
        "f10.m4a,miss make,,yes,,yes,,invariant trap\n")
    rc = score_and_print(sandbox)
    out = capsys.readouterr().out
    assert rc == 1
    assert "invariant_mismatches" in out

def test_aggregate_gates():
    from hoops.score import FixtureScore
    good = FixtureScore(name="a", expected=["make"] * 4, got=["make"] * 4, matched=4,
                        inserted=0, deleted=0, misclassified=0, exact=True, gap_mae=None,
                        traps=False, invariants_ok_expected=True, invariants_ok_got=True)
    agg = aggregate([good])
    assert agg["recall"] == 1.0 and agg["precision"] == 1.0
    assert agg["exact_fraction"] == 1.0 and agg["phantom_on_traps"] == 0
