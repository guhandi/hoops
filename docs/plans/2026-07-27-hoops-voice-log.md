# Hoops Voice Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Voice-logged free-throw sessions: m4a in → shot table, invariant checks, PNG shot strip, and an emailed report, per `docs/specs/2026-07-27-hoops-voice-log-design.md` and `docs/PRD-hoops-voice-log.md`.

**Architecture:** A deterministic Python pipeline (transcribe → parse → validate → persist → render → email) driven by a CLI whose core entry point takes a file path. Word-level whisper-1 timestamps feed an isolation-gated vocabulary parser (pure functions). LLM calls (Anthropic) only for invariant repair and email narrative, both optional and degradable. A launchd-scheduled poller watches an iCloud drop folder and calls the same `process` path.

**Tech Stack:** Python 3.12, uv, pytest, openai (whisper-1), anthropic, matplotlib, mutagen, pyyaml, python-dotenv, stdlib smtplib/sqlite3.

## Global Constraints

- Working directory / repo root: `~/Documents/hoops` (all paths below relative to it).
- Python 3.12, managed by `uv`. All commands run as `uv run ...`.
- Runtime deps limited to: `openai`, `anthropic`, `matplotlib`, `mutagen`, `pyyaml`, `python-dotenv`. Dev dep: `pytest`. The parser (`parse.py`, `stats.py`, `invariants.py`) is pure stdlib.
- pytest markers: `unit` (pure, synthetic), `parse` (fixture transcripts → shots), `paid` (hits paid APIs). `paid` is deselected by default via `addopts = -m "not paid"`.
- Vocabulary default: `make: [make, splash]`, `miss: [miss, brick]` (spec §2.1 — supersedes PRD §6.3).
- Isolation gate defaults: `isolation_low: 0.15`, `isolation_high: 0.4` seconds (spec §4.4).
- Invariant constants: min inter-call gap 1.5s, max gap 120s; duration reject <5s, flag >20min (PRD §6.5, §10).
- Narrative may contain no digits; quote must be a verbatim transcript substring; ≤3 sentences; no comparative/historical claims (PRD §9.3).
- Committed: text (transcripts, csv, json, code, fixture audio). Gitignored: `.env`, `out/`, `hoops.db`, session `audio.m4a`/`report.html`/`strip.png`, logs.
- LLM model: `claude-sonnet-5`. Transcriber: `whisper-1`, `response_format="verbose_json"`, `timestamp_granularities=["word"]`, prompt biased to active vocabulary (PRD §9.1).
- Every persisted timestamp field in filenames/session IDs is local time in the configured timezone (PRD §6.7).
- Commit after every task; messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`, `src/hoops/__init__.py`, `src/hoops/cli.py` (stub), `config.yaml`, `.env.example`, `fixtures/manifest.csv`, `tests/test_cli.py`

**Interfaces:**
- Produces: installable package `hoops` with console script `hoops`; `hoops.cli.build_parser() -> argparse.ArgumentParser` with subcommands `process`, `process-all`, `replay`, `poll`, `score`, `transcribe-fixtures` (stubs); `config.yaml` keys exactly as listed below (Task 2 parses them).

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
import pytest
from hoops.cli import build_parser

pytestmark = pytest.mark.unit

def test_parser_has_all_subcommands():
    p = build_parser()
    args = p.parse_args(["process", "some.m4a", "--no-email"])
    assert args.command == "process" and args.no_email is True
    for cmd, extra in [("process-all", ["fixtures"]), ("replay", []), ("poll", []),
                       ("score", []), ("transcribe-fixtures", [])]:
        assert p.parse_args([cmd, *extra]).command == cmd

def test_replay_flags():
    p = build_parser()
    assert p.parse_args(["replay", "--all"]).all is True
    assert p.parse_args(["replay", "20260727-061204"]).sid == "20260727-061204"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Documents/hoops && uv run pytest tests/test_cli.py -v`
Expected: FAIL (module `hoops` not found — pyproject not yet written) or collection error.

- [ ] **Step 3: Write scaffold**

`pyproject.toml`:
```toml
[project]
name = "hoops"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "openai>=1.35", "anthropic>=0.40", "matplotlib>=3.9",
  "mutagen>=1.47", "pyyaml>=6.0", "python-dotenv>=1.0",
]

[project.scripts]
hoops = "hoops.cli:main"

[dependency-groups]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/hoops"]

[tool.pytest.ini_options]
addopts = "-m 'not paid'"
markers = [
  "unit: pure functions, synthetic inputs",
  "parse: fixture transcripts -> shots, no network",
  "paid: hits paid APIs, run on demand",
]
```

`src/hoops/__init__.py`:
```python
PARSER_VERSION = "1"
```

`src/hoops/cli.py`:
```python
import argparse

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hoops", description="Morning free-throw voice log")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("process", help="Process one audio file end to end")
    sp.add_argument("path")
    sp.add_argument("--no-email", dest="no_email", action="store_true")

    sa = sub.add_parser("process-all", help="Process a fixtures dir + gallery")
    sa.add_argument("fixtures_dir")
    sa.add_argument("--no-email", dest="no_email", action="store_true", default=True)

    sr = sub.add_parser("replay", help="Re-parse from stored transcript.json")
    g = sr.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true")
    g.add_argument("sid", nargs="?")

    sub.add_parser("poll", help="One-shot inbox scan")
    sub.add_parser("score", help="Print the gate table from manifest.csv")

    st = sub.add_parser("transcribe-fixtures", help="Refresh committed fixture transcripts (paid)")
    st.add_argument("--only")
    return p

def main() -> int:
    args = build_parser().parse_args()
    raise SystemExit(f"{args.command}: not implemented yet")
```

`config.yaml`:
```yaml
timezone: America/Los_Angeles     # EDIT if not your timezone
inbox: ~/Library/Mobile Documents/com~apple~CloudDocs/Capture/inbox
sessions_root: sessions
prefix: hoops

vocab_default: default
vocabularies:
  default:
    make: [make, splash]
    miss: [miss, brick]

isolation:
  low: 0.15
  high: 0.4

limits:
  min_duration_s: 5
  max_duration_s: 1200
  min_gap_s: 1.5
  max_gap_s: 120

transcriber:
  model: whisper-1

llm:
  model: claude-sonnet-5

email:
  from: guhandiji@gmail.com
  to: guhandiji@gmail.com
  smtp_host: smtp.gmail.com
  smtp_port: 465

profanity: [fuck, fucking, shit, damn, goddamn, bullshit, ass]
```

`.env.example`:
```
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GMAIL_APP_PASSWORD=
```

`fixtures/manifest.csv` (single source of truth, PRD §11.1 + spec §3.3; `expected_gaps` optional, blank = skip timing gate):
```csv
filename,expected_calls,traps_planted,expect_invariants_pass,vocab,gating,expected_gaps,notes
dev/dev01.m4a,,,,,no,,Bball shot 2
dev/dev02.m4a,,,,,no,,Morning basketball shot
dev/dev03.m4a,,,,,no,,Normal make-miss 10am beep
dev/dev04.m4a,,,,,no,,Normal make-miss only
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv sync && uv run pytest tests/test_cli.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: project scaffold — cli skeleton, config, manifest"
```

---

### Task 2: Config loader (`config.py`)

**Files:**
- Create: `src/hoops/config.py`, `tests/test_config.py`

**Interfaces:**
- Produces:
  - `Vocabulary` dataclass: fields `name: str`, `surface_to_canonical: dict[str, str]`.
  - `Config` dataclass: `tz: zoneinfo.ZoneInfo`, `inbox: Path`, `sessions_root: Path`, `prefix: str`, `vocab_default: str`, `vocabularies: dict[str, Vocabulary]`, `isolation_low: float`, `isolation_high: float`, `min_duration_s: float`, `max_duration_s: float`, `min_gap_s: float`, `max_gap_s: float`, `transcriber_model: str`, `llm_model: str`, `email: dict` (keys `from`, `to`, `smtp_host`, `smtp_port`), `profanity: list[str]`, `repo_root: Path`. Method `vocab(name: str | None = None) -> Vocabulary`.
  - `load_config(path: Path | None = None) -> Config` — default `repo_root/config.yaml` where `repo_root` is the config file's parent.

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
import pytest
from pathlib import Path
from hoops.config import load_config

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[1]

def test_load_real_config():
    cfg = load_config(REPO / "config.yaml")
    assert cfg.vocab().surface_to_canonical == {
        "make": "make", "splash": "make", "miss": "miss", "brick": "miss"}
    assert cfg.isolation_low == 0.15 and cfg.isolation_high == 0.4
    assert cfg.min_gap_s == 1.5 and cfg.max_gap_s == 120
    assert cfg.inbox.is_absolute()          # ~ expanded
    assert cfg.sessions_root == REPO / "sessions"
    assert cfg.email["smtp_port"] == 465
    assert str(cfg.tz)                       # valid zoneinfo

def test_named_vocab_lookup():
    cfg = load_config(REPO / "config.yaml")
    assert cfg.vocab("default").name == "default"
    with pytest.raises(KeyError):
        cfg.vocab("nope")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v` — Expected: FAIL, no module `hoops.config`.

- [ ] **Step 3: Implement**

`src/hoops/config.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes** — `uv run pytest tests/test_config.py -v` → 2 PASS.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: config loader with named vocabularies"`

---

### Task 3: Transcript model + whisper backend (`transcribe.py`)

**Files:**
- Create: `src/hoops/transcribe.py`, `tests/test_transcribe.py`, `tests/conftest.py`

**Interfaces:**
- Produces:
  - `Word` dataclass: `text: str` (normalized: lowercased, punctuation-stripped), `raw: str` (as transcribed), `start: float`, `end: float`, `confidence: float | None`.
  - `make_envelope(response: dict, model_id: str) -> dict` — `{"model": model_id, "response": response}`; this dict is what gets written verbatim as `transcript.json` (PRD §7.1: store the full transcriber response).
  - `words_from_envelope(env: dict) -> list[Word]` — reads `response["words"]`; per-word confidence = `exp(avg_logprob)` of the containing segment from `response["segments"]`, else `None`.
  - `envelope_text(env: dict) -> str` — `response["text"]`.
  - `envelope_duration(env: dict) -> float` — `response["duration"]`, falling back to last word `end`, else `0.0`.
  - `normalize_token(s: str) -> str`.
  - `class WhisperApiTranscriber:` `__init__(self, model: str = "whisper-1")`, attribute `model_id: str`, method `transcribe(self, audio_path: Path, prompt: str) -> dict` (returns raw response dict via `resp.model_dump()`).
  - `vocab_prompt(vocab: Vocabulary) -> str` — bias prompt listing the surface forms plus "scratch that" and "note".
  - conftest helper `make_env(words, duration=None)` used by all later tests: takes `list[tuple[str, float, float]]` of (raw_word, start, end), returns an envelope shaped like whisper verbose_json.

- [ ] **Step 1: Write conftest helper + failing tests**

`tests/conftest.py`:
```python
def make_env(words: list[tuple[str, float, float]], duration: float | None = None) -> dict:
    resp = {
        "text": " ".join(w for w, _, _ in words),
        "duration": duration if duration is not None else (words[-1][2] if words else 0.0),
        "words": [{"word": w, "start": s, "end": e} for w, s, e in words],
        "segments": [],
    }
    return {"model": "whisper-1", "response": resp}
```

`tests/test_transcribe.py`:
```python
import math
import pytest
from hoops.transcribe import (Word, make_envelope, words_from_envelope,
                              envelope_text, envelope_duration, normalize_token,
                              vocab_prompt, WhisperApiTranscriber)
from hoops.config import Vocabulary
from conftest import make_env

pytestmark = pytest.mark.unit

def test_normalize_token():
    assert normalize_token(" Make,") == "make"
    assert normalize_token("BRICK!") == "brick"

def test_words_from_envelope_with_segment_confidence():
    env = make_env([(" make", 1.0, 1.4), (" miss", 3.0, 3.4)])
    env["response"]["segments"] = [
        {"start": 0.0, "end": 2.0, "avg_logprob": -0.1},
        {"start": 2.0, "end": 4.0, "avg_logprob": -0.5},
    ]
    ws = words_from_envelope(env)
    assert [w.text for w in ws] == ["make", "miss"]
    assert ws[0].raw == " make" and ws[0].start == 1.0 and ws[0].end == 1.4
    assert math.isclose(ws[0].confidence, math.exp(-0.1))
    assert math.isclose(ws[1].confidence, math.exp(-0.5))

def test_words_without_segments_have_none_confidence():
    ws = words_from_envelope(make_env([("hi", 0.0, 0.2)]))
    assert ws[0].confidence is None

def test_envelope_accessors():
    env = make_env([("a", 0.0, 0.5)], duration=9.9)
    assert envelope_duration(env) == 9.9
    assert envelope_text(env) == "a"

def test_vocab_prompt_mentions_surfaces():
    v = Vocabulary.from_dict("default", {"make": ["make", "splash"], "miss": ["miss", "brick"]})
    p = vocab_prompt(v)
    for s in ["make", "splash", "miss", "brick", "scratch that", "note"]:
        assert s in p

def test_whisper_transcriber_calls_api(monkeypatch, tmp_path):
    calls = {}
    class FakeResp:
        def model_dump(self): return {"text": "ok", "duration": 1.0, "words": []}
    class FakeTranscriptions:
        def create(self, **kw):
            calls.update(kw); return FakeResp()
    class FakeClient:
        def __init__(self): self.audio = type("A", (), {"transcriptions": FakeTranscriptions()})()
    monkeypatch.setattr("hoops.transcribe.OpenAI", lambda: FakeClient())
    f = tmp_path / "a.m4a"; f.write_bytes(b"x")
    t = WhisperApiTranscriber()
    resp = t.transcribe(f, prompt="hint")
    assert resp["text"] == "ok"
    assert calls["model"] == "whisper-1"
    assert calls["response_format"] == "verbose_json"
    assert calls["timestamp_granularities"] == ["word"]
    assert calls["prompt"] == "hint"
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_transcribe.py -v` → import error.

