"""Tests for benchmarks/report.py against the REAL metrics.json schema written by
benchmarks/analyze.py::assemble_metrics (see tests/test_benchmark_analyze.py for the
ground-truth shape). A prior version of this file validated an invented schema
(boundary/rtf/peak_rss_mb/coverage/detection nesting, models[model]["detections"],
per-model isolation, raw real/bait lists, a metrics["draft_truth"] key, a per-detection
"consensus" flag) that analyze.py never produces. That mismatch is exactly what let
report.py drift from reality, so this file is now built against fields analyze.py
actually writes, plus an integration test that runs assemble_metrics for real.
"""
import csv
import json
import tempfile
from pathlib import Path

import pytest

from benchmarks.analyze import assemble_metrics
from benchmarks.report import render

pytestmark = pytest.mark.unit

METRICS = {
    "models": {
        "model_a": {
            "runtime_mean": 0.5, "runtime_min": 0.4, "runtime_max": 0.6,
            "rtf_mean": 0.021, "rtf_median": 0.02,
            "peak_rss_mean": 105.0, "peak_rss_max": 120.0,
            "cost_usd": 0.012,
            "detections_found": 9, "detections_matched": 9, "detections_extra": 0,
        },
        "model_b": {
            "runtime_mean": 0.55, "runtime_min": 0.45, "runtime_max": 0.65,
            "rtf_mean": 0.025, "rtf_median": 0.024,
            "peak_rss_mean": 110.0, "peak_rss_max": 130.0,
            "detections_found": 6, "detections_matched": 5, "detections_extra": 1,
        },
    },
    "fixtures": {
        "F01": {
            "detections_by_model": {
                "model_a": [{"canonical": "make", "raw": "swish", "start": 5.0, "end": 5.4,
                             "mid": 5.2, "isolation": 4.4}],
                "model_b": [{"canonical": "make", "raw": "swish", "start": 5.1, "end": 5.5,
                             "mid": 5.3, "isolation": 4.3}],
            },
            "clusters": [
                {"canonical": "make", "mid": 5.25,
                 "models": {
                     "model_a": {"canonical": "make", "raw": "swish", "start": 5.0, "end": 5.4,
                                 "mid": 5.2, "isolation": 4.4},
                     "model_b": {"canonical": "make", "raw": "swish", "start": 5.1, "end": 5.5,
                                 "mid": 5.3, "isolation": 4.3},
                 },
                 "consensus": True},
            ],
            "accuracy_mode": "consensus",
            "per_model_accuracy": {"model_a": 1.0, "model_b": 1.0},
            "gap_stats": {},
        },
        "F03": {
            "detections_by_model": {
                "model_a": [{"canonical": "make", "raw": "make", "start": 1.0, "end": 1.3,
                             "mid": 1.15, "isolation": 5.0}],
            },
            "clusters": [],
            "accuracy_mode": "expected",
            "per_model_accuracy": {"model_a": 1.0},
            "gap_stats": {},
        },
        "F06": {
            "detections_by_model": {
                "model_a": [{"canonical": "make", "raw": "swish", "start": 5.0, "end": 5.4,
                             "mid": 5.2, "isolation": 9.7}],
            },
            "clusters": [],
            "accuracy_mode": "consensus",
            "per_model_accuracy": {"model_a": 1.0},
            "gap_stats": {"model_a": {"mean": 0.15, "median": 0.1, "p95": 0.3, "max": 0.3, "n_gaps": 3}},
        },
    },
    "isolation": {"threshold": 2.4, "margin": 4.6, "real_below": 0, "bait_above": 0},
    "agreement": {"model_a|model_b": 0.1},
    "skips": [{"model": "crisper-whisper", "fixture": "*", "reason": "gated model"}],
    "silence": {"status": "pending F10"},
    "load_errors": [],
    "unknown_vocab": [],
}

DRAFT_TRUTH_ROWS = [
    {"fixture_id": "F01", "draft_expected_calls": "make", "disagreements": ""},
    {"fixture_id": "F02", "draft_expected_calls": "make miss",
     "disagreements": "make@10.0 found by 1/2"},
]


def test_render_self_contained_html():
    html_out = render(METRICS, DRAFT_TRUTH_ROWS)
    assert html_out.startswith("<!doctype html>")
    for marker in ["Summary", "F01", "F03", "F06", "Draft ground truth", "pending F10",
                   "crisper-whisper", "model_a", "model_b"]:
        assert marker in html_out
    low = html_out.lower()
    assert "<svg" in low and "cdn" not in low
    assert 'src="http' not in low and 'href="http' not in low


def test_summary_table_uses_real_fields_not_placeholders():
    html_out = render(METRICS, DRAFT_TRUTH_ROWS)
    assert "0.021" in html_out  # model_a rtf_mean
    assert "105.0" in html_out  # model_a peak_rss_mean
    assert "Matched*" in html_out  # header notes the found/matched/extra adaptation


def test_best_cell_highlighting():
    html_out = render(METRICS, DRAFT_TRUTH_ROWS)
    assert 'class="best"' in html_out
    # model_a has more detections_found (9 > 6) so its cell should carry the class
    assert '<td class="best">9</td>' in html_out


def test_isolation_section_renders_threshold_and_margin():
    html_out = render(METRICS, DRAFT_TRUTH_ROWS)
    assert "threshold 2.400s" in html_out
    assert "margin 4.600s" in html_out


def test_isolation_guard_for_empty_dict():
    metrics = {**METRICS, "isolation": {}}
    html_out = render(metrics, DRAFT_TRUTH_ROWS)
    assert "No isolation split available" in html_out


