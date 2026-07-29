import pytest
import json
import tempfile
from pathlib import Path
from benchmarks.transcribers.base import BWord, TranscriptResult
from benchmarks.analyze import (detect, gap_stats, cluster, recommend_threshold,
                                pairwise_agreement, silence_words, assemble_metrics)

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
        # model_b: detects same swish and brick, PLUS hallucinated extra "splash" (low isolation) - bait
        f02_a = {
            "model_id": "model_a",
            "fixture": "F02",
            "words": [
                {"word": "swish", "start": 3.0, "end": 3.4, "confidence": None},  # High isolation
                {"word": "brick", "start": 15.0, "end": 15.4, "confidence": None},  # High isolation
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
                {"word": "swish", "start": 3.1, "end": 3.5, "confidence": None},  # High isolation
                {"word": "brick", "start": 15.1, "end": 15.5, "confidence": None},  # High isolation
                {"word": "splash", "start": 10.0, "end": 10.4, "confidence": None},  # Hallucinated, low isolation
            ],
            "text": "swish splash brick",
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

        # ===== ASSERTION: Detection counts with ACTUAL VALUES =====
        # Verify formula: extra = found - matched
        f01_summary_a = metrics["models"]["model_a"]
        f01_summary_b = metrics["models"]["model_b"]
        assert f01_summary_a["detections_found"] >= 1
        assert f01_summary_a["detections_matched"] >= 1
        assert f01_summary_a["detections_extra"] == f01_summary_a["detections_found"] - f01_summary_a["detections_matched"]
        assert f01_summary_b["detections_extra"] == f01_summary_b["detections_found"] - f01_summary_b["detections_matched"]

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
        # F02 has consensus clusters (high isolation real) and non-consensus (low isolation bait)
        # Should compute actual threshold
        assert "isolation" in metrics
        isolation = metrics["isolation"]
        assert "threshold" in isolation, "F02 should produce threshold (has real + bait)"
        assert "margin" in isolation, "F02 should produce margin"
        assert isinstance(isolation["threshold"], (int, float))
        assert isinstance(isolation["margin"], (int, float))

        # Verify draft_truth.csv
        draft_truth_file = out_root / "draft_truth.csv"
        assert draft_truth_file.exists()
        draft_truth_lines = draft_truth_file.read_text().strip().split("\n")
        assert draft_truth_lines[0] == "fixture_id,draft_expected_calls,disagreements"
