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
            # Validate output is valid JSON and correct schema
            from benchmarks.transcribers.base import TranscriptResult
            TranscriptResult.load(out_json)
        return "ok"
    except subprocess.TimeoutExpired:
        # A timeout proves the env resolved and the model actually started running —
        # distinguish it from env-resolve/import failures so the first-fixture abort
        # rule (below) doesn't discard a backend that's simply slow.
        out_json.unlink(missing_ok=True)
        SKIPS.append({"model": model, "fixture": fid, "reason": f"timeout after {timeout}s"})
        return "skip"
    except Exception as e:  # noqa: BLE001 — any other backend failure is a logged skip
        out_json.unlink(missing_ok=True)  # Clean up any partial/corrupt output
        SKIPS.append({"model": model, "fixture": fid, "reason": repr(e)[:500]})
        return "skip"

def is_timeout_reason(reason: str) -> bool:
    """True when a skip reason string was produced by the subprocess-timeout branch
    of run_one (not a generic env-resolve/import/runtime failure)."""
    return reason.startswith("timeout after ")


def merge_skips(out_root: Path, new_skips: list[dict]) -> list[dict]:
    """Merge new_skips into any existing skips.json rather than clobbering it — staged
    invocations (e.g. one per model, or one per fixture subset) each report only the
    (model, fixture) pairs they touched, so a later stage must not erase an earlier
    stage's entries. Existing entries for (model, fixture) pairs being re-reported are
    dropped in favor of the new entry (re-running a model/fixture supersedes its old skip)."""
    skips_file = out_root / "skips.json"
    existing: list[dict] = []
    if skips_file.exists():
        try:
            loaded = json.loads(skips_file.read_text())
            if isinstance(loaded, list):
                existing = loaded
        except (json.JSONDecodeError, OSError):
            existing = []
    keys = {(s.get("model"), s.get("fixture")) for s in new_skips}
    merged = [s for s in existing if (s.get("model"), s.get("fixture")) not in keys]
    merged.extend(new_skips)
    return merged


def run_model(model: str, rows: list[dict], cfg, out_root: Path, force: bool, timeout: int) -> dict:
    """Run one model over all rows, applying the first-fixture-abort rule. Appends to
    the global SKIPS list (same convention as run_one). Returns the ok/cached/skip counts.

    Abort rule: if the very first fixture fails and nothing has succeeded/cached yet,
    the model is assumed broken (env-resolve/import failure) and remaining fixtures are
    skipped — UNLESS that first failure was a timeout, which proves the env resolved and
    the model actually ran (it's just slower than --timeout allows).
    """
    counts = {"ok": 0, "cached": 0, "skip": 0}
    for i, row in enumerate(rows):
        status = run_one(model, row, cfg, out_root, force, timeout)
        counts[status] += 1
        print(f"{model} {row['fixture_id']}: {status}", flush=True)
        if status == "skip" and i == 0 and counts["ok"] == counts["cached"] == 0:
            first_reason = SKIPS[-1]["reason"] if SKIPS else ""
            if not is_timeout_reason(first_reason):
                SKIPS.append({"model": model, "fixture": "*",
                              "reason": "first fixture failed; skipping model"})
                break
    return counts


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

    if not rows:
        print(f"warning: no rows matched --fixtures={a.fixtures!r} "
              "(check for typos against fixtures/manifest.csv); nothing to do")

    for model in a.models.split(","):
        if model not in BACKENDS:
            print(f"unknown model {model!r}; available: {', '.join(BACKENDS)}")
            return 2
        counts = run_model(model, rows, cfg, OUT, a.force, a.timeout)
        print(f"{model}: {counts}")
    OUT.mkdir(parents=True, exist_ok=True)
    merged = merge_skips(OUT, SKIPS)
    (OUT / "skips.json").write_text(json.dumps(merged, indent=1))
    return 0

if __name__ == "__main__":
    sys.exit(main())
