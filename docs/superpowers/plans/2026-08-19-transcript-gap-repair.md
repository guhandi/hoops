# Transcript Gap Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover call words whisper-1 silently drops in sparse audio stretches, by re-transcribing word-timeline coverage gaps and merging the recovered words into the transcript envelope before parsing.

**Architecture:** A new `src/hoops/gap_repair.py` runs as a second pass inside the transcription stage of `process_file` — pure span math picks gaps > `trigger_gap_s`, each gap is clipped (±`pad_s`) via librosa and sent to whisper, and recovered words merge into the envelope under a sibling `gap_repair` key (raw `response` stays pristine). `words_from_envelope` merges on read, so the parser and everything downstream are untouched. A new `hoops retranscribe` CLI command backfills archived sessions.

**Tech Stack:** Python 3.12, uv, pytest (offline by default; `-m paid` for real API), OpenAI whisper-1, librosa/soundfile (already deps), Modal (cloud deploy).

**Spec:** `docs/superpowers/specs/2026-08-19-transcript-gap-repair-design.md`

## Global Constraints

- `parse.py` / `stats.py` / `invariants.py` stay pure stdlib, no I/O. The new pure gap math must also be stdlib-pure; librosa only in `extract_clip`.
- Default test suite never touches the network. Whisper/librosa are stubbed or monkeypatched in unit tests.
- Replay byte-identity: envelopes **without** a `gap_repair` key must behave exactly as today. `uv run hoops replay --all` must leave all existing session outputs byte-identical (gate in Task 10, run BEFORE any backfill).
- Gap repair is non-fatal: it may never raise out of `apply_gap_repair`; report/email are never blocked.
- Config defaults (spec §7): `enabled: true` in `config.yaml`/`cloud/config.cloud.yaml`; fallback `DEFAULT_GAP_REPAIR` in `config.py` has `enabled: False` (same pattern as `DEFAULT_GUDATA`) so old configs/tests keep prior behavior. `trigger_gap_s: 10`, `pad_s: 2.0`, `max_spans: 8`, `transcriber.language: en`.
- Run tests with `uv run pytest tests/<file>.py -q`; full suite `uv run pytest -q`.
- Commit style: `feat(scope): …` / `test(scope): …` / `docs: …`, ending with the Claude co-author line.

**Implementation deviation from spec (already reconciled in the spec):** padded clips are NOT merged when they overlap — gaps are disjoint by construction, and the keep-only-inside-the-unpadded-gap rule makes cross-span duplicates impossible; overlapping padding just re-transcribes a couple of seconds twice.

---

### Task 1: Config plumbing (`transcriber_language`, `gap_repair`)

**Files:**
- Modify: `src/hoops/config.py`
- Modify: `config.yaml`
- Modify: `cloud/config.cloud.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `Config.transcriber_language: str` (default `"en"`), `Config.gap_repair: dict` with keys `enabled: bool`, `trigger_gap_s: float`, `pad_s: float`, `max_spans: int`; module constant `DEFAULT_GAP_REPAIR`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_config.py`:

```python
def test_gap_repair_defaults_when_absent(tmp_path):
    # a config.yaml with no transcriber.language / gap_repair keys
    src = (REPO / "config.yaml").read_text()
    stripped = "\n".join(l for l in src.splitlines()
                         if not l.strip().startswith(("language:", "gap_repair:",
                                                      "enabled: true", "trigger_gap_s:",
                                                      "pad_s:", "max_spans:")))
    (tmp_path / "config.yaml").write_text(stripped)
    c = load_config(tmp_path / "config.yaml")
    assert c.transcriber_language == "en"
    assert c.gap_repair == {"enabled": False, "trigger_gap_s": 10.0,
                            "pad_s": 2.0, "max_spans": 8}

def test_gap_repair_from_repo_config():
    c = load_config(REPO / "config.yaml")
    assert c.transcriber_language == "en"
    assert c.gap_repair["enabled"] is True
    assert c.gap_repair["trigger_gap_s"] == 10.0
```