- [ ] **Step 3: Implement**

`src/hoops/transcribe.py`:
```python
import math
import string
from dataclasses import dataclass
from pathlib import Path
from openai import OpenAI
from .config import Vocabulary

_PUNCT = string.punctuation + "’‘“”…"

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
    if resp.get("duration"):
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
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_transcribe.py -v` → all PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat: transcript envelope model + whisper-1 backend"`

---

### Task 4: Parser (`parse.py`) — isolation gate, vocab map, voids, notes

**Files:**
- Create: `src/hoops/parse.py`, `tests/test_parse.py`

**Interfaces:**
- Consumes: `Word` from `hoops.transcribe`, `Vocabulary` from `hoops.config`.
- Produces:
  - `Call` dataclass: `result: str` ("make"|"miss"), `raw_token: str`, `t_s: float`, `isolation_s: float`, `confidence: float | None`, `voided: bool = False`.
  - `Ambiguous` dataclass: `text: str`, `t_s: float`, `isolation_s: float`, `canonical: str`.
  - `ParseResult` dataclass: `calls: list[Call]` (time-ordered, includes voided), `ambiguous: list[Ambiguous]`, `note: str | None`.
  - `parse_words(words: list[Word], vocab: Vocabulary, iso_low: float, iso_high: float) -> ParseResult`.

Rules (spec §4.4, PRD §6.1–6.2): isolation = `min(gap_before, gap_after)`, edges count as infinite gaps. `>= iso_high` ⇒ call; `<= iso_low` ⇒ discard; between ⇒ `ambiguous`. Unknown tokens silently ignored. "scratch that" = consecutive tokens `scratch`,`that` with inter-word gap ≤0.75s; voids the latest prior non-voided call. Note = everything after the **last** standalone `note` token, joined verbatim from `raw`; the note region is excluded from call scanning.

- [ ] **Step 1: Write the failing tests**

`tests/test_parse.py`:
```python
import pytest
from hoops.config import Vocabulary
from hoops.parse import parse_words
from hoops.transcribe import words_from_envelope
from conftest import make_env

pytestmark = pytest.mark.unit
V = Vocabulary.from_dict("default", {"make": ["make", "splash"], "miss": ["miss", "brick"]})

def words(*triples):
    return words_from_envelope(make_env(list(triples)))

def parse(ws): return parse_words(ws, V, iso_low=0.15, iso_high=0.4)

def test_isolated_calls_detected():
    r = parse(words(("make", 1.0, 1.4), ("miss", 4.0, 4.4), ("splash", 8.0, 8.5)))
    assert [c.result for c in r.calls] == ["make", "miss", "make"]
    assert r.calls[0].t_s == 1.0 and r.calls[0].raw_token == "make"

def test_commentary_bait_words_discarded():
    # "come on make it" — continuous run, gaps ~0.05s → no phantom call
    r = parse(words(("come", 1.0, 1.2), ("on", 1.25, 1.4), ("make", 1.45, 1.7), ("it", 1.75, 1.9),
                    ("miss", 5.0, 5.4)))
    assert [c.result for c in r.calls] == ["miss"]

def test_midband_isolation_goes_to_ambiguous():
    # gap 0.25s both sides → between 0.15 and 0.4
    r = parse(words(("uh", 1.0, 1.2), ("make", 1.45, 1.7), ("so", 1.95, 2.1)))
    assert r.calls == []
    assert len(r.ambiguous) == 1 and r.ambiguous[0].canonical == "make"

def test_scratch_that_voids_previous_call():
    r = parse(words(("make", 1.0, 1.3), ("miss", 4.0, 4.3),
                    ("scratch", 6.0, 6.3), ("that", 6.4, 6.7), ("make", 9.0, 9.3)))
    assert [(c.result, c.voided) for c in r.calls] == [
        ("make", False), ("miss", True), ("make", False)]

def test_scratch_words_are_not_calls_or_ambiguous():
    r = parse(words(("scratch", 6.0, 6.3), ("that", 6.4, 6.7)))
    assert r.calls == [] and r.ambiguous == []

def test_note_captured_verbatim_and_excluded_from_calls():
    r = parse(words(("make", 1.0, 1.3), ("note", 5.0, 5.3),
                    ("elbow", 5.5, 5.8), ("stiff", 5.9, 6.2), ("brick", 6.3, 6.6)))
    assert [c.result for c in r.calls] == ["make"]
    assert r.note == "elbow stiff brick"

def test_no_note_returns_none():
    assert parse(words(("make", 1.0, 1.3))).note is None

def test_empty_input():
    r = parse([])
    assert r.calls == [] and r.ambiguous == [] and r.note is None
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_parse.py -v` → import error.

- [ ] **Step 3: Implement**

`src/hoops/parse.py`:
```python
import math
from dataclasses import dataclass, field
from .config import Vocabulary
from .transcribe import Word

@dataclass
class Call:
    result: str
    raw_token: str
    t_s: float
    isolation_s: float
    confidence: float | None
    voided: bool = False

@dataclass(frozen=True)
class Ambiguous:
    text: str
    t_s: float
    isolation_s: float
    canonical: str

@dataclass
class ParseResult:
    calls: list[Call] = field(default_factory=list)
    ambiguous: list[Ambiguous] = field(default_factory=list)
    note: str | None = None

def _split_note(words: list[Word]) -> tuple[list[Word], str | None]:
    idx = None
    for i, w in enumerate(words):
        if w.text == "note":
            idx = i
    if idx is None:
        return words, None
    tail = [w.raw.strip() for w in words[idx + 1:]]
    return words[:idx], (" ".join(tail) if tail else None)

def _scratch_events(words: list[Word]) -> tuple[set[int], list[float]]:
    consumed, times = set(), []
    for i in range(len(words) - 1):
        if (words[i].text == "scratch" and words[i + 1].text == "that"
                and words[i + 1].start - words[i].end <= 0.75):
            consumed.update({i, i + 1})
            times.append(words[i].start)
    return consumed, times

def _isolation(words: list[Word], i: int) -> float:
    before = words[i].start - words[i - 1].end if i > 0 else math.inf
    after = words[i + 1].start - words[i].end if i < len(words) - 1 else math.inf
    return min(before, after)

def parse_words(words: list[Word], vocab: Vocabulary,
                iso_low: float, iso_high: float) -> ParseResult:
    body, note = _split_note(words)
    consumed, scratch_times = _scratch_events(body)
    calls: list[Call] = []
    ambiguous: list[Ambiguous] = []
    for i, w in enumerate(body):
        if i in consumed:
            continue
        canonical = vocab.surface_to_canonical.get(w.text)
        if canonical is None:
            continue
        iso = _isolation(body, i)
        if iso >= iso_high:
            calls.append(Call(result=canonical, raw_token=w.raw.strip(), t_s=w.start,
                              isolation_s=iso, confidence=w.confidence))
        elif iso > iso_low:
            ambiguous.append(Ambiguous(text=w.text, t_s=w.start,
                                       isolation_s=iso, canonical=canonical))
    for t in scratch_times:
        for c in reversed(calls):
            if c.t_s < t and not c.voided:
                c.voided = True
                break
    return ParseResult(calls=calls, ambiguous=ambiguous, note=note)
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_parse.py -v` → 8 PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat: isolation-gated parser with voids, notes, ambiguity band"`

---

### Task 5: Shot rows and session stats (`stats.py`)

**Files:**
- Create: `src/hoops/stats.py`, `tests/test_stats.py`

**Interfaces:**
- Consumes: `Call`, `ParseResult` from `hoops.parse`; `Word` from `hoops.transcribe`.
- Produces:
  - `build_shot_rows(calls: list[Call], session_id: str, session_date_local: str) -> list[dict]` — one dict per call (voided included), keys exactly per PRD §7.6: `session_id, session_date_local, shot_num, result, t_call_s, gap_s, streak_after, voided, isolation_s, confidence, raw_token`. `shot_num` numbers **all** rows 1-indexed (auditable); `gap_s` and `streak_after` computed over **non-voided** rows only (voided row: `gap_s=None`, `streak_after` = streak value unchanged).
  - `build_session_stats(rows: list[dict], parse: ParseResult, words: list[Word], *, session_id: str, session_date_local: str, start_time_local: str, session_len_s: float, transcriber: str, parser_version: str, profanity: list[str]) -> dict` — keys per PRD §7.7: `session_id, session_date_local, start_time_local, shots_to_three, makes, misses, fg_pct, longest_make_streak, longest_miss_streak, time_to_first_make_s, median_gap_s, fastest_gap_s, slowest_gap_s, session_len_s, notes, quote_of_day, profanity_count, words_per_miss, invariants_passed, ambiguous_calls, transcriber, parser_version`. `quote_of_day` starts `""` and `invariants_passed` starts `True` — the pipeline overwrites both.

- [ ] **Step 1: Write the failing tests**

`tests/test_stats.py`:
```python
import pytest
from hoops.parse import Call, ParseResult
from hoops.stats import build_shot_rows, build_session_stats
from hoops.transcribe import words_from_envelope
from conftest import make_env

pytestmark = pytest.mark.unit

def call(result, t, voided=False):
    return Call(result=result, raw_token=result, t_s=t, isolation_s=1.0,
                confidence=0.9, voided=voided)

SEQ = [call("miss", 5.0), call("make", 12.0), call("make", 18.0, voided=True),
       call("miss", 25.0), call("make", 33.0), call("make", 40.0), call("make", 46.0)]

def test_shot_rows_numbering_gaps_streaks():
    rows = build_shot_rows(SEQ, "20260727-061204", "2026-07-27")
    assert [r["shot_num"] for r in rows] == [1, 2, 3, 4, 5, 6, 7]
    assert rows[0]["gap_s"] is None and rows[1]["gap_s"] == 7.0
    assert rows[2]["voided"] is True and rows[2]["gap_s"] is None
    assert rows[3]["gap_s"] == 13.0          # 25.0 - 12.0, skipping voided
    assert [r["streak_after"] for r in rows] == [0, 1, 1, 0, 1, 2, 3]
    assert rows[0]["session_id"] == "20260727-061204"

def test_session_stats():
    rows = build_shot_rows(SEQ, "s", "2026-07-27")
    ws = words_from_envelope(make_env([("blah", i * 1.0, i * 1.0 + 0.3) for i in range(12)]))
    stats = build_session_stats(rows, ParseResult(calls=SEQ, note="tired"), ws,
        session_id="s", session_date_local="2026-07-27", start_time_local="06:12:04",
        session_len_s=50.0, transcriber="whisper-1", parser_version="1",
        profanity=["fuck"])
    assert stats["shots_to_three"] == 6           # non-voided count
    assert stats["makes"] == 4 and stats["misses"] == 2
    assert stats["fg_pct"] == pytest.approx(4 / 6)
    assert stats["longest_make_streak"] == 3
    assert stats["longest_miss_streak"] == 1
    assert stats["time_to_first_make_s"] == 12.0
    assert stats["median_gap_s"] == 7.0           # gaps: 7, 13, 8, 7, 6 → median 7
    assert stats["fastest_gap_s"] == 6.0 and stats["slowest_gap_s"] == 13.0
    assert stats["notes"] == "tired"
    assert stats["words_per_miss"] == 6.0         # 12 words / 2 misses
    assert stats["profanity_count"] == 0
    assert stats["quote_of_day"] == "" and stats["invariants_passed"] is True

def test_profanity_counted():
    rows = build_shot_rows([call("make", 1.0)] * 1, "s", "2026-07-27")
    ws = words_from_envelope(make_env([("Fuck!", 0.0, 0.3), ("ok", 1.0, 1.2)]))
    stats = build_session_stats(rows, ParseResult(), ws, session_id="s",
        session_date_local="2026-07-27", start_time_local="06:00:00",
        session_len_s=2.0, transcriber="t", parser_version="1", profanity=["fuck"])
    assert stats["profanity_count"] == 1

def test_zero_miss_words_per_miss_none():
    rows = build_shot_rows([call("make", 1.0), call("make", 4.0), call("make", 7.0)],
                           "s", "2026-07-27")
    stats = build_session_stats(rows, ParseResult(), [], session_id="s",
        session_date_local="2026-07-27", start_time_local="06:00:00",
        session_len_s=8.0, transcriber="t", parser_version="1", profanity=[])
    assert stats["words_per_miss"] is None
    assert stats["median_gap_s"] == 3.0
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_stats.py -v` → import error.

- [ ] **Step 3: Implement**

`src/hoops/stats.py`:
```python
import statistics
from .parse import Call, ParseResult
from .transcribe import Word

def build_shot_rows(calls: list[Call], session_id: str, session_date_local: str) -> list[dict]:
    rows, prev_t, streak = [], None, 0
    for i, c in enumerate(calls, start=1):
        gap = None
        if not c.voided:
            if prev_t is not None:
                gap = round(c.t_s - prev_t, 3)
            prev_t = c.t_s
            streak = streak + 1 if c.result == "make" else 0
        rows.append({
            "session_id": session_id, "session_date_local": session_date_local,
            "shot_num": i, "result": c.result, "t_call_s": c.t_s, "gap_s": gap,
            "streak_after": streak, "voided": c.voided, "isolation_s": c.isolation_s,
            "confidence": c.confidence, "raw_token": c.raw_token,
        })
    return rows

def _longest_streak(results: list[str], target: str) -> int:
    best = cur = 0
    for r in results:
        cur = cur + 1 if r == target else 0
        best = max(best, cur)
    return best

def build_session_stats(rows, parse: ParseResult, words: list[Word], *,
                        session_id, session_date_local, start_time_local,
                        session_len_s, transcriber, parser_version, profanity) -> dict:
    live = [r for r in rows if not r["voided"]]
    results = [r["result"] for r in live]
    makes, misses = results.count("make"), results.count("miss")
    gaps = [r["gap_s"] for r in live if r["gap_s"] is not None]
    first_make = next((r["t_call_s"] for r in live if r["result"] == "make"), None)
    pset = set(profanity)
    return {
        "session_id": session_id, "session_date_local": session_date_local,
        "start_time_local": start_time_local,
        "shots_to_three": len(live),
        "makes": makes, "misses": misses,
        "fg_pct": (makes / len(live)) if live else None,
        "longest_make_streak": _longest_streak(results, "make"),
        "longest_miss_streak": _longest_streak(results, "miss"),
        "time_to_first_make_s": first_make,
        "median_gap_s": statistics.median(gaps) if gaps else None,
        "fastest_gap_s": min(gaps) if gaps else None,
        "slowest_gap_s": max(gaps) if gaps else None,
        "session_len_s": session_len_s,
        "notes": parse.note or "",
        "quote_of_day": "",
        "profanity_count": sum(1 for w in words if w.text in pset),
        "words_per_miss": (len(words) / misses) if misses else None,
        "invariants_passed": True,
        "ambiguous_calls": len(parse.ambiguous),
        "transcriber": transcriber, "parser_version": parser_version,
    }
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_stats.py -v` → 4 PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat: shot rows and session stats per schema"`

