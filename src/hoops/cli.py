import argparse

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hoops", description="Morning free-throw voice log")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("process", help="Process one audio file end to end")
    sp.add_argument("path")
    sp.add_argument("--no-email", dest="no_email", action="store_true")
    sp.add_argument("--vocab", default=None,
                    help="vocabulary name from config.yaml (default: vocab_default)")

    sa = sub.add_parser("process-all", help="Process a fixtures dir + gallery")
    sa.add_argument("fixtures_dir")
    sa.add_argument("--no-email", dest="no_email", action="store_true", default=True)

    sr = sub.add_parser("replay", help="Re-parse from stored transcript.json")
    g = sr.add_mutually_exclusive_group(required=False)
    g.add_argument("--all", action="store_true")
    g.add_argument("sid", nargs="?")

    spu = sub.add_parser("push", help="Push archived session(s) to GuData (idempotent)")
    gp = spu.add_mutually_exclusive_group(required=False)
    gp.add_argument("--all", action="store_true")
    gp.add_argument("sid", nargs="?")

    sub.add_parser("poll", help="One-shot inbox scan")
    sub.add_parser("score", help="Print the gate table from manifest.csv")

    st = sub.add_parser("transcribe-fixtures", help="Refresh committed fixture transcripts (paid)")
    st.add_argument("--only")
    return p

def main() -> int:
    import sys
    from pathlib import Path
    from dotenv import load_dotenv
    from .config import load_config
    from .fixtures import (run_all, read_manifest, transcript_cache_path, run_fixture,
                           fixture_out_dir)
    from .pipeline import process_file, replay_session
    from .session import find_session_dirs
    from .transcribe import WhisperApiTranscriber

    args = build_parser().parse_args()
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    cfg = load_config(Path(__file__).resolve().parents[2] / "config.yaml")
    transcriber = WhisperApiTranscriber(cfg.transcriber_model)

    if args.command == "process":
        if args.vocab and args.vocab not in cfg.vocabularies:
            print(f"unknown vocabulary '{args.vocab}' — available: "
                  f"{', '.join(sorted(cfg.vocabularies))}")
            return 2
        out = process_file(Path(args.path).expanduser(), cfg, transcriber,
                           email=not args.no_email, archive="copy", vocab_name=args.vocab)
        print(f"{out.sid}: {out.status}" + (f" — {out.session_dir}" if out.session_dir else ""))
        return 0 if out.status in ("ok", "duplicate") else 1

    if args.command == "process-all":
        entries = run_all(cfg, transcriber, Path(args.fixtures_dir).expanduser())
        bad = [e for e in entries if e["expected"] and e["expected"] != e["got"]]
        print(f"{len(entries)} fixtures processed, {len(bad)} mismatches — "
              f"open {cfg.repo_root / 'out' / 'index.html'}")
        return 0

    if args.command == "replay":
        if not args.all and not args.sid:
            print("replay: specify --all or a session id")
            return 2
        dirs = (find_session_dirs(cfg.sessions_root) if args.all
                else [d for d in find_session_dirs(cfg.sessions_root)
                      if d.name.endswith(args.sid)])
        for d in dirs:
            r = replay_session(d, cfg)
            print(f"{r.sid}: replayed ({len(r.rows)} calls, "
                  f"{'clean' if not r.flags else 'FLAGS: ' + '; '.join(r.flags)})")
        return 0

    if args.command == "push":
        from .gudata import backfill_session
        if not args.all and not args.sid:
            print("push: specify --all or a session id")
            return 2
        dirs = (find_session_dirs(cfg.sessions_root) if args.all
                else [d for d in find_session_dirs(cfg.sessions_root)
                      if d.name.endswith(args.sid)])
        if not dirs:
            print("push: no matching sessions (run pull_sessions to sync from R2 first)")
            return 2
        failures = 0
        for d in dirs:
            try:
                res = backfill_session(d, cfg.tz.key)
                print(f"{d.name}: pushed — session {res.get('session_id')}, "
                      f"{res.get('count')} observation(s)")
            except Exception as e:
                failures += 1
                print(f"{d.name}: FAILED — {e}")
        return 1 if failures else 0

    if args.command == "score":
        from .score import score_and_print
        return score_and_print(cfg)

    if args.command == "transcribe-fixtures":
        import shutil
        for row in read_manifest(cfg.repo_root / "fixtures" / "manifest.csv"):
            if not row.get("filename") or row.get("status", "recorded") != "recorded":
                continue
            if args.only and args.only not in row["filename"]:
                continue
            cache = transcript_cache_path(cfg.repo_root, row["filename"])
            cache.unlink(missing_ok=True)
            # Clear any stale out dir from a prior process-all/transcribe-fixtures run —
            # otherwise the I7 duplicate check in process_file skips transcription and
            # the stale transcript.json gets copied right back into the cache.
            shutil.rmtree(fixture_out_dir(cfg.repo_root, row["filename"]), ignore_errors=True)
            run_fixture(row, cfg, transcriber, cfg.repo_root / "out" / "fixtures")
            print(f"transcribed {row['filename']} -> {cache}")
        return 0

    if args.command == "poll":
        from .ingest import poll_once
        processed = poll_once(cfg, transcriber)
        print(f"poll: {len(processed)} file(s) processed")
        return 0
    return 2
