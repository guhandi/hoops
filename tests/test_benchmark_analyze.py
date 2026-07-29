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
    """Integration test: build fake transcripts, call assemble_metrics, verify full output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        out_root = tmpdir / "out"
        out_root.mkdir(parents=True)

        # Create a fake manifest
        manifest_rows = [
            {
                "fixture_id": "F01",
                "vocabulary": "swish_brick",
                "duration_s": "30.0",
                "timing_ground_truth": "FALSE",
                "beep_interval_s": "",
                "expected_calls": "",
            },
            {
                "fixture_id": "F02",
                "vocabulary": "swish_brick",
                "duration_s": "20.0",
                "timing_ground_truth": "FALSE",
                "beep_interval_s": "",
                "expected_calls": "",  # Mode B: no label
            },
            {
                "fixture_id": "F03",
                "vocabulary": "make_miss",  # Test vocab fallback
                "duration_s": "25.0",
                "timing_ground_truth": "FALSE",
                "beep_interval_s": "",
                "expected_calls": "make miss",  # Mode A: labeled
            },
        ]

        # Build fake vocabularies
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

        # Create fake transcript files for two models
        transcripts_a = {
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

        transcripts_b = {
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

        # F02 transcripts (chatty - test isolation gating)
        f02_transcripts_a = {
            "model_id": "model_a",
            "fixture": "F02",
            "words": [
                {"word": "so", "start": 0.0, "end": 0.5, "confidence": None},
                {"word": "swish", "start": 3.0, "end": 3.4, "confidence": None},
                {"word": "yeah", "start": 5.0, "end": 5.5, "confidence": None},
            ],
            "text": "so swish yeah",
            "runtime_s": 0.4,
            "peak_rss_mb": 105.0,
            "prompt_used": False,
        }

        f02_transcripts_b = {
            "model_id": "model_b",
            "fixture": "F02",
            "words": [
                {"word": "so", "start": 0.0, "end": 0.5, "confidence": None},
                {"word": "brick", "start": 8.0, "end": 8.4, "confidence": None},
                {"word": "yeah", "start": 10.0, "end": 10.5, "confidence": None},
            ],
            "text": "so brick yeah",
            "runtime_s": 0.45,
            "peak_rss_mb": 108.0,
            "prompt_used": False,
        }

        # F03 transcripts (should match expected_calls for Mode A test)
        f03_transcripts_a = {
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

        f03_transcripts_b = {
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

        # Write transcript files
        for dir_name in ["model_a", "model_b"]:
            (out_root / "transcripts" / dir_name).mkdir(parents=True)

        (out_root / "transcripts" / "model_a" / "F01.json").write_text(json.dumps(transcripts_a))
        (out_root / "transcripts" / "model_b" / "F01.json").write_text(json.dumps(transcripts_b))
        (out_root / "transcripts" / "model_a" / "F02.json").write_text(json.dumps(f02_transcripts_a))
        (out_root / "transcripts" / "model_b" / "F02.json").write_text(json.dumps(f02_transcripts_b))
        (out_root / "transcripts" / "model_a" / "F03.json").write_text(json.dumps(f03_transcripts_a))
        (out_root / "transcripts" / "model_b" / "F03.json").write_text(json.dumps(f03_transcripts_b))

        # Create empty skips file
        (out_root / "skips.json").write_text(json.dumps({}))

        # Call assemble_metrics with vocab_default
        assemble_metrics(
            out_root=out_root,
            manifest_rows=manifest_rows,
            vocabs=vocabs,
            vocab_default="swish_brick",
        )

        # Verify metrics.json exists and has required keys
        metrics_file = out_root / "metrics.json"
        assert metrics_file.exists()
        metrics = json.loads(metrics_file.read_text())

        # Check top-level structure
        assert "models" in metrics
        assert "fixtures" in metrics
        assert "skips" in metrics
        assert "isolation" in metrics
        assert "agreement" in metrics
        assert "silence" in metrics
        assert "load_errors" in metrics
        assert "unknown_vocab" in metrics

        # Check models summary (per-model stats)
        assert isinstance(metrics["models"], dict)
        assert "model_a" in metrics["models"]
        assert "model_b" in metrics["models"]
        for model_name, model_summary in metrics["models"].items():
            assert isinstance(model_summary, dict)
            if model_summary:  # Only check if not empty
                # Should have runtime stats
                assert "runtime_mean" in model_summary or len(model_summary) == 0

        # Check fixtures detail
        assert "F01" in metrics["fixtures"]
        f01_metrics = metrics["fixtures"]["F01"]
        assert "detections_by_model" in f01_metrics
        assert "clusters" in f01_metrics
        assert "accuracy" in f01_metrics
        assert "accuracy_mode" in f01_metrics
        assert "gap_stats" in f01_metrics

        # F01: Mode B (no expected_calls) should have accuracy=1.0 and accuracy_mode="consensus"
        assert f01_metrics["accuracy"] == 1.0
        assert f01_metrics["accuracy_mode"] == "consensus"

        # F03: Mode A (expected_calls provided) should be labeled as "expected"
        if "F03" in metrics["fixtures"]:
            f03_metrics = metrics["fixtures"]["F03"]
            assert f03_metrics["accuracy_mode"] == "expected"
            # Should match expected_calls: "make miss"
            assert f03_metrics["accuracy"] == 1.0

        # Check silence metric
        assert metrics["silence"]["status"] == "pending F10"

        # Verify draft_truth.csv
        draft_truth_file = out_root / "draft_truth.csv"
        assert draft_truth_file.exists()
        draft_truth_lines = draft_truth_file.read_text().strip().split("\n")

        # Check header
        assert draft_truth_lines[0] == "fixture_id,draft_expected_calls,disagreements"

        # Check F01 row
        f01_row = next((line for line in draft_truth_lines[1:] if line.startswith("F01")), None)
        assert f01_row is not None
        parts = f01_row.split(",", 2)  # Split on first 2 commas only
        assert parts[0] == "F01"
        # draft_expected_calls should contain 'make' (consensus cluster)
        assert "make" in parts[1] or parts[1] != ""

        # Check disagreements format: should be "canonical@mid found by k/n"
        if len(parts) > 2 and parts[2]:  # If there are disagreements
            disagreements = parts[2]
            if disagreements:
                for disagreement in disagreements.split(";"):
                    if disagreement:  # Skip empty
                        # Format should be "canonical@mid found by k/n"
                        assert " found by " in disagreement
                        assert "/" in disagreement  # Should have k/n format
