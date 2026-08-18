import json
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path
from mutagen.mp4 import MP4
from . import PARSER_VERSION
from .config import Config, Vocabulary
from .acoustics import write_acoustics
from .fusion import write_fusion
from .gudata import push_stage
from .invariants import check_invariants
from .parse import parse_words
from .repair import attempt_repair
from .render import render_strip, Narrative
from .report_html import render_interactive_report
from .session import (session_id_for, session_dir_for, sid_date_and_time,
                      write_transcript, write_shots_csv, write_session_json,
                      read_session_json, read_envelope)
from .stats import build_shot_rows, build_session_stats
from .transcribe import (make_envelope, words_from_envelope, envelope_duration,
                         vocab_prompt)

class SidecarError(ValueError):
    pass

def _validate_vocab_map(vm) -> None:
    """Spec: 'never guess'. A sidecar vocab_map must be unambiguous — reject
    anything that would silently produce a nonsense canonical key or a
    per-character surface mapping (e.g. a string where a list was expected)."""
    if not isinstance(vm, dict):
        raise SidecarError("vocab_map must be a JSON object mapping "
                            "'make'/'miss' to lists of surface forms")
    keys = set(vm.keys())
    required = {"make", "miss"}
    if keys != required:
        parts = []
        missing = required - keys
        extra = keys - required
        if missing:
            parts.append(f"missing {', '.join(sorted(missing))}")
        if extra:
            parts.append(f"unknown key(s) {', '.join(sorted(extra))}")
        raise SidecarError("vocab_map must have exactly the keys 'make' and "
                           f"'miss' ({'; '.join(parts)})")
    for canonical, surfaces in vm.items():
        if not isinstance(surfaces, list) or not surfaces:
            raise SidecarError(f"vocab_map[{canonical!r}] must be a non-empty "
                               "list of surface-form strings")
        for s in surfaces:
            if not isinstance(s, str) or not s:
                raise SidecarError(f"vocab_map[{canonical!r}] has a non-string "
                                   f"or empty surface form: {s!r}")

