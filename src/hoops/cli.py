import argparse

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hoops", description="Morning free-throw voice log")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("process", help="Process one audio file end to end")
    sp.add_argument("path")
    sp.add_argument("--no-email", dest="no_email", action="store_true")

    sa = sub.add_parser("process-all", help="Process a fixtures dir + gallery")
    sa.add_argument("fixtures_dir")
    sa.add_argument("--no-email", dest="no_email", action="store_true", default=True)

    sr = sub.add_parser("replay", help="Re-parse from stored transcript.json")
    g = sr.add_mutually_exclusive_group(required=False)
    g.add_argument("--all", action="store_true")
    g.add_argument("sid", nargs="?")

    sub.add_parser("poll", help="One-shot inbox scan")
    sub.add_parser("score", help="Print the gate table from manifest.csv")

    st = sub.add_parser("transcribe-fixtures", help="Refresh committed fixture transcripts (paid)")
    st.add_argument("--only")
    return p

def main() -> int:
    args = build_parser().parse_args()
    raise SystemExit(f"{args.command}: not implemented yet")
