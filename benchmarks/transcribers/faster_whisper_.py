# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["faster-whisper>=1.0"]
# ///
"""faster-whisper large-v3, int8, CPU. Self-contained: run via `uv run --script`."""
import argparse, json, resource, time
from pathlib import Path

MODEL_ID = "faster-whisper-large-v3-int8"

def peak_rss_mb() -> float:
    # ru_maxrss is BYTES on macOS (KB on Linux); this benchmark targets macOS.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6

def result_dict(fixture, words, text, runtime_s, prompt_used) -> dict:
    return {"model_id": MODEL_ID, "fixture": fixture, "words": words, "text": text,
            "runtime_s": runtime_s, "peak_rss_mb": peak_rss_mb(), "prompt_used": prompt_used}

def run(audio: str, out: str, prompt: str, fixture: str) -> None:
    from faster_whisper import WhisperModel
    t0 = time.monotonic()
    model = WhisperModel("large-v3", device="cpu", compute_type="int8")
    segments, _info = model.transcribe(audio, word_timestamps=True,
                                       initial_prompt=prompt or None)
    words, texts = [], []
    for seg in segments:  # generator — iteration IS the transcription work
        texts.append(seg.text)
        for w in seg.words or []:
            words.append({"word": w.word.strip(), "start": round(w.start, 3),
                          "end": round(w.end, 3), "confidence": w.probability})
    d = result_dict(fixture, words, "".join(texts).strip(), time.monotonic() - t0, bool(prompt))
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
