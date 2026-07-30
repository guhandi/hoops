import json, shutil
import pytest
from pathlib import Path
from hoops.config import load_config
from hoops.score import score_fixture, aggregate
from hoops.fixtures import transcript_cache_path
from conftest import make_env

pytestmark = pytest.mark.parse
REPO = Path(__file__).resolve().parents[1]
NEW_HEADER = ("filename,fixture_id,category,status,vocabulary,duration_s,size_bytes,"
              "audio_format,conditions,what_it_tests,use_for,timing_ground_truth,"
              "beep_interval_s,expected_calls,expected_shot_count,expect_invariants_pass,"
              "contains_correction,contains_note,traps_planted,label_status,notes")

@pytest.fixture
def sandbox(tmp_path):
    shutil.copy(REPO / "config.yaml", tmp_path / "config.yaml")
    (tmp_path / "fixtures" / "transcripts").mkdir(parents=True)
    return load_config(tmp_path / "config.yaml")

def put_cache(cfg, filename, words):
    p = transcript_cache_path(cfg.repo_root, filename)
    p.write_text(json.dumps(make_env(words, duration=60.0)))

def row(filename, expected, traps="", use_for="GATE", gaps="", expect_invariants_pass="TRUE"):
    return {"filename": filename, "expected_calls": expected, "traps_planted": traps,
            "expect_invariants_pass": expect_invariants_pass, "vocabulary": "", "use_for": use_for,
            "expected_gaps": gaps, "notes": ""}

CLEAN = [("brick", 5.0, 5.3), ("swish", 12.0, 12.3), ("swish", 18.0, 18.3), ("swish", 24.0, 24.3)]

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
    words = [("brick", 5.0, 5.3), ("swish", 12.0, 12.3)]      # only 2 live calls -> invariants fail
    put_cache(sandbox, "f10.m4a", words)
    s = score_fixture(row("f10.m4a", "miss make"), sandbox)  # row() hardcodes expect_invariants_pass=TRUE
    assert s.invariants_ok_expected is True and s.invariants_ok_got is False
    agg = aggregate([s])
    assert agg["invariant_mismatches"] == 1

def test_score_and_print_fails_on_invariant_mismatch(sandbox, capsys):
    from hoops.score import score_and_print
    words = [("brick", 5.0, 5.3), ("swish", 12.0, 12.3)]
    put_cache(sandbox, "f10.m4a", words)
    (sandbox.repo_root / "fixtures" / "manifest.csv").write_text(
        NEW_HEADER + "\n"
        "f10.m4a,F10,fixture,recorded,,,,,x,x,GATE,FALSE,,miss make,,TRUE,,,,LABELED,invariant trap\n")
    rc = score_and_print(sandbox)
    out = capsys.readouterr().out
    assert rc == 1
    assert "invariant_mismatches" in out

def test_aggregate_gates():
    from hoops.score import FixtureScore
    good = FixtureScore(name="a", expected=["make"] * 4, got=["make"] * 4, heard=["brick"] * 4, matched=4,
                        inserted=0, deleted=0, misclassified=0, exact=True, gap_mae=None,
                        traps=False, invariants_ok_expected=True, invariants_ok_got=True)
    agg = aggregate([good])
    assert agg["recall"] == 1.0 and agg["precision"] == 1.0
    assert agg["exact_fraction"] == 1.0 and agg["phantom_on_traps"] == 0

MACHINE_COLS = ["heard_calls", "got_calls", "match", "scored_at"]

def manifest_file(tmp_path, rows_text):
    p = tmp_path / "fixtures" / "manifest.csv"
    p.parent.mkdir(exist_ok=True)
    p.write_text(NEW_HEADER + "\n" + rows_text)
    return p

def _row_text(filename, expected_calls):
    cells = [""] * 21
    cells[0] = filename
    cells[13] = expected_calls
    cells[20] = "note, with comma"          # comma forces quoting — survives round-trip
    return ",".join(f'"{c}"' if "," in c else c for c in cells)

