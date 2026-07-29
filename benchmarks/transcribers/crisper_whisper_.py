# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["transformers>=4.40,<4.47", "torch>=2.2", "accelerate", "librosa", "soundfile"]
# ///
"""CrisperWhisper (nyrahealth): verbatim transcription, retuned tokenizer for pause
attribution. GATED model — requires HF license acceptance + HF_TOKEN in env.
CPU fp32 on 8 GB RAM: slow and memory-heavy. Best-effort backend."""
import argparse, json, os, resource, time
from pathlib import Path

MODEL_ID = "crisper-whisper"

def peak_rss_mb() -> float:
    # ru_maxrss is BYTES on macOS (KB on Linux); this benchmark targets macOS.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6

def result_dict(fixture, words, text, runtime_s, prompt_used) -> dict:
    return {"model_id": MODEL_ID, "fixture": fixture, "words": words, "text": text,
            "runtime_s": runtime_s, "peak_rss_mb": peak_rss_mb(), "prompt_used": prompt_used}

def run(audio: str, out: str, prompt: str, fixture: str) -> None:
    from transformers import pipeline
    t0 = time.monotonic()
    pipe = pipeline("automatic-speech-recognition", model="nyrahealth/CrisperWhisper",
                    device="cpu", return_timestamps="word", chunk_length_s=30,
                    token=os.environ.get("HF_TOKEN"))
    res = pipe(audio)
    words = []
    for ch in res.get("chunks", []):
        s, e = ch.get("timestamp", (None, None))
        if s is not None and e is not None:
            words.append({"word": str(ch["text"]).strip(), "start": round(float(s), 3),
                          "end": round(float(e), 3), "confidence": None})
    d = result_dict(fixture, words, res.get("text", "").strip(), time.monotonic() - t0, False)
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
