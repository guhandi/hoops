# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["whisperx>=3.1"]
# ///
"""WhisperX: whisper + wav2vec2 forced alignment, CPU. Best-effort backend."""
import argparse, json, resource, time
from pathlib import Path

MODEL_ID = "whisperx-large-v3-int8"

def peak_rss_mb() -> float:
    # ru_maxrss is BYTES on macOS (KB on Linux); this benchmark targets macOS.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6

def result_dict(fixture, words, text, runtime_s, prompt_used) -> dict:
    return {"model_id": MODEL_ID, "fixture": fixture, "words": words, "text": text,
            "runtime_s": runtime_s, "peak_rss_mb": peak_rss_mb(), "prompt_used": prompt_used}

def run(audio: str, out: str, prompt: str, fixture: str) -> None:
    import whisperx
    t0 = time.monotonic()
    model = whisperx.load_model("large-v3", device="cpu", compute_type="int8",
                                asr_options={"initial_prompt": prompt or None})
    wav = whisperx.load_audio(audio)
    res = model.transcribe(wav, batch_size=4)
    align_model, meta = whisperx.load_align_model(language_code=res["language"], device="cpu")
    aligned = whisperx.align(res["segments"], align_model, meta, wav, "cpu")
    words = []
    for w in aligned.get("word_segments", []):
        if "start" in w and "end" in w:  # alignment can fail per-word; drop those
            words.append({"word": str(w["word"]).strip(), "start": round(float(w["start"]), 3),
                          "end": round(float(w["end"]), 3), "confidence": w.get("score")})
    text = " ".join(s.get("text", "").strip() for s in res["segments"]).strip()
    d = result_dict(fixture, words, text, time.monotonic() - t0, bool(prompt))
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