---

### Task 6: Invariants I1–I6 (`invariants.py`)

**Files:**
- Create: `src/hoops/invariants.py`, `tests/test_invariants.py`

**Interfaces:**
- Consumes: shot-row dicts from `build_shot_rows`; `Vocabulary`.
- Produces:
  - `Violation` dataclass: `id: str` ("I1".."I6"), `message: str`.
  - `check_invariants(rows: list[dict], *, min_gap_s: float, max_gap_s: float, vocab: Vocabulary) -> list[Violation]` — empty list = pass. Operates on non-voided rows. I7 (session dir exists) is filesystem-level and lives in the pipeline (Task 12), not here.

- [ ] **Step 1: Write the failing tests**

`tests/test_invariants.py`:
```python
import pytest
from hoops.config import Vocabulary
from hoops.invariants import check_invariants
from hoops.parse import Call
from hoops.stats import build_shot_rows

pytestmark = pytest.mark.unit
V = Vocabulary.from_dict("default", {"make": ["make", "splash"], "miss": ["miss", "brick"]})

def rows_from(seq, spacing=6.0, start=5.0):
    calls = [Call(result=r, raw_token=r, t_s=start + i * spacing, isolation_s=1.0,
                  confidence=0.9) for i, r in enumerate(seq)]
    return build_shot_rows(calls, "s", "2026-07-27")

def check(rows): return check_invariants(rows, min_gap_s=1.5, max_gap_s=120, vocab=V)

def test_clean_session_passes():
    assert check(rows_from(["miss", "make", "miss", "make", "make", "make"])) == []

def test_i1_not_ending_on_three_makes():
    ids = [v.id for v in check(rows_from(["make", "make", "miss"]))]
    assert "I1" in ids

def test_i2_fewer_than_three_shots():
    ids = [v.id for v in check(rows_from(["make", "make"]))]
    assert "I2" in ids

def test_i3_calls_too_close():
    rows = rows_from(["miss", "make", "make", "make"], spacing=1.0)
    assert "I3" in [v.id for v in check(rows)]

def test_i4_gap_too_long():
    rows = rows_from(["miss", "make", "make", "make"], spacing=130.0)
    assert "I4" in [v.id for v in check(rows)]

def test_i5_unknown_raw_token():
    rows = rows_from(["miss", "make", "make", "make"])
    rows[0]["raw_token"] = "swoosh"
    assert "I5" in [v.id for v in check(rows)]

def test_i6_early_triple_make():
    seq = ["make", "make", "make", "miss", "make", "make", "make"]
    assert "I6" in [v.id for v in check(rows_from(seq))]

def test_voided_rows_excluded():
    calls = [Call("make", "make", 5.0, 1.0, 0.9), Call("make", "make", 6.0, 1.0, 0.9, voided=True),
             Call("make", "make", 11.0, 1.0, 0.9), Call("make", "make", 17.0, 1.0, 0.9)]
    rows = build_shot_rows(calls, "s", "2026-07-27")
    assert check(rows) == []   # voided 1s-gap row ignored; ends on three makes
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_invariants.py -v` → import error.

- [ ] **Step 3: Implement**

`src/hoops/invariants.py`:
```python
from dataclasses import dataclass
from .config import Vocabulary

@dataclass(frozen=True)
class Violation:
    id: str
    message: str

def check_invariants(rows: list[dict], *, min_gap_s: float, max_gap_s: float,
                     vocab: Vocabulary) -> list[Violation]:
    v: list[Violation] = []
    live = [r for r in rows if not r["voided"]]
    results = [r["result"] for r in live]

    if len(live) < 3:
        v.append(Violation("I2", f"only {len(live)} non-voided calls (< 3)"))
    if results[-3:] != ["make", "make", "make"]:
        v.append(Violation("I1", f"final three calls are {results[-3:]}, not all makes"))
    for r in live:
        if r["gap_s"] is not None and r["gap_s"] < min_gap_s:
            v.append(Violation("I3", f"shot {r['shot_num']}: gap {r['gap_s']}s < {min_gap_s}s"))
        if r["gap_s"] is not None and r["gap_s"] > max_gap_s:
            v.append(Violation("I4", f"shot {r['shot_num']}: gap {r['gap_s']}s > {max_gap_s}s"))
    known = set(vocab.surface_to_canonical)
    for r in rows:
        from .transcribe import normalize_token
        if normalize_token(r["raw_token"]) not in known:
            v.append(Violation("I5", f"shot {r['shot_num']}: raw_token {r['raw_token']!r} not in vocabulary"))
    streak = 0
    for i, res in enumerate(results):
        streak = streak + 1 if res == "make" else 0
        if streak == 3 and i != len(results) - 1:
            v.append(Violation("I6", f"three-make run ends at call {i + 1}, before the final call"))
            break
    return v
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_invariants.py -v` → 8 PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat: invariants I1-I6"`

---

### Task 7: Session folders and persistence (`session.py`)

**Files:**
- Create: `src/hoops/session.py`, `tests/test_session.py`

**Interfaces:**
- Consumes: envelope dict from `hoops.transcribe`; row/stats dicts from `hoops.stats`.
- Produces:
  - `session_id_for(path: Path, tz: ZoneInfo) -> tuple[str, str]` — returns `(sid, source)`; sid `"YYYYMMDD-HHMMSS"`; source `"filename"` when the name matches `hoops__YYYYMMDD-HHMMSS.m4a` (case-insensitive), else `"mtime"` (file mtime in `tz`). Spec §3.1.
  - `session_dir_for(root: Path, sid: str) -> Path` — `root/YYYY/MM/hoops__<sid>`.
  - `sid_date_and_time(sid: str) -> tuple[str, str]` — `("2026-07-27", "06:12:04")`.
  - `write_transcript(sdir: Path, env: dict) -> None` — writes `transcript.json` (envelope verbatim, indent=2) and `transcript.txt` (plain text).
  - `write_shots_csv(sdir: Path, rows: list[dict]) -> None` — header exactly the 11 schema columns, empty string for `None`.
  - `write_session_json(sdir: Path, stats: dict) -> None` / `read_session_json(sdir: Path) -> dict`.
  - `read_envelope(sdir: Path) -> dict`.
  - `find_session_dirs(root: Path) -> list[Path]` — sorted dirs containing `transcript.json`.

- [ ] **Step 1: Write the failing tests**

`tests/test_session.py`:
```python
import csv, json, os
import pytest
from pathlib import Path
from zoneinfo import ZoneInfo
from hoops.session import (session_id_for, session_dir_for, sid_date_and_time,
                           write_transcript, write_shots_csv, write_session_json,
                           read_session_json, read_envelope, find_session_dirs)
from conftest import make_env

pytestmark = pytest.mark.unit
TZ = ZoneInfo("America/Los_Angeles")

def test_sid_from_filename(tmp_path):
    f = tmp_path / "hoops__20260727-061204.m4a"; f.write_bytes(b"x")
    assert session_id_for(f, TZ) == ("20260727-061204", "filename")

def test_sid_from_mtime(tmp_path):
    f = tmp_path / "dev01.m4a"; f.write_bytes(b"x")
    ts = 1753621200.0  # fixed epoch
    os.utime(f, (ts, ts))
    sid, source = session_id_for(f, TZ)
    assert source == "mtime" and len(sid) == 15 and sid[8] == "-"

def test_session_dir_layout(tmp_path):
    d = session_dir_for(tmp_path, "20260727-061204")
    assert d == tmp_path / "2026" / "07" / "hoops__20260727-061204"

def test_sid_date_and_time():
    assert sid_date_and_time("20260727-061204") == ("2026-07-27", "06:12:04")

def test_write_and_read_roundtrip(tmp_path):
    sdir = tmp_path / "s"; sdir.mkdir()
    env = make_env([("make", 1.0, 1.3)])
    write_transcript(sdir, env)
    assert read_envelope(sdir) == env
    assert (sdir / "transcript.txt").read_text() == "make"
    rows = [{"session_id": "s", "session_date_local": "2026-07-27", "shot_num": 1,
             "result": "make", "t_call_s": 1.0, "gap_s": None, "streak_after": 1,
             "voided": False, "isolation_s": 2.0, "confidence": None, "raw_token": "make"}]
    write_shots_csv(sdir, rows)
    with (sdir / "shots.csv").open() as f:
        rec = list(csv.DictReader(f))
    assert rec[0]["result"] == "make" and rec[0]["gap_s"] == "" and rec[0]["confidence"] == ""
    write_session_json(sdir, {"session_id": "s", "makes": 1})
    assert read_session_json(sdir)["makes"] == 1

def test_find_session_dirs(tmp_path):
    a = tmp_path / "2026" / "07" / "hoops__20260727-061204"; a.mkdir(parents=True)
    (a / "transcript.json").write_text("{}")
    (tmp_path / "2026" / "07" / "empty").mkdir()
    assert find_session_dirs(tmp_path) == [a]
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_session.py -v` → import error.

- [ ] **Step 3: Implement**

`src/hoops/session.py`:
```python
import csv, json, re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SHOT_COLUMNS = ["session_id", "session_date_local", "shot_num", "result", "t_call_s",
                "gap_s", "streak_after", "voided", "isolation_s", "confidence", "raw_token"]
_PREFIX_RE = re.compile(r"^hoops__(\d{8}-\d{6})\.m4a$", re.IGNORECASE)

def session_id_for(path: Path, tz: ZoneInfo) -> tuple[str, str]:
    m = _PREFIX_RE.match(path.name)
    if m:
        return m.group(1), "filename"
    dt = datetime.fromtimestamp(path.stat().st_mtime, tz)
    return dt.strftime("%Y%m%d-%H%M%S"), "mtime"

def session_dir_for(root: Path, sid: str) -> Path:
    return root / sid[:4] / sid[4:6] / f"hoops__{sid}"

def sid_date_and_time(sid: str) -> tuple[str, str]:
    d, t = sid.split("-")
    return f"{d[:4]}-{d[4:6]}-{d[6:]}", f"{t[:2]}:{t[2:4]}:{t[4:]}"

def write_transcript(sdir: Path, env: dict) -> None:
    (sdir / "transcript.json").write_text(json.dumps(env, indent=2, ensure_ascii=False))
    (sdir / "transcript.txt").write_text(env["response"].get("text", ""))

def write_shots_csv(sdir: Path, rows: list[dict]) -> None:
    with (sdir / "shots.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SHOT_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r[k] is None else r[k]) for k in SHOT_COLUMNS})

def write_session_json(sdir: Path, stats: dict) -> None:
    (sdir / "session.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False))

def read_session_json(sdir: Path) -> dict:
    return json.loads((sdir / "session.json").read_text())

def read_envelope(sdir: Path) -> dict:
    return json.loads((sdir / "transcript.json").read_text())

def find_session_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(p.parent for p in root.rglob("transcript.json"))
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_session.py -v` → 6 PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat: session id derivation and folder persistence"`

---

### Task 8: Charts and reports (`render.py`)

**Files:**
- Create: `src/hoops/render.py`, `tests/test_render.py`

**Interfaces:**
- Consumes: row dicts, stats dict, `Narrative` (defined here as a dataclass to avoid a circular import; Task 10 imports it from `hoops.render`).
- Produces:
  - `Narrative` dataclass: `headline: str`, `recap: str`, `quote: str`, `quote_t_s: float | None`.
  - `render_strip(rows: list[dict], out_png: Path) -> None` — circles at `t_call_s` on a horizontal time axis; filled = make, hollow = miss, grey × = voided; closing three non-voided makes underlined (PRD §7.8). Uses matplotlib `Agg` backend.
  - `render_report(stats: dict, rows: list[dict], narrative: Narrative | None, flags: list[str], out_html: Path, img_src: str) -> None` — self-contained HTML; `img_src` is `"strip.png"` for on-disk viewing or `"cid:strip"` for email. Flags block rendered only when non-empty.
  - `render_gallery(entries: list[dict], out_html: Path) -> None` — entry keys: `name, expected (list[str]), got (list[str]), strip_rel (str), flags (list[str]), note (str)`; mismatched sequences highlighted red.

- [ ] **Step 1: Write the failing tests**

