import sys
from types import SimpleNamespace

import pytest
from hoops.cli import build_parser

pytestmark = pytest.mark.unit

def test_parser_has_all_subcommands():
    p = build_parser()
    args = p.parse_args(["process", "some.m4a", "--no-email"])
    assert args.command == "process" and args.no_email is True
    for cmd, extra in [("process-all", ["fixtures"]), ("replay", []), ("poll", []),
                       ("score", []), ("transcribe-fixtures", []), ("push", ["--all"]),
                       ("retranscribe", ["--all"])]:
        assert p.parse_args([cmd, *extra]).command == cmd

def test_replay_flags():
    p = build_parser()
    assert p.parse_args(["replay", "--all"]).all is True
    assert p.parse_args(["replay", "20260727-061204"]).sid == "20260727-061204"

def test_push_parser_flags():
    p = build_parser()
    assert p.parse_args(["push", "--all"]).all is True
    assert p.parse_args(["push", "20260728-061204"]).sid == "20260728-061204"

def test_retranscribe_parser_flags():
    p = build_parser()
    assert p.parse_args(["retranscribe", "--all"]).all is True
    args = p.parse_args(["retranscribe", "20260819-131500", "--email"])
    assert args.sid == "20260819-131500" and args.email is True

def test_process_accepts_vocab_flag():
    p = build_parser()
    args = p.parse_args(["process", "some.m4a", "--vocab", "make_miss"])
    assert args.vocab == "make_miss"
    assert p.parse_args(["process", "some.m4a"]).vocab is None

def test_main_loads_dotenv_before_config(monkeypatch):
    """Regression for the pending_email bug: load_config applies the
    GMAIL_ADDRESS env override at load time, so .env must be loaded
    BEFORE load_config runs, or the override never fires in a real
    CLI invocation (main() previously called load_config first)."""
    import dotenv
    import hoops.config as config_mod
    import hoops.score as score_mod

    order = []

    def fake_load_dotenv(*a, **k):
        order.append("dotenv")

    fake_cfg = SimpleNamespace(transcriber_model="whisper-1", transcriber_language="en")

    def fake_load_config(*a, **k):
        order.append("config")
        return fake_cfg

    def fake_score_and_print(cfg):
        order.append("score_and_print")
        return 0

    monkeypatch.setattr(dotenv, "load_dotenv", fake_load_dotenv)
    monkeypatch.setattr(config_mod, "load_config", fake_load_config)
    monkeypatch.setattr(score_mod, "score_and_print", fake_score_and_print)
    monkeypatch.setattr(sys, "argv", ["hoops", "score"])

    from hoops.cli import main
    rc = main()

    assert order == ["dotenv", "config", "score_and_print"]
    assert rc == 0
