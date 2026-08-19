"""acoustics:/fusion: config blocks parse, and defaults survive their absence."""
from pathlib import Path
import pytest
from hoops.config import load_config, DEFAULT_ACOUSTICS, DEFAULT_FUSION

MINIMAL = """\
timezone: America/Los_Angeles
inbox: /tmp/inbox
sessions_root: sessions
prefix: hoops
vocab_default: swish_brick
vocabularies:
  swish_brick: {make: [swish], miss: [brick]}
isolation: {low: 0.15, high: 0.4}
limits: {min_duration_s: 5, max_duration_s: 1200, min_gap_s: 1.5, max_gap_s: 120}
transcriber: {model: whisper-1}
llm: {model: claude-sonnet-5}
email: {from: a@b.c, to: a@b.c, smtp_host: h, smtp_port: 465}
"""

@pytest.mark.unit
def test_missing_blocks_fall_back_to_defaults(tmp_path):
    (tmp_path / "config.yaml").write_text(MINIMAL)
    cfg = load_config(tmp_path / "config.yaml")
    assert cfg.acoustics == DEFAULT_ACOUSTICS
    assert cfg.fusion == DEFAULT_FUSION

@pytest.mark.unit
def test_partial_block_merges_over_defaults(tmp_path):
    (tmp_path / "config.yaml").write_text(MINIMAL + "\nacoustics:\n  onset_delta: 0.3\n")
    cfg = load_config(tmp_path / "config.yaml")
    assert cfg.acoustics["onset_delta"] == 0.3
    assert cfg.acoustics["cluster_gap_s"] == DEFAULT_ACOUSTICS["cluster_gap_s"]

@pytest.mark.unit
def test_gudata_block_defaults_disabled(tmp_path):
    (tmp_path / "config.yaml").write_text(MINIMAL)
    cfg = load_config(tmp_path / "config.yaml")
    assert cfg.gudata == {"enabled": False}

@pytest.mark.unit
def test_gudata_block_parses(tmp_path):
    (tmp_path / "config.yaml").write_text(MINIMAL + "\ngudata:\n  enabled: true\n")
    cfg = load_config(tmp_path / "config.yaml")
    assert cfg.gudata["enabled"] is True

@pytest.mark.unit
def test_repo_configs_carry_explicit_blocks():
    # raw yaml, not load_config: cloud/config.cloud.yaml is a partial config
    import yaml
    root = Path(__file__).resolve().parents[1]
    for name in ("config.yaml", "cloud/config.cloud.yaml"):
        raw = yaml.safe_load((root / name).read_text())
        assert set(raw.get("acoustics") or {}) == set(DEFAULT_ACOUSTICS), name
        assert set(raw.get("fusion") or {}) == set(DEFAULT_FUSION), name