`tests/test_render.py`:
```python
import pytest
from hoops.render import Narrative, render_strip, render_report, render_gallery

pytestmark = pytest.mark.unit

ROWS = [
    {"shot_num": 1, "result": "miss", "t_call_s": 5.0, "voided": False},
    {"shot_num": 2, "result": "make", "t_call_s": 12.0, "voided": False},
    {"shot_num": 3, "result": "make", "t_call_s": 15.0, "voided": True},
    {"shot_num": 4, "result": "make", "t_call_s": 20.0, "voided": False},
    {"shot_num": 5, "result": "make", "t_call_s": 26.0, "voided": False},
    {"shot_num": 6, "result": "make", "t_call_s": 31.0, "voided": False},
]
STATS = {"session_id": "20260727-061204", "session_date_local": "2026-07-27",
         "shots_to_three": 5, "makes": 4, "misses": 1, "fg_pct": 0.8,
         "longest_make_streak": 4, "longest_miss_streak": 1, "median_gap_s": 6.0,
         "session_len_s": 35.0, "notes": "", "ambiguous_calls": 0}

def test_render_strip_writes_png(tmp_path):
    out = tmp_path / "strip.png"
    render_strip(ROWS, out)
    assert out.exists() and out.stat().st_size > 1000

def test_render_report_full(tmp_path):
    out = tmp_path / "report.html"
    n = Narrative("Cold start, hot finish", "Recap here.", "ugh come on", 14.2)
    render_report(STATS, ROWS, n, ["I4: gap 130s > 120s"], out, img_src="strip.png")
    html = out.read_text()
    assert "Cold start, hot finish" in html and "strip.png" in html
    assert "I4" in html and "ugh come on" in html

def test_render_report_no_narrative_no_flags(tmp_path):
    out = tmp_path / "report.html"
    render_report(STATS, ROWS, None, [], out, img_src="cid:strip")
    html = out.read_text()
    assert "cid:strip" in html and "Flags" not in html

def test_render_gallery(tmp_path):
    out = tmp_path / "index.html"
    render_gallery([{"name": "dev01", "expected": ["make"], "got": ["make", "miss"],
                     "strip_rel": "dev01/strip.png", "flags": [], "note": ""}], out)
    html = out.read_text()
    assert "dev01" in html and "mismatch" in html
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_render.py -v` → import error.

- [ ] **Step 3: Implement**

`src/hoops/render.py`:
```python
import html as _html
from dataclasses import dataclass
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

@dataclass(frozen=True)
class Narrative:
    headline: str
    recap: str
    quote: str
    quote_t_s: float | None

def render_strip(rows: list[dict], out_png: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 1.6), dpi=150)
    live = [r for r in rows if not r["voided"]]
    for r in rows:
        t = r["t_call_s"]
        if r["voided"]:
            ax.plot(t, 0, marker="x", color="#999999", markersize=9)
        elif r["result"] == "make":
            ax.plot(t, 0, marker="o", color="#1a7f37", markersize=11)
        else:
            ax.plot(t, 0, marker="o", markerfacecolor="white",
                    markeredgecolor="#c0392b", markeredgewidth=2, markersize=11)
    if len(live) >= 3 and all(r["result"] == "make" for r in live[-3:]):
        ax.plot([live[-3]["t_call_s"], live[-1]["t_call_s"]], [-0.35, -0.35],
                color="#1a7f37", linewidth=3, solid_capstyle="round")
    ax.set_ylim(-0.8, 0.8)
    ax.set_yticks([])
    ax.set_xlabel("seconds")
    for side in ["left", "top", "right"]:
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_png)
    plt.close(fig)

def _stat_cells(stats: dict) -> str:
    fg = stats.get("fg_pct")
    items = [("FG%", f"{fg:.0%}" if fg is not None else "—"),
             ("Make streak", stats.get("longest_make_streak", "—")),
             ("Miss streak", stats.get("longest_miss_streak", "—")),
             ("Length", f"{stats.get('session_len_s', 0):.0f}s"),
             ("Median gap", f"{stats['median_gap_s']:.1f}s" if stats.get("median_gap_s") else "—")]
    return "".join(f"<td style='padding:6px 14px;text-align:center'>"
                   f"<div style='font-size:20px;font-weight:700'>{v}</div>"
                   f"<div style='font-size:11px;color:#666'>{k}</div></td>" for k, v in items)

def render_report(stats, rows, narrative, flags, out_html: Path, img_src: str) -> None:
    e = _html.escape
    parts = [f"<div style='font-family:-apple-system,Helvetica,sans-serif;max-width:640px;margin:auto'>"]
    if narrative:
        parts.append(f"<h2 style='margin-bottom:4px'>{e(narrative.headline)}</h2>")
    parts.append(f"<div style='font-size:64px;font-weight:800;line-height:1'>{stats['shots_to_three']}"
                 f"<span style='font-size:16px;font-weight:400;color:#666'> shots to close it out</span></div>")
    parts.append(f"<img src='{img_src}' alt='shot strip' style='max-width:100%;margin:12px 0'>")
    parts.append(f"<table style='border-collapse:collapse'><tr>{_stat_cells(stats)}</tr></table>")
    if narrative:
        parts.append(f"<p>{e(narrative.recap)}</p>")
        q_t = f" <span style='color:#999'>@{narrative.quote_t_s:.0f}s</span>" if narrative.quote_t_s is not None else ""
        parts.append(f"<blockquote style='border-left:3px solid #ccc;margin:8px 0;padding:4px 12px;"
                     f"color:#444'>“{e(narrative.quote)}”{q_t}</blockquote>")
    if stats.get("notes"):
        parts.append(f"<p><b>Note:</b> {e(stats['notes'])}</p>")
    if flags:
        lis = "".join(f"<li>{e(f)}</li>" for f in flags)
        parts.append(f"<div style='background:#fff3cd;border:1px solid #ffe69c;padding:8px 12px;"
                     f"border-radius:6px'><b>Flags</b><ul style='margin:4px 0'>{lis}</ul></div>")
    parts.append(f"<p style='color:#999;font-size:11px'>Session {stats['session_id']} · "
                 f"{stats['session_date_local']}</p></div>")
    out_html.write_text("\n".join(parts))

def render_gallery(entries: list[dict], out_html: Path) -> None:
    e = _html.escape
    rows_html = []
    for en in entries:
        match = en["expected"] == en["got"] if en["expected"] else None
        badge = ("<span style='color:#1a7f37'>match</span>" if match
                 else "<span style='color:#c0392b'>mismatch</span>" if match is False
                 else "<span style='color:#999'>unlabeled</span>")
        rows_html.append(
            f"<div style='border-bottom:1px solid #ddd;padding:16px 0'>"
            f"<h3>{e(en['name'])} — {badge}</h3>"
            f"<img src='{e(en['strip_rel'])}' style='max-width:100%'>"
            f"<div>expected: <code>{e(' '.join(en['expected']) or '—')}</code></div>"
            f"<div>got: <code>{e(' '.join(en['got']))}</code></div>"
            f"<div>{''.join('<div>⚠ ' + e(f) + '</div>' for f in en['flags'])}</div>"
            f"<div style='color:#666'>{e(en.get('note', ''))}</div></div>")
    out_html.write_text("<div style='font-family:-apple-system,sans-serif;max-width:800px;"
                        "margin:auto'><h1>Fixture gallery</h1>" + "\n".join(rows_html) + "</div>")
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_render.py -v` → 4 PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat: shot strip, HTML report, fixture gallery"`

---

### Task 9: LLM repair pass (`repair.py`)

**Files:**
- Create: `src/hoops/repair.py`, `tests/test_repair.py`

**Interfaces:**
- Consumes: envelope, row dicts, `Violation` list, `Vocabulary`; `Call` from `hoops.parse`.
- Produces:
  - `attempt_repair(env: dict, rows: list[dict], violations: list[Violation], vocab: Vocabulary, model: str) -> list[Call] | None` — asks claude for a corrected call list constrained by the stop rule (PRD §9.2); returns `Call` objects (with `isolation_s=0.0`, `confidence=None`) or `None` on any API/parse failure. **Never** re-validates itself — the pipeline re-runs `check_invariants` on the result and keeps the original rows if it still fails.
  - `extract_json(text: str)` — first JSON value found in a string (handles code fences / prose around it).

- [ ] **Step 1: Write the failing tests**

`tests/test_repair.py`:
```python
import json
import pytest
from hoops.config import Vocabulary
from hoops.invariants import Violation
from hoops.repair import attempt_repair, extract_json
from conftest import make_env

pytestmark = pytest.mark.unit
V = Vocabulary.from_dict("default", {"make": ["make", "splash"], "miss": ["miss", "brick"]})

def _fake_anthropic(monkeypatch, reply_text):
    class Msg:
        content = [type("T", (), {"text": reply_text})()]
    class Messages:
        def create(self, **kw): return Msg()
    class FakeClient:
        def __init__(self): self.messages = Messages()
    monkeypatch.setattr("hoops.repair.anthropic.Anthropic", lambda: FakeClient())

def test_extract_json_with_fence():
    assert extract_json("```json\n[{\"a\": 1}]\n```") == [{"a": 1}]
    assert extract_json("here: {\"b\": 2} done") == {"b": 2}

def test_repair_returns_calls(monkeypatch):
    reply = json.dumps([{"result": "miss", "t_s": 5.0, "raw_token": "miss"},
                        {"result": "make", "t_s": 12.0, "raw_token": "make"},
                        {"result": "make", "t_s": 18.0, "raw_token": "make"},
                        {"result": "make", "t_s": 24.0, "raw_token": "make"}])
    _fake_anthropic(monkeypatch, reply)
    env = make_env([("miss", 5.0, 5.3)])
    calls = attempt_repair(env, [], [Violation("I1", "x")], V, model="claude-sonnet-5")
    assert [c.result for c in calls] == ["miss", "make", "make", "make"]
    assert calls[0].t_s == 5.0 and calls[0].voided is False

def test_repair_bad_reply_returns_none(monkeypatch):
    _fake_anthropic(monkeypatch, "I cannot help with that")
    assert attempt_repair(make_env([]), [], [Violation("I1", "x")], V, "m") is None

def test_repair_api_error_returns_none(monkeypatch):
    class Boom:
        def __init__(self): raise RuntimeError("api down")
    monkeypatch.setattr("hoops.repair.anthropic.Anthropic", Boom)
    assert attempt_repair(make_env([]), [], [Violation("I1", "x")], V, "m") is None
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_repair.py -v` → import error.

- [ ] **Step 3: Implement**

`src/hoops/repair.py`:
```python
import json
import anthropic
from .config import Vocabulary
from .invariants import Violation
from .parse import Call
from .transcribe import envelope_text

def extract_json(text: str):
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "[{":
            try:
                obj, _ = dec.raw_decode(text[i:])
                return obj
            except ValueError:
                continue
    return None

_SYSTEM = """You reconstruct a basketball free-throw call sequence from a noisy transcript.
Hard constraints:
- The session ended the moment three consecutive makes occurred; the sequence must end
  with exactly one run of three consecutive makes, and no earlier run of three.
- Calls come only from this vocabulary (surface -> canonical): {vocab}
- A real call is an isolated utterance; words inside continuous commentary are not calls.
- "scratch that" voids the preceding call.
Return ONLY a JSON array of objects: {{"result": "make"|"miss", "t_s": <float seconds>,
"raw_token": "<surface form>"}} in time order, voided calls omitted. No other text."""

def attempt_repair(env: dict, rows: list[dict], violations: list[Violation],
                   vocab: Vocabulary, model: str) -> list[Call] | None:
    words = env["response"].get("words") or []
    word_dump = " ".join(f"{w['word'].strip()}@{w['start']:.2f}" for w in words)
    user = (f"Transcript words with start times:\n{word_dump}\n\n"
            f"Full text: {envelope_text(env)}\n\n"
            f"Deterministic parse produced {len(rows)} calls but violated: "
            + "; ".join(f"{v.id}: {v.message}" for v in violations)
            + "\nReconstruct the true call sequence.")
    try:
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=model, max_tokens=1000,
            system=_SYSTEM.format(vocab=json.dumps(vocab.surface_to_canonical)),
            messages=[{"role": "user", "content": user}])
        data = extract_json(msg.content[0].text)
        if not isinstance(data, list) or not data:
            return None
        calls = []
        for d in data:
            if d.get("result") not in ("make", "miss"):
                return None
            calls.append(Call(result=d["result"], raw_token=str(d.get("raw_token", d["result"])),
                              t_s=float(d["t_s"]), isolation_s=0.0, confidence=None))
        return sorted(calls, key=lambda c: c.t_s)
    except Exception:
        return None
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_repair.py -v` → 4 PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat: LLM repair pass constrained by stop rule"`

---

### Task 10: Narrative with guardrails (`narrative.py`)

**Files:**
- Create: `src/hoops/narrative.py`, `tests/test_narrative.py`

**Interfaces:**
- Consumes: stats dict, envelope; `Narrative` from `hoops.render`.
- Produces:
  - `generate_narrative(stats: dict, env: dict, model: str) -> Narrative | None` — headline + ≤3-sentence recap + verbatim quote with timestamp (PRD §9.3). Returns `None` on API failure **or any guardrail violation**: any digit (0-9) in headline/recap, quote not a verbatim substring of the transcript text (whitespace-normalized, case-insensitive), or recap >3 sentences. The pipeline treats `None` as "send without narrative blocks".

- [ ] **Step 1: Write the failing tests**

`tests/test_narrative.py`:
```python
import json
import pytest
from hoops.narrative import generate_narrative
from conftest import make_env

pytestmark = pytest.mark.unit
STATS = {"shots_to_three": 8, "makes": 4, "misses": 4, "fg_pct": 0.5,
         "longest_make_streak": 3, "longest_miss_streak": 2, "median_gap_s": 6.0,
         "session_len_s": 60.0, "notes": ""}
ENV = make_env([("come", 1.0, 1.2), ("on", 1.3, 1.5), ("make", 5.0, 5.3)])

def _fake(monkeypatch, reply):
    class Msg:
        content = [type("T", (), {"text": reply})()]
    class Messages:
        def create(self, **kw): return Msg()
    class FakeClient:
        def __init__(self): self.messages = Messages()
    monkeypatch.setattr("hoops.narrative.anthropic.Anthropic", lambda: FakeClient())

def good_reply(quote="come on", t=1.0):
    return json.dumps({"headline": "Slow start, clean finish",
                       "recap": "A rough opening stretch. Then the rhythm arrived.",
                       "quote": quote, "quote_t_s": t})

def test_valid_narrative(monkeypatch):
    _fake(monkeypatch, good_reply())
    n = generate_narrative(STATS, ENV, "m")
    assert n.headline == "Slow start, clean finish" and n.quote == "come on"

def test_digit_in_recap_rejected(monkeypatch):
    bad = json.dumps({"headline": "ok", "recap": "Took 8 shots today.",
                      "quote": "come on", "quote_t_s": 1.0})
    _fake(monkeypatch, bad)
    assert generate_narrative(STATS, ENV, "m") is None

def test_non_verbatim_quote_rejected(monkeypatch):
    _fake(monkeypatch, good_reply(quote="lets go champ"))
    assert generate_narrative(STATS, ENV, "m") is None

def test_four_sentence_recap_rejected(monkeypatch):
    bad = json.dumps({"headline": "ok", "recap": "One. Two. Three. Four.",
                      "quote": "come on", "quote_t_s": 1.0})
    _fake(monkeypatch, bad)
    assert generate_narrative(STATS, ENV, "m") is None

def test_api_failure_returns_none(monkeypatch):
    class Boom:
        def __init__(self): raise RuntimeError("down")
    monkeypatch.setattr("hoops.narrative.anthropic.Anthropic", Boom)
    assert generate_narrative(STATS, ENV, "m") is None
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_narrative.py -v` → import error.

