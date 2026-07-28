import pytest
from hoops.cli import build_parser

pytestmark = pytest.mark.unit

def test_parser_has_all_subcommands():
    p = build_parser()
    args = p.parse_args(["process", "some.m4a", "--no-email"])
    assert args.command == "process" and args.no_email is True
    for cmd, extra in [("process-all", ["fixtures"]), ("replay", []), ("poll", []),
                       ("score", []), ("transcribe-fixtures", [])]:
        assert p.parse_args([cmd, *extra]).command == cmd

def test_replay_flags():
    p = build_parser()
    assert p.parse_args(["replay", "--all"]).all is True
    assert p.parse_args(["replay", "20260727-061204"]).sid == "20260727-061204"

def test_process_accepts_vocab_flag():
    p = build_parser()
    args = p.parse_args(["process", "some.m4a", "--vocab", "make_miss"])
    assert args.vocab == "make_miss"
    assert p.parse_args(["process", "some.m4a"]).vocab is None
