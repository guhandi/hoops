import csv, json, re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SHOT_COLUMNS = ["session_id", "session_date_local", "shot_num", "result", "t_call_s",
                "gap_s", "streak_after", "voided", "isolation_s", "confidence", "raw_token"]
_PREFIX_RE = re.compile(r"^hoops__(\d{8}-\d{6})\.m4a$", re.IGNORECASE)

def session_id_for(path: Path, tz: ZoneInfo) -> tuple[str, str]:
    m = _PREFIX_RE.match(path.name)
    if m:
        return m.group(1), "filename"
    dt = datetime.fromtimestamp(path.stat().st_mtime, tz)
    return dt.strftime("%Y%m%d-%H%M%S"), "mtime"

def session_dir_for(root: Path, sid: str) -> Path:
    return root / sid[:4] / sid[4:6] / f"hoops__{sid}"

def sid_date_and_time(sid: str) -> tuple[str, str]:
    d, t = sid.split("-")
    return f"{d[:4]}-{d[4:6]}-{d[6:]}", f"{t[:2]}:{t[2:4]}:{t[4:]}"

def write_transcript(sdir: Path, env: dict) -> None:
    (sdir / "transcript.json").write_text(json.dumps(env, indent=2, ensure_ascii=False))
    text = env["response"].get("text", "")
    recovered = [w for s in (env.get("gap_repair") or {}).get("spans", [])
                 for w in s.get("recovered", [])]
    if recovered:
        ann = " ".join(f"{w['word'].strip()}@{w['start']:.1f}" for w in recovered)
        text = (text + "\n" if text else "") + f"[gap repair recovered: {ann}]"
    (sdir / "transcript.txt").write_text(text)

def write_shots_csv(sdir: Path, rows: list[dict]) -> None:
    with (sdir / "shots.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SHOT_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r[k] is None else r[k]) for k in SHOT_COLUMNS})

def write_session_json(sdir: Path, stats: dict) -> None:
    (sdir / "session.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False))

def read_session_json(sdir: Path) -> dict:
    return json.loads((sdir / "session.json").read_text())

def read_envelope(sdir: Path) -> dict:
    return json.loads((sdir / "transcript.json").read_text())

def find_session_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(p.parent for p in root.rglob("transcript.json"))
