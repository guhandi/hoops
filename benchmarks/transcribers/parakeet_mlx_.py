# /// script
# requires-python = ">=3.10"
# dependencies = ["parakeet-mlx"]
# ///
"""Parakeet TDT 0.6B via parakeet-mlx (Apple-native RNN-T, native token timestamps).
No prompt support — prompt arg accepted and ignored, prompt_used stays False."""
import argparse, json, resource, time
from pathlib import Path

MODEL_ID = "parakeet-tdt-0.6b-mlx"

def peak_rss_mb() -> float:
    # ru_maxrss is BYTES on macOS (KB on Linux); this benchmark targets macOS.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6

def result_dict(fixture, words, text, runtime_s, prompt_used) -> dict:
    return {"model_id": MODEL_ID, "fixture": fixture, "words": words, "text": text,
            "runtime_s": runtime_s, "peak_rss_mb": peak_rss_mb(), "prompt_used": prompt_used}

def run(audio: str, out: str, prompt: str, fixture: str) -> None:
    from parakeet_mlx import from_pretrained
    t0 = time.monotonic()
    model = from_pretrained("mlx-community/parakeet-tdt-0.6b-v2")
    result = model.transcribe(audio)
    # AlignedResult: sentences -> tokens with .text/.start/.end. Tokens are SUBWORD
    # units ("B","re","ak" for "Break"); a leading space/▁ marks a word start. Merge
    # tokens into words so downstream vocab matching sees "Break", not fragments.
    words = []
    cur = None
    for sent in result.sentences:
        for tok in sent.tokens:
            raw = tok.text
            t = raw.replace("▁", " ").strip()
            if not t:
                continue
            if cur is None or raw.startswith((" ", "▁")):
                if cur:
                    words.append(cur)
                cur = {"word": t, "start": round(float(tok.start), 3),
                       "end": round(float(tok.end), 3), "confidence": None}
            else:
                cur["word"] += t
                cur["end"] = round(float(tok.end), 3)
        if cur:  # sentence boundary always ends the current word
            words.append(cur)
            cur = None
    if cur:
        words.append(cur)
    d = result_dict(fixture, words, result.text.strip(), time.monotonic() - t0, False)
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
