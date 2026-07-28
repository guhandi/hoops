import shutil
from dataclasses import dataclass, field
from pathlib import Path
from mutagen.mp4 import MP4
from . import PARSER_VERSION
from .config import Config
from .invariants import check_invariants
from .parse import parse_words
from .repair import attempt_repair
from .render import render_strip, render_report
from .session import (session_id_for, session_dir_for, sid_date_and_time,
                      write_transcript, write_shots_csv, write_session_json,
                      read_session_json, read_envelope)
from .stats import build_shot_rows, build_session_stats
from .transcribe import (make_envelope, words_from_envelope, envelope_duration,
                         vocab_prompt)

@dataclass
class Outcome:
    status: str
    sid: str
    session_dir: Path | None = None
    stats: dict | None = None
    rows: list = field(default_factory=list)
    flags: list = field(default_factory=list)

def _audio_duration(path: Path) -> float | None:
    try:
        return float(MP4(str(path)).info.length)
    except Exception:
        return None

def _reject(path: Path, cfg: Config, archive: str, sid: str, base: Path) -> Outcome:
    rej = base / "rejected"
    if archive != "none":
        rej.mkdir(exist_ok=True)
        (shutil.move if archive == "move" else shutil.copy)(str(path), str(rej / path.name))
    return Outcome(status="rejected", sid=sid)

def process_file(path: Path, cfg: Config, transcriber, *, email: bool,
                 out_root: Path | None = None, archive: str = "copy",
                 vocab_name: str | None = None, cached_env: dict | None = None,
                 repair_enabled: bool = True,
                 min_duration_override: float | None = None) -> Outcome:
    vocab = cfg.vocab(vocab_name)
    sid, sid_source = session_id_for(path, cfg.tz)
    root = out_root or cfg.sessions_root
    base = out_root.parent if out_root is not None else cfg.repo_root
    sdir = session_dir_for(root, sid)
    if sdir.exists():                                   # I7
        return Outcome(status="duplicate", sid=sid, session_dir=sdir)

    dur = _audio_duration(path)
    min_dur = min_duration_override or cfg.min_duration_s
    if dur is None or dur < min_dur:
        return _reject(path, cfg, archive, sid, base)

    if cached_env is not None:
        env = cached_env
    else:
        env = make_envelope(transcriber.transcribe(path, vocab_prompt(vocab)),
                            transcriber.model_id)
    sdir.mkdir(parents=True)
    write_transcript(sdir, env)                         # L2 persisted BEFORE parse

    words = words_from_envelope(env)
    parsed = parse_words(words, vocab, cfg.isolation_low, cfg.isolation_high)
    date_local, time_local = sid_date_and_time(sid)

    if not parsed.calls:
        nr = base / "needs_review"
        nr.mkdir(exist_ok=True)
        target = nr / sdir.name
        if target.exists():                              # idempotent: don't crash/nest
            n = 2
            while (nr / f"{sdir.name}__{n}").exists():
                n += 1
            target = nr / f"{sdir.name}__{n}"
        shutil.move(str(sdir), str(target))
        if archive == "move":
            shutil.move(str(path), str(target / "audio.m4a"))
        elif archive == "copy":
            shutil.copy(str(path), str(target / "audio.m4a"))
        if email:
            _email_needs_review(target, sid, cfg)
        return Outcome(status="needs_review", sid=sid, session_dir=target)

    rows = build_shot_rows(parsed.calls, sid, date_local)
    violations = check_invariants(rows, min_gap_s=cfg.min_gap_s,
                                  max_gap_s=cfg.max_gap_s, vocab=vocab)
    if violations and repair_enabled:
        repaired = attempt_repair(env, rows, violations, vocab, cfg.llm_model)
        if repaired:
            new_rows = build_shot_rows(repaired, sid, date_local)
            if not check_invariants(new_rows, min_gap_s=cfg.min_gap_s,
                                    max_gap_s=cfg.max_gap_s, vocab=vocab):
                rows, violations = new_rows, []

    stats = build_session_stats(rows, parsed, words, session_id=sid,
        session_date_local=date_local, start_time_local=time_local,
        session_len_s=envelope_duration(env), transcriber=env["model"],
        parser_version=PARSER_VERSION, profanity=cfg.profanity)
    flags = [f"{v.id}: {v.message}" for v in violations]
    if parsed.ambiguous:
        flags.append(f"{len(parsed.ambiguous)} ambiguous call-like token(s)")
    if dur > cfg.max_duration_s:
        flags.append(f"session audio {dur:.0f}s exceeds {cfg.max_duration_s:.0f}s — forgot to stop?")
    stats["invariants_passed"] = not violations
    stats["session_id_source"] = sid_source

    write_shots_csv(sdir, rows)
    write_session_json(sdir, stats)

    narrative = None
    if email:
        from .narrative import generate_narrative
        narrative = generate_narrative(stats, env, cfg.llm_model)
        if narrative:
            stats["quote_of_day"] = narrative.quote
            write_session_json(sdir, stats)

    render_strip(rows, sdir / "strip.png")
    render_report(stats, rows, narrative, flags, sdir / "report.html", img_src="strip.png")

    if archive == "move":
        shutil.move(str(path), str(sdir / "audio.m4a"))
    elif archive == "copy":
        shutil.copy(str(path), str(sdir / "audio.m4a"))

    if email:
        try:
            from .mailer import build_email, send
            send(build_email(stats, sdir, narrative, flags, cfg), cfg)
        except Exception:
            (sdir / "pending_email").touch()

    return Outcome(status="ok", sid=sid, session_dir=sdir, stats=stats,
                   rows=rows, flags=flags)

