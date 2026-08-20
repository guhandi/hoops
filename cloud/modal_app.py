"""Modal wiring: `modal deploy cloud/modal_app.py`.

Everything testable lives in web.py/processor.py/store.py; this file only
binds them to Modal primitives (image, secrets, endpoint, spawn, retries).
"""
from pathlib import Path
import modal

app = modal.App("hoops")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg")
    .pip_install("openai>=1.35", "anthropic>=0.40", "matplotlib>=3.9",
                 "mutagen>=1.47", "pyyaml>=6.0", "python-dotenv>=1.0",
                 "librosa>=0.10", "numpy>=1.26",
                 "fastapi>=0.110", "python-multipart>=0.0.9", "boto3>=1.34")
    .add_local_python_source("hoops", "cloud")
    .add_local_file(Path(__file__).parent / "config.cloud.yaml",
                    "/root/cloud/config.cloud.yaml")
)
secrets = [modal.Secret.from_name("hoops-secrets")]

@app.function(image=image, secrets=secrets, timeout=600,
              retries=modal.Retries(max_retries=3, backoff_coefficient=2.0))
def processor(name: str) -> str:
    import tempfile, traceback, yaml
    from cloud.processor import run_from_bucket
    from cloud.store import ObjectStore
    from hoops.transcribe import WhisperApiTranscriber
    store = ObjectStore.from_env()
    try:
        with tempfile.TemporaryDirectory() as scratch:
            cfg_path = Path("/root/cloud/config.cloud.yaml")
            tblock = yaml.safe_load(cfg_path.read_text())["transcriber"]
            transcriber = WhisperApiTranscriber(tblock["model"],
                                                tblock.get("language", "en"))
            return run_from_bucket(name, store, transcriber, Path(scratch))
    except Exception as e:
        _alert(name, f"{e!r}\n{traceback.format_exc()[-1500:]}")
        raise

def _alert(name: str, err: str) -> None:
    try:
        import os, smtplib
        from email.message import EmailMessage
        import yaml
        raw = yaml.safe_load(Path("/root/cloud/config.cloud.yaml").read_text())
        email = raw["email"]
        addr = os.environ.get("GMAIL_ADDRESS", "").strip() or email["from"]
        msg = EmailMessage()
        msg["From"], msg["To"] = addr, addr
        msg["Subject"] = f"⚠️ 🏀 cloud processing failed for {name}"
        msg.set_content(
            "A processing attempt failed (Modal retries up to 3x with backoff — "
            f"check the dashboard; a later attempt may succeed).\n\n{err}")
        with smtplib.SMTP_SSL(email["smtp_host"], int(email["smtp_port"])) as s:
            s.login(addr, os.environ["GMAIL_APP_PASSWORD"])
            s.send_message(msg)
    except Exception:
        pass  # alerting is best-effort; Modal logs still capture everything

@app.function(image=image, secrets=secrets)
@modal.asgi_app()
def web():
    import os
    from cloud.web import make_app
    from cloud.store import ObjectStore
    return make_app(ObjectStore.from_env(),
                    lambda name: processor.spawn.aio(name),
                    os.environ["HOOPS_UPLOAD_KEY"])

@app.local_entrypoint()
def pull_sessions(dest: str = "sessions"):
    """modal run cloud/modal_app.py::pull_sessions — sync bucket sessions -> local."""
    import os
    from cloud.store import ObjectStore
    store = ObjectStore.from_env()
    n = 0
    for key in store.list_keys("sessions/"):
        target = Path(dest) / Path(key).relative_to("sessions")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(store.get_bytes(key))
            n += 1
    print(f"pulled {n} new file(s) into {dest}/")

@app.local_entrypoint()
def push_sessions(src: str = "sessions"):
    """modal run cloud/modal_app.py::push_sessions — one-way local -> bucket backfill.

    Uploads any file missing from the bucket; never overwrites existing keys."""
    from cloud.store import ObjectStore
    store = ObjectStore.from_env()
    n = 0
    for f in sorted(Path(src).rglob("*")):
        if f.is_file() and not f.name.startswith("."):
            key = f"sessions/{f.relative_to(src)}"
            if not store.exists(key):
                store.put_bytes(key, f.read_bytes())
                n += 1
    print(f"pushed {n} new file(s) from {src}/ to the bucket")