def test_update_manifest_writes_machine_columns(sandbox, tmp_path):
    from hoops.score import update_manifest
    put_cache(sandbox, "f01.m4a", CLEAN)
    s = score_fixture(row("f01.m4a", "miss make make make"), sandbox)
    p = manifest_file(tmp_path, _row_text("f01.m4a", "miss make make make") + "\n")
    update_manifest(p, [s], scored_at="2026-07-30")
    import csv
    rows = list(csv.DictReader(p.open()))
    assert rows[0]["heard_calls"] == "brick swish swish swish"
    assert rows[0]["got_calls"] == "miss make make make"
    assert rows[0]["match"] == "TRUE"
    assert rows[0]["scored_at"] == "2026-07-30"
    # Prove lowercasing: score a fixture with capitalized tokens
    s2 = type(s)(**{**s.__dict__, "heard": ["Brick", "SWISH"]})
    update_manifest(p, [s2], scored_at="2026-07-30")
    rows = list(csv.DictReader(p.open()))
    assert rows[0]["heard_calls"] == "brick swish"

def test_update_manifest_preserves_hand_columns(sandbox, tmp_path):
    from hoops.score import update_manifest
    put_cache(sandbox, "f01.m4a", CLEAN)
    s = score_fixture(row("f01.m4a", "miss make miss make"), sandbox)   # mismatch
    p = manifest_file(tmp_path, _row_text("f01.m4a", "miss make miss make") + "\n")
    import csv
    before = list(csv.DictReader(p.open()))
    update_manifest(p, [s], scored_at="2026-07-30")
    after = list(csv.DictReader(p.open()))
    hand_cols = NEW_HEADER.split(",")
    for b, a in zip(before, after):
        assert {k: b[k] for k in hand_cols} == {k: a[k] for k in hand_cols}
    assert after[0]["match"] == "FALSE"
    assert after[0]["notes"] == "note, with comma"    # quoting survived round-trip

def test_update_manifest_leaves_unscored_rows_blank(sandbox, tmp_path):
    from hoops.score import update_manifest
    put_cache(sandbox, "f01.m4a", CLEAN)
    s = score_fixture(row("f01.m4a", "miss make make make"), sandbox)
    p = manifest_file(tmp_path,
                      _row_text("f01.m4a", "miss make make make") + "\n" +
                      _row_text("f99.m4a", "") + "\n")     # never scored
    update_manifest(p, [s], scored_at="2026-07-30")
    import csv
    rows = list(csv.DictReader(p.open()))
    assert rows[1]["heard_calls"] == "" and rows[1]["scored_at"] == ""

def test_update_manifest_idempotent_columns(sandbox, tmp_path):
    from hoops.score import update_manifest
    put_cache(sandbox, "f01.m4a", CLEAN)
    s = score_fixture(row("f01.m4a", "miss make make make"), sandbox)
    p = manifest_file(tmp_path, _row_text("f01.m4a", "miss make make make") + "\n")
    update_manifest(p, [s], scored_at="2026-07-30")
    update_manifest(p, [s], scored_at="2026-07-31")       # second run
    header = p.read_text().splitlines()[0]
    assert header.count("heard_calls") == 1               # columns not duplicated
    import csv
    assert list(csv.DictReader(p.open()))[0]["scored_at"] == "2026-07-31"

def test_score_fixture_records_heard_tokens(sandbox):
    put_cache(sandbox, "f01.m4a", CLEAN)
    s = score_fixture(row("f01.m4a", "miss make make make"), sandbox)
    assert s.heard == ["brick", "swish", "swish", "swish"]

def test_update_manifest_rejects_duplicate_filenames(sandbox, tmp_path):
    from hoops.score import update_manifest
    put_cache(sandbox, "f01.m4a", CLEAN)
    s = score_fixture(row("f01.m4a", "miss make make make"), sandbox)
    p = manifest_file(tmp_path,
                      _row_text("f01.m4a", "miss make make make") + "\n" +
                      _row_text("f01.m4a", "miss miss miss miss") + "\n")
    with pytest.raises(ValueError, match="duplicate filename"):
        update_manifest(p, [s], scored_at="2026-07-30")
    import csv
    rows = list(csv.DictReader(p.open()))
    assert all(r.get("scored_at") in (None, "") for r in rows)   # file untouched on error