def _resolve_vocab(path: Path, cfg: Config, vocab_name: str | None):
    """Returns (vocab, sidecar_path | None). Raises SidecarError on a bad sidecar."""
    if vocab_name:
        return cfg.vocab(vocab_name), None
    sc = path.with_suffix(".json")
    if not sc.exists():
        return cfg.vocab(None), None
    try:
        data = json.loads(sc.read_text())
        if not isinstance(data, dict):
            raise SidecarError("sidecar is not a JSON object")
        if "vocabulary" in data:
            try:
                return cfg.vocab(str(data["vocabulary"])), sc
            except KeyError:
                raise SidecarError(f"unknown vocabulary {data['vocabulary']!r} — "
                                   f"available: {', '.join(sorted(cfg.vocabularies))}")
        if "vocab_map" in data:
            _validate_vocab_map(data["vocab_map"])
            return Vocabulary.from_dict("sidecar", data["vocab_map"]), sc
        raise SidecarError("sidecar needs a 'vocabulary' or 'vocab_map' key")
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as e:
        raise e if isinstance(e, SidecarError) else SidecarError(f"unreadable sidecar: {e}")

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
    sid, sid_source = session_id_for(path, cfg.tz)
    root = out_root or cfg.sessions_root
    base = out_root.parent if out_root is not None else cfg.repo_root
    try:
        vocab, sidecar = _resolve_vocab(path, cfg, vocab_name)
    except SidecarError as e:
        nr = base / "needs_review"
        nr.mkdir(exist_ok=True)
        if archive != "none":
            op = shutil.move if archive == "move" else shutil.copy
            op(str(path), str(nr / path.name))
            sc = path.with_suffix(".json")
            if sc.exists():
                op(str(sc), str(nr / sc.name))
        return Outcome(status="needs_review", sid=sid, flags=[f"sidecar: {e}"])
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
    stats["vocab_name"] = vocab.name
    stats["vocab_map"] = vocab.surface_to_canonical

    acoustics = write_acoustics(sdir, path if path.exists() else None, cfg.acoustics)
    fused = write_fusion(sdir, rows, acoustics["events"] if acoustics else None,
                         cfg.fusion)
    if fused is not None:
        stats["uncorroborated_calls"] = fused["summary"]["n_impact_missing"]

    write_shots_csv(sdir, rows)
    write_session_json(sdir, stats)

    gud_result, gud_err = push_stage(cfg, stats, rows, sdir.name)
    if gud_result is not None:
        (sdir / "gudata_push.json").write_text(json.dumps(gud_result, indent=2))
    if gud_err:
        flags.append(f"gudata push failed: {gud_err}")

    narrative = None
    if email:
        from .narrative import generate_narrative
        narrative = generate_narrative(stats, env, cfg.llm_model)
        if narrative:
            stats["quote_of_day"] = narrative.quote
            write_session_json(sdir, stats)
            (sdir / "narrative.json").write_text(json.dumps(asdict(narrative), indent=2))

    if archive == "move":
        shutil.move(str(path), str(sdir / "audio.m4a"))
    elif archive == "copy":
        shutil.copy(str(path), str(sdir / "audio.m4a"))
    if archive in ("move", "copy") and sidecar is not None and sidecar.exists():
        (shutil.move if archive == "move" else shutil.copy)(str(sidecar), str(sdir / "vocab.json"))

    render_strip(rows, sdir / "strip.png")
    audio_path = sdir / "audio.m4a"
    if not audio_path.exists():                     # archive="none" leaves audio in place
        audio_path = path if path.exists() else None
    (sdir / "report.html").write_text(render_interactive_report(
        stats, rows, narrative, flags, words, audio_path,
        acoustics=acoustics, fusion=fused))

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
    try:
        old = read_session_json(sdir)
    except FileNotFoundError:
        old = {}
    narrative = None
    nfile = sdir / "narrative.json"
    if nfile.exists():
        try:
            narrative = Narrative(**json.loads(nfile.read_text()))
        except (TypeError, ValueError):
            narrative = None
    if vocab_name:
        vocab = cfg.vocab(vocab_name)
    elif old.get("vocab_map"):
        vocab = Vocabulary(name=old.get("vocab_name", "persisted"),
                           surface_to_canonical=old["vocab_map"])
    else:
        vocab = cfg.vocab(None)
    sid = sdir.name.removeprefix("hoops__")
    date_local, time_local = sid_date_and_time(sid)
    audio_path = sdir / "audio.m4a"
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
    stats["quote_of_day"] = old.get("quote_of_day", "")
    if "session_id_source" in old:
        stats["session_id_source"] = old["session_id_source"]
    stats["vocab_name"], stats["vocab_map"] = vocab.name, vocab.surface_to_canonical
    (sdir / "impacts.json").unlink(missing_ok=True)      # retired sidecar
    acoustics = write_acoustics(sdir, audio_path if audio_path.exists() else None,
                                cfg.acoustics)
    fused = write_fusion(sdir, rows, acoustics["events"] if acoustics else None,
                         cfg.fusion)
    if fused is not None:
        stats["uncorroborated_calls"] = fused["summary"]["n_impact_missing"]
    if acoustics is None:
        (sdir / "acoustics.json").unlink(missing_ok=True)  # stale from a prior run
    if fused is None:
        (sdir / "fusion.json").unlink(missing_ok=True)
    flags = [f"{v.id}: {v.message}" for v in violations]
    write_shots_csv(sdir, rows)
    write_session_json(sdir, stats)
    render_strip(rows, sdir / "strip.png")
    (sdir / "report.html").write_text(render_interactive_report(
        stats, rows, narrative, flags, words,
        audio_path if audio_path.exists() else None,
        acoustics=acoustics, fusion=fused))
    return Outcome(status="ok", sid=sid, session_dir=sdir, stats=stats,
                   rows=rows, flags=flags)
