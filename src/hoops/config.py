from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo
import os
import yaml

# Branch B / fusion tunables. config.yaml lists these explicitly; this table
# is the fallback so older configs (and tests) keep working. Values chosen by
# scripts/sweep_thresholds.py — see docs/decisions/002-impact-detection-params.md.
DEFAULT_ACOUSTICS = {
    "sr": 22050, "hop": 256, "n_fft": 1024,
    "hpss_margin_harmonic": 1.0, "hpss_margin_percussive": 4.0,
    "onset_delta": 0.4, "min_spacing_frames": 15, "cluster_gap_s": 2.0,
    "envelope_hz": 15, "feature_win_s": 0.15,
}
DEFAULT_FUSION = {"pair_min_s": 0.5, "pair_max_s": 4.0}

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
    acoustics: dict = field(default_factory=lambda: dict(DEFAULT_ACOUSTICS))
    fusion: dict = field(default_factory=lambda: dict(DEFAULT_FUSION))

    def vocab(self, name: str | None = None) -> Vocabulary:
        return self.vocabularies[name or self.vocab_default]

def _email_with_env_override(email: dict) -> dict:
    addr = os.environ.get("GMAIL_ADDRESS", "").strip()
    if addr:
        return {**email, "from": addr, "to": addr}
    return dict(email)

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
        email=_email_with_env_override(raw["email"]),
        profanity=[w.lower() for w in raw.get("profanity", [])],
        repo_root=root,
        acoustics={**DEFAULT_ACOUSTICS, **(raw.get("acoustics") or {})},
        fusion={**DEFAULT_FUSION, **(raw.get("fusion") or {})},
    )