def test_truth_row_only_for_mode_a_fixtures():
    html_out = render(METRICS, DRAFT_TRUTH_ROWS)
    assert "Truth (Mode A labeled)" in html_out
    # Only F03 has accuracy_mode == "expected"; F01/F06 are "consensus" and must not
    # get a fabricated Truth row.
    assert html_out.count("Truth (Mode A labeled)") == 1


def test_draft_truth_no_double_escaping():
    rows = [{"fixture_id": "F01", "draft_expected_calls": "make & miss", "disagreements": ""}]
    html_out = render(METRICS, rows)
    assert "make &amp; miss" in html_out
    assert "&amp;amp;" not in html_out


def test_draft_truth_disagreement_gets_warning_line():
    html_out = render(METRICS, DRAFT_TRUTH_ROWS)
    assert "⚠ make@10.0 found by 1/2" in html_out


def test_render_without_draft_truth_rows_defaults_to_empty():
    html_out = render(METRICS)
    assert "No draft ground truth available" in html_out


def test_consensus_derived_from_clusters_not_a_detection_flag():
    # F01's single detection for each model sits inside the one consensus cluster,
    # so both should render as in-consensus (✓) in the per-fixture detail table.
    html_out = render(METRICS, DRAFT_TRUTH_ROWS)
    assert "✓" in html_out


def test_assemble_metrics_integration_feeds_report():
    """Contract-lock: build fake transcripts, run the REAL assemble_metrics, feed its
    actual output (+ the draft_truth.csv it writes) into render(), and assert real
    content survives end to end. This is what should catch schema drift between
    analyze.py and report.py in the future."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        out_root = tmpdir / "out"
        out_root.mkdir(parents=True)

        manifest_rows = [
            {"fixture_id": "F01", "vocabulary": "swish_brick", "duration_s": "30.0",
             "timing_ground_truth": "FALSE", "beep_interval_s": "", "expected_calls": ""},
            {"fixture_id": "F02", "vocabulary": "swish_brick", "duration_s": "20.0",
             "timing_ground_truth": "FALSE", "beep_interval_s": "", "expected_calls": ""},
        ]
        vocabs = {"swish_brick": {"swish": "make", "splash": "make",
                                   "brick": "miss", "break": "miss"}}

        f01_a = {"model_id": "model_a", "fixture": "F01",
                  "words": [{"word": "swish", "start": 5.0, "end": 5.4, "confidence": None}],
                  "text": "swish", "runtime_s": 0.5, "peak_rss_mb": 100.0, "prompt_used": False}
        f01_b = {"model_id": "model_b", "fixture": "F01",
                  "words": [{"word": "swish", "start": 5.1, "end": 5.5, "confidence": None}],
                  "text": "swish", "runtime_s": 0.6, "peak_rss_mb": 110.0, "prompt_used": False}
        # F02: model_b hallucinates an extra "splash" wedged next to a filler word so it
        # has low isolation, giving recommend_threshold a real (non-empty) bait sample.
        f02_a = {"model_id": "model_a", "fixture": "F02",
                  "words": [{"word": "swish", "start": 3.0, "end": 3.4, "confidence": None},
                            {"word": "brick", "start": 15.0, "end": 15.4, "confidence": None}],
                  "text": "swish brick", "runtime_s": 0.4, "peak_rss_mb": 105.0, "prompt_used": False}
        f02_b = {"model_id": "model_b", "fixture": "F02",
                  "words": [{"word": "swish", "start": 3.1, "end": 3.5, "confidence": None},
                            {"word": "uh", "start": 9.8, "end": 9.9, "confidence": None},
                            {"word": "splash", "start": 10.0, "end": 10.4, "confidence": None},
                            {"word": "brick", "start": 15.1, "end": 15.5, "confidence": None}],
                  "text": "swish uh splash brick", "runtime_s": 0.45, "peak_rss_mb": 108.0,
                  "prompt_used": False}

        for d in ["model_a", "model_b"]:
            (out_root / "transcripts" / d).mkdir(parents=True)
        (out_root / "transcripts" / "model_a" / "F01.json").write_text(json.dumps(f01_a))
        (out_root / "transcripts" / "model_b" / "F01.json").write_text(json.dumps(f01_b))
        (out_root / "transcripts" / "model_a" / "F02.json").write_text(json.dumps(f02_a))
        (out_root / "transcripts" / "model_b" / "F02.json").write_text(json.dumps(f02_b))
        (out_root / "skips.json").write_text(json.dumps(
            [{"model": "crisper-whisper", "fixture": "*", "reason": "gated"}]))

        assemble_metrics(out_root=out_root, manifest_rows=manifest_rows, vocabs=vocabs,
                          vocab_default="swish_brick")

        metrics = json.loads((out_root / "metrics.json").read_text())
        with (out_root / "draft_truth.csv").open(newline="") as f:
            draft_truth_rows = list(csv.DictReader(f))

        html_out = render(metrics, draft_truth_rows)

        assert html_out.startswith("<!doctype html>")
        assert "model_a" in html_out and "model_b" in html_out
        assert "<circle" in html_out  # detection circles in the timeline SVG
        assert "threshold" in html_out and "margin" in html_out  # isolation section
        assert "F01" in html_out and "F02" in html_out  # draft-truth pre block has fixture rows
        assert "crisper-whisper" in html_out  # skips footer
        low = html_out.lower()
        assert "cdn" not in low and 'src="http' not in low and 'href="http' not in low
