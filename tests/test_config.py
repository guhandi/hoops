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
    assert cfg.email["from"] == "guhandiji@gmail.com"
