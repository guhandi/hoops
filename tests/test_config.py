import pytest
from pathlib import Path
from hoops.config import load_config

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[1]

def test_load_real_config():
    cfg = load_config(REPO / "config.yaml")
    assert cfg.vocab().surface_to_canonical == {
        "swish": "make", "splash": "make", "make": "make",
        "brick": "miss", "break": "miss", "miss": "miss",
    }
    assert cfg.isolation_low == 0.15 and cfg.isolation_high == 0.4
    assert cfg.min_gap_s == 1.5 and cfg.max_gap_s == 120
    assert cfg.inbox.is_absolute()          # ~ expanded
    assert cfg.sessions_root == REPO / "sessions"
    assert cfg.email["smtp_port"] == 465
    assert str(cfg.tz)                       # valid zoneinfo

def test_named_vocab_lookup():
    cfg = load_config(REPO / "config.yaml")
    assert cfg.vocab("swish_brick").name == "swish_brick"
    assert cfg.vocab("make_miss").surface_to_canonical == {"make": "make", "miss": "miss"}
    with pytest.raises(KeyError):
        cfg.vocab("default")

def test_gmail_address_env_overrides_from_and_to(monkeypatch):
    monkeypatch.setenv("GMAIL_ADDRESS", "robot@example.com")
    cfg = load_config(REPO / "config.yaml")
    assert cfg.email["from"] == "robot@example.com"
    assert cfg.email["to"] == "robot@example.com"
    assert cfg.email["smtp_host"] == "smtp.gmail.com"

def test_no_gmail_address_env_keeps_yaml_values(monkeypatch):
    monkeypatch.delenv("GMAIL_ADDRESS", raising=False)
    cfg = load_config(REPO / "config.yaml")
    assert cfg.email["from"] == "you@example.com"
    assert cfg.email["to"] == "you@example.com"

def test_gap_repair_defaults_when_absent(tmp_path):
    # a config.yaml with no transcriber.language / gap_repair keys
    src = (REPO / "config.yaml").read_text()
    stripped = "\n".join(l for l in src.splitlines()
                         if not l.strip().startswith(("language:", "gap_repair:",
                                                      "enabled: true", "trigger_gap_s:",
                                                      "pad_s:", "max_spans:")))
    (tmp_path / "config.yaml").write_text(stripped)
    c = load_config(tmp_path / "config.yaml")
    assert c.transcriber_language == "en"
    assert c.gap_repair == {"enabled": False, "trigger_gap_s": 10.0,
                            "pad_s": 2.0, "max_spans": 8}

def test_gap_repair_from_repo_config():
    c = load_config(REPO / "config.yaml")
    assert c.transcriber_language == "en"
    assert c.gap_repair["enabled"] is True
    assert c.gap_repair["trigger_gap_s"] == 10.0