- [ ] **Step 3: Implement**

`src/hoops/narrative.py`:
```python
import json, re
import anthropic
from .render import Narrative
from .repair import extract_json
from .transcribe import envelope_text

_SYSTEM = """You are a beat writer filing a very short recap of a tiny basketball game:
one person shooting at a closet hoop until they make three in a row. Dry and specific,
not enthusiastic. Rules, all hard:
- NO digits or numerals anywhere. Numbers you receive are context only; the email
  template injects all figures.
- NO comparative or historical claims (no "best", "fastest yet", "this week"). You see
  one session and nothing else.
- Recap: at most three sentences. Within-session dynamics only.
- quote: an EXACT verbatim substring of the transcript, with its start time.
Return ONLY JSON: {"headline": str, "recap": str, "quote": str, "quote_t_s": float}"""

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()

def generate_narrative(stats: dict, env: dict, model: str) -> Narrative | None:
    try:
        client = anthropic.Anthropic()
        payload = (f"Session stats (context only, do not restate numbers): "
                   f"{json.dumps({k: stats.get(k) for k in ['shots_to_three', 'makes', 'misses', 'longest_make_streak', 'longest_miss_streak', 'median_gap_s', 'session_len_s', 'notes']})}\n\n"
                   f"Transcript: {envelope_text(env)}")
        msg = client.messages.create(model=model, max_tokens=500, system=_SYSTEM,
                                     messages=[{"role": "user", "content": payload}])
        data = extract_json(msg.content[0].text)
        if not isinstance(data, dict):
            return None
        headline, recap = str(data["headline"]), str(data["recap"])
        quote = str(data["quote"])
        if re.search(r"\d", headline + recap):
            return None
        if len(re.findall(r"[.!?]+", recap)) > 3:
            return None
        if _norm(quote) not in _norm(envelope_text(env)):
            return None
        t = data.get("quote_t_s")
        return Narrative(headline=headline, recap=recap, quote=quote,
                         quote_t_s=float(t) if t is not None else None)
    except Exception:
        return None
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_narrative.py -v` → 5 PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat: guardrailed narrative generation"`

---

### Task 11: Email (`mailer.py`)

**Files:**
- Create: `src/hoops/mailer.py`, `tests/test_mailer.py`

**Interfaces:**
- Consumes: stats dict, session dir (containing artifacts), `Narrative | None`, flags, `Config`.
- Produces:
  - `build_subject(stats: dict, flags: list[str]) -> str` — `🏀 Mon Jul 27 — 8 shots to close it out (4/8)`; prefix `⚠️ ` when flags non-empty. `(makes/shots_to_three)`.
  - `build_email(stats: dict, session_dir: Path, narrative, flags: list[str], cfg: Config) -> EmailMessage` — HTML body from `render_report` with `img_src="cid:strip"`; `strip.png` attached as related inline part with `Content-ID: <strip>`; every existing artifact in the session folder attached (`shots.csv, session.json, transcript.json, transcript.txt, report.html, strip.png, audio.m4a`) (PRD §7.8).
  - `send(msg: EmailMessage, cfg: Config) -> None` — `smtplib.SMTP_SSL(cfg.email["smtp_host"], cfg.email["smtp_port"])`, login `cfg.email["from"]` / env `GMAIL_APP_PASSWORD`.

- [ ] **Step 1: Write the failing tests**

`tests/test_mailer.py`:
```python
import pytest
from pathlib import Path
from hoops.config import load_config
from hoops.mailer import build_subject, build_email

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[1]
STATS = {"session_id": "20260727-061204", "session_date_local": "2026-07-27",
         "shots_to_three": 8, "makes": 4, "misses": 4, "fg_pct": 0.5,
         "longest_make_streak": 3, "longest_miss_streak": 2, "median_gap_s": 6.0,
         "session_len_s": 60.0, "notes": "", "ambiguous_calls": 0}

def test_subject():
    assert build_subject(STATS, []) == "🏀 Mon Jul 27 — 8 shots to close it out (4/8)"
    assert build_subject(STATS, ["I1: bad"]).startswith("⚠️ 🏀")

def test_build_email_attachments(tmp_path):
    cfg = load_config(REPO / "config.yaml")
    sdir = tmp_path / "hoops__20260727-061204"; sdir.mkdir()
    for name, data in [("shots.csv", b"a"), ("session.json", b"{}"),
                       ("transcript.json", b"{}"), ("transcript.txt", b"t"),
                       ("strip.png", b"\x89PNG_fake"), ("audio.m4a", b"m4a")]:
        (sdir / name).write_bytes(data)
    msg = build_email(STATS, sdir, None, [], cfg)
    assert msg["To"] == cfg.email["to"] and "8 shots" in msg["Subject"]
    names = {p.get_filename() for p in msg.iter_attachments()}
    assert {"shots.csv", "session.json", "transcript.json",
            "transcript.txt", "strip.png", "audio.m4a"} <= names
    body = msg.get_body(("html",)).get_content()
    assert "cid:strip" in body
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_mailer.py -v` → import error.

- [ ] **Step 3: Implement**

`src/hoops/mailer.py`:
```python
import mimetypes, os, smtplib
from datetime import date
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from .config import Config
from .render import render_report

ARTIFACTS = ["shots.csv", "session.json", "transcript.json", "transcript.txt",
             "report.html", "strip.png", "audio.m4a"]

def build_subject(stats: dict, flags: list[str]) -> str:
    d = date.fromisoformat(stats["session_date_local"])
    core = (f"🏀 {d.strftime('%a %b')} {d.day} — {stats['shots_to_three']} shots "
            f"to close it out ({stats['makes']}/{stats['shots_to_three']})")
    return ("⚠️ " + core) if flags else core

def build_email(stats: dict, session_dir: Path, narrative, flags: list[str],
                cfg: Config) -> EmailMessage:
    msg = EmailMessage()
    msg["From"], msg["To"] = cfg.email["from"], cfg.email["to"]
    msg["Subject"] = build_subject(stats, flags)
    tmp = session_dir / "_email_body.html"
    render_report(stats, [], narrative, flags, tmp, img_src="cid:strip")
    body = tmp.read_text(); tmp.unlink()
    msg.set_content("Session report attached (HTML email).")
    msg.add_alternative(body, subtype="html")
    strip = session_dir / "strip.png"
    if strip.exists():
        msg.get_payload()[1].add_related(strip.read_bytes(), maintype="image",
                                         subtype="png", cid="<strip>",
                                         filename="strip.png")
    for name in ARTIFACTS:
        p = session_dir / name
        if not p.exists():
            continue
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(p.read_bytes(), maintype=maintype, subtype=subtype,
                           filename=name)
    return msg

def send(msg: EmailMessage, cfg: Config) -> None:
    password = os.environ["GMAIL_APP_PASSWORD"]
    with smtplib.SMTP_SSL(cfg.email["smtp_host"], int(cfg.email["smtp_port"])) as s:
        s.login(cfg.email["from"], password)
        s.send_message(msg)
```

