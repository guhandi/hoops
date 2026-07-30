import io, os, smtplib, zipfile
from datetime import date
from email.message import EmailMessage
from pathlib import Path
from .config import Config
from .render import render_email_body

def build_subject(stats: dict, flags: list[str]) -> str:
    d = date.fromisoformat(stats["session_date_local"])
    core = (f"🏀 {d.strftime('%a %b')} {d.day} — {stats['shots_to_three']} shots "
            f"to close it out ({stats['makes']}/{stats['shots_to_three']})")
    return ("⚠️ " + core) if flags else core

def build_email(stats: dict, session_dir: Path, narrative, flags: list[str],
                cfg: Config) -> EmailMessage:
    msg = EmailMessage()
    msg["From"], msg["To"] = cfg.email["from"], cfg.email["to"]
    msg["Subject"] = build_subject(stats, flags)
    msg.set_content("Extract the attached zip; open report.html inside "
                    "for the interactive session report.")
    msg.add_alternative(render_email_body(stats, narrative, flags, img_src="cid:strip"),
                        subtype="html")
    strip = session_dir / "strip.png"
    if strip.exists():
        msg.get_payload()[1].add_related(strip.read_bytes(), maintype="image",
                                         subtype="png", cid="<strip>",
                                         disposition="inline")
    msg.add_attachment(build_session_zip(session_dir), maintype="application",
                       subtype="zip", filename=f"{session_dir.name}.zip")
    return msg

def build_session_zip(session_dir: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(session_dir.iterdir()):
            if f.is_file():
                zf.write(f, arcname=f"{session_dir.name}/{f.name}")
    return buf.getvalue()

def send(msg: EmailMessage, cfg: Config) -> None:
    password = os.environ["GMAIL_APP_PASSWORD"]
    with smtplib.SMTP_SSL(cfg.email["smtp_host"], int(cfg.email["smtp_port"])) as s:
        s.login(cfg.email["from"], password)
        s.send_message(msg)
