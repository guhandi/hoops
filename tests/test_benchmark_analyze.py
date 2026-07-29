import pytest
import json
import tempfile
from pathlib import Path
from benchmarks.transcribers.base import BWord, TranscriptResult
from benchmarks.analyze import (detect, gap_stats, cluster, recommend_threshold,
                                pairwise_agreement, silence_words, assemble_metrics,
                                fixture_duration)

pytestmark = pytest.mark.unit
V = {"swish": "make", "splash": "make", "brick": "miss", "break": "miss"}

def W(word, start, end): return BWord(word, start, end, None)

def test_detect_isolation_and_edges():
    words = [W("uh", 0.0, 0.2), W("Swish,", 5.0, 5.4), W("nice", 9.0, 9.3)]
    d = detect(words, V)
    assert len(d) == 1 and d[0]["canonical"] == "make"
    assert d[0]["isolation"] == pytest.approx(3.6)  # min(4.8 before, 3.6 after)
    only = detect([W("brick", 1.0, 1.3)], V)
    assert only[0]["isolation"] == float("inf")

def test_gap_stats_ten_second_beep():
    mids = [5.0, 15.2, 24.9, 35.0]
    s = gap_stats(mids, 10.0)
    assert s["n_gaps"] == 3 and s["max"] == pytest.approx(0.3)
    assert gap_stats([5.0], 10.0) == {}

def test_cluster_consensus_majority():
    dets = {
        "a": [{"canonical": "make", "mid": 5.0}],
        "b": [{"canonical": "make", "mid": 5.3}],
        "c": [{"canonical": "make", "mid": 20.0}],
    }
    cl = cluster(dets)
    assert len(cl) == 2
    big = next(c for c in cl if len(c["models"]) == 2)
    assert big["consensus"] is True  # 2 of 3 = strict majority
    lone = next(c for c in cl if len(c["models"]) == 1)
    assert lone["consensus"] is False

def test_recommend_threshold_clean_split():
    r = recommend_threshold(real=[2.0, 3.0, 4.0], bait=[0.1, 0.2, 0.4])
    assert 0.4 < r["threshold"] < 2.0
    assert r["margin"] == pytest.approx(1.6)
    assert recommend_threshold([], [0.1]) == {}

def test_pairwise_agreement():
    cl = [{"canonical": "make", "mid": 5.0,
           "models": {"a": {"mid": 5.0}, "b": {"mid": 5.2}}, "consensus": True},
          {"canonical": "miss", "mid": 9.0,
           "models": {"a": {"mid": 9.0}, "b": {"mid": 9.4}}, "consensus": True}]
    agg = pairwise_agreement(cl, ["a", "b"])
    assert agg["a|b"] == pytest.approx(0.3)  # median of 0.2, 0.4

def test_silence_words():
    assert silence_words([W("the", 100.0, 100.3)], 90.0) == 1
    assert silence_words([W("the", 80.0, 80.3)], 90.0) == 0


def _transcript(words, runtime_s=1.0):
    return TranscriptResult(model_id="m", fixture="F", words=words, text="",
                             runtime_s=runtime_s, peak_rss_mb=None, prompt_used=False)


def test_fixture_duration_uses_manifest_when_present():
    t = _transcript([W("swish", 0.0, 0.3)])
    duration, used_fallback = fixture_duration({"duration_s": "30.0"}, t)
    assert duration == pytest.approx(30.0)
    assert used_fallback is False


def test_fixture_duration_falls_back_to_last_word_end_when_blank():
    """Finding 4: D01-D04 have empty duration_s in the manifest; without a fallback,
    cost_usd undercounts for whisper-1 and those fixtures' RTF silently drops out."""
    t = _transcript([W("swish", 0.0, 0.3), W("brick", 10.0, 10.4), W("swish", 25.5, 25.9)])
    duration, used_fallback = fixture_duration({"duration_s": ""}, t)
    assert duration == pytest.approx(25.9)
    assert used_fallback is True


def test_fixture_duration_falls_back_when_manifest_value_unparseable():
    t = _transcript([W("swish", 0.0, 0.3), W("brick", 12.0, 12.4)])
    duration, used_fallback = fixture_duration({"duration_s": "not-a-number"}, t)
    assert duration == pytest.approx(12.4)
    assert used_fallback is True


