import json, os, re, shutil, subprocess, time
from pathlib import Path
from .config import Config
from .pipeline import process_file

def _is_dataless(st: os.stat_result) -> bool:
    # iCloud "Optimize Mac Storage" evicts file content but keeps the entry
    # under its real name: logical st_size intact, zero blocks on disk.
    # (st_flags SF_DATALESS also marks these; blocks==0 is the portable signal.)
    return st.st_size > 0 and st.st_blocks == 0

def stable_files(inbox: Path, state: dict, prefix: str) -> tuple[list[Path], dict]:
    pat = re.compile(rf"^{re.escape(prefix)}__.*\.m4a$")
    new_state = {k: v for k, v in state.items() if k.startswith("_")}
    ready = []
    if not inbox.exists():
        return ready, new_state
    for p in sorted(inbox.iterdir()):
        if p.name.endswith(".icloud"):
            subprocess.run(["brctl", "download", str(p)], check=False)
            continue
        if not pat.match(p.name):
            continue
        try:
            st = p.stat()
            size = st.st_size
            new_state[p.name] = {"size": size}      # remember size even while downloading
            if _is_dataless(st):
                subprocess.run(["brctl", "download", str(p)], check=False)
                continue
            prev = state.get(p.name)
            if prev and prev["size"] == size and time.time() - p.stat().st_mtime > 60:
                ready.append(p)
        except (FileNotFoundError, OSError):
            continue
    return ready, new_state

def _repair_duplicate(inbox_file: Path, session_dir: Path | None, repo_root: Path) -> None:
    """A duplicate hit means the session dir already exists but this inbox file was
    never consumed. If the session is missing its audio, adopt this copy; otherwise
    it's a redundant copy — file it under rejected/ so the inbox still drains."""
    if session_dir is None:
        return
    target_audio = session_dir / "audio.m4a"
    if not target_audio.exists():
        shutil.move(str(inbox_file), str(target_audio))
        return
    rej = repo_root / "rejected"
    rej.mkdir(exist_ok=True)
    target = rej / inbox_file.name
    if target.exists():
        n = 2
        while (rej / f"{inbox_file.stem}__{n}{inbox_file.suffix}").exists():
            n += 1
        target = rej / f"{inbox_file.stem}__{n}{inbox_file.suffix}"
    shutil.move(str(inbox_file), str(target))

def _retry_pending_emails(cfg: Config) -> None:
    from .mailer import build_email, send
    from .render import Narrative
    from .session import find_session_dirs, read_session_json
    for sdir in find_session_dirs(cfg.sessions_root):
        marker = sdir / "pending_email"
        if not marker.exists():
            continue
        try:
            stats = read_session_json(sdir)
            flags = ([] if stats.get("invariants_passed", True)
                     else ["invariants failed — see session.json"])
            narrative = None
            nfile = sdir / "narrative.json"
            if nfile.exists():
                try:
                    narrative = Narrative(**json.loads(nfile.read_text()))
                except (TypeError, ValueError):
                    narrative = None
            msg = build_email(stats, sdir, narrative, flags, cfg)
            send(msg, cfg)
            marker.unlink()
        except Exception:
            pass                                           # leave marker, retry next poll

def _alert_email(cfg: Config, name: str, err: str) -> None:
    try:
        from email.message import EmailMessage
        from .mailer import send
        msg = EmailMessage()
        msg["From"], msg["To"] = cfg.email["from"], cfg.email["to"]
        msg["Subject"] = f"⚠️ 🏀 processing failing for {name}"
        msg.set_content(f"Repeated consecutive failed polls.\nLast error: {err}")
        send(msg, cfg)
    except Exception:
        pass

def poll_once(cfg: Config, transcriber) -> list[Path]:
    lock = cfg.repo_root / ".poll.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        if time.time() - lock.stat().st_mtime < 1800:
            return []
        lock.unlink(missing_ok=True)                      # stale lock
        return poll_once(cfg, transcriber)
    try:
        state_path = cfg.repo_root / ".poll_state.json"
        try:
            state = json.loads(state_path.read_text()) if state_path.exists() else {}
        except (json.JSONDecodeError, OSError):
            state = {}
        failures = state.get("_failures", {})
        ready, new_state = stable_files(cfg.inbox, state, cfg.prefix)
        processed = []
        for f in ready:
            try:
                out = process_file(f, cfg, transcriber, email=True, archive="move")
                if out.status == "duplicate":
                    _repair_duplicate(f, out.session_dir, cfg.repo_root)
                # "ok" / "needs_review" / "rejected" already consumed the inbox file
                # via archive="move" inside process_file.
                processed.append(f)
                failures.pop(f.name, None)
            except Exception as e:
                failures[f.name] = failures.get(f.name, 0) + 1
                if failures[f.name] % 3 == 0:
                    _alert_email(cfg, f.name, repr(e))
        new_state["_failures"] = failures
        _retry_pending_emails(cfg)
        tmp_path = state_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(new_state))
        os.replace(tmp_path, state_path)
        return processed
    finally:
        lock.unlink(missing_ok=True)
