import math
import string
from dataclasses import dataclass
from pathlib import Path
from openai import OpenAI
from .config import Vocabulary

_PUNCT = string.punctuation + "’‘”“…"

def normalize_token(s: str) -> str:
    return s.strip().strip(_PUNCT).lower()

@dataclass(frozen=True)
class Word:
    text: str
    raw: str
    start: float
    end: float
    confidence: float | None

def make_envelope(response: dict, model_id: str) -> dict:
    return {"model": model_id, "response": response}

def words_from_envelope(env: dict) -> list[Word]:
    resp = env["response"]
    segments = resp.get("segments") or []
    out = []
    for w in resp.get("words") or []:
        conf = None
        for seg in segments:
            if seg["start"] <= w["start"] < seg["end"]:
                lp = seg.get("avg_logprob")
                conf = math.exp(lp) if lp is not None else None
                break
        out.append(Word(text=normalize_token(w["word"]), raw=w["word"],
                        start=float(w["start"]), end=float(w["end"]), confidence=conf))
    return out

def envelope_text(env: dict) -> str:
    return env["response"].get("text", "")

def envelope_duration(env: dict) -> float:
    resp = env["response"]
    if resp.get("duration") is not None:
        return float(resp["duration"])
    words = resp.get("words") or []
    return float(words[-1]["end"]) if words else 0.0

def vocab_prompt(vocab: Vocabulary) -> str:
    surfaces = sorted(set(vocab.surface_to_canonical))
    return ("Basketball shooting session. Isolated call-outs of: "
            + ", ".join(surfaces) + ". Also: scratch that, note.")

class WhisperApiTranscriber:
    def __init__(self, model: str = "whisper-1"):
        self.model_id = model

    def transcribe(self, audio_path: Path, prompt: str) -> dict:
        client = OpenAI()
        with audio_path.open("rb") as f:
            resp = client.audio.transcriptions.create(
                model=self.model_id, file=f, response_format="verbose_json",
                timestamp_granularities=["word"], prompt=prompt)
        return resp.model_dump()
