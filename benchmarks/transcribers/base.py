"""TranscriptResult: the JSON contract every backend writes and every analysis reads."""
from __future__ import annotations
import json
import string
from dataclasses import dataclass, field
from pathlib import Path

_PUNCT = string.punctuation + "’‘”“…"

def normalize_token(s: str) -> str:
    return s.strip().strip(_PUNCT).lower()

@dataclass(frozen=True)
class BWord:
    word: str
    start: float
    end: float
    confidence: float | None = None

@dataclass
class TranscriptResult:
    model_id: str
    fixture: str
    words: list[BWord]
    text: str
    runtime_s: float
    peak_rss_mb: float | None = None
    prompt_used: bool = False

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id, "fixture": self.fixture,
            "words": [{"word": w.word, "start": w.start, "end": w.end,
                       "confidence": w.confidence} for w in self.words],
            "text": self.text, "runtime_s": self.runtime_s,
            "peak_rss_mb": self.peak_rss_mb, "prompt_used": self.prompt_used,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TranscriptResult":
        return cls(
            model_id=d["model_id"], fixture=d["fixture"],
            words=[BWord(w["word"], float(w["start"]), float(w["end"]),
                         w.get("confidence")) for w in d["words"]],
            text=d["text"], runtime_s=float(d["runtime_s"]),
            peak_rss_mb=d.get("peak_rss_mb"), prompt_used=bool(d.get("prompt_used", False)))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=1))

    @classmethod
    def load(cls, path: Path) -> "TranscriptResult":
        return cls.from_dict(json.loads(path.read_text()))