def test_fixture_duration_falls_back_when_manifest_value_non_positive():
    t = _transcript([W("swish", 0.0, 0.3), W("brick", 8.0, 8.4)])
    duration, used_fallback = fixture_duration({"duration_s": "0"}, t)
    assert duration == pytest.approx(8.4)
    assert used_fallback is True


def test_fixture_duration_none_when_no_manifest_value_and_no_words():
    t = _transcript([])
    duration, used_fallback = fixture_duration({"duration_s": ""}, t)
    assert duration is None
    assert used_fallback is False


def test_assemble_metrics_integration():
    """Integration test covering all metric assembly paths with strict value assertions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        out_root = tmpdir / "out"
        out_root.mkdir(parents=True)

        # Comprehensive manifest covering all paths
        manifest_rows = [
            # F01: Both models agree (baseline)
            {
                "fixture_id": "F01",
                "vocabulary": "swish_brick",
                "duration_s": "30.0",
                "timing_ground_truth": "FALSE",
                "beep_interval_s": "",
                "expected_calls": "",
            },
            # F02: Model disagreement - model_b hallucinates extra detection for isolation split
            {
                "fixture_id": "F02",
                "vocabulary": "swish_brick",
                "duration_s": "20.0",
                "timing_ground_truth": "FALSE",
                "beep_interval_s": "",
                "expected_calls": "",
            },
            # F03: Mode A (expected_calls ref)
            {
                "fixture_id": "F03",
                "vocabulary": "make_miss",
                "duration_s": "25.0",
                "timing_ground_truth": "FALSE",
                "beep_interval_s": "",
                "expected_calls": "make miss",
            },
            # F04: Empty vocabulary field (tests vocab_default fallback)
            {
                "fixture_id": "F04",
                "vocabulary": "",
                "duration_s": "15.0",
                "timing_ground_truth": "FALSE",
                "beep_interval_s": "",
                "expected_calls": "",
            },
            # F05: Invalid vocabulary (tests unknown_vocab tracking)
            {
                "fixture_id": "F05",
                "vocabulary": "nonexistent_vocab",
                "duration_s": "10.0",
                "timing_ground_truth": "FALSE",
                "beep_interval_s": "",
                "expected_calls": "",
            },
            # F06: Beep fixture with gap_stats
            {
                "fixture_id": "F06",
                "vocabulary": "swish_brick",
                "duration_s": "40.0",
                "timing_ground_truth": "TRUE",
                "beep_interval_s": "10.0",
                "expected_calls": "",
            },
        ]

        vocabs = {
            "swish_brick": {
                "swish": "make", "splash": "make",
                "brick": "miss", "break": "miss"
            },
            "make_miss": {
                "make": "make",
                "miss": "miss",
            },
        }

        # F01: Both models agree on "make"
        f01_a = {
            "model_id": "model_a",
            "fixture": "F01",
            "words": [
                {"word": "uh", "start": 0.0, "end": 0.2, "confidence": None},
                {"word": "swish", "start": 5.0, "end": 5.4, "confidence": None},
                {"word": "nice", "start": 9.0, "end": 9.3, "confidence": None},
            ],
            "text": "uh swish nice",
            "runtime_s": 0.5,
            "peak_rss_mb": 100.0,
            "prompt_used": False,
        }
        f01_b = {
            "model_id": "model_b",
            "fixture": "F01",
            "words": [
                {"word": "uh", "start": 0.0, "end": 0.2, "confidence": None},
                {"word": "swish", "start": 5.1, "end": 5.5, "confidence": None},
                {"word": "nice", "start": 9.0, "end": 9.3, "confidence": None},
            ],
            "text": "uh swish nice",
            "runtime_s": 0.6,
            "peak_rss_mb": 110.0,
            "prompt_used": False,
        }

        # F02: Real consensus + bait for isolation split
        # model_a: detects swish (high isolation) and brick (high isolation) - both consensus
        # model_b: detects same swish and brick, PLUS a hallucinated "splash" wedged right next
        # to a filler word ("uh") so its isolation is genuinely low, unlike the well-separated
        # real calls. Words are listed in chronological order (detect()'s gap math assumes it).
        f02_a = {
            "model_id": "model_a",
            "fixture": "F02",
            "words": [
                {"word": "swish", "start": 3.0, "end": 3.4, "confidence": None},  # High isolation (11.6)
                {"word": "brick", "start": 15.0, "end": 15.4, "confidence": None},  # High isolation (11.6)
            ],
            "text": "swish brick",
            "runtime_s": 0.4,
            "peak_rss_mb": 105.0,
            "prompt_used": False,
        }
        f02_b = {
            "model_id": "model_b",
            "fixture": "F02",
            "words": [
                {"word": "swish", "start": 3.1, "end": 3.5, "confidence": None},  # isolation 6.3
                {"word": "uh", "start": 9.8, "end": 9.9, "confidence": None},  # filler, not a vocab word
                {"word": "splash", "start": 10.0, "end": 10.4, "confidence": None},  # Hallucinated, isolation 0.1
                {"word": "brick", "start": 15.1, "end": 15.5, "confidence": None},  # isolation 4.7
            ],
            "text": "swish uh splash brick",
            "runtime_s": 0.45,
            "peak_rss_mb": 108.0,
            "prompt_used": False,
        }

        # F03: Mode A test - both models match expected_calls "make miss"
        f03_a = {
            "model_id": "model_a",
            "fixture": "F03",
            "words": [
                {"word": "make", "start": 1.0, "end": 1.3, "confidence": None},
                {"word": "miss", "start": 6.0, "end": 6.3, "confidence": None},
            ],
            "text": "make miss",
            "runtime_s": 0.3,
            "peak_rss_mb": 95.0,
            "prompt_used": False,
        }
        f03_b = {
            "model_id": "model_b",
            "fixture": "F03",
            "words": [
                {"word": "make", "start": 1.1, "end": 1.4, "confidence": None},
                {"word": "miss", "start": 6.1, "end": 6.4, "confidence": None},
            ],
            "text": "make miss",
            "runtime_s": 0.35,
            "peak_rss_mb": 98.0,
            "prompt_used": False,
        }

        # F04: Vocab fallback - uses "swish_brick" default
        f04_a = {
            "model_id": "model_a",
            "fixture": "F04",
            "words": [
                {"word": "splash", "start": 2.0, "end": 2.3, "confidence": None},
            ],
            "text": "splash",
            "runtime_s": 0.25,
            "peak_rss_mb": 92.0,
            "prompt_used": False,
        }

        # F06: Beep fixture with detections at regular intervals for gap_stats
        f06_a = {
            "model_id": "model_a",
            "fixture": "F06",
            "words": [
                {"word": "swish", "start": 5.0, "end": 5.4, "confidence": None},
                {"word": "swish", "start": 15.1, "end": 15.5, "confidence": None},
                {"word": "swish", "start": 24.9, "end": 25.3, "confidence": None},
            ],
            "text": "swish swish swish",
            "runtime_s": 1.0,
            "peak_rss_mb": 120.0,
            "prompt_used": False,
        }

        # Create transcript files
        for dir_name in ["model_a", "model_b"]:
            (out_root / "transcripts" / dir_name).mkdir(parents=True)

        (out_root / "transcripts" / "model_a" / "F01.json").write_text(json.dumps(f01_a))
        (out_root / "transcripts" / "model_b" / "F01.json").write_text(json.dumps(f01_b))
        (out_root / "transcripts" / "model_a" / "F02.json").write_text(json.dumps(f02_a))
        (out_root / "transcripts" / "model_b" / "F02.json").write_text(json.dumps(f02_b))
        (out_root / "transcripts" / "model_a" / "F03.json").write_text(json.dumps(f03_a))
        (out_root / "transcripts" / "model_b" / "F03.json").write_text(json.dumps(f03_b))
        (out_root / "transcripts" / "model_a" / "F04.json").write_text(json.dumps(f04_a))
        (out_root / "transcripts" / "model_a" / "F06.json").write_text(json.dumps(f06_a))

        # Add malformed JSON file for load_errors
        (out_root / "transcripts" / "model_b" / "F06.json").write_text("{invalid json")

        # Create skips file
        (out_root / "skips.json").write_text(json.dumps({}))

        # Call assemble_metrics
        assemble_metrics(
            out_root=out_root,
            manifest_rows=manifest_rows,
            vocabs=vocabs,
            vocab_default="swish_brick",
        )

        metrics_file = out_root / "metrics.json"
        assert metrics_file.exists()
        metrics = json.loads(metrics_file.read_text())

        # ===== ASSERTION: Top-level structure =====
        assert "models" in metrics
        assert "fixtures" in metrics
        assert "skips" in metrics
        assert "isolation" in metrics
        assert "agreement" in metrics
        assert "silence" in metrics
        assert "load_errors" in metrics
        assert "unknown_vocab" in metrics

        # ===== ASSERTION: Error tracking (populated, not just present) =====
        assert len(metrics["load_errors"]) > 0, "load_errors must be populated"
        assert any(e["fixture_id"] == "F06" for e in metrics["load_errors"])
        assert len(metrics["unknown_vocab"]) > 0, "unknown_vocab must be populated"
        assert any(u["fixture_id"] == "F05" for u in metrics["unknown_vocab"])

        # ===== ASSERTION: Detection counts with ACTUAL VALUES (models summary) =====
        # These are cumulative across F01, F02, F03, F04, F06 (F05 is skipped as unknown
        # vocab). Every fixture is fully agreed except F02, where model_b hallucinates
        # "splash" (1 extra, 2 matched, 3 found) while model_a stays clean (2 matched, 2
        # found, 0 extra). Since extra is additive per fixture, the aggregate must show
        # exactly model_a: 0 extra, model_b: 1 extra -- not just a self-consistent formula.
        model_a_summary = metrics["models"]["model_a"]
        model_b_summary = metrics["models"]["model_b"]
        assert model_a_summary["detections_found"] == 9
        assert model_a_summary["detections_matched"] == 9
        assert model_a_summary["detections_extra"] == 0, "model_a never hallucinates: extra must be 0"
        assert model_b_summary["detections_found"] == 6
        assert model_b_summary["detections_matched"] == 5
        assert model_b_summary["detections_extra"] == 1, "model_b hallucinated 1 extra call (F02 splash)"

        # ===== ASSERTION: F02 hallucination - model_b has extra detection =====
        # model_a: found=2 (swish, brick), matched=2 (both consensus), extra=0
        # model_b: found=3 (swish, brick, splash), matched=2 (swish, brick), extra=1 (splash)
        f02_metrics = metrics["fixtures"]["F02"]
        model_a_found = len(f02_metrics["detections_by_model"]["model_a"])
        model_b_found = len(f02_metrics["detections_by_model"]["model_b"])
        assert model_b_found > model_a_found, "model_b should have more detections (hallucinated splash)"
        assert model_b_found == 3 and model_a_found == 2, "F02: model_a=2, model_b=3 (hallucination)"
        # Verify F02 has 2 consensus clusters (swish and brick)
        assert len([c for c in f02_metrics["clusters"] if c["consensus"]]) == 2, "F02 should have 2 consensus clusters"

        # ===== ASSERTION: Per-model accuracy with disagreement =====
        # F01: Both models agree on consensus ["make"] → both score 1.0
        f01_metrics = metrics["fixtures"]["F01"]
        assert f01_metrics["accuracy_mode"] == "consensus"
        assert f01_metrics["per_model_accuracy"]["model_a"] == 1.0
        assert f01_metrics["per_model_accuracy"]["model_b"] == 1.0

        # F02: model_b detected ["make", "make", "miss"] but consensus is ["make", "miss"]
        # → model_b's sequence doesn't match → scores 0.0 in Mode B
        # → model_a's sequence ["make", "miss"] matches → scores 1.0
        f02_metrics = metrics["fixtures"]["F02"]
        assert f02_metrics["accuracy_mode"] == "consensus"
        assert f02_metrics["per_model_accuracy"]["model_a"] == 1.0, "model_a should score 1.0 (matches consensus)"
        assert f02_metrics["per_model_accuracy"]["model_b"] == 0.0, "model_b should score 0.0 (hallucinated extra call)"

        # F03: Mode A - both models match expected_calls "make miss"
        f03_metrics = metrics["fixtures"]["F03"]
        assert f03_metrics["accuracy_mode"] == "expected"
        assert f03_metrics["per_model_accuracy"]["model_a"] == 1.0
        assert f03_metrics["per_model_accuracy"]["model_b"] == 1.0

        # ===== ASSERTION: Vocab fallback =====
        assert "F04" in metrics["fixtures"]
        f04_metrics = metrics["fixtures"]["F04"]
        assert "model_a" in f04_metrics["detections_by_model"]
        assert len(f04_metrics["detections_by_model"]["model_a"]) > 0

        # ===== ASSERTION: Gap stats with ACTUAL NUMBERS =====
        f06_metrics = metrics["fixtures"]["F06"]
        assert "gap_stats" in f06_metrics
        if "model_a" in f06_metrics["gap_stats"]:
            gap_stats = f06_metrics["gap_stats"]["model_a"]
            assert "mean" in gap_stats
            assert "median" in gap_stats
            assert "max" in gap_stats
            assert isinstance(gap_stats["mean"], (int, float))
            assert isinstance(gap_stats["median"], (int, float))
            assert isinstance(gap_stats["max"], (int, float))

        # ===== ASSERTION: Isolation split with REAL threshold/margin values =====
        # F02's consensus detections (swish, brick) sit far from any neighboring word
        # (isolation 4.7-11.6); the hallucinated "splash" is wedged next to a filler word
        # (isolation 0.1). recommend_threshold must find a clean, positive-margin split --
        # asserted unconditionally, no `if` guard, since real/bait are both non-empty here.
        isolation = metrics["isolation"]
        assert isolation["threshold"] == pytest.approx(2.4)
        assert isolation["margin"] == pytest.approx(4.6)
        assert isolation["margin"] > 0, "real and bait isolation values must not overlap"
        assert isolation["real_below"] == 0
        assert isolation["bait_above"] == 0

        # Verify draft_truth.csv
        draft_truth_file = out_root / "draft_truth.csv"
        assert draft_truth_file.exists()
        draft_truth_lines = draft_truth_file.read_text().strip().split("\n")
        assert draft_truth_lines[0] == "fixture_id,draft_expected_calls,disagreements"


def test_duration_fallback_counted_in_model_summary_and_cost():
    """Finding 4 (integration): a fixture with blank manifest duration_s (like the real
    D01-D04 dev fixtures) must still contribute to RTF/cost via the transcript-derived
    fallback duration, and the fallback usage must be surfaced per model."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        out_root = tmpdir / "out"
        (out_root / "transcripts" / "whisper-1").mkdir(parents=True)

        manifest_rows = [
            {"fixture_id": "F01", "filename": "F01.wav", "status": "recorded",
             "vocabulary": "swish_brick", "duration_s": "30.0",
             "timing_ground_truth": "FALSE", "beep_interval_s": "", "expected_calls": ""},
            {"fixture_id": "D01", "filename": "dev/dev01.m4a", "status": "recorded",
             "vocabulary": "make_miss", "duration_s": "",
             "timing_ground_truth": "FALSE", "beep_interval_s": "", "expected_calls": ""},
        ]
        vocabs = {
            "swish_brick": {"swish": "make", "splash": "make", "brick": "miss", "break": "miss"},
            "make_miss": {"make": "make", "miss": "miss"},
        }

        f01 = {"model_id": "whisper-1", "fixture": "F01",
               "words": [{"word": "swish", "start": 5.0, "end": 5.4, "confidence": None}],
               "text": "swish", "runtime_s": 3.0, "peak_rss_mb": None, "prompt_used": True}
        d01 = {"model_id": "whisper-1", "fixture": "D01",
               "words": [{"word": "make", "start": 29.5, "end": 30.0, "confidence": None}],
               "text": "make", "runtime_s": 3.0, "peak_rss_mb": None, "prompt_used": True}
        (out_root / "transcripts" / "whisper-1" / "F01.json").write_text(json.dumps(f01))
        (out_root / "transcripts" / "whisper-1" / "D01.json").write_text(json.dumps(d01))
        (out_root / "skips.json").write_text(json.dumps([]))

        assemble_metrics(out_root=out_root, manifest_rows=manifest_rows, vocabs=vocabs,
                          vocab_default="swish_brick")

        metrics = json.loads((out_root / "metrics.json").read_text())
        summary = metrics["models"]["whisper-1"]

        # D01's duration_s is blank -> its 30.0s duration comes entirely from the
        # transcript's last-word end (29.5-30.0), so exactly 1 fixture used the fallback.
        assert summary["duration_fallback_fixtures"] == 1
        # total_minutes = 30.0/60 (F01, manifest) + 30.0/60 (D01, fallback) = 1.0 minute
        assert summary["cost_usd"] == pytest.approx(0.006)
        # rtf = 3.0/30.0 = 0.1 for both fixtures
        assert summary["rtf_mean"] == pytest.approx(0.1)
        assert summary["rtf_median"] == pytest.approx(0.1)


