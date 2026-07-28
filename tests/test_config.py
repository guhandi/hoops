import pytest
from pathlib import Path
from hoops.config import load_config

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[1]

def test_load_real_config():
    cfg = load_config(REPO / "config.yaml")
    assert cfg.vocab().surface_to_canonical == {
        "make": "make", "splash": "make", "miss": "miss", "brick": "miss"}
    assert cfg.isolation_low == 0.15 and cfg.isolation_high == 0.4
    assert cfg.min_gap_s == 1.5 and cfg.max_gap_s == 120
    assert cfg.inbox.is_absolute()          # ~ expanded
    assert cfg.sessions_root == REPO / "sessions"
    assert cfg.email["smtp_port"] == 465
    assert str(cfg.tz)                       # valid zoneinfo

def test_named_vocab_lookup():
    cfg = load_config(REPO / "config.yaml")
    assert cfg.vocab("default").name == "default"
    with pytest.raises(KeyError):
        cfg.vocab("nope")
