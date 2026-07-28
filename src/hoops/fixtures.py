import csv, json, shutil
from pathlib import Path
from .config import Config
from .pipeline import process_file
from .render import render_gallery

def read_manifest(path: Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))

def transcript_cache_path(repo_root: Path, fixture_filename: str) -> Path:
    stem = fixture_filename.replace("/", "__").rsplit(".", 1)[0]
    return repo_root / "fixtures" / "transcripts" / f"{stem}.json"

def run_fixture(row: dict, cfg: Config, transcriber, out_root: Path) -> dict:
    audio = cfg.repo_root / "fixtures" / row["filename"]
    cache = transcript_cache_path(cfg.repo_root, row["filename"])
    cached_env = json.loads(cache.read_text()) if cache.exists() else None
    stem = row["filename"].replace("/", "__").rsplit(".", 1)[0]
    out = process_file(audio, cfg, transcriber, email=False, out_root=out_root / stem,
                       archive="none", vocab_name=row.get("vocab") or None,
                       cached_env=cached_env, repair_enabled=False)
    if cached_env is None and out.session_dir and (out.session_dir / "transcript.json").exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(out.session_dir / "transcript.json", cache)
    name = row["filename"]
    expected = row.get("expected_calls", "").split() if row.get("expected_calls") else []
    if out.status != "ok":
        return {"name": name, "expected": expected, "got": [],
                "strip_rel": "", "flags": [f"status: {out.status}"], "note": row.get("notes", "")}
    got = [r["result"] for r in out.rows if not r["voided"]]
    strip_rel = str((out.session_dir / "strip.png").relative_to(cfg.repo_root / "out"))
    return {"name": name, "expected": expected, "got": got,
            "strip_rel": strip_rel, "flags": out.flags, "note": row.get("notes", "")}

def run_all(cfg: Config, transcriber, fixtures_dir: Path) -> list[dict]:
    out_root = cfg.repo_root / "out" / "fixtures"
    if out_root.exists():
        shutil.rmtree(out_root)
    entries = []
    for row in read_manifest(fixtures_dir / "manifest.csv"):
        if not (cfg.repo_root / "fixtures" / row["filename"]).exists():
            continue
        entries.append(run_fixture(row, cfg, transcriber, out_root))
    render_gallery(entries, cfg.repo_root / "out" / "index.html")
    return entries