def _email_needs_review(sdir: Path, sid: str, cfg: Config) -> None:
    try:
        from email.message import EmailMessage
        from .mailer import send
        msg = EmailMessage()
        msg["From"], msg["To"] = cfg.email["from"], cfg.email["to"]
        msg["Subject"] = f"⚠️ 🏀 {sid} — zero calls detected, needs review"
        msg.set_content((sdir / "transcript.txt").read_text() or "(empty transcript)")
        send(msg, cfg)
    except Exception:
        (sdir / "pending_email").touch()

def replay_session(sdir: Path, cfg: Config, vocab_name: str | None = None) -> Outcome:
    env = read_envelope(sdir)
    vocab = cfg.vocab(vocab_name)
    sid = sdir.name.removeprefix("hoops__")
    date_local, time_local = sid_date_and_time(sid)
    words = words_from_envelope(env)
    parsed = parse_words(words, vocab, cfg.isolation_low, cfg.isolation_high)
    rows = build_shot_rows(parsed.calls, sid, date_local)
    violations = check_invariants(rows, min_gap_s=cfg.min_gap_s,
                                  max_gap_s=cfg.max_gap_s, vocab=vocab)
    stats = build_session_stats(rows, parsed, words, session_id=sid,
        session_date_local=date_local, start_time_local=time_local,
        session_len_s=envelope_duration(env), transcriber=env["model"],
        parser_version=PARSER_VERSION, profanity=cfg.profanity)
    stats["invariants_passed"] = not violations
    try:
        old = read_session_json(sdir)
        stats["quote_of_day"] = old.get("quote_of_day", "")
        if "session_id_source" in old:
            stats["session_id_source"] = old["session_id_source"]
    except FileNotFoundError:
        pass
    flags = [f"{v.id}: {v.message}" for v in violations]
    write_shots_csv(sdir, rows)
    write_session_json(sdir, stats)
    render_strip(rows, sdir / "strip.png")
    render_report(stats, rows, None, flags, sdir / "report.html", img_src="strip.png")
    return Outcome(status="ok", sid=sid, session_dir=sdir, stats=stats,
                   rows=rows, flags=flags)
