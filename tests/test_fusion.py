"""Fusion pairing — all five brief cases + voided, on hand-built data.
Also enforces the core rule: branch modules never import each other."""
import json
from pathlib import Path
import pytest
from hoops.fusion import fuse, write_fusion

SRC = Path(__file__).resolve().parents[1] / "src" / "hoops"
P = dict(pair_min_s=0.5, pair_max_s=4.0)

def row(n, t, result="make", voided=False):
    return {"session_id": "s1", "session_date_local": "2026-08-01", "shot_num": n,
            "result": result, "t_call_s": t, "gap_s": None, "streak_after": 0,
            "voided": voided, "isolation_s": 1.0, "confidence": 1.0,
            "raw_token": "swish"}

def ev(t0, t1=None, n=1):
    t1 = t0 + 0.2 if t1 is None else t1
    return {"t_start": t0, "t_end": t1, "n_impacts": n,
            "impact_times": [t0], "burst_duration_s": round(t1 - t0, 3),
            "mean_centroid_hz": 3000.0, "max_peak_rms": 0.5,
            "mean_decay_ratio": 0.3, "impacts": []}

@pytest.mark.unit
def test_paired_call_gets_features_and_latency():
    out = fuse([row(1, 10.0)], [ev(8.5)], **P)
    s = out["shots"][0]
    assert s["pairing_status"] == "paired"
    assert s["t_impact_s"] == 8.5 and s["call_latency_s"] == 1.5
    assert s["mean_centroid_hz"] == 3000.0 and s["decay_ratio"] == 0.3
    assert out["summary"]["pairing_rate"] == 1.0

@pytest.mark.unit
def test_nearest_preceding_wins():
    out = fuse([row(1, 10.0)], [ev(6.5), ev(8.8)], **P)
    assert out["shots"][0]["t_impact_s"] == 8.8

@pytest.mark.unit
def test_no_candidate_is_impact_missing_voice_kept():
    out = fuse([row(1, 20.0, result="miss")], [ev(10.0)], **P)
    s = out["shots"][0]
    assert s["pairing_status"] == "impact_missing"
    assert s["result"] == "miss" and s["t_impact_s"] is None
    assert out["summary"]["n_impact_missing"] == 1

@pytest.mark.unit
def test_event_closer_than_pair_min_does_not_pair():
    # guards against the caller's own voice onset being taken as the impact
    out = fuse([row(1, 10.0)], [ev(9.7)], **P)
    assert out["shots"][0]["pairing_status"] == "impact_missing"

@pytest.mark.unit
def test_two_calls_one_event_flags_both():
    out = fuse([row(1, 10.0), row(2, 11.0)], [ev(8.5)], **P)
    a, b = out["shots"]
    assert a["pairing_status"] == "ambiguous" and a["t_impact_s"] == 8.5  # keeps data
    assert b["pairing_status"] == "ambiguous" and b["t_impact_s"] is None
    assert out["summary"]["n_paired"] == 0 and out["summary"]["n_ambiguous"] == 2

@pytest.mark.unit
def test_warmup_and_call_missing_events_kept():
    out = fuse([row(1, 10.0)], [ev(2.0), ev(8.5), ev(30.0)], **P)
    assert out["shots"][0]["t_impact_s"] == 8.5
    statuses = {e["t_start"]: e["pairing_status"] for e in out["extra_events"]}
    assert statuses == {2.0: "warmup", 30.0: "call_missing"}
    assert out["summary"]["n_warmup"] == 1 and out["summary"]["n_call_missing"] == 1

@pytest.mark.unit
def test_voided_rows_never_pair_and_free_the_event():
    out = fuse([row(1, 10.0, voided=True), row(2, 11.5)], [ev(9.0)], **P)
    a, b = out["shots"]
    assert a["pairing_status"] == "voided" and a["t_impact_s"] is None
    assert b["pairing_status"] == "paired" and b["t_impact_s"] == 9.0
    assert out["summary"]["n_calls"] == 1        # live calls only

@pytest.mark.unit
def test_gap_call_and_gap_impact():
    out = fuse([row(1, 10.0), row(2, 20.0), row(3, 30.0)],
               [ev(8.5), ev(18.0)], **P)
    s1, s2, s3 = out["shots"]
    assert s1["gap_call_s"] is None and s2["gap_call_s"] == 10.0
    assert s2["gap_impact_s"] == 9.5             # 18.0 - 8.5
    assert s3["pairing_status"] == "impact_missing" and s3["gap_impact_s"] is None

@pytest.mark.unit
def test_summary_median_latency():
    out = fuse([row(1, 10.0), row(2, 20.0)], [ev(8.5), ev(18.9)], **P)
    assert out["summary"]["median_latency_s"] == pytest.approx(1.3)
    assert out["summary"]["latencies_s"] == [1.1, 1.5]

@pytest.mark.unit
def test_write_fusion_none_events_returns_none(tmp_path):
    assert write_fusion(tmp_path, [row(1, 10.0)], None, P) is None
    assert not (tmp_path / "fusion.json").exists()

@pytest.mark.unit
def test_write_fusion_writes_sidecar_and_never_raises(tmp_path):
    out = write_fusion(tmp_path, [row(1, 10.0)], [ev(8.5)], P)
    assert json.loads((tmp_path / "fusion.json").read_text()) == out
    assert write_fusion(tmp_path, [row(1, 10.0)], [ev(8.5)], {}) is None  # bad params

@pytest.mark.unit
def test_branch_modules_never_import_each_other():
    """The core architectural rule, enforced on source text."""
    banned = {
        "acoustics.py": ["parse", "transcribe", "fusion"],
        "fusion.py": ["acoustics", "parse", "transcribe"],
        "parse.py": ["acoustics", "fusion"],
        "transcribe.py": ["acoustics", "fusion"],
    }
    for fname, mods in banned.items():
        src = (SRC / fname).read_text()
        for m in mods:
            assert f"from .{m}" not in src, f"{fname} imports {m}"
            assert f"from hoops.{m}" not in src, f"{fname} imports {m}"
            assert f"import {m}\n" not in src, f"{fname} imports {m}"
