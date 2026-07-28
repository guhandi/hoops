from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo
import yaml

@dataclass(frozen=True)
class Vocabulary:
    name: str
    surface_to_canonical: dict[str, str]

    @classmethod
    def from_dict(cls, name: str, d: dict) -> "Vocabulary":
        m = {}
        for canonical, surfaces in d.items():
            for s in surfaces:
                m[str(s).lower()] = canonical
        return cls(name=name, surface_to_canonical=m)

@dataclass(frozen=True)
class Config:
    tz: ZoneInfo
    inbox: Path
    sessions_root: Path
    prefix: str
    vocab_default: str
    vocabularies: dict[str, Vocabulary]
    isolation_low: float
    isolation_high: float
    min_duration_s: float
    max_duration_s: float
    min_gap_s: float
    max_gap_s: float
    transcriber_model: str
    llm_model: str
    email: dict
    profanity: list[str]
    repo_root: Path

    def vocab(self, name: str | None = None) -> Vocabulary:
        return self.vocabularies[name or self.vocab_default]

def load_config(path: Path | None = None) -> Config:
    path = Path(path or Path.cwd() / "config.yaml").resolve()
    raw = yaml.safe_load(path.read_text())
    root = path.parent
    vocabs = {n: Vocabulary.from_dict(n, d) for n, d in raw["vocabularies"].items()}
    sessions_root = Path(raw["sessions_root"])
    if not sessions_root.is_absolute():
        sessions_root = root / sessions_root
    return Config(
        tz=ZoneInfo(raw["timezone"]),
        inbox=Path(raw["inbox"]).expanduser(),
        sessions_root=sessions_root,
        prefix=raw["prefix"],
        vocab_default=raw["vocab_default"],
        vocabularies=vocabs,
        isolation_low=float(raw["isolation"]["low"]),
        isolation_high=float(raw["isolation"]["high"]),
        min_duration_s=float(raw["limits"]["min_duration_s"]),
        max_duration_s=float(raw["limits"]["max_duration_s"]),
        min_gap_s=float(raw["limits"]["min_gap_s"]),
        max_gap_s=float(raw["limits"]["max_gap_s"]),
        transcriber_model=raw["transcriber"]["model"],
        llm_model=raw["llm"]["model"],
        email=raw["email"],
        profanity=[w.lower() for w in raw.get("profanity", [])],
        repo_root=root,
    )
