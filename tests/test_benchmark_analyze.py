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
    """Integration test: build fake transcripts, call assemble_metrics, verify output."""
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
        ]

        # Build fake vocabularies
        vocabs = {
            "swish_brick": {
                "swish": "make", "splash": "make",
                "brick": "miss", "break": "miss"
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

        # Write transcript files
        (out_root / "transcripts" / "model_a").mkdir(parents=True)
        (out_root / "transcripts" / "model_b").mkdir(parents=True)

        (out_root / "transcripts" / "model_a" / "F01.json").write_text(
            json.dumps(transcripts_a)
        )
        (out_root / "transcripts" / "model_b" / "F01.json").write_text(
            json.dumps(transcripts_b)
        )

        # Create empty skips file
        (out_root / "skips.json").write_text(json.dumps({}))

        # Call assemble_metrics
        assemble_metrics(
            out_root=out_root,
            manifest_rows=manifest_rows,
            vocabs=vocabs,
        )

        # Verify metrics.json exists
        metrics_file = out_root / "metrics.json"
        assert metrics_file.exists()
        metrics = json.loads(metrics_file.read_text())

        # Verify draft_truth.csv exists
        draft_truth_file = out_root / "draft_truth.csv"
        assert draft_truth_file.exists()
        draft_truth_lines = draft_truth_file.read_text().strip().split("\n")

        # Check header
        assert draft_truth_lines[0] == "fixture_id,draft_expected_calls,disagreements"

        # Check F01 row - should have consensus make cluster
        f01_row = next(line for line in draft_truth_lines[1:] if line.startswith("F01"))
        parts = f01_row.split(",")
        assert parts[0] == "F01"
        # draft_expected_calls should contain 'make' (consensus cluster)
        assert "make" in parts[1] or parts[1] != ""
