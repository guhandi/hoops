"""Run selected ASR backends over all recorded fixtures; cache TranscriptResult JSONs.

Usage: uv run python benchmarks/run_benchmark.py [--models m1,m2] [--fixtures F01,F06]
                                                 [--force] [--timeout 600]
"""
import argparse, json, subprocess, sys
from pathlib import Path
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))  # script runs with benchmarks/ on sys.path, not repo root
SCRIPTS = REPO / "benchmarks" / "transcribers"
OUT = REPO / "benchmarks" / "out"

BACKENDS = {
    "whisper-1":       {"kind": "inproc"},
    "faster-whisper":  {"kind": "script", "script": SCRIPTS / "faster_whisper_.py"},
    "mlx-whisper":     {"kind": "script", "script": SCRIPTS / "mlx_whisper_.py"},
    "parakeet-mlx":    {"kind": "script", "script": SCRIPTS / "parakeet_mlx_.py"},
    "whisperx":        {"kind": "script", "script": SCRIPTS / "whisperx_.py"},
    "crisper-whisper": {"kind": "script", "script": SCRIPTS / "crisper_whisper_.py"},
}
SKIPS: list[dict] = []

def _prompt_for(row, cfg) -> str:
    from hoops.transcribe import vocab_prompt
    return vocab_prompt(cfg.vocab(row.get("vocabulary") or None))

def run_one(model: str, row: dict, cfg, out_root: Path, force: bool, timeout: int) -> str:
    spec = BACKENDS[model]
    fid = row["fixture_id"]
    out_json = out_root / "transcripts" / model / f"{fid}.json"
    if out_json.exists() and not force:
        return "cached"
    audio = cfg.repo_root / "fixtures" / row["filename"]
    prompt = _prompt_for(row, cfg)
    try:
        if spec["kind"] == "inproc":
            from benchmarks.transcribers.whisper_api import transcribe
            transcribe(audio, fid, prompt).save(out_json)
        else:
            cmd = ["uv", "run", "--script", str(spec["script"]), str(audio),
                   str(out_json), "--prompt", prompt, "--fixture", fid]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if proc.returncode != 0 or not out_json.exists():
                raise RuntimeError(proc.stderr[-500:] or f"exit {proc.returncode}")
        return "ok"
    except Exception as e:  # noqa: BLE001 — any backend failure is a logged skip
        SKIPS.append({"model": model, "fixture": fid, "reason": repr(e)[:500]})
        return "skip"

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--models", default=",".join(BACKENDS))
    p.add_argument("--fixtures", default="")
    p.add_argument("--force", action="store_true")
    p.add_argument("--timeout", type=int, default=600)
    a = p.parse_args()

    load_dotenv(REPO / ".env")
    from hoops.config import load_config
    from hoops.fixtures import read_manifest
    cfg = load_config(REPO / "config.yaml")
    rows = [r for r in read_manifest(REPO / "fixtures" / "manifest.csv")
            if r.get("filename") and r.get("status", "recorded") == "recorded"]
    if a.fixtures:
        want = set(a.fixtures.split(","))
        rows = [r for r in rows if r["fixture_id"] in want]

    for model in a.models.split(","):
        if model not in BACKENDS:
            print(f"unknown model {model!r}; available: {', '.join(BACKENDS)}")
            return 2
        counts = {"ok": 0, "cached": 0, "skip": 0}
        for i, row in enumerate(rows):
            status = run_one(model, row, cfg, OUT, a.force, a.timeout)
            counts[status] += 1
            print(f"{model} {row['fixture_id']}: {status}", flush=True)
            if status == "skip" and i == 0 and counts["ok"] == counts["cached"] == 0:
                SKIPS.append({"model": model, "fixture": "*",
                              "reason": "first fixture failed; skipping model"})
                break
        print(f"{model}: {counts}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "skips.json").write_text(json.dumps(SKIPS, indent=1))
    return 0

if __name__ == "__main__":
    sys.exit(main())
