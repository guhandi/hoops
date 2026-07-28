import mimetypes, os, smtplib
from datetime import date
from email.message import EmailMessage
from pathlib import Path
from .config import Config
from .render import render_report

ARTIFACTS = ["shots.csv", "session.json", "transcript.json", "transcript.txt",
             "report.html", "strip.png", "audio.m4a"]

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
    tmp = session_dir / "_email_body.html"
    render_report(stats, [], narrative, flags, tmp, img_src="cid:strip")
    body = tmp.read_text(); tmp.unlink()
    msg.set_content("Session report attached (HTML email).")
    msg.add_alternative(body, subtype="html")
    strip = session_dir / "strip.png"
    if strip.exists():
        msg.get_payload()[1].add_related(strip.read_bytes(), maintype="image",
                                         subtype="png", cid="<strip>",
                                         disposition="inline")
    for name in ARTIFACTS:
        p = session_dir / name
        if not p.exists():
            continue
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(p.read_bytes(), maintype=maintype, subtype=subtype,
                           filename=name)
    return msg

def send(msg: EmailMessage, cfg: Config) -> None:
    password = os.environ["GMAIL_APP_PASSWORD"]
    with smtplib.SMTP_SSL(cfg.email["smtp_host"], int(cfg.email["smtp_port"])) as s:
        s.login(cfg.email["from"], password)
        s.send_message(msg)
