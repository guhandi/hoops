# /// script
# requires-python = ">=3.10"
# dependencies = ["mlx-whisper>=0.4"]
# ///
"""mlx-whisper large-v3 (Apple-native). Requires ffmpeg on PATH."""
import argparse, json, resource, time
from pathlib import Path

MODEL_ID = "mlx-whisper-large-v3"

def peak_rss_mb() -> float:
    # ru_maxrss is BYTES on macOS (KB on Linux); this benchmark targets macOS.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6

def result_dict(fixture, words, text, runtime_s, prompt_used) -> dict:
    return {"model_id": MODEL_ID, "fixture": fixture, "words": words, "text": text,
            "runtime_s": runtime_s, "peak_rss_mb": peak_rss_mb(), "prompt_used": prompt_used}

def run(audio: str, out: str, prompt: str, fixture: str) -> None:
    import mlx_whisper
    t0 = time.monotonic()
    res = mlx_whisper.transcribe(audio, path_or_hf_repo="mlx-community/whisper-large-v3-mlx",
                                 word_timestamps=True, initial_prompt=prompt or None)
    words = []
    for seg in res.get("segments", []):
        for w in seg.get("words", []):
            words.append({"word": str(w["word"]).strip(), "start": round(float(w["start"]), 3),
                          "end": round(float(w["end"]), 3),
                          "confidence": w.get("probability")})
    d = result_dict(fixture, words, res.get("text", "").strip(), time.monotonic() - t0, bool(prompt))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(d, indent=1))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("audio"); p.add_argument("out")
    p.add_argument("--prompt", default=""); p.add_argument("--fixture", default="")
    a = p.parse_args()
    run(a.audio, a.out, a.prompt, a.fixture)

if __name__ == "__main__":
    main()