(Use the existing `REPO` / `load_config` imports already present in `tests/test_config.py`; add them if that file defines paths differently — follow its local pattern.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -q -k gap_repair`
Expected: FAIL — `Config` has no attribute `gap_repair` / KeyError.

- [ ] **Step 3: Implement** — in `src/hoops/config.py`:

Add after `DEFAULT_GUDATA` (line 17):

```python
DEFAULT_GAP_REPAIR = {"enabled": False, "trigger_gap_s": 10.0, "pad_s": 2.0,
                      "max_spans": 8}
```

Add two fields at the end of the `Config` dataclass (after `gudata`):

```python
    transcriber_language: str = "en"
    gap_repair: dict = field(default_factory=lambda: dict(DEFAULT_GAP_REPAIR))
```

Add to the `Config(...)` construction in `load_config` (after `gudata=...`):

```python
        transcriber_language=str(raw["transcriber"].get("language", "en")),
        gap_repair={**DEFAULT_GAP_REPAIR,
                    **(raw["transcriber"].get("gap_repair") or {})},
```

In `config.yaml`, replace the `transcriber:` block with:

```yaml
transcriber:
  model: whisper-1
  language: en          # pin whisper language (main + gap-repair clip calls)
  gap_repair:           # re-transcribe word-timeline gaps whisper skipped
    enabled: true
    trigger_gap_s: 10   # gap length that triggers a clip re-transcription
    pad_s: 2.0          # context padding around each gap
    max_spans: 8        # per-session cost bound; hitting it adds a flag
```

Apply the identical block to `cloud/config.cloud.yaml`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -q`
Expected: PASS (all, including pre-existing).

- [ ] **Step 5: Commit**

```bash
git add src/hoops/config.py config.yaml cloud/config.cloud.yaml tests/test_config.py
git commit -m "feat(config): transcriber.language pin + gap_repair block

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Language pin in `WhisperApiTranscriber`

**Files:**
- Modify: `src/hoops/transcribe.py:55-65`
- Modify: `src/hoops/cli.py:48`
- Modify: `cloud/modal_app.py:35-36`
- Test: `tests/test_transcribe.py`

**Interfaces:**
- Consumes: `Config.transcriber_language` (Task 1).
- Produces: `WhisperApiTranscriber(model: str = "whisper-1", language: str = "en")` with attribute `self.language`; `transcribe(audio_path, prompt)` signature unchanged (stubs unaffected).

- [ ] **Step 1: Write the failing test** — append to `tests/test_transcribe.py`:

```python
def test_transcriber_language_attr():
    from hoops.transcribe import WhisperApiTranscriber
    t = WhisperApiTranscriber("whisper-1", language="en")
    assert t.language == "en"
    assert WhisperApiTranscriber("whisper-1").language == "en"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_transcribe.py -q -k language`
Expected: FAIL — unexpected keyword argument `language`.

- [ ] **Step 3: Implement** — in `src/hoops/transcribe.py` replace the class:

```python
class WhisperApiTranscriber:
    def __init__(self, model: str = "whisper-1", language: str = "en"):
        self.model_id = model
        self.language = language

    def transcribe(self, audio_path: Path, prompt: str) -> dict:
        client = OpenAI()
        with audio_path.open("rb") as f:
            resp = client.audio.transcriptions.create(
                model=self.model_id, file=f, response_format="verbose_json",
                timestamp_granularities=["word"], prompt=prompt,
                language=self.language)
        return resp.model_dump()
```

In `src/hoops/cli.py` line 48:

```python
    transcriber = WhisperApiTranscriber(cfg.transcriber_model, cfg.transcriber_language)
```

In `cloud/modal_app.py` lines 35–36:

```python
            tblock = yaml.safe_load(cfg_path.read_text())["transcriber"]
            transcriber = WhisperApiTranscriber(tblock["model"],
                                                tblock.get("language", "en"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_transcribe.py tests/test_cli.py tests/test_cloud_processor.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hoops/transcribe.py src/hoops/cli.py cloud/modal_app.py tests/test_transcribe.py
git commit -m "feat(transcribe): pin whisper language (kills nynorsk detection drift)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Pure gap math (`find_gaps`, `build_spans`, `merge_recovered`)

**Files:**
- Create: `src/hoops/gap_repair.py`
- Create: `tests/test_gap_repair.py`

**Interfaces:**
- Consumes: nothing (stdlib pure).
- Produces:
  - `find_gaps(word_times: list[tuple[float, float]], duration: float, trigger_gap_s: float) -> list[tuple[float, float]]`
  - `build_spans(gaps: list[tuple[float, float]], duration: float, pad_s: float, max_spans: int) -> tuple[list[dict], bool]` — span dict `{"gap": [g0, g1], "clip": [c0, c1]}`; bool = truncated by `max_spans`.
  - `merge_recovered(gap: tuple[float, float], clip_start: float, clip_words: list[dict]) -> list[dict]` — session-time `{"word", "start", "end"}` dicts, only words starting inside the unpadded gap.

- [ ] **Step 1: Write the failing tests** — create `tests/test_gap_repair.py`:

```python
import pytest
from hoops.gap_repair import find_gaps, build_spans, merge_recovered

pytestmark = pytest.mark.unit

def test_no_gaps_dense_words():
    words = [(0.5, 1.0), (6.0, 6.5), (12.0, 12.5)]
    assert find_gaps(words, 15.0, 10.0) == []

def test_interior_gap():
    words = [(5.6, 7.0), (30.1, 31.5), (49.6, 50.2)]
    assert find_gaps(words, 55.0, 10.0) == [(31.5, 49.6)]

def test_head_and_tail_gaps():
    words = [(20.0, 20.5), (25.0, 25.5)]
    assert find_gaps(words, 40.0, 10.0) == [(0.0, 20.0), (25.5, 40.0)]

def test_empty_transcript_is_one_full_gap():
    assert find_gaps([], 41.5, 10.0) == [(0.0, 41.5)]

def test_gap_exactly_at_threshold_does_not_trigger():
    words = [(0.0, 1.0), (11.0, 11.5)]
    assert find_gaps(words, 12.0, 10.0) == []

def test_r03_shape():
    # the two real gaps from session 20260819-131500 (word ends → next starts)
    words = [(30.1, 31.5), (49.6, 50.2), (110.96, 111.66), (127.48, 128.36)]
    gaps = find_gaps(words, 136.13, 10.0)
    assert (31.5, 49.6) in gaps and (111.66, 127.48) in gaps

def test_build_spans_pads_and_clamps():
    spans, truncated = build_spans([(1.0, 12.0), (100.0, 130.0)], 131.0, 2.0, 8)
    assert truncated is False
    assert spans == [{"gap": [1.0, 12.0], "clip": [0.0, 14.0]},
                     {"gap": [100.0, 130.0], "clip": [98.0, 131.0]}]

def test_build_spans_cap():
    gaps = [(float(i * 20), float(i * 20 + 11)) for i in range(10)]
    spans, truncated = build_spans(gaps, 500.0, 2.0, 8)
    assert len(spans) == 8 and truncated is True

def test_merge_recovered_keeps_only_inside_gap():
    clip_words = [{"word": "break", "start": 0.5, "end": 0.9},    # 110.16 — before gap
                  {"word": "splash", "start": 10.0, "end": 10.4},  # 119.66 — inside
                  {"word": "go", "start": 19.0, "end": 19.3}]      # 128.66 — after gap
    out = merge_recovered((111.66, 127.48), 109.66, clip_words)
    assert out == [{"word": "splash", "start": 119.66, "end": 120.06}]

def test_merge_recovered_empty_clip():
    assert merge_recovered((10.0, 25.0), 8.0, []) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_gap_repair.py -q`
Expected: FAIL — `ModuleNotFoundError: hoops.gap_repair`.

- [ ] **Step 3: Implement** — create `src/hoops/gap_repair.py`:

```python
"""Transcript gap repair — recover call words whisper-1 silently drops.

Whisper decodes ~30s windows; sparse, mostly-silent stretches lose isolated
call words (see docs/superpowers/specs/2026-08-19-transcript-gap-repair-design.md).
Pure span math lives here alongside the clip/merge orchestration; the raw
API response in the envelope is never mutated — recovered words ride a
sibling "gap_repair" key.
"""

def find_gaps(word_times: list[tuple[float, float]], duration: float,
              trigger_gap_s: float) -> list[tuple[float, float]]:
    gaps = []
    prev = 0.0
    for start, end in sorted(word_times):
        if start - prev > trigger_gap_s:
            gaps.append((prev, start))
        prev = max(prev, end)
    if duration - prev > trigger_gap_s:
        gaps.append((prev, duration))
    return gaps

def build_spans(gaps: list[tuple[float, float]], duration: float, pad_s: float,
                max_spans: int) -> tuple[list[dict], bool]:
    # Gaps are disjoint, so padded clips may overlap but recovered words can
    # never duplicate across spans (merge_recovered keeps inside-gap only).
    spans = [{"gap": [g0, g1],
              "clip": [max(0.0, g0 - pad_s), min(duration, g1 + pad_s)]}
             for g0, g1 in gaps[:max_spans]]
    return spans, len(gaps) > max_spans

def merge_recovered(gap: tuple[float, float], clip_start: float,
                    clip_words: list[dict]) -> list[dict]:
    out = []
    for w in clip_words:
        t0 = clip_start + float(w["start"])
        if gap[0] < t0 < gap[1]:
            out.append({"word": w["word"], "start": t0,
                        "end": clip_start + float(w["end"])})
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_gap_repair.py -q`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add src/hoops/gap_repair.py tests/test_gap_repair.py
git commit -m "feat(gap-repair): pure gap detection, span building, recovered-word merge

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: `words_from_envelope` merges recovered words

**Files:**
- Modify: `src/hoops/transcribe.py:24-37`
- Test: `tests/test_transcribe.py`

**Interfaces:**
- Consumes: envelope shape `{"model", "response", "gap_repair": {"spans": [{"recovered": [...]}, ...]}}` (Task 3/5 produce it).
- Produces: `words_from_envelope(env)` returns time-sorted `Word`s including recovered ones (confidence `None`). Envelopes without `gap_repair` behave byte-identically to today.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_transcribe.py`:

```python
def test_words_from_envelope_merges_gap_repair():
    from hoops.transcribe import words_from_envelope
    env = {"model": "whisper-1",
           "response": {"words": [{"word": "break", "start": 5.0, "end": 5.4},
                                  {"word": "splash", "start": 111.0, "end": 111.6}],
                        "segments": []},
           "gap_repair": {"spans": [
               {"gap": [31.5, 49.6], "clip": [29.5, 51.6],
                "recovered": [{"word": "break", "start": 39.6, "end": 40.0}]},
               {"gap": [111.7, 127.5], "clip": [109.7, 129.5],
                "recovered": [{"word": "splash", "start": 119.7, "end": 120.1}]}],
               "n_recovered": 2, "truncated": False, "errors": []}}
    words = words_from_envelope(env)
    assert [w.text for w in words] == ["break", "break", "splash", "splash"]
    assert [w.start for w in words] == [5.0, 39.6, 111.0, 119.7]
    assert words[1].confidence is None

def test_words_from_envelope_without_gap_repair_unchanged():
    from hoops.transcribe import words_from_envelope
    env = {"model": "whisper-1",
           "response": {"words": [{"word": "swish", "start": 1.0, "end": 1.3}],
                        "segments": []}}
    words = words_from_envelope(env)
    assert len(words) == 1 and words[0].text == "swish"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_transcribe.py -q -k merges`
Expected: FAIL — recovered words absent (only 2 words returned).

- [ ] **Step 3: Implement** — in `src/hoops/transcribe.py`, replace `words_from_envelope`:

```python
def words_from_envelope(env: dict) -> list[Word]:
    resp = env["response"]
    segments = resp.get("segments") or []
    raw_words = list(resp.get("words") or [])
    for span in (env.get("gap_repair") or {}).get("spans", []):
        raw_words.extend(span.get("recovered", []))
    raw_words.sort(key=lambda w: float(w["start"]))
    out = []
    for w in raw_words:
        conf = None
        for seg in segments:
            if seg["start"] <= w["start"] < seg["end"]:
                lp = seg.get("avg_logprob")
                conf = math.exp(lp) if lp is not None else None
                break
        out.append(Word(text=normalize_token(w["word"]), raw=w["word"],
                        start=float(w["start"]), end=float(w["end"]), confidence=conf))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_transcribe.py tests/test_parse.py tests/test_pipeline.py -q`
Expected: PASS (recovered words merge; no-key envelopes unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/hoops/transcribe.py tests/test_transcribe.py
git commit -m "feat(transcribe): words_from_envelope merges gap-repair recovered words

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: `extract_clip` + `apply_gap_repair` orchestration

**Files:**
- Modify: `src/hoops/gap_repair.py`
- Test: `tests/test_gap_repair.py`

**Interfaces:**
- Consumes: `find_gaps`/`build_spans`/`merge_recovered` (Task 3); a transcriber object with `.transcribe(path, prompt) -> dict` (raw response dict).
- Produces:
  - `extract_clip(audio_path: Path, t0: float, t1: float, dest_wav: Path) -> Path` (librosa I/O — monkeypatch in unit tests).
  - `apply_gap_repair(env: dict, audio_path: Path, transcriber, prompt: str, gr_cfg: dict, duration: float) -> dict` — returns env unchanged when no gaps; otherwise returns a new env with a `gap_repair` key `{"trigger_gap_s", "pad_s", "spans": [{"gap", "clip", "response", "recovered"}], "n_recovered", "truncated", "errors"}`. **Never raises.**

- [ ] **Step 1: Write the failing tests** — append to `tests/test_gap_repair.py`:

```python
from pathlib import Path
from hoops.gap_repair import apply_gap_repair

GR_CFG = {"enabled": True, "trigger_gap_s": 10.0, "pad_s": 2.0, "max_spans": 8}

class ClipTranscriber:
    """Returns canned clip responses in call order."""
    model_id = "fake"
    def __init__(self, responses): self.responses, self.calls = list(responses), []
    def transcribe(self, path, prompt):
        self.calls.append(prompt)
        return self.responses.pop(0)

def _stub_clip(monkeypatch):
    monkeypatch.setattr("hoops.gap_repair.extract_clip",
                        lambda audio, t0, t1, dest: dest)

def _env(words):
    return {"model": "whisper-1",
            "response": {"words": [{"word": w, "start": s, "end": e}
                                   for w, s, e in words], "segments": []}}

def test_apply_no_gaps_returns_env_unchanged(monkeypatch):
    _stub_clip(monkeypatch)
    env = _env([("break", 0.5, 0.9), ("splash", 8.0, 8.4)])
    t = ClipTranscriber([])
    out = apply_gap_repair(env, Path("x.m4a"), t, "p", GR_CFG, duration=12.0)
    assert out is env and t.calls == []

# Dense words up to ~112s so ONLY the tail gap (112.4 -> 136.13) qualifies.
# (A lone word at 111s would also create a head gap — two spans, not one.)
DENSE_THEN_TAIL = [("w", float(t), float(t) + 0.4) for t in range(0, 113, 8)]

def test_apply_recovers_words(monkeypatch, tmp_path):
    _stub_clip(monkeypatch)
    env = _env(DENSE_THEN_TAIL)                      # tail gap 112.4 -> 136.13
    clip_resp = {"words": [{"word": "splash", "start": 9.26, "end": 9.66}]}
    t = ClipTranscriber([clip_resp])                 # clip starts 112.4-2 = 110.4
    out = apply_gap_repair(env, tmp_path / "a.m4a", t, "p", GR_CFG, duration=136.13)
    gr = out["gap_repair"]
    assert len(gr["spans"]) == 1
    assert gr["n_recovered"] == 1 and gr["errors"] == []
    rec = gr["spans"][0]["recovered"][0]
    assert rec["word"] == "splash" and abs(rec["start"] - 119.66) < 0.01
    assert out["response"] == env["response"]        # raw response pristine

def test_apply_span_failure_is_recorded_not_raised(monkeypatch, tmp_path):
    _stub_clip(monkeypatch)
    class Boom:
        def transcribe(self, path, prompt): raise RuntimeError("api down")
    env = _env(DENSE_THEN_TAIL)
    out = apply_gap_repair(env, tmp_path / "a.m4a", Boom(), "p", GR_CFG, duration=136.13)
    gr = out["gap_repair"]
    assert gr["n_recovered"] == 0 and len(gr["errors"]) == 1
    assert gr["errors"][0].startswith("span [112.4, 136.1]")

def test_apply_whole_stage_failure_returns_original(monkeypatch):
    def explode(*a, **k): raise RuntimeError("librosa gone")
    monkeypatch.setattr("hoops.gap_repair.build_spans", explode)
    env = _env(DENSE_THEN_TAIL)
    out = apply_gap_repair(env, Path("a.m4a"), ClipTranscriber([]), "p",
                           GR_CFG, duration=136.13)
    assert out["response"] == env["response"]
    assert out["gap_repair"]["n_recovered"] == 0 and out["gap_repair"]["errors"]

def test_apply_single_pass_no_recursion(monkeypatch, tmp_path):
    _stub_clip(monkeypatch)
    # clip response leaves the gap still "open" — must not re-trigger
    t = ClipTranscriber([{"words": []}])
    env = _env(DENSE_THEN_TAIL)
    apply_gap_repair(env, tmp_path / "a.m4a", t, "p", GR_CFG, duration=136.13)
    assert len(t.calls) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_gap_repair.py -q -k apply`
Expected: FAIL — `ImportError: apply_gap_repair`.

- [ ] **Step 3: Implement** — append to `src/hoops/gap_repair.py`:

```python
import tempfile
from pathlib import Path

def extract_clip(audio_path: Path, t0: float, t1: float, dest_wav: Path) -> Path:
    import librosa
    import soundfile
    y, sr = librosa.load(str(audio_path), sr=16000, mono=True,
                         offset=t0, duration=max(0.1, t1 - t0))
    soundfile.write(str(dest_wav), y, sr)
    return dest_wav

def apply_gap_repair(env: dict, audio_path: Path, transcriber, prompt: str,
                     gr_cfg: dict, duration: float) -> dict:
    """Non-fatal by contract: returns env (possibly augmented), never raises."""
    result = {"trigger_gap_s": gr_cfg["trigger_gap_s"], "pad_s": gr_cfg["pad_s"],
              "spans": [], "n_recovered": 0, "truncated": False, "errors": []}
    try:
        words = env["response"].get("words") or []
        word_times = [(float(w["start"]), float(w["end"])) for w in words]
        gaps = find_gaps(word_times, duration, gr_cfg["trigger_gap_s"])
        if not gaps:
            return env
        spans, result["truncated"] = build_spans(gaps, duration,
                                                 gr_cfg["pad_s"], gr_cfg["max_spans"])
        for sp in spans:
            try:
                with tempfile.TemporaryDirectory() as td:
                    wav = extract_clip(audio_path, sp["clip"][0], sp["clip"][1],
                                       Path(td) / "clip.wav")
                    resp = transcriber.transcribe(wav, prompt)
                recovered = merge_recovered(tuple(sp["gap"]), sp["clip"][0],
                                            resp.get("words") or [])
                result["spans"].append({**sp, "response": resp,
                                        "recovered": recovered})
                result["n_recovered"] += len(recovered)
            except Exception as e:
                result["errors"].append(
                    f"span [{sp['gap'][0]:.1f}, {sp['gap'][1]:.1f}]: {e}")
    except Exception as e:
        result["errors"].append(f"gap repair stage: {e}")
    return {**env, "gap_repair": result}
```

Move the `import tempfile` / `from pathlib import Path` lines to the top of the module with the docstring.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_gap_repair.py -q`
Expected: PASS (15 tests).

- [ ] **Step 5: Commit**

```bash
git add src/hoops/gap_repair.py tests/test_gap_repair.py
git commit -m "feat(gap-repair): clip extraction + apply_gap_repair orchestration

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: `transcript.txt` annotation

**Files:**
- Modify: `src/hoops/session.py:24-26`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: envelope with optional `gap_repair` key (Task 5 shape).
- Produces: `write_transcript(sdir, env)` — unchanged JSON dump; `transcript.txt` gains one trailing line `[gap repair recovered: <word>@<t> …]` only when words were recovered.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_session.py`:

```python
def test_write_transcript_annotates_recovered(tmp_path):
    from hoops.session import write_transcript
    env = {"model": "whisper-1", "response": {"text": "break. splash."},
           "gap_repair": {"spans": [
               {"gap": [111.7, 127.5], "clip": [109.7, 129.5],
                "recovered": [{"word": " splash", "start": 119.66, "end": 120.1}]}],
               "n_recovered": 1, "truncated": False, "errors": []}}
    write_transcript(tmp_path, env)
    txt = (tmp_path / "transcript.txt").read_text()
    assert txt == "break. splash.\n[gap repair recovered: splash@119.7]"

def test_write_transcript_no_gap_repair_unchanged(tmp_path):
    from hoops.session import write_transcript
    env = {"model": "whisper-1", "response": {"text": "break. splash."}}
    write_transcript(tmp_path, env)
    assert (tmp_path / "transcript.txt").read_text() == "break. splash."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_session.py -q -k transcript`
Expected: FAIL — no annotation line.

- [ ] **Step 3: Implement** — in `src/hoops/session.py`, replace `write_transcript`:

```python
def write_transcript(sdir: Path, env: dict) -> None:
    (sdir / "transcript.json").write_text(json.dumps(env, indent=2, ensure_ascii=False))
    text = env["response"].get("text", "")
    recovered = [w for s in (env.get("gap_repair") or {}).get("spans", [])
                 for w in s.get("recovered", [])]
    if recovered:
        ann = " ".join(f"{w['word'].strip()}@{w['start']:.1f}" for w in recovered)
        text = (text + "\n" if text else "") + f"[gap repair recovered: {ann}]"
    (sdir / "transcript.txt").write_text(text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_session.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hoops/session.py tests/test_session.py
git commit -m "feat(session): annotate recovered words in transcript.txt

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Pipeline integration

**Files:**
- Modify: `src/hoops/pipeline.py` (import block; fresh-transcription branch ~line 129-133; flags block ~line 174-182)
- Modify: `tests/test_pipeline.py` (the `cfg` fixture + new tests)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `apply_gap_repair` (Task 5), `cfg.gap_repair` (Task 1).
- Produces: on fresh transcription with `cfg.gap_repair["enabled"]`, envelope is repaired before `write_transcript`; `stats["gap_repair_recovered"]` set whenever the envelope carries a `gap_repair` key — in **both** `process_file` and `replay_session` (replay rebuilds stats from the envelope; without this, replaying a repaired session would silently drop the stat and the flags, breaking replay-reproduces-processing). Flag strings: `"N call word(s) recovered by transcript gap repair"`, `"gap repair span cap (M) hit — later gaps unprocessed"`, `"gap repair error: …"`. Module-level helper `_gap_repair_stats(env, cfg, stats, flags) -> None` shared by both paths.

- [ ] **Step 1: Update the `cfg` test fixture** so existing tests keep prior behavior (repo `config.yaml` now enables gap repair, and `fixtures/dev/dev03.m4a` is 41.5s — long enough to trigger surprise repairs). In `tests/test_pipeline.py` replace the fixture:

```python
@pytest.fixture
def cfg(tmp_path, monkeypatch):
    shutil.copy(REPO / "config.yaml", tmp_path / "config.yaml")
    c = load_config(tmp_path / "config.yaml")
    c.gap_repair["enabled"] = False      # gap-repair tests opt in explicitly
    return c
```

- [ ] **Step 2: Write the failing tests** — append to `tests/test_pipeline.py`:

```python
class SeqTranscriber:
    """Main response first, then one canned clip response per gap span."""
    model_id = "fake"
    def __init__(self, responses): self.responses = list(responses)
    def transcribe(self, path, prompt): return self.responses.pop(0)

def test_gap_repair_recovers_calls(tmp_path, cfg, monkeypatch):
    monkeypatch.setattr("hoops.gap_repair.extract_clip",
                        lambda audio, t0, t1, dest: dest)
    cfg.gap_repair["enabled"] = True
    # dev03.m4a is ~41.5s; main transcript ends at 24.3 -> tail gap ~17s
    main = make_env([("brick", 5.0, 5.3), ("swish", 12.0, 12.3),
                     ("swish", 18.0, 18.3), ("swish", 24.0, 24.3)],
                    duration=41.5)["response"]
    clip = {"words": [{"word": "swish", "start": 8.0, "end": 8.3}]}  # ~30.3s session time
    f = audio(tmp_path)
    out = process_file(f, cfg, SeqTranscriber([main, clip]),
                       email=False, archive="copy", repair_enabled=False)
    assert out.status == "ok"
    assert len(out.rows) == 5
    assert out.stats["gap_repair_recovered"] == 1
    assert any("recovered by transcript gap repair" in fl for fl in out.flags)
    env = json.loads((out.session_dir / "transcript.json").read_text())
    assert env["gap_repair"]["n_recovered"] == 1

def test_gap_repair_disabled_no_stage(tmp_path, cfg):
    f = audio(tmp_path)
    out = process_file(f, cfg, FakeTranscriber(make_env(GOOD, duration=30.0)),
                       email=False, archive="copy", repair_enabled=False)
    assert "gap_repair_recovered" not in out.stats
    env = json.loads((out.session_dir / "transcript.json").read_text())
    assert "gap_repair" not in env

def test_gap_repair_errors_flagged(tmp_path, cfg, monkeypatch):
    def broken(audio, t0, t1, dest): raise RuntimeError("no codec")
    monkeypatch.setattr("hoops.gap_repair.extract_clip", broken)
    cfg.gap_repair["enabled"] = True
    main = make_env([("brick", 5.0, 5.3), ("swish", 12.0, 12.3),
                     ("swish", 18.0, 18.3), ("swish", 24.0, 24.3)],
                    duration=41.5)["response"]
    f = audio(tmp_path)
    out = process_file(f, cfg, SeqTranscriber([main]), email=False,
                       archive="copy", repair_enabled=False)
    assert out.status == "ok"                       # never blocks the report
    assert out.stats["gap_repair_recovered"] == 0
    assert any(fl.startswith("gap repair error:") for fl in out.flags)

def test_replay_preserves_gap_repair_stats(tmp_path, cfg, monkeypatch):
    monkeypatch.setattr("hoops.gap_repair.extract_clip",
                        lambda audio, t0, t1, dest: dest)
    cfg.gap_repair["enabled"] = True
    main = make_env([("brick", 5.0, 5.3), ("swish", 12.0, 12.3),
                     ("swish", 18.0, 18.3), ("swish", 24.0, 24.3)],
                    duration=41.5)["response"]
    clip = {"words": [{"word": "swish", "start": 8.0, "end": 8.3}]}
    f = audio(tmp_path)
    out = process_file(f, cfg, SeqTranscriber([main, clip]),
                       email=False, archive="copy", repair_enabled=False)
    r = replay_session(out.session_dir, cfg)
    assert r.stats["gap_repair_recovered"] == 1
    assert any("recovered by transcript gap repair" in fl for fl in r.flags)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_pipeline.py -q -k gap_repair`
Expected: FAIL — `gap_repair_recovered` missing, no `gap_repair` key in envelope.

- [ ] **Step 4: Implement** — in `src/hoops/pipeline.py`:

Add to imports:

```python
from .gap_repair import apply_gap_repair
```

Replace the fresh-transcription branch (lines 129–133):

```python
    if cached_env is not None:
        env = cached_env
    else:
        env = make_envelope(transcriber.transcribe(path, vocab_prompt(vocab)),
                            transcriber.model_id)
        if cfg.gap_repair.get("enabled"):
            env = apply_gap_repair(env, path, transcriber, vocab_prompt(vocab),
                                   cfg.gap_repair, duration=dur)
```

Add a module-level helper (near `_audio_duration`):

```python
def _gap_repair_stats(env: dict, cfg: Config, stats: dict, flags: list) -> None:
    gr = env.get("gap_repair")
    if gr is None:
        return
    stats["gap_repair_recovered"] = gr["n_recovered"]
    if gr["n_recovered"]:
        flags.append(f"{gr['n_recovered']} call word(s) recovered by "
                     "transcript gap repair")
    if gr.get("truncated"):
        flags.append(f"gap repair span cap ({cfg.gap_repair['max_spans']}) "
                     "hit — later gaps unprocessed")
    for err in gr.get("errors", []):
        flags.append(f"gap repair error: {err}")
```

In `process_file`, after the `flags = [...]` line (~174), add `_gap_repair_stats(env, cfg, stats, flags)` before the `parsed.ambiguous` check (it must run before `write_session_json`, which it does — the flags block sits above it).

In `replay_session`, after its `flags = [...]` line (~293) and before `write_shots_csv`/`write_session_json`, add the same call: `_gap_repair_stats(env, cfg, stats, flags)`. Old envelopes have no `gap_repair` key, so replay byte-identity for existing sessions is untouched.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_pipeline.py -q`
Expected: PASS (all — new and pre-existing).

- [ ] **Step 6: Run the full offline suite**

Run: `uv run pytest -q`
Expected: PASS — proves no other test tripped the new stage.

- [ ] **Step 7: Commit**

```bash
git add src/hoops/pipeline.py tests/test_pipeline.py
git commit -m "feat(pipeline): gap-repair second pass on fresh transcription

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: `retranscribe_session` + `hoops retranscribe` CLI

**Files:**
- Modify: `src/hoops/pipeline.py` (new function after `replay_session`)
- Modify: `src/hoops/cli.py` (parser after the `push` block; handler after the `push` handler)
- Test: `tests/test_pipeline.py` (logic), `tests/test_cli.py` (parser flags)

**Interfaces:**
- Consumes: `apply_gap_repair`, `find_gaps` (Tasks 3/5), `words_from_envelope`/`envelope_duration`/`vocab_prompt` (transcribe), `read_envelope`/`write_transcript`/`read_session_json` (session — all already imported in pipeline.py), `replay_session`, `_audio_duration`.
- Produces:
  - `retranscribe_session(sdir: Path, cfg: Config, transcriber) -> Outcome` in pipeline.py. Status is one of `"skipped_repaired"`, `"skipped_no_audio"`, `"skipped_no_gaps"` (free checks — no API call), or the `replay_session` Outcome (`"ok"`) after repair. Runs regardless of `cfg.gap_repair["enabled"]` — the command is an explicit request.
  - CLI: `hoops retranscribe [<sid> | --all] [--email]`. Exit 0 on success/skips, 1 if any session failed, 2 on bad args / no matches.

- [ ] **Step 1: Write the failing logic tests** — append to `tests/test_pipeline.py`:

```python
def _archived_session(tmp_path, cfg, env_words, duration):
    """Build a real archived session dir by processing, then strip it back
    to the artifacts retranscribe needs."""
    f = audio(tmp_path)
    out = process_file(f, cfg, FakeTranscriber(make_env(env_words, duration=duration)),
                       email=False, archive="copy", repair_enabled=False)
    assert out.status == "ok"
    return out.session_dir

DENSE = [("brick", float(t), float(t) + 0.3) for t in range(1, 40, 5)]  # no gaps in 41.5s
HOLED = [("brick", 5.0, 5.3), ("swish", 12.0, 12.3),
         ("swish", 18.0, 18.3), ("swish", 24.0, 24.3)]                  # tail gap ~17s

def test_retranscribe_skips_no_gaps(tmp_path, cfg):
    from hoops.pipeline import retranscribe_session
    sdir = _archived_session(tmp_path, cfg, DENSE, 41.5)
    before = (sdir / "transcript.json").read_text()
    class NeverCalled:
        def transcribe(self, path, prompt): raise AssertionError("no API call allowed")
    r = retranscribe_session(sdir, cfg, NeverCalled())
    assert r.status == "skipped_no_gaps"
    assert (sdir / "transcript.json").read_text() == before

def test_retranscribe_skips_already_repaired(tmp_path, cfg):
    import json as _json
    from hoops.pipeline import retranscribe_session
    sdir = _archived_session(tmp_path, cfg, HOLED, 41.5)
    env = _json.loads((sdir / "transcript.json").read_text())
    env["gap_repair"] = {"spans": [], "n_recovered": 0, "truncated": False,
                         "errors": [], "trigger_gap_s": 10.0, "pad_s": 2.0}
    (sdir / "transcript.json").write_text(_json.dumps(env))
    class NeverCalled:
        def transcribe(self, path, prompt): raise AssertionError("no API call allowed")
    r = retranscribe_session(sdir, cfg, NeverCalled())
    assert r.status == "skipped_repaired"

def test_retranscribe_skips_missing_audio(tmp_path, cfg):
    from hoops.pipeline import retranscribe_session
    sdir = _archived_session(tmp_path, cfg, HOLED, 41.5)
    (sdir / "audio.m4a").unlink()
    r = retranscribe_session(sdir, cfg, FakeTranscriber(make_env([])))
    assert r.status == "skipped_no_audio"

def test_retranscribe_repairs_and_replays(tmp_path, cfg, monkeypatch):
    import json as _json
    from hoops.pipeline import retranscribe_session
    monkeypatch.setattr("hoops.gap_repair.extract_clip",
                        lambda audio, t0, t1, dest: dest)
    sdir = _archived_session(tmp_path, cfg, HOLED, 41.5)
    n_before = len(_json.loads((sdir / "transcript.json").read_text())
                   ["response"]["words"])
    clip = {"words": [{"word": "swish", "start": 8.0, "end": 8.3}]}
    r = retranscribe_session(sdir, cfg, FakeTranscriber({"response": clip}))
    assert r.status == "ok"
    assert len(r.rows) == n_before + 1                       # recovered call landed
    assert r.stats["gap_repair_recovered"] == 1
    env = _json.loads((sdir / "transcript.json").read_text())
    assert env["gap_repair"]["n_recovered"] == 1
```

(`FakeTranscriber` returns `self.env["response"]` — for the clip call pass `{"response": clip}` so it returns the raw clip dict.)

- [ ] **Step 2: Write the failing parser test** — append to `tests/test_cli.py`, matching its conventions:

```python
def test_retranscribe_parser_flags():
    p = build_parser()
    assert p.parse_args(["retranscribe", "--all"]).all is True
    args = p.parse_args(["retranscribe", "20260819-131500", "--email"])
    assert args.sid == "20260819-131500" and args.email is True
```

Also extend `test_parser_has_all_subcommands`'s loop list with `("retranscribe", ["--all"])`.

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_pipeline.py tests/test_cli.py -q -k retranscribe`
Expected: FAIL — `ImportError: retranscribe_session`; argparse rejects `retranscribe`.

- [ ] **Step 4: Implement the logic** — in `src/hoops/pipeline.py`, add after `replay_session` (add `find_gaps` to the existing `.gap_repair` import and `vocab_prompt` is already imported):

```python
def retranscribe_session(sdir: Path, cfg: Config, transcriber) -> Outcome:
    """Backfill: gap-repair an archived session's transcript, then replay.
    Free checks first — the API is only hit when qualifying gaps exist."""
    sid = sdir.name.removeprefix("hoops__")
    env = read_envelope(sdir)
    if "gap_repair" in env:
        return Outcome(status="skipped_repaired", sid=sid, session_dir=sdir)
    audio_f = sdir / "audio.m4a"
    if not audio_f.exists():
        return Outcome(status="skipped_no_audio", sid=sid, session_dir=sdir)
    dur = _audio_duration(audio_f) or envelope_duration(env)
    words = words_from_envelope(env)
    gaps = find_gaps([(w.start, w.end) for w in words], dur,
                     cfg.gap_repair["trigger_gap_s"])
    if not gaps:
        return Outcome(status="skipped_no_gaps", sid=sid, session_dir=sdir)
    try:
        old = read_session_json(sdir)
    except FileNotFoundError:
        old = {}
    if old.get("vocab_map"):
        vocab = Vocabulary(name=old.get("vocab_name", "persisted"),
                           surface_to_canonical=old["vocab_map"])
    else:
        vocab = cfg.vocab(None)
    env2 = apply_gap_repair(env, audio_f, transcriber, vocab_prompt(vocab),
                            cfg.gap_repair, dur)
    write_transcript(sdir, env2)
    return replay_session(sdir, cfg)
```

- [ ] **Step 5: Implement the CLI** — in `src/hoops/cli.py`:

Add to `build_parser()` after the `push` block:

```python
    srt = sub.add_parser("retranscribe",
                         help="Gap-repair archived session transcripts (paid)")
    grt = srt.add_mutually_exclusive_group(required=False)
    grt.add_argument("--all", action="store_true")
    grt.add_argument("sid", nargs="?")
    srt.add_argument("--email", action="store_true",
                     help="resend the report email after repair")
```

Add the handler in `main()` after the `push` handler:

```python
    if args.command == "retranscribe":
        import json as _json
        from .pipeline import retranscribe_session
        if not args.all and not args.sid:
            print("retranscribe: specify --all or a session id")
            return 2
        dirs = (find_session_dirs(cfg.sessions_root) if args.all
                else [d for d in find_session_dirs(cfg.sessions_root)
                      if d.name.endswith(args.sid)])
        if not dirs:
            print("retranscribe: no matching sessions "
                  "(run pull_sessions to sync from R2 first)")
            return 2
        failures = repaired = 0
        for d in dirs:
            try:
                r = retranscribe_session(d, cfg, transcriber)
                if r.status.startswith("skipped_"):
                    reason = r.status.removeprefix("skipped_").replace("_", " ")
                    print(f"{d.name}: {reason} — skipped")
                    continue
                repaired += 1
                n = r.stats.get("gap_repair_recovered", 0)
                print(f"{d.name}: {n} word(s) recovered, replayed "
                      f"({len(r.rows)} calls, "
                      f"{'clean' if not r.flags else 'FLAGS: ' + '; '.join(r.flags)})")
                if args.email:
                    from .mailer import build_email, send
                    from .render import Narrative
                    narrative = None
                    nfile = d / "narrative.json"
                    if nfile.exists():
                        try:
                            narrative = Narrative(**_json.loads(nfile.read_text()))
                        except (TypeError, ValueError):
                            narrative = None
                    send(build_email(r.stats, d, narrative, r.flags, cfg), cfg)
            except Exception as e:
                failures += 1
                print(f"{d.name}: FAILED — {e}")
        if repaired:
            print("\nreminders: `hoops push <sid>` re-pushes stats to GuData "
                  "(server dedupes on external_id — corrected values may be "
                  "skipped unless GuData upserts); "
                  "`uv run modal run cloud/modal_app.py::push_sessions` syncs "
                  "repaired artifacts back to R2.")
        return 1 if failures else 0
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_pipeline.py tests/test_cli.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hoops/pipeline.py src/hoops/cli.py tests/test_pipeline.py tests/test_cli.py
git commit -m "feat(cli): hoops retranscribe — gap-repair backfill for archived sessions

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: R03 fixture + manifest row (PAID acceptance gate)

**Files:**
- Create: `fixtures/08192026_MorningHoops.m4a` (copy of session audio)
- Modify: `fixtures/manifest.csv`

**Interfaces:**
- Consumes: session `sessions/2026/08/hoops__20260819-131500/audio.m4a` (must exist locally — it does).
- Produces: fixture R03 with owner-confirmable ground truth; the project's acceptance gate for this feature.

- [ ] **Step 1: Copy the audio**

```bash
cp sessions/2026/08/hoops__20260819-131500/audio.m4a fixtures/08192026_MorningHoops.m4a
```

- [ ] **Step 2: Add the manifest row** — append to `fixtures/manifest.csv` (one line, matching the header column order exactly; `size_bytes` from `stat -f%z fixtures/08192026_MorningHoops.m4a`, expected 1899554):

```csv
08192026_MorningHoops.m4a,R03,real_session,recorded,,136.13,1899554,aac 48kHz stereo ~112kbps,natural midday session; sparse calls with long silences; ends on splash x3 closeout,Whisper-1 dropped 5 of 21 calls in sparse stretches (3 mid-file breaks + 2 closing splashes) — the gap-repair acceptance case. See docs/superpowers/specs/2026-08-19-transcript-gap-repair-design.md,gate,FALSE,,miss miss miss miss miss miss miss miss miss miss miss miss miss make miss miss miss miss make make make,21,TRUE,,,,LABELED,"Recorded 2026-08-19 13:15. Ground truth derived from diagnostic re-transcription of the two gaps (spec §Problem) — owner confirmed. Without gap repair the pipeline heard 16 calls / 2 makes.",,,,
```

- [ ] **Step 3: Owner eyeball** — pause and ask the owner to confirm the `expected_calls` sequence (21 calls: `miss×13 make miss×4 make make make`) against memory before committing. **This is a human checkpoint — do not skip.**

- [ ] **Step 4 (PAID): Transcribe the fixture and run the gate**

```bash
set -a; source .env; set +a
uv run hoops transcribe-fixtures --only 08192026
uv run hoops score
```

Expected: R03 row shows `heard_calls` == `expected_calls` (21 calls), `match=TRUE`. If whisper variance produces a benign diff (e.g. an extra non-call word), investigate before touching thresholds — `trigger_gap_s` changes require re-running the full suite and noting the change in the spec.

- [ ] **Step 5: Commit**

```bash
git add fixtures/08192026_MorningHoops.m4a fixtures/manifest.csv
git commit -m "test(fixtures): R03 — real session with whisper-dropped sparse calls (gap-repair gate)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 10: Gates, docs, deploy, backfill

**Files:**
- Modify: `docs/architecture.md`, `CLAUDE.md`
- No code changes.

**Interfaces:** consumes everything above; produces the released feature.

- [ ] **Step 1: Replay byte-identity gate (run BEFORE any backfill)**

```bash
cp -R sessions /tmp/sessions_snapshot
uv run hoops replay --all
git diff --no-index /tmp/sessions_snapshot sessions
```

Expected: empty diff. Old envelopes have no `gap_repair` key, so nothing may change. Any diff is a hard failure — stop and investigate.

- [ ] **Step 2: Full offline suite + existing fixture scores**

```bash
uv run pytest -q
uv run hoops score
```

Expected: pytest green; score table unchanged for all previously-scored fixtures (guards the language pin).

- [ ] **Step 3: Update docs**

- `docs/architecture.md`: in the module map add `gap_repair.py — transcript gap repair: re-transcribes word-timeline gaps > trigger_gap_s, merges recovered words into the envelope (sibling gap_repair key; raw response pristine)`; document the `retranscribe` CLI command next to `replay`/`push`; add a row to the failure-handling table: `Whisper drops sparse calls | gap-repair second pass re-transcribes gaps; recovered words flagged in report/email`.
- `CLAUDE.md`: update Current status (gap repair live, date), and Pending work — note item 1 (R01/R02 refresh) can now use `retranscribe`'s free gap detection as a first look, and item 8's shadow-period eyeball now includes gap-repair flags.

- [ ] **Step 4: Commit docs**

```bash
git add docs/architecture.md CLAUDE.md
git commit -m "docs: gap repair — architecture, CLAUDE.md status

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Deploy cloud (dev rule: tests then deploy)**

```bash
set -a; source .env; set +a
uv run pytest -q && uv run modal deploy cloud/modal_app.py
```

Expected: deploy succeeds; future phone sessions get gap repair cloud-side.

- [ ] **Step 6 (PAID): Backfill the two known-affected sessions**

```bash
uv run hoops retranscribe 20260819-131500
uv run hoops retranscribe 20260803-111200
```

Expected for `20260819-131500`: 5 words recovered, replay shows 21 calls, invariants clean (closes out splash×3). For `20260803-111200`: gap detection decides — if it prints "no qualifying gaps — skipped", that session was fine (nynorsk label was cosmetic there too).

- [ ] **Step 7: Verify the repaired session before syncing anywhere**

```bash
uv run python -c "
import json
d = json.load(open('sessions/2026/08/hoops__20260819-131500/session.json'))
print(d['shots_to_three'], d['makes'], d['invariants_passed'], d.get('gap_repair_recovered'))"
```

Expected: `21 4 True 5`. Open the regenerated `report.html` and eyeball the tail: three make markers after 110s.

- [ ] **Step 8: Sync back (R2 + GuData) — confirm with owner first, then:**

```bash
uv run modal run cloud/modal_app.py::push_sessions
uv run hoops push 20260819-131500
```

Note the GuData `external_id` dedupe caveat: if the push reports a duplicate/skip, the corrected stats did NOT land — report that to the owner rather than papering over it (GuData-side upsert is out of scope per the spec).

- [ ] **Step 9: Final commit & push (owner confirms)**

```bash
git status   # should be clean except intentional changes
git log --oneline main@{u}..HEAD
```

Ask the owner before `git push`.
