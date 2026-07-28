import json, os, re, subprocess, time
from pathlib import Path
from .config import Config
from .pipeline import process_file

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
        size = p.stat().st_size
        new_state[p.name] = {"size": size}
        prev = state.get(p.name)
        if prev and prev["size"] == size and time.time() - p.stat().st_mtime > 60:
            ready.append(p)
    return ready, new_state

def _alert_email(cfg: Config, name: str, err: str) -> None:
    try:
        from email.message import EmailMessage
        from .mailer import send
        msg = EmailMessage()
        msg["From"], msg["To"] = cfg.email["from"], cfg.email["to"]
        msg["Subject"] = f"⚠️ 🏀 processing failing for {name}"
        msg.set_content(f"3 consecutive failed polls.\nLast error: {err}")
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
        lock.unlink()                                    # stale lock
        return poll_once(cfg, transcriber)
    try:
        state_path = cfg.repo_root / ".poll_state.json"
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        failures = state.get("_failures", {})
        ready, new_state = stable_files(cfg.inbox, state, cfg.prefix)
        processed = []
        for f in ready:
            try:
                out = process_file(f, cfg, transcriber, email=True, archive="move")
                processed.append(f)
                failures.pop(f.name, None)
            except Exception as e:
                failures[f.name] = failures.get(f.name, 0) + 1
                if failures[f.name] == 3:
                    _alert_email(cfg, f.name, repr(e))
        new_state["_failures"] = failures
        state_path.write_text(json.dumps(new_state))
        return processed
    finally:
        lock.unlink(missing_ok=True)
