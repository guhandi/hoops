"""Stateless worker: bucket -> scratch -> existing pipeline -> bucket.

The bucket is the source of truth; this process owns nothing durable.
"""
import shutil
from pathlib import Path
from hoops.config import load_config
from hoops.pipeline import process_file
from .web import session_key_for

_TEMPLATE = Path(__file__).parent / "config.cloud.yaml"

def _upload_dir(store, local_dir: Path, key_prefix: str) -> None:
    for f in sorted(local_dir.rglob("*")):
        if f.is_file():
            store.put_bytes(f"{key_prefix}/{f.relative_to(local_dir)}", f.read_bytes())

def run_from_bucket(name: str, store, transcriber, scratch: Path) -> str:
    # duplicate guard (idempotent retries / racing spawns)
    if store.exists(session_key_for(name)):
        store.delete(f"raw/{name}")
        return "duplicate"

    work = scratch / "work"
    if work.exists():
        shutil.rmtree(work)
    (work / "inbox").mkdir(parents=True)
    shutil.copy(_TEMPLATE, work / "config.yaml")
    cfg = load_config(work / "config.yaml")        # repo_root == work

    audio = work / "inbox" / name
    audio.write_bytes(store.get_bytes(f"raw/{name}"))

    out = process_file(audio, cfg, transcriber, email=True, archive="move")

    if out.status in ("ok", "duplicate") and out.session_dir is not None:
        sid = out.sid
        _upload_dir(store, out.session_dir, f"sessions/{sid[:4]}/{sid[4:6]}/{out.session_dir.name}")
    elif out.status == "needs_review" and out.session_dir is not None:
        _upload_dir(store, out.session_dir, f"needs_review/{out.session_dir.name}")
    elif out.status == "rejected":
        rej = work / "rejected" / name
        if rej.exists():
            store.put_bytes(f"rejected/{name}", rej.read_bytes())

    store.delete(f"raw/{name}")
    return out.status