Note: `render_report` is called with `rows=[]` for the email body — the strip PNG carries the sequence; rows are only used by the report for nothing else in the current template (they're a parameter for future use, and the on-disk `report.html` written by the pipeline passes real rows).

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_mailer.py -v` → 2 PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat: email builder with CID strip and full artifact attachments"`

---

### Task 12: Pipeline (`pipeline.py`) — process, replay, degenerate inputs

**Files:**
- Create: `src/hoops/pipeline.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: everything above. Audio duration via `mutagen.mp4.MP4(str(path)).info.length`.
- Produces:
  - `Outcome` dataclass: `status: str` ("ok"|"duplicate"|"rejected"|"needs_review"), `sid: str`, `session_dir: Path | None`, `stats: dict | None`, `rows: list[dict]`, `flags: list[str]`.
  - `process_file(path: Path, cfg: Config, transcriber, *, email: bool, out_root: Path | None = None, archive: str = "copy", vocab_name: str | None = None, cached_env: dict | None = None, repair_enabled: bool = True) -> Outcome`.
  - `replay_session(sdir: Path, cfg: Config) -> Outcome` — stages 4–8 from `transcript.json`; preserves existing `quote_of_day` from `session.json` if present; never emails, never repairs (deterministic), re-renders strip/report.
  - Stage order (PRD §8): I7 duplicate check → duration gate → transcribe (or `cached_env`) → **persist L2 before parsing** → parse → zero-call branch → rows → invariants → repair (if enabled and email path) → re-validate → stats (+`invariants_passed`, flags) → persist L3 → narrative (only when `email=True`) → render strip + on-disk report → email (failure ⇒ `pending_email` marker file, never raises) → archive audio (`"move"`/`"copy"`/`"none"`).
  - Flags list built from: violations (`"I1: ..."`), `ambiguous_calls > 0`, duration > `max_duration_s`, `session_id_source == "mtime"` is NOT a flag (normal for dev files).
  - Rejected (<`min_duration_s`) or unreadable/truncated audio (mutagen raises) ⇒ file moved (or copied for `archive="copy"`) to `repo_root/rejected/`, status `"rejected"`, no session dir, no email (PRD §12). Zero calls ⇒ session dir moved under `repo_root/needs_review/`, status `"needs_review"`; email with transcript attached if `email=True`.

- [ ] **Step 1: Write the failing tests**

`tests/test_pipeline.py`:
```python
import shutil
import pytest
from pathlib import Path
from hoops.config import load_config
from hoops.pipeline import process_file, replay_session
from hoops.session import read_session_json
from conftest import make_env

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[1]
GOOD = [("okay", 0.5, 0.8), ("miss", 5.0, 5.3), ("come", 8.0, 8.2), ("on", 8.25, 8.4),
        ("make", 12.0, 12.3), ("make", 18.0, 18.3), ("make", 24.0, 24.3),
        ("note", 27.0, 27.2), ("felt", 27.5, 27.7), ("good", 27.8, 28.0)]

class FakeTranscriber:
    model_id = "fake"
    def __init__(self, env): self.env = env
    def transcribe(self, path, prompt): return self.env["response"]

@pytest.fixture
def cfg(tmp_path, monkeypatch):
    shutil.copy(REPO / "config.yaml", tmp_path / "config.yaml")
    c = load_config(tmp_path / "config.yaml")
    return c

def audio(tmp_path, name="hoops__20260727-061204.m4a"):
    src = REPO / "fixtures" / "dev" / "dev03.m4a"   # real m4a → mutagen duration works
    dst = tmp_path / name
    shutil.copy(src, dst)
    return dst

def test_happy_path(tmp_path, cfg):
    f = audio(tmp_path)
    out = process_file(f, cfg, FakeTranscriber(make_env(GOOD, duration=30.0)),
                       email=False, archive="copy")
    assert out.status == "ok" and out.sid == "20260727-061204"
    sdir = out.session_dir
    for name in ["transcript.json", "transcript.txt", "shots.csv", "session.json",
                 "strip.png", "report.html", "audio.m4a"]:
        assert (sdir / name).exists(), name
    assert out.stats["shots_to_three"] == 4 and out.stats["invariants_passed"] is True
    assert out.stats["notes"] == "felt good"
    assert out.flags == []

def test_duplicate_skipped(tmp_path, cfg):
    f = audio(tmp_path)
    t = FakeTranscriber(make_env(GOOD, duration=30.0))
    process_file(f, cfg, t, email=False, archive="copy")
    out2 = process_file(f, cfg, t, email=False, archive="copy")
    assert out2.status == "duplicate"

def test_short_audio_rejected(tmp_path, cfg):
    f = audio(tmp_path)
    out = process_file(f, cfg, FakeTranscriber(make_env(GOOD)), email=False,
                       archive="copy", min_duration_override=999999)
    assert out.status == "rejected"
    assert any((cfg.repo_root / "rejected").iterdir())

def test_truncated_audio_rejected(tmp_path, cfg):
    f = tmp_path / "hoops__20260727-070000.m4a"
    f.write_bytes(b"not an mp4 at all")
    out = process_file(f, cfg, FakeTranscriber(make_env(GOOD)), email=False, archive="copy")
    assert out.status == "rejected"

def test_zero_calls_needs_review(tmp_path, cfg):
    env = make_env([("just", 1.0, 1.2), ("talking", 1.3, 1.6)], duration=30.0)
    out = process_file(audio(tmp_path), cfg, FakeTranscriber(env), email=False, archive="copy")
    assert out.status == "needs_review"
    assert (cfg.repo_root / "needs_review").exists()

def test_invariant_failure_flagged_not_dropped(tmp_path, cfg):
    env = make_env([("make", 5.0, 5.3), ("miss", 10.0, 10.3)], duration=30.0)
    out = process_file(audio(tmp_path), cfg, FakeTranscriber(env), email=False,
                       archive="copy", repair_enabled=False)
    assert out.status == "ok"
    assert out.stats["invariants_passed"] is False and out.flags

def test_replay_rewrites_and_preserves_quote(tmp_path, cfg):
    f = audio(tmp_path)
    out = process_file(f, cfg, FakeTranscriber(make_env(GOOD, duration=30.0)),
                       email=False, archive="copy")
    stats = read_session_json(out.session_dir)
    stats["quote_of_day"] = "kept quote"
    (out.session_dir / "session.json").write_text(__import__("json").dumps(stats))
    r = replay_session(out.session_dir, cfg)
    assert r.status == "ok"
    assert read_session_json(out.session_dir)["quote_of_day"] == "kept quote"
    assert read_session_json(out.session_dir)["shots_to_three"] == 4
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_pipeline.py -v` → import error.

- [ ] **Step 3: Implement**

`src/hoops/pipeline.py`:
```python
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from mutagen.mp4 import MP4
from . import PARSER_VERSION
from .config import Config
from .invariants import check_invariants
from .parse import parse_words
from .repair import attempt_repair
from .render import render_strip, render_report
from .session import (session_id_for, session_dir_for, sid_date_and_time,
                      write_transcript, write_shots_csv, write_session_json,
                      read_session_json, read_envelope)
from .stats import build_shot_rows, build_session_stats
from .transcribe import (make_envelope, words_from_envelope, envelope_duration,
                         vocab_prompt)

@dataclass
class Outcome:
    status: str
    sid: str
    session_dir: Path | None = None
    stats: dict | None = None
    rows: list = field(default_factory=list)
    flags: list = field(default_factory=list)

def _audio_duration(path: Path) -> float | None:
    try:
        return float(MP4(str(path)).info.length)
    except Exception:
        return None

def _reject(path: Path, cfg: Config, archive: str, sid: str) -> Outcome:
    rej = cfg.repo_root / "rejected"
    rej.mkdir(exist_ok=True)
    (shutil.move if archive == "move" else shutil.copy)(str(path), str(rej / path.name))
    return Outcome(status="rejected", sid=sid)

def process_file(path: Path, cfg: Config, transcriber, *, email: bool,
                 out_root: Path | None = None, archive: str = "copy",
                 vocab_name: str | None = None, cached_env: dict | None = None,
                 repair_enabled: bool = True,
                 min_duration_override: float | None = None) -> Outcome:
    vocab = cfg.vocab(vocab_name)
    sid, sid_source = session_id_for(path, cfg.tz)
    root = out_root or cfg.sessions_root
    sdir = session_dir_for(root, sid)
    if sdir.exists():                                   # I7
        return Outcome(status="duplicate", sid=sid, session_dir=sdir)

    dur = _audio_duration(path)
    min_dur = min_duration_override or cfg.min_duration_s
    if dur is None or dur < min_dur:
        return _reject(path, cfg, archive, sid)

    if cached_env is not None:
        env = cached_env
    else:
        env = make_envelope(transcriber.transcribe(path, vocab_prompt(vocab)),
                            transcriber.model_id)
    sdir.mkdir(parents=True)
    write_transcript(sdir, env)                         # L2 persisted BEFORE parse

    words = words_from_envelope(env)
    parsed = parse_words(words, vocab, cfg.isolation_low, cfg.isolation_high)
    date_local, time_local = sid_date_and_time(sid)

    if not parsed.calls:
        nr = cfg.repo_root / "needs_review"
        nr.mkdir(exist_ok=True)
        target = nr / sdir.name
        shutil.move(str(sdir), str(target))
        if email:
            _email_needs_review(target, sid, cfg)
        return Outcome(status="needs_review", sid=sid, session_dir=target)

    rows = build_shot_rows(parsed.calls, sid, date_local)
    violations = check_invariants(rows, min_gap_s=cfg.min_gap_s,
                                  max_gap_s=cfg.max_gap_s, vocab=vocab)
    if violations and repair_enabled:
        repaired = attempt_repair(env, rows, violations, vocab, cfg.llm_model)
        if repaired:
            new_rows = build_shot_rows(repaired, sid, date_local)
            if not check_invariants(new_rows, min_gap_s=cfg.min_gap_s,
                                    max_gap_s=cfg.max_gap_s, vocab=vocab):
                rows, violations = new_rows, []

    stats = build_session_stats(rows, parsed, words, session_id=sid,
        session_date_local=date_local, start_time_local=time_local,
        session_len_s=envelope_duration(env), transcriber=env["model"],
        parser_version=PARSER_VERSION, profanity=cfg.profanity)
    flags = [f"{v.id}: {v.message}" for v in violations]
    if parsed.ambiguous:
        flags.append(f"{len(parsed.ambiguous)} ambiguous call-like token(s)")
    if dur > cfg.max_duration_s:
        flags.append(f"session audio {dur:.0f}s exceeds {cfg.max_duration_s:.0f}s — forgot to stop?")
    stats["invariants_passed"] = not violations

    write_shots_csv(sdir, rows)
    write_session_json(sdir, stats)

    narrative = None
    if email:
        from .narrative import generate_narrative
        narrative = generate_narrative(stats, env, cfg.llm_model)
        if narrative:
            stats["quote_of_day"] = narrative.quote
            write_session_json(sdir, stats)

    render_strip(rows, sdir / "strip.png")
    render_report(stats, rows, narrative, flags, sdir / "report.html", img_src="strip.png")

    if archive == "move":
        shutil.move(str(path), str(sdir / "audio.m4a"))
    elif archive == "copy":
        shutil.copy(str(path), str(sdir / "audio.m4a"))

    if email:
        try:
            from .mailer import build_email, send
            send(build_email(stats, sdir, narrative, flags, cfg), cfg)
        except Exception:
            (sdir / "pending_email").touch()

    return Outcome(status="ok", sid=sid, session_dir=sdir, stats=stats,
                   rows=rows, flags=flags)

def _email_needs_review(sdir: Path, sid: str, cfg: Config) -> None:
    try:
        from email.message import EmailMessage
        from .mailer import send
        msg = EmailMessage()
        msg["From"], msg["To"] = cfg.email["from"], cfg.email["to"]
        msg["Subject"] = f"⚠️ 🏀 {sid} — zero calls detected, needs review"
        msg.set_content((sdir / "transcript.txt").read_text() or "(empty transcript)")
        send(msg, cfg)
    except Exception:
        (sdir / "pending_email").touch()

def replay_session(sdir: Path, cfg: Config, vocab_name: str | None = None) -> Outcome:
    env = read_envelope(sdir)
    vocab = cfg.vocab(vocab_name)
    sid = sdir.name.removeprefix("hoops__")
    date_local, time_local = sid_date_and_time(sid)
    words = words_from_envelope(env)
    parsed = parse_words(words, vocab, cfg.isolation_low, cfg.isolation_high)
    rows = build_shot_rows(parsed.calls, sid, date_local)
    violations = check_invariants(rows, min_gap_s=cfg.min_gap_s,
                                  max_gap_s=cfg.max_gap_s, vocab=vocab)
    stats = build_session_stats(rows, parsed, words, session_id=sid,
        session_date_local=date_local, start_time_local=time_local,
        session_len_s=envelope_duration(env), transcriber=env["model"],
        parser_version=PARSER_VERSION, profanity=cfg.profanity)
    stats["invariants_passed"] = not violations
    try:
        stats["quote_of_day"] = read_session_json(sdir).get("quote_of_day", "")
    except FileNotFoundError:
        pass
    flags = [f"{v.id}: {v.message}" for v in violations]
    write_shots_csv(sdir, rows)
    write_session_json(sdir, stats)
    render_strip(rows, sdir / "strip.png")
    render_report(stats, rows, None, flags, sdir / "report.html", img_src="strip.png")
    return Outcome(status="ok", sid=sid, session_dir=sdir, stats=stats,
                   rows=rows, flags=flags)
```

Note: `FakeTranscriber.transcribe` returns `self.env["response"]` (the raw response), and `process_file` wraps it with `make_envelope` — same as the real backend.

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_pipeline.py -v` → 7 PASS. Also run the full suite: `uv run pytest -v` → all green.

- [ ] **Step 5: Commit** — `git commit -am "feat: end-to-end pipeline with replay and degenerate-input handling"`

---

### Task 13: Fixture runner + CLI wiring (`fixtures.py`, `cli.py`)

**Files:**
- Create: `src/hoops/fixtures.py`, `tests/test_fixtures.py`
- Modify: `src/hoops/cli.py` (replace `main`)

**Interfaces:**
- Consumes: pipeline, manifest, `WhisperApiTranscriber`.
- Produces:
  - `read_manifest(path: Path) -> list[dict]` — DictReader rows; blank strings kept as `""`.
  - `transcript_cache_path(repo_root: Path, fixture_filename: str) -> Path` — `fixtures/transcripts/<stem>.json` where stem is the filename with `/` → `__` and no extension (`dev/dev01.m4a` → `dev__dev01.json`).
  - `run_fixture(row: dict, cfg: Config, transcriber, out_root: Path) -> dict` — gallery entry (`name, expected, got, strip_rel, flags, note`): uses cached transcript if present, else transcribes **and writes the cache** (spec §3.2); processes with `out_root=out_root/<stem>` (per-fixture subfolder — dev fixtures derive their sid from mtime, and a fresh clone gives every fixture the same mtime, so a shared out_root would collide as "duplicate"), `archive="none"`, `email=False`, `repair_enabled=False` (fixture scoring must measure the deterministic parse, not the LLM), `vocab_name=row["vocab"] or None`. `got` = non-voided results in order; for `status != "ok"` outcomes, `got=[]` and status appended to `flags`.
  - `run_all(cfg: Config, transcriber, fixtures_dir: Path) -> list[dict]` — every manifest row whose audio exists; writes gallery to `repo_root/out/index.html`; deletes stale `out/fixtures/` first so re-runs are clean.
  - `cli.main()` — wires all subcommands; loads `.env` via `dotenv.load_dotenv(repo_root/".env")`; `process` uses `archive="copy"` for paths outside the inbox; prints a one-line outcome summary per file; `replay --all` iterates `find_session_dirs(cfg.sessions_root)`; exit code 0 on success, 1 when `score` gates fail (Task 14) or any processed file errors.

- [ ] **Step 1: Write the failing tests**

`tests/test_fixtures.py`:
```python
import json, shutil
import pytest
from pathlib import Path
from hoops.config import load_config
from hoops.fixtures import (read_manifest, transcript_cache_path, run_fixture, run_all)
from conftest import make_env

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[1]
GOOD = [("miss", 5.0, 5.3), ("make", 12.0, 12.3), ("make", 18.0, 18.3), ("make", 24.0, 24.3)]

class FakeTranscriber:
    model_id = "fake"
    def __init__(self, env): self.env = env; self.calls = 0
    def transcribe(self, path, prompt): self.calls += 1; return self.env["response"]

@pytest.fixture
def sandbox(tmp_path):
    shutil.copy(REPO / "config.yaml", tmp_path / "config.yaml")
    (tmp_path / "fixtures" / "dev").mkdir(parents=True)
    (tmp_path / "fixtures" / "transcripts").mkdir()
    shutil.copy(REPO / "fixtures" / "dev" / "dev03.m4a",
                tmp_path / "fixtures" / "dev" / "dev01.m4a")
    (tmp_path / "fixtures" / "manifest.csv").write_text(
        "filename,expected_calls,traps_planted,expect_invariants_pass,vocab,gating,expected_gaps,notes\n"
        "dev/dev01.m4a,miss make make make,,yes,,no,,smoke\n")
    return load_config(tmp_path / "config.yaml")

def test_cache_path():
    assert transcript_cache_path(Path("/r"), "dev/dev01.m4a") == \
        Path("/r/fixtures/transcripts/dev__dev01.json")

def test_run_fixture_writes_cache_then_reuses(sandbox):
    t = FakeTranscriber(make_env(GOOD, duration=30.0))
    row = read_manifest(sandbox.repo_root / "fixtures" / "manifest.csv")[0]
    e1 = run_fixture(row, sandbox, t, sandbox.repo_root / "out" / "fixtures")
    assert e1["got"] == ["miss", "make", "make", "make"] and t.calls == 1
    assert transcript_cache_path(sandbox.repo_root, row["filename"]).exists()
    # second run: cache hit, no new transcription
    shutil.rmtree(sandbox.repo_root / "out")
    e2 = run_fixture(row, sandbox, t, sandbox.repo_root / "out" / "fixtures")
    assert e2["got"] == e1["got"] and t.calls == 1

def test_run_all_writes_gallery(sandbox):
    t = FakeTranscriber(make_env(GOOD, duration=30.0))
    entries = run_all(sandbox, t, sandbox.repo_root / "fixtures")
    assert len(entries) == 1
    assert (sandbox.repo_root / "out" / "index.html").exists()
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_fixtures.py -v` → import error.

- [ ] **Step 3: Implement**

`src/hoops/fixtures.py`:
```python
import csv, json, shutil
from pathlib import Path
from .config import Config
from .pipeline import process_file
from .render import render_gallery

def read_manifest(path: Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))

def transcript_cache_path(repo_root: Path, fixture_filename: str) -> Path:
    stem = fixture_filename.replace("/", "__").rsplit(".", 1)[0]
    return repo_root / "fixtures" / "transcripts" / f"{stem}.json"

def run_fixture(row: dict, cfg: Config, transcriber, out_root: Path) -> dict:
    audio = cfg.repo_root / "fixtures" / row["filename"]
    cache = transcript_cache_path(cfg.repo_root, row["filename"])
    cached_env = json.loads(cache.read_text()) if cache.exists() else None
    stem = row["filename"].replace("/", "__").rsplit(".", 1)[0]
    out = process_file(audio, cfg, transcriber, email=False, out_root=out_root / stem,
                       archive="none", vocab_name=row.get("vocab") or None,
                       cached_env=cached_env, repair_enabled=False)
    if cached_env is None and out.session_dir and (out.session_dir / "transcript.json").exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(out.session_dir / "transcript.json", cache)
    name = row["filename"]
    expected = row.get("expected_calls", "").split() if row.get("expected_calls") else []
    if out.status != "ok":
        return {"name": name, "expected": expected, "got": [],
                "strip_rel": "", "flags": [f"status: {out.status}"], "note": row.get("notes", "")}
    got = [r["result"] for r in out.rows if not r["voided"]]
    strip_rel = str((out.session_dir / "strip.png").relative_to(cfg.repo_root / "out"))
    return {"name": name, "expected": expected, "got": got,
            "strip_rel": strip_rel, "flags": out.flags, "note": row.get("notes", "")}

def run_all(cfg: Config, transcriber, fixtures_dir: Path) -> list[dict]:
    out_root = cfg.repo_root / "out" / "fixtures"
    if out_root.exists():
        shutil.rmtree(out_root)
    entries = []
    for row in read_manifest(fixtures_dir / "manifest.csv"):
        if not (cfg.repo_root / "fixtures" / row["filename"]).exists():
            continue
        entries.append(run_fixture(row, cfg, transcriber, out_root))
    render_gallery(entries, cfg.repo_root / "out" / "index.html")
    return entries
```

`src/hoops/cli.py` — replace `main` (keep `build_parser` unchanged):
```python
def main() -> int:
    import sys
    from pathlib import Path
    from dotenv import load_dotenv
    from .config import load_config
    from .fixtures import run_all, read_manifest, transcript_cache_path, run_fixture
    from .pipeline import process_file, replay_session
    from .session import find_session_dirs
    from .transcribe import WhisperApiTranscriber

    args = build_parser().parse_args()
    cfg = load_config(Path(__file__).resolve().parents[2] / "config.yaml")
    load_dotenv(cfg.repo_root / ".env")
    transcriber = WhisperApiTranscriber(cfg.transcriber_model)

    if args.command == "process":
        out = process_file(Path(args.path).expanduser(), cfg, transcriber,
                           email=not args.no_email, archive="copy")
        print(f"{out.sid}: {out.status}" + (f" — {out.session_dir}" if out.session_dir else ""))
        return 0 if out.status in ("ok", "duplicate") else 1

    if args.command == "process-all":
        entries = run_all(cfg, transcriber, Path(args.fixtures_dir).expanduser())
        bad = [e for e in entries if e["expected"] and e["expected"] != e["got"]]
        print(f"{len(entries)} fixtures processed, {len(bad)} mismatches — "
              f"open {cfg.repo_root / 'out' / 'index.html'}")
        return 0

    if args.command == "replay":
        dirs = (find_session_dirs(cfg.sessions_root) if args.all
                else [d for d in find_session_dirs(cfg.sessions_root)
                      if d.name.endswith(args.sid)])
        for d in dirs:
            r = replay_session(d, cfg)
            print(f"{r.sid}: replayed ({len(r.rows)} calls, "
                  f"{'clean' if not r.flags else 'FLAGS: ' + '; '.join(r.flags)})")
        return 0

    if args.command == "score":
        from .score import score_and_print
        return score_and_print(cfg)

    if args.command == "transcribe-fixtures":
        for row in read_manifest(cfg.repo_root / "fixtures" / "manifest.csv"):
            if args.only and args.only not in row["filename"]:
                continue
            cache = transcript_cache_path(cfg.repo_root, row["filename"])
            cache.unlink(missing_ok=True)
            run_fixture(row, cfg, transcriber, cfg.repo_root / "out" / "fixtures")
            print(f"transcribed {row['filename']} -> {cache}")
        return 0

    if args.command == "poll":
        from .ingest import poll_once
        processed = poll_once(cfg, transcriber)
        print(f"poll: {len(processed)} file(s) processed")
        return 0
    return 2
```

(`score` and `ingest` land in Tasks 14–15; until then those subcommands raise ImportError if invoked — tests don't invoke them.)

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_fixtures.py tests/test_cli.py -v` → all PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat: fixture runner with transcript cache, gallery, cli wiring"`

---

### Task 14: Gate scoring (`score.py`)

**Files:**
- Create: `src/hoops/score.py`, `tests/test_score.py`

**Interfaces:**
- Consumes: manifest rows, cached fixture transcripts, parser (never the transcriber — this is the free tier, spec §4.7).
- Produces:
  - `FixtureScore` dataclass: `name: str`, `expected: list[str]`, `got: list[str]`, `matched: int`, `inserted: int`, `deleted: int`, `misclassified: int`, `exact: bool`, `gap_mae: float | None`, `traps: bool` (row has non-empty, non-zero `traps_planted`), `invariants_ok_expected: bool`, `invariants_ok_got: bool`.
  - `score_fixture(row: dict, cfg: Config) -> FixtureScore | None` — `None` if no cached transcript or blank `expected_calls`; parses the cached envelope with the row's vocab, compares non-voided result sequences via `difflib.SequenceMatcher`; `gap_mae` only when `expected_gaps` is non-blank and lengths align.
  - `aggregate(scores: list[FixtureScore]) -> dict` — keys `recall, precision, classification, exact_fraction, gap_mae, phantom_on_traps` computed over **gating** fixtures passed in.
  - `score_and_print(cfg: Config) -> int` — scores gating rows, prints the §11.2 gate table, returns 0 if all gates pass (recall ≥0.99, precision ≥0.99, classification ≥0.98, exact ≥0.90, gap_mae ≤0.5 or None, phantom_on_traps == 0), else 1. Non-gating rows are printed in a separate informational section.

- [ ] **Step 1: Write the failing tests**

`tests/test_score.py`:
```python
import json, shutil
import pytest
from pathlib import Path
from hoops.config import load_config
from hoops.score import score_fixture, aggregate
from hoops.fixtures import transcript_cache_path
from conftest import make_env

pytestmark = pytest.mark.parse
REPO = Path(__file__).resolve().parents[1]

@pytest.fixture
def sandbox(tmp_path):
    shutil.copy(REPO / "config.yaml", tmp_path / "config.yaml")
    (tmp_path / "fixtures" / "transcripts").mkdir(parents=True)
    return load_config(tmp_path / "config.yaml")

def put_cache(cfg, filename, words):
    p = transcript_cache_path(cfg.repo_root, filename)
    p.write_text(json.dumps(make_env(words, duration=60.0)))

def row(filename, expected, traps="", gating="yes", gaps=""):
    return {"filename": filename, "expected_calls": expected, "traps_planted": traps,
            "expect_invariants_pass": "yes", "vocab": "", "gating": gating,
            "expected_gaps": gaps, "notes": ""}

CLEAN = [("miss", 5.0, 5.3), ("make", 12.0, 12.3), ("make", 18.0, 18.3), ("make", 24.0, 24.3)]

def test_exact_match(sandbox):
    put_cache(sandbox, "f01.m4a", CLEAN)
    s = score_fixture(row("f01.m4a", "miss make make make"), sandbox)
    assert s.exact and s.matched == 4 and s.inserted == 0 and s.deleted == 0

def test_phantom_detected_on_trap_fixture(sandbox):
    words = CLEAN + [("brick", 30.0, 30.3)]     # extra isolated call = phantom
    put_cache(sandbox, "f02.m4a", words)
    s = score_fixture(row("f02.m4a", "miss make make make", traps="3"), sandbox)
    assert s.traps and s.inserted == 1 and not s.exact

def test_gap_mae(sandbox):
    put_cache(sandbox, "f06.m4a", CLEAN)
    s = score_fixture(row("f06.m4a", "miss make make make", gaps="7.0 6.0 6.0"), sandbox)
    assert s.gap_mae == pytest.approx(0.0)

def test_aggregate_gates():
    from hoops.score import FixtureScore
    good = FixtureScore(name="a", expected=["make"] * 4, got=["make"] * 4, matched=4,
                        inserted=0, deleted=0, misclassified=0, exact=True, gap_mae=None,
                        traps=False, invariants_ok_expected=True, invariants_ok_got=True)
    agg = aggregate([good])
    assert agg["recall"] == 1.0 and agg["precision"] == 1.0
    assert agg["exact_fraction"] == 1.0 and agg["phantom_on_traps"] == 0
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_score.py -v` → import error.

- [ ] **Step 3: Implement**

`src/hoops/score.py`:
```python
import difflib, json
from dataclasses import dataclass
from .config import Config
from .fixtures import read_manifest, transcript_cache_path
from .invariants import check_invariants
from .parse import parse_words
from .stats import build_shot_rows
from .transcribe import words_from_envelope

GATES = {"recall": 0.99, "precision": 0.99, "classification": 0.98,
         "exact_fraction": 0.90, "gap_mae": 0.5}

@dataclass
class FixtureScore:
    name: str
    expected: list
    got: list
    matched: int
    inserted: int
    deleted: int
    misclassified: int
    exact: bool
    gap_mae: float | None
    traps: bool
    invariants_ok_expected: bool
    invariants_ok_got: bool

def score_fixture(row: dict, cfg: Config) -> FixtureScore | None:
    if not row.get("expected_calls"):
        return None
    cache = transcript_cache_path(cfg.repo_root, row["filename"])
    if not cache.exists():
        return None
    env = json.loads(cache.read_text())
    vocab = cfg.vocab(row.get("vocab") or None)
    parsed = parse_words(words_from_envelope(env), vocab,
                         cfg.isolation_low, cfg.isolation_high)
    live = [c for c in parsed.calls if not c.voided]
    got = [c.result for c in live]
    expected = row["expected_calls"].split()
    sm = difflib.SequenceMatcher(a=expected, b=got, autojunk=False)
    matched = sum(b.size for b in sm.get_matching_blocks())
    mis = sum(min(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in sm.get_opcodes()
              if tag == "replace")
    rows = build_shot_rows(parsed.calls, "score", "1970-01-01")
    inv_got = not check_invariants(rows, min_gap_s=cfg.min_gap_s,
                                   max_gap_s=cfg.max_gap_s, vocab=vocab)
    gap_mae = None
    if row.get("expected_gaps"):
        exp_gaps = [float(x) for x in row["expected_gaps"].split()]
        got_gaps = [r["gap_s"] for r in rows if not r["voided"] and r["gap_s"] is not None]
        if len(exp_gaps) == len(got_gaps):
            gap_mae = sum(abs(a - b) for a, b in zip(exp_gaps, got_gaps)) / len(exp_gaps)
    traps = bool(row.get("traps_planted", "").strip()) and row["traps_planted"].strip() != "0"
    return FixtureScore(name=row["filename"], expected=expected, got=got,
                        matched=matched, inserted=len(got) - matched,
                        deleted=len(expected) - matched, misclassified=mis,
                        exact=expected == got, gap_mae=gap_mae, traps=traps,
                        invariants_ok_expected=row.get("expect_invariants_pass", "yes") == "yes",
                        invariants_ok_got=inv_got)

def aggregate(scores: list[FixtureScore]) -> dict:
    te = sum(len(s.expected) for s in scores) or 1
    tg = sum(len(s.got) for s in scores) or 1
    tm = sum(s.matched for s in scores)
    mis = sum(s.misclassified for s in scores)
    maes = [s.gap_mae for s in scores if s.gap_mae is not None]
    return {
        "recall": tm / te,
        "precision": tm / tg,
        "classification": tm / (tm + mis) if (tm + mis) else 1.0,
        "exact_fraction": sum(s.exact for s in scores) / (len(scores) or 1),
        "gap_mae": (sum(maes) / len(maes)) if maes else None,
        "phantom_on_traps": sum(s.inserted for s in scores if s.traps),
    }

def score_and_print(cfg: Config) -> int:
    rows = read_manifest(cfg.repo_root / "fixtures" / "manifest.csv")
    gating, info = [], []
    for r in rows:
        s = score_fixture(r, cfg)
        if s is None:
            continue
        (gating if r.get("gating", "").strip().lower() == "yes" else info).append(s)
    agg = aggregate(gating) if gating else None
    print(f"{'fixture':<28}{'expected':<10}{'got':<10}exact")
    for s in gating + info:
        tag = "" if s in gating else "  (non-gating)"
        print(f"{s.name:<28}{len(s.expected):<10}{len(s.got):<10}{s.exact}{tag}")
    if not gating:
        print("\nNo gating fixtures with cached transcripts yet — gates not evaluated.")
        return 0
    ok = True
    print("\nGate table:")
    for k, gate in GATES.items():
        val = agg[k]
        if k == "gap_mae":
            passed = val is None or val <= gate
            shown = "n/a" if val is None else f"{val:.2f}s"
        else:
            passed = val >= gate
            shown = f"{val:.3f}"
        ok &= passed
        print(f"  {k:<16}{shown:>8}   gate {gate}   {'PASS' if passed else 'FAIL'}")
    phantom_ok = agg["phantom_on_traps"] == 0
    ok &= phantom_ok
    print(f"  {'phantom_on_traps':<16}{agg['phantom_on_traps']:>8}   gate 0   "
          f"{'PASS' if phantom_ok else 'FAIL (hard build failure)'}")
    return 0 if ok else 1
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_score.py -v` → 4 PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat: gate scoring against manifest with phantom hard-fail"`

---

### Task 15: iCloud inbox poller (`ingest.py`)

**Files:**
- Create: `src/hoops/ingest.py`, `tests/test_ingest.py`
- Modify: `.gitignore` (append `rejected/`, `needs_review/`, `logs/`, `.poll_state.json`, `.poll.lock`)

**Interfaces:**
- Consumes: `Config`, transcriber, `process_file`.
- Produces:
  - `stable_files(inbox: Path, state: dict, prefix: str) -> tuple[list[Path], dict]` — returns files ready to process and the new state. Ready = name matches `^<prefix>__.*\.m4a$`, not an `.icloud` stub, size equals size recorded in previous poll state, and mtime older than 60s (PRD §6.8). Files seen for the first time (or with changed size) are recorded in state, not returned. `.icloud` stubs (`.<name>.icloud`) trigger `subprocess.run(["brctl", "download", str(path)])` and are skipped this round.
  - `poll_once(cfg: Config, transcriber) -> list[Path]` — acquires `repo_root/.poll.lock` (O_EXCL; a lock older than 30 min is stale and replaced; if held, return `[]`), loads/saves state json at `repo_root/.poll_state.json`, calls `process_file(..., email=True, archive="move")` for each ready file. Transcription failures: `process_file` may raise from the API client — catch per-file, leave file in inbox, increment `state["_failures"][name]`; after 3 consecutive failures for the same file, send a plain alert email (best-effort) and keep trying on later polls (PRD §12).

- [ ] **Step 1: Write the failing tests**

`tests/test_ingest.py`:
```python
import json, os, time, shutil
import pytest
from pathlib import Path
from hoops.config import load_config
from hoops.ingest import stable_files, poll_once
from conftest import make_env

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[1]
GOOD = [("miss", 5.0, 5.3), ("make", 12.0, 12.3), ("make", 18.0, 18.3), ("make", 24.0, 24.3)]

def old(path):  # push mtime beyond the 60s freshness guard
    ts = time.time() - 120
    os.utime(path, (ts, ts))

@pytest.fixture
def cfg(tmp_path):
    text = (REPO / "config.yaml").read_text().replace(
        "~/Library/Mobile Documents/com~apple~CloudDocs/Capture/inbox",
        str(tmp_path / "inbox"))
    (tmp_path / "config.yaml").write_text(text)
    (tmp_path / "inbox").mkdir()
    return load_config(tmp_path / "config.yaml")

def drop(cfg, name="hoops__20260727-061204.m4a"):
    dst = cfg.inbox / name
    shutil.copy(REPO / "fixtures" / "dev" / "dev03.m4a", dst)
    old(dst)
    return dst

def test_new_file_not_ready_until_second_poll(cfg):
    f = drop(cfg)
    ready, state = stable_files(cfg.inbox, {}, "hoops")
    assert ready == []                       # first sighting: record size only
    ready, _ = stable_files(cfg.inbox, state, "hoops")
    assert ready == [f]                      # unchanged size on second poll

def test_wrong_prefix_ignored(cfg):
    (cfg.inbox / "food__x.m4a").write_bytes(b"x")
    old(cfg.inbox / "food__x.m4a")
    _, state = stable_files(cfg.inbox, {}, "hoops")
    ready, _ = stable_files(cfg.inbox, state, "hoops")
    assert ready == []

def test_fresh_mtime_not_ready(cfg):
    f = cfg.inbox / "hoops__20260727-070000.m4a"
    shutil.copy(REPO / "fixtures" / "dev" / "dev03.m4a", f)   # mtime = now
    _, state = stable_files(cfg.inbox, {}, "hoops")
    ready, _ = stable_files(cfg.inbox, state, "hoops")
    assert ready == []

def test_poll_once_processes_and_moves(cfg, monkeypatch):
    class FakeTranscriber:
        model_id = "fake"
        def transcribe(self, path, prompt): return make_env(GOOD, duration=30.0)["response"]
    # never let unit tests reach real APIs, even if keys are in the shell env
    monkeypatch.setattr("hoops.narrative.generate_narrative", lambda *a, **k: None)
    def boom(*a, **k): raise RuntimeError("no smtp in tests")
    monkeypatch.setattr("hoops.mailer.send", boom)
    f = drop(cfg)
    assert poll_once(cfg, FakeTranscriber()) == []      # poll 1: records size
    done = poll_once(cfg, FakeTranscriber())            # poll 2: processes
    assert done == [f]
    assert not f.exists()                               # moved into session folder
    sdirs = list((cfg.sessions_root).rglob("audio.m4a"))
    assert len(sdirs) == 1
    assert (sdirs[0].parent / "pending_email").exists() # email failed (no SMTP) → marker

def test_poll_lock_blocks_concurrent(cfg):
    (cfg.repo_root / ".poll.lock").write_text("999999")
    assert poll_once(cfg, None) == []
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_ingest.py -v` → import error.

- [ ] **Step 3: Implement**

`src/hoops/ingest.py`:
```python
import json, os, re, subprocess, time
from pathlib import Path
from .config import Config
from .pipeline import process_file

def stable_files(inbox: Path, state: dict, prefix: str) -> tuple[list[Path], dict]:
    pat = re.compile(rf"^{re.escape(prefix)}__.*\.m4a$")
    new_state = {k: v for k, v in state.items() if k.startswith("_")}
    ready = []
    if not inbox.exists():
        return ready, new_state
    for p in sorted(inbox.iterdir()):
        if p.name.endswith(".icloud"):
            subprocess.run(["brctl", "download", str(p)], check=False)
            continue
        if not pat.match(p.name):
            continue
        size = p.stat().st_size
        new_state[p.name] = {"size": size}
        prev = state.get(p.name)
        if prev and prev["size"] == size and time.time() - p.stat().st_mtime > 60:
            ready.append(p)
    return ready, new_state

def _alert_email(cfg: Config, name: str, err: str) -> None:
    try:
        from email.message import EmailMessage
        from .mailer import send
        msg = EmailMessage()
        msg["From"], msg["To"] = cfg.email["from"], cfg.email["to"]
        msg["Subject"] = f"⚠️ 🏀 processing failing for {name}"
        msg.set_content(f"3 consecutive failed polls.\nLast error: {err}")
        send(msg, cfg)
    except Exception:
        pass

def poll_once(cfg: Config, transcriber) -> list[Path]:
    lock = cfg.repo_root / ".poll.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        if time.time() - lock.stat().st_mtime < 1800:
            return []
        lock.unlink()                                    # stale lock
        return poll_once(cfg, transcriber)
    try:
        state_path = cfg.repo_root / ".poll_state.json"
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        failures = state.get("_failures", {})
        ready, new_state = stable_files(cfg.inbox, state, cfg.prefix)
        processed = []
        for f in ready:
            try:
                out = process_file(f, cfg, transcriber, email=True, archive="move")
                processed.append(f)
                failures.pop(f.name, None)
            except Exception as e:
                failures[f.name] = failures.get(f.name, 0) + 1
                if failures[f.name] == 3:
                    _alert_email(cfg, f.name, repr(e))
        new_state["_failures"] = failures
        state_path.write_text(json.dumps(new_state))
        return processed
    finally:
        lock.unlink(missing_ok=True)
```

Append to `.gitignore`:
```
rejected/
needs_review/
logs/
.poll_state.json
.poll.lock
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_ingest.py -v` → 5 PASS. Full suite green: `uv run pytest`.

- [ ] **Step 5: Commit** — `git commit -am "feat: inbox poller with stability checks, lock, failure alerts"`

---

### Task 16: launchd, build_db.py, README

**Files:**
- Create: `scripts/com.guhan.hoops.plist`, `scripts/install_launchd.sh`, `scripts/build_db.py`, `tests/test_build_db.py`, `README.md`, `CLAUDE.md`

**Interfaces:**
- Produces: launchd job running `hoops poll` every 300s; `scripts/build_db.py` rebuilding `hoops.db` from committed session text (PRD §7.4 — pipeline never touches the DB).

- [ ] **Step 1: Write the failing test for build_db**

`tests/test_build_db.py`:
```python
import json, sqlite3, subprocess, sys
import pytest
from pathlib import Path

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[1]

def test_build_db(tmp_path):
    sdir = tmp_path / "sessions" / "2026" / "07" / "hoops__20260727-061204"
    sdir.mkdir(parents=True)
    (sdir / "shots.csv").write_text(
        "session_id,session_date_local,shot_num,result,t_call_s,gap_s,streak_after,"
        "voided,isolation_s,confidence,raw_token\n"
        "20260727-061204,2026-07-27,1,make,5.0,,1,False,2.0,,make\n")
    (sdir / "session.json").write_text(json.dumps(
        {"session_id": "20260727-061204", "session_date_local": "2026-07-27",
         "shots_to_three": 1, "makes": 1, "misses": 0}))
    db = tmp_path / "hoops.db"
    subprocess.run([sys.executable, str(REPO / "scripts" / "build_db.py"),
                    "--sessions", str(tmp_path / "sessions"), "--db", str(db)], check=True)
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM shots").fetchone()[0] == 1
    assert con.execute("SELECT makes FROM sessions").fetchone()[0] == 1
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_build_db.py -v` → script missing.

- [ ] **Step 3: Implement**

`scripts/build_db.py`:
```python
"""Rebuild hoops.db from committed session text. Derived, disposable (PRD §7.4)."""
import argparse, csv, json, sqlite3
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", default="sessions")
    ap.add_argument("--db", default="hoops.db")
    a = ap.parse_args()
    root, db = Path(a.sessions), Path(a.db)
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    shot_rows, sess_rows = [], []
    for sj in sorted(root.rglob("session.json")):
        sess_rows.append(json.loads(sj.read_text()))
        with (sj.parent / "shots.csv").open() as f:
            shot_rows.extend(list(csv.DictReader(f)))
    if not sess_rows:
        print("no sessions found"); return
    def create(table, rows):
        cols = list(rows[0].keys())
        con.execute(f"CREATE TABLE {table} ({', '.join(c for c in cols)})")
        con.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * len(cols))})",
                        [[json.dumps(r[c]) if isinstance(r.get(c), (dict, list))
                          else r.get(c) for c in cols] for r in rows])
    create("sessions", sess_rows)
    create("shots", shot_rows)
    con.commit()
    print(f"{db}: {len(sess_rows)} sessions, {len(shot_rows)} shots")

if __name__ == "__main__":
    main()
```

`scripts/com.guhan.hoops.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.guhan.hoops</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/guhansundar/Documents/hoops/.venv/bin/hoops</string>
    <string>poll</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/guhansundar/Documents/hoops</string>
  <key>StartInterval</key><integer>300</integer>
  <key>StandardOutPath</key><string>/Users/guhansundar/Documents/hoops/logs/poll.log</string>
  <key>StandardErrorPath</key><string>/Users/guhansundar/Documents/hoops/logs/poll.log</string>
</dict>
</plist>
```

`scripts/install_launchd.sh`:
```bash
#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs
uv sync                                    # ensures .venv/bin/hoops exists
cp scripts/com.guhan.hoops.plist ~/Library/LaunchAgents/
launchctl bootout "gui/$(id -u)/com.guhan.hoops" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.guhan.hoops.plist
launchctl print "gui/$(id -u)/com.guhan.hoops" | head -20
echo "installed: hoops poll every 300s, logs in logs/poll.log"
```

`README.md` — quickstart: what this is (one paragraph), `uv sync`, `cp .env.example .env` + fill keys, command list (the six subcommands with one line each), owner checklist from spec §5, fixture-recording workflow (record → drop in `fixtures/`, add manifest row with `expected_calls` immediately — PRD §11.1), `bash scripts/install_launchd.sh` to schedule, shadow-period note (first 14 sessions: eyeball transcript vs table, PRD §11.5).

`CLAUDE.md`:
```markdown
# hoops — morning free-throw voice log
Voice-called shots → shot table → emailed report. Spec: docs/specs/2026-07-27-hoops-voice-log-design.md (supersedes docs/PRD-hoops-voice-log.md where they conflict).
- Run tests: `uv run pytest` (paid API tests excluded by default; `-m paid` to include)
- Parser work: iterate with `uv run hoops replay --all` then `git diff sessions/` — a no-op change must produce no diff (PRD §11.6)
- Gates: `uv run hoops score` must pass before merging parser/config changes; phantom shots on trap fixtures are a hard failure
- Text is committed; audio/binaries/db are gitignored. Never make the pipeline write to hoops.db.
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_build_db.py -v` → PASS. `bash -n scripts/install_launchd.sh` and `plutil -lint scripts/com.guhan.hoops.plist` both clean.

- [ ] **Step 5: Commit** — `git commit -am "feat: launchd schedule, build_db, README, CLAUDE.md"`

---

### Task 17: Live integration (paid; owner-in-the-loop)

**Files:**
- Modify: `fixtures/manifest.csv` (owner fills `expected_calls` for dev01–dev04), `fixtures/transcripts/*` (generated, committed)

This task needs `.env` filled and costs a few cents. Everything before it is fully offline.

- [ ] **Step 1: Owner fills `.env`** — `cp .env.example .env`, paste the three keys.

- [ ] **Step 2: Transcribe dev fixtures (paid)**

Run: `uv run hoops transcribe-fixtures`
Expected: four `fixtures/transcripts/dev__dev0*.json` files appear. Spot-check one: it must contain `response.words[*].start/end` (word timestamps present — if `words` is missing the whisper call parameters are wrong).

- [ ] **Step 3: Process all fixtures and open the gallery**

Run: `uv run hoops process-all fixtures --no-email && open out/index.html`
Expected: gallery shows dev01–dev04 with strips and parsed sequences (unlabeled → "unlabeled" badge).

- [ ] **Step 4: Owner labels dev fixtures** — listen to each recording once, fill `expected_calls` in `fixtures/manifest.csv` (space-separated `make`/`miss`). Re-run `uv run hoops process-all fixtures --no-email` and `uv run hoops score`; iterate isolation thresholds in `config.yaml` only if sequences mismatch, re-running `hoops score` after each change.

- [ ] **Step 5: SMTP smoke test (one real email, end of P2 per PRD §14.1)**

Run: `uv run hoops process fixtures/dev/dev04.m4a`
Expected: email arrives at guhandiji@gmail.com within a minute — subject `🏀 ...`, strip renders inline in Gmail, all artifacts attached. (This writes a real session under `sessions/` from the dev file — delete the session dir afterwards and note it: `git status` should be clean.)

- [ ] **Step 6: Install the schedule + live end-to-end**

Run: `bash scripts/install_launchd.sh`. Owner records a real (or test) session via the Shortcut saving to `iCloud Drive/Capture/inbox/hoops__<timestamp>.m4a`. Within ~10 min (two polls: stability check then process) the email arrives with no interaction.

- [ ] **Step 7: Commit** — `git add fixtures/ sessions/ && git commit -m "chore: dev fixture transcripts + labels; live smoke test passed"` and `git push`.

---

## Post-plan notes for the executor

- Tasks 1–16 are fully offline and TDD-able without any API key. Task 17 is the only paid/owner step.
- The F01–F10 golden set arrives from the owner in parallel (PRD §14.1): each new recording is a file under `fixtures/` + a manifest row with `gating=yes` — no code changes. §11.2 gates are only meaningful once those exist; `hoops score` says so explicitly when no gating fixtures are cached.
- Vocabulary comparison (spec §2.1): only if trap fixtures show phantoms, add an alternate vocabulary block to `config.yaml`, re-record the trap fixture with those words, compare `hoops score` runs, and record the outcome in `docs/decisions/`.