def test_n_fixtures_total_counts_only_recorded_rows_with_filename():
    """Finding 6: n_fixtures_total must reflect the eligible (recorded, has-audio)
    manifest rows -- the same criterion run_benchmark.py uses to pick what to
    transcribe -- not just fixtures that happen to have a transcript already."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        out_root = tmpdir / "out"
        (out_root / "transcripts" / "whisper-1").mkdir(parents=True)

        manifest_rows = [
            {"fixture_id": "F01", "filename": "F01.wav", "status": "recorded",
             "vocabulary": "swish_brick", "duration_s": "30.0",
             "timing_ground_truth": "FALSE", "beep_interval_s": "", "expected_calls": ""},
            {"fixture_id": "D01", "filename": "dev/dev01.m4a", "status": "recorded",
             "vocabulary": "make_miss", "duration_s": "",
             "timing_ground_truth": "FALSE", "beep_interval_s": "", "expected_calls": ""},
            # No "status" key at all -> defaults to "recorded" (matches hoops/fixtures.py
            # convention row.get("status", "recorded")); still eligible.
            {"fixture_id": "D02", "filename": "dev/dev02.m4a",
             "vocabulary": "make_miss", "duration_s": "",
             "timing_ground_truth": "FALSE", "beep_interval_s": "", "expected_calls": ""},
            # NOT_RECORDED placeholder row (like real F09/F10 in the manifest): no audio,
            # must not count toward the eligible total.
            {"fixture_id": "F09", "filename": "", "status": "NOT_RECORDED",
             "vocabulary": "swish_brick", "duration_s": "",
             "timing_ground_truth": "FALSE", "beep_interval_s": "", "expected_calls": ""},
        ]
        vocabs = {
            "swish_brick": {"swish": "make", "splash": "make", "brick": "miss", "break": "miss"},
            "make_miss": {"make": "make", "miss": "miss"},
        }
        f01 = {"model_id": "whisper-1", "fixture": "F01",
               "words": [{"word": "swish", "start": 5.0, "end": 5.4, "confidence": None}],
               "text": "swish", "runtime_s": 3.0, "peak_rss_mb": None, "prompt_used": True}
        (out_root / "transcripts" / "whisper-1" / "F01.json").write_text(json.dumps(f01))
        (out_root / "skips.json").write_text(json.dumps([]))

        assemble_metrics(out_root=out_root, manifest_rows=manifest_rows, vocabs=vocabs,
                          vocab_default="swish_brick")

        metrics = json.loads((out_root / "metrics.json").read_text())
        # F01, D01, D02 are recorded-with-filename; F09 (NOT_RECORDED, no filename) is not.
        assert metrics["n_fixtures_total"] == 3


def test_missing_skips_file_defaults_to_empty_list():
    """Finding 5: skips.json's real shape on disk is a list, not a dict -- the
    missing-file fallback must match that shape."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        out_root = tmpdir / "out"
        (out_root / "transcripts" / "model_a").mkdir(parents=True)

        manifest_rows = [
            {"fixture_id": "F01", "filename": "F01.wav", "status": "recorded",
             "vocabulary": "swish_brick", "duration_s": "30.0",
             "timing_ground_truth": "FALSE", "beep_interval_s": "", "expected_calls": ""},
        ]
        vocabs = {"swish_brick": {"swish": "make", "splash": "make", "brick": "miss", "break": "miss"}}
        f01 = {"model_id": "model_a", "fixture": "F01",
               "words": [{"word": "swish", "start": 5.0, "end": 5.4, "confidence": None}],
               "text": "swish", "runtime_s": 1.0, "peak_rss_mb": None, "prompt_used": False}
        (out_root / "transcripts" / "model_a" / "F01.json").write_text(json.dumps(f01))
        # Deliberately do NOT create out_root/skips.json.

        assemble_metrics(out_root=out_root, manifest_rows=manifest_rows, vocabs=vocabs,
                          vocab_default="swish_brick")

        metrics = json.loads((out_root / "metrics.json").read_text())
        assert metrics["skips"] == []
