"""In-process whisper-1 backend: production parity via hoops' own transcriber + bias prompt."""
import time
from pathlib import Path
from hoops.transcribe import WhisperApiTranscriber, make_envelope, words_from_envelope
from .base import BWord, TranscriptResult

MODEL_ID = "whisper-1"

def transcribe(audio_path: Path, fixture_id: str, prompt: str) -> TranscriptResult:
    t0 = time.monotonic()
    resp = WhisperApiTranscriber().transcribe(audio_path, prompt)
    runtime = time.monotonic() - t0
    env = make_envelope(resp, MODEL_ID)
    words = [BWord(word=w.raw.strip(), start=w.start, end=w.end, confidence=w.confidence)
             for w in words_from_envelope(env)]
    return TranscriptResult(MODEL_ID, fixture_id, words, resp.get("text", ""),
                            runtime, peak_rss_mb=None, prompt_used=bool(prompt))
