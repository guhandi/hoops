# Report Delight Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the per-session interactive HTML report physically honest and more fun: ball lands at the detected impact sound (with a "no contact heard" lie-detector flag), make/miss choreography, a waveform scrubber, runs-and-chase storytelling, richer narrative context, and a shot-anchored transcript.

**Architecture:** One new I/O-isolated module `src/hoops/impacts.py` (ffmpeg → WAV → stdlib `wave` → pure-stdlib DSP) produces an optional per-session sidecar `impacts.json`. `stats.py` gains a pure-stdlib chase/runs computation. `report_html.py` consumes both (gracefully degrading when absent). `pipeline.py` wires the impacts stage in as one removable call. Spec: `docs/superpowers/specs/2026-08-01-report-delight-pass-design.md`.

**Tech Stack:** Python 3.12, stdlib only for new logic (`wave`, `array`, `subprocess`, `statistics`), ffmpeg as an optional external binary, pytest.

## Global Constraints

- `parse.py` / `invariants.py`: DO NOT TOUCH. `stats.py` stays pure stdlib, **additive keys only** — never change an existing key's meaning or value.
- Impact search window: **[t_word − 2.0 s, t_word − 0.15 s]** exactly. No peak → `impact_t_s: null` + `no_contact: true`; the voice stays ground truth.
- `impacts.py` is the only module that touches audio bytes; it must **never raise** out of its public entry point and never block the email path.
- Report output stays ONE self-contained HTML file: no external requests, no CDN, inline CSS/JS/SVG only (`tests/test_report_html.py::test_self_contained` enforces `(src|href)="https?://` absence).
- Replay fallback when no impact: ball lands at **t_word − 0.5 s**. Flight duration **0.6 s**.
- No numpy / no new Python dependencies. ffmpeg absent ⇒ stage silently skips.
- Run tests with `uv run pytest` (paid API tests are excluded by default — never add a test that hits the network).
- Never print or commit `.env` values.
- Parser artifacts must stay byte-identical (`uv run hoops replay --all` on synced sessions); `shots.csv` is a parser-derived artifact whose columns must not change — new data goes in `session.json` and `impacts.json` only.

---

### Task 1: `impacts.py` — impact detection + loudness envelope

**Files:**
- Create: `src/hoops/impacts.py`
- Test: `tests/test_impacts.py`

**Interfaces:**
- Consumes: shot rows as produced by `hoops.stats.build_shot_rows` (dicts with `shot_num: int`, `t_call_s: float`, `voided: bool`).
- Produces (Task 3/5 rely on these exact names):
  - `ENVELOPE_HZ: int = 15`
  - `find_impact(envelope: list[float], hz: int, t_word: float) -> float | None`
  - `loudness_envelope(samples, rate: int = 16000, hz: int = 15) -> list[float]` (normalized 0–1)
  - `decode_pcm(audio_path: Path, rate: int = 16000) -> array | None` (mono 16-bit ints; None on any failure)
  - `build_impacts(audio_path: Path, rows: list[dict]) -> dict | None` — `{"envelope": [...], "envelope_hz": 15, "shots": [{"shot_num", "impact_t_s", "no_contact"}]}`
  - `write_impacts(sdir: Path, audio_path: Path | None, rows: list[dict]) -> dict | None` — writes `sdir/impacts.json` when detection succeeds; **never raises**.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_impacts.py
import json
import shutil
import subprocess
import wave
from array import array
from pathlib import Path

import pytest

from hoops.impacts import (ENVELOPE_HZ, build_impacts, decode_pcm,
                           find_impact, loudness_envelope, write_impacts)

pytestmark = pytest.mark.unit

def _flat(n, level=0.02):
    return [level] * n

def test_find_impact_hits_peak():
    env = _flat(150)
    env[45] = 0.9                       # 15 Hz -> peak at t = 3.03s
    t = find_impact(env, 15, t_word=4.0)  # window [2.0, 3.85] covers index 30..57
    assert t is not None
    assert abs(t - (45 + 0.5) / 15) < 0.05

def test_find_impact_ignores_peak_before_window():
    env = _flat(150)
    env[10] = 0.9                       # t = 0.7s, outside [2.0, 3.85]
    assert find_impact(env, 15, t_word=4.0) is None

def test_find_impact_ignores_peak_inside_guard():
    env = _flat(150)
    env[59] = 0.9                       # t = 3.97s, inside the 0.15s guard before 4.0
    assert find_impact(env, 15, t_word=4.0) is None

def test_no_contact_when_window_is_quiet():
    assert find_impact(_flat(150), 15, t_word=4.0) is None

def test_no_contact_when_whole_window_is_loud():
    # constant loudness (music/noise) has no transient: peak barely above median
    env = _flat(150, level=0.5)
    assert find_impact(env, 15, t_word=4.0) is None

def test_window_clamped_at_session_start():
    env = _flat(30)
    env[5] = 0.9
    t = find_impact(env, 15, t_word=1.0)  # window would start at -1.0s -> clamp to 0
    assert t is not None

def test_loudness_envelope_normalized_and_sized():
    rate, hz = 16000, 15
    quiet = [100] * rate                 # 1s quiet
    loud = [20000] * (rate // hz)        # one loud block
    samples = array("h", quiet + loud)
    env = loudness_envelope(samples, rate=rate, hz=hz)
    assert max(env) == 1.0
    assert env[-1] == 1.0
    assert all(0.0 <= v <= 1.0 for v in env)
    assert len(env) == (len(samples) + rate // hz - 1) // (rate // hz)

def _rows():
    return [
        {"shot_num": 1, "t_call_s": 4.0, "voided": False},
        {"shot_num": 2, "t_call_s": 8.0, "voided": False},
        {"shot_num": 3, "t_call_s": 9.0, "voided": True},
    ]

def test_build_impacts_marks_no_contact(monkeypatch, tmp_path):
    # impact only before shot 1; shot 2 window is silent -> lie flag
    env = _flat(200)
    env[45] = 0.9
    monkeypatch.setattr("hoops.impacts.decode_pcm", lambda p, rate=16000: array("h", [1]))
    monkeypatch.setattr("hoops.impacts.loudness_envelope",
                        lambda s, rate=16000, hz=ENVELOPE_HZ: env)
    data = build_impacts(tmp_path / "a.m4a", _rows())
    shots = {s["shot_num"]: s for s in data["shots"]}
    assert shots[1]["impact_t_s"] is not None and shots[1]["no_contact"] is False
    assert shots[2]["impact_t_s"] is None and shots[2]["no_contact"] is True
    assert shots[3]["impact_t_s"] is None and shots[3]["no_contact"] is False  # voided: not a lie
    assert data["envelope_hz"] == ENVELOPE_HZ

def test_build_impacts_none_when_decode_fails(monkeypatch, tmp_path):
    monkeypatch.setattr("hoops.impacts.decode_pcm", lambda p, rate=16000: None)
    assert build_impacts(tmp_path / "a.m4a", _rows()) is None

def test_write_impacts_writes_sidecar(monkeypatch, tmp_path):
    env = _flat(200)
    env[45] = 0.9
    monkeypatch.setattr("hoops.impacts.decode_pcm", lambda p, rate=16000: array("h", [1]))
    monkeypatch.setattr("hoops.impacts.loudness_envelope",
                        lambda s, rate=16000, hz=ENVELOPE_HZ: env)
    out = write_impacts(tmp_path, tmp_path / "a.m4a", _rows())
    assert out is not None
    on_disk = json.loads((tmp_path / "impacts.json").read_text())
    assert on_disk == out

def test_write_impacts_never_raises(monkeypatch, tmp_path):
    def boom(p, rate=16000):
        raise RuntimeError("decoder exploded")
    monkeypatch.setattr("hoops.impacts.decode_pcm", boom)
    assert write_impacts(tmp_path, tmp_path / "a.m4a", _rows()) is None
    assert not (tmp_path / "impacts.json").exists()

def test_write_impacts_none_audio(tmp_path):
    assert write_impacts(tmp_path, None, _rows()) is None

@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_decode_pcm_real_ffmpeg(tmp_path):
    # ffmpeg reads WAV too; a synthetic click file proves the subprocess path.
    src = tmp_path / "click.wav"
    rate = 16000
    samples = array("h", [0] * rate + [20000] * 160 + [0] * rate)
    with wave.open(str(src), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    out = decode_pcm(src, rate=rate)
    assert out is not None and len(out) > rate
    assert max(out) > 10000

def test_decode_pcm_missing_binary(monkeypatch, tmp_path):
    monkeypatch.setattr("hoops.impacts.shutil.which", lambda n: None)
    assert decode_pcm(tmp_path / "a.m4a") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_impacts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hoops.impacts'`

- [ ] **Step 3: Write the implementation**

```python
# src/hoops/impacts.py
"""Impact-sound detection + loudness envelope — optional post-processing stage.

Decodes session audio (ffmpeg -> WAV -> stdlib wave), then for each call word
searches ONLY [t_word - 2.0s, t_word - 0.15s] for a loud transient (the ball
hitting rim/board/net). No qualifying peak -> no_contact ("called a shot the
mic never heard land"); the voice stays ground truth. Fully removable: the
pipeline calls write_impacts() once and everything degrades gracefully.
"""
import json
import math
import shutil
import subprocess
import tempfile
import wave
from array import array
from pathlib import Path

SEARCH_BEFORE_S = 2.0    # how far before the call word to look
GUARD_BEFORE_S = 0.15    # stop this far before the word (its own onset)
ENVELOPE_HZ = 15         # loudness samples per second in the sidecar
DECODE_RATE = 16000      # mono 16 kHz is plenty for impact transients
PEAK_OVER_FLOOR = 4.0    # peak must exceed this multiple of the window median
MIN_PEAK_LEVEL = 0.10    # ...and this fraction of the session's loudest moment
FLOOR_EPS = 0.005        # median floor for the ratio test on near-silent windows

def decode_pcm(audio_path: Path, rate: int = DECODE_RATE):
    """Audio file -> mono 16-bit PCM samples (array('h')), or None on any failure."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return None
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "decoded.wav"
        proc = subprocess.run(
            [ffmpeg, "-v", "error", "-i", str(audio_path),
             "-ac", "1", "-ar", str(rate), "-f", "wav", str(out)],
            capture_output=True)
        if proc.returncode != 0 or not out.exists():
            return None
        try:
            with wave.open(str(out)) as w:
                if w.getsampwidth() != 2:
                    return None
                frames = w.readframes(w.getnframes())
        except (wave.Error, EOFError, OSError):
            return None
    samples = array("h")
    samples.frombytes(frames[: len(frames) - len(frames) % 2])
    return samples

def loudness_envelope(samples, rate: int = DECODE_RATE, hz: int = ENVELOPE_HZ) -> list[float]:
    """RMS per 1/hz block, normalized so the loudest block is 1.0."""
    block = max(1, rate // hz)
    out = []
    for i in range(0, len(samples), block):
        chunk = samples[i:i + block]
        out.append(math.sqrt(sum(s * s for s in chunk) / len(chunk)))
    peak = max(out) if out else 0.0
    if peak <= 0:
        return [0.0] * len(out)
    return [round(v / peak, 4) for v in out]

def find_impact(envelope: list[float], hz: int, t_word: float) -> float | None:
    """Loudest transient in [t_word - 2.0, t_word - 0.15], or None (no contact)."""
    lo = max(0, int((t_word - SEARCH_BEFORE_S) * hz))
    hi = int((t_word - GUARD_BEFORE_S) * hz)
    window = envelope[lo:hi]
    if not window:
        return None
    peak = max(window)
    floor = sorted(window)[len(window) // 2]
    if peak < MIN_PEAK_LEVEL or peak < PEAK_OVER_FLOOR * max(floor, FLOOR_EPS):
        return None
    return round((lo + window.index(peak) + 0.5) / hz, 3)

def build_impacts(audio_path: Path, rows: list[dict]) -> dict | None:
    samples = decode_pcm(audio_path)
    if not samples:
        return None
    envelope = loudness_envelope(samples)
    shots = []
    for r in rows:
        if r["voided"]:
            shots.append({"shot_num": r["shot_num"], "impact_t_s": None,
                          "no_contact": False})
            continue
        t = find_impact(envelope, ENVELOPE_HZ, r["t_call_s"])
        shots.append({"shot_num": r["shot_num"], "impact_t_s": t,
                      "no_contact": t is None})
    return {"envelope": envelope, "envelope_hz": ENVELOPE_HZ, "shots": shots}

def write_impacts(sdir: Path, audio_path: Path | None, rows: list[dict]) -> dict | None:
    """The removable pipeline stage. Never raises, never blocks the email."""
    if audio_path is None:
        return None
    try:
        data = build_impacts(audio_path, rows)
        if data is not None:
            (sdir / "impacts.json").write_text(json.dumps(data))
        return data
    except Exception:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_impacts.py -v`
Expected: all PASS (the ffmpeg test may SKIP on machines without ffmpeg — macOS dev box has it via Homebrew; a skip is acceptable).

- [ ] **Step 5: Commit**

```bash
git add src/hoops/impacts.py tests/test_impacts.py
git commit -m "feat: impact-sound detection + loudness envelope (impacts.py)"
```

---

### Task 2: Chase/runs in `stats.py` + narrative drama context

**Files:**
- Modify: `src/hoops/stats.py` (append `build_chase`, extend `build_session_stats` return — additive keys only)
- Modify: `src/hoops/narrative.py` (payload keys + system prompt)
- Test: `tests/test_stats.py` (append), `tests/test_narrative.py` (append)

**Interfaces:**
- Consumes: shot rows (`build_shot_rows` output).
- Produces (Tasks 4/5 rely on these): `build_chase(rows) -> dict` with keys `runs: list[{"result","start_shot","end_shot","start_t","end_t","length"}]`, `almosts: int`, `closed_out: bool`. `build_session_stats` output gains exactly three keys: `"runs"`, `"almost_closeouts"`, `"closed_out"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_stats.py` (follow its existing style — build rows via `hoops.parse.Call` + `build_shot_rows` if that's the file's pattern, otherwise hand-built dicts are fine; the functions only read `result`, `shot_num`, `t_call_s`, `voided`):

```python
from hoops.stats import build_chase

def _row(n, result, t, voided=False):
    return {"shot_num": n, "result": result, "t_call_s": float(t), "voided": voided}

def test_chase_counts_broken_two_in_a_row():
    # miss, make, make, miss, make, make, miss, make, make, make -> 2 almosts, closed
    seq = ["miss", "make", "make", "miss", "make", "make", "miss",
           "make", "make", "make"]
    rows = [_row(i + 1, r, 5 * (i + 1)) for i, r in enumerate(seq)]
    chase = build_chase(rows)
    assert chase["almosts"] == 2
    assert chase["closed_out"] is True
    assert chase["runs"][0] == {"result": "miss", "start_shot": 1, "end_shot": 1,
                                "start_t": 5.0, "end_t": 5.0, "length": 1}
    assert chase["runs"][-1]["length"] == 3

def test_chase_final_two_run_is_not_an_almost():
    seq = ["make", "make"]                       # session ended without closing
    rows = [_row(i + 1, r, 5 * (i + 1)) for i, r in enumerate(seq)]
    chase = build_chase(rows)
    assert chase["almosts"] == 0
    assert chase["closed_out"] is False

def test_chase_skips_voided_rows():
    rows = [_row(1, "make", 5), _row(2, "make", 8, voided=True),
            _row(3, "miss", 12)]
    chase = build_chase(rows)
    assert [r["result"] for r in chase["runs"]] == ["make", "miss"]

def test_chase_empty():
    assert build_chase([]) == {"runs": [], "almosts": 0, "closed_out": False}

def test_session_stats_gains_chase_keys():
    # SEQ and call() are this file's existing module-level helpers
    rows = build_shot_rows(SEQ, "s", "2026-07-27")
    stats = build_session_stats(rows, ParseResult(), [], session_id="s",
        session_date_local="2026-07-27", start_time_local="06:12:04",
        session_len_s=50.0, transcriber="whisper-1", parser_version="1",
        profanity=["fuck"])
    assert stats["closed_out"] is True            # SEQ ends make, make, make
    assert stats["almost_closeouts"] == 0         # no broken 2-run: the make at
                                                  # 12.0 stands alone (18.0 voided)
    assert stats["runs"][-1]["length"] == 3
```

Append to `tests/test_narrative.py` (uses the file's existing `_fake`/`good_reply` helpers, but with a payload-capturing client):

```python
def test_narrative_payload_includes_chase_context(monkeypatch):
    sent = {}
    class Msg:
        content = [type("T", (), {"text": good_reply()})()]
    class Messages:
        def create(self, **kw):
            sent.update(kw)
            return Msg()
    class FakeClient:
        def __init__(self): self.messages = Messages()
    monkeypatch.setattr("hoops.narrative.anthropic.Anthropic", lambda: FakeClient())
    stats = dict(STATS, almost_closeouts=2, closed_out=True, uncorroborated_calls=1)
    n = generate_narrative(stats, ENV, "m")
    assert n is not None
    payload = sent["messages"][0]["content"]
    assert "almost_closeouts" in payload and "uncorroborated_calls" in payload
    assert "almost_closeouts" in sent["system"] or "almost_closeouts" in payload
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_stats.py tests/test_narrative.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_chase'`

- [ ] **Step 3: Implement**

Append to `src/hoops/stats.py`:

```python
def build_chase(rows: list[dict]) -> dict:
    """Run structure of the session: consecutive same-result runs over live shots,
    how many two-in-a-row make runs got broken ('almosts'), and whether the
    session closed on three straight makes."""
    live = [r for r in rows if not r["voided"]]
    runs: list[dict] = []
    for r in live:
        if runs and runs[-1]["result"] == r["result"]:
            runs[-1]["end_shot"] = r["shot_num"]
            runs[-1]["end_t"] = r["t_call_s"]
            runs[-1]["length"] += 1
        else:
            runs.append({"result": r["result"], "start_shot": r["shot_num"],
                         "end_shot": r["shot_num"], "start_t": r["t_call_s"],
                         "end_t": r["t_call_s"], "length": 1})
    closed_out = bool(runs) and runs[-1]["result"] == "make" and runs[-1]["length"] >= 3
    almosts = sum(1 for i, run in enumerate(runs)
                  if run["result"] == "make" and run["length"] == 2
                  and i < len(runs) - 1)
    return {"runs": runs, "almosts": almosts, "closed_out": closed_out}
```

In `build_session_stats`, before the `return`, compute `chase = build_chase(rows)` and add to the returned dict (keep every existing key untouched):

```python
        "runs": chase["runs"],
        "almost_closeouts": chase["almosts"],
        "closed_out": chase["closed_out"],
```

In `src/hoops/narrative.py`, extend the payload key list (line ~25) to:

```python
['shots_to_three', 'makes', 'misses', 'longest_make_streak',
 'longest_miss_streak', 'median_gap_s', 'session_len_s', 'notes',
 'almost_closeouts', 'closed_out', 'uncorroborated_calls']
```

and add two lines to `_SYSTEM` after the quote rule (keeping every existing rule verbatim):

```
- Context may include almost_closeouts (two-in-a-row make runs that got broken
  before the closeout) and uncorroborated_calls (calls where no ball-impact
  sound was heard — feel free to tease, gently, that the mic has doubts).
  Reference them only in words, never digits.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_stats.py tests/test_narrative.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/hoops/stats.py src/hoops/narrative.py tests/test_stats.py tests/test_narrative.py
git commit -m "feat: chase/runs session structure + narrative drama context"
```

---

### Task 3: Report — impacts plumbing, replay physics, waveform, lie markers

**Files:**
- Modify: `src/hoops/report_html.py`
- Test: `tests/test_report_html.py` (append; also add `"runs": [...]`, `"almost_closeouts": 0`, `"closed_out": True` keys to the shared `STATS` fixture since Task 2 made stats carry them)

**Interfaces:**
- Consumes: `impacts` dict from Task 1 (`{"envelope", "envelope_hz", "shots"}`) — as a new **keyword arg**.
- Produces (Task 5 relies on this): `render_interactive_report(stats, rows, narrative, flags, words, audio_path, impacts=None)`. DATA blob gains: per-shot `impact` (float|null) and `lie` (bool); top-level `wave` (`{"env": [...], "hz": 15}` or null).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_report_html.py`:

```python
IMPACTS = {"envelope": [0.02] * 500 + [0.9] + [0.02] * 30, "envelope_hz": 15,
           "shots": [{"shot_num": 1, "impact_t_s": 3.9, "no_contact": False},
                     {"shot_num": 2, "impact_t_s": None, "no_contact": True},
                     {"shot_num": 3, "impact_t_s": None, "no_contact": False},
                     {"shot_num": 4, "impact_t_s": 19.2, "no_contact": False},
                     {"shot_num": 5, "impact_t_s": 25.1, "no_contact": False}]}

def test_data_carries_impacts():
    d = data_blob(render(impacts=IMPACTS))
    by_n = {s["n"]: s for s in d["shots"]}
    assert by_n[1]["impact"] == 3.9 and by_n[1]["lie"] is False
    assert by_n[2]["impact"] is None and by_n[2]["lie"] is True
    assert d["wave"]["hz"] == 15 and len(d["wave"]["env"]) == 531

def test_data_without_impacts_degrades():
    d = data_blob(render())            # impacts omitted entirely
    assert d["wave"] is None
    assert all(s["impact"] is None and s["lie"] is False for s in d["shots"])

def test_waveform_svg_present():
    html = render(impacts=IMPACTS)
    assert "id='waveform'" in html or 'id="waveform"' in html

def test_uncorroborated_stat_shown():
    stats = dict(STATS, uncorroborated_calls=1)
    html = render(stats=stats)
    assert "Uncorroborated" in html and "🤥" in html

def test_replay_physics_constants_in_js():
    html = render(impacts=IMPACTS)
    assert "FLIGHT_S = 0.6" in html
    assert "FALLBACK_LEAD_S = 0.5" in html

def test_self_contained_with_impacts():
    html = render(impacts=IMPACTS)
    assert not re.search(r"(src|href)\s*=\s*['\"]https?://", html)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_report_html.py -v`
Expected: new tests FAIL (`unexpected keyword argument 'impacts'`); pre-existing tests still pass.

- [ ] **Step 3: Implement**

In `src/hoops/report_html.py`:

**(a)** Signature + data. `render_interactive_report(stats, rows, narrative, flags, words, audio_path, impacts=None)` passes `impacts` to `_build_data`:

```python
def _build_data(stats, rows, narrative, flags, words, has_audio: bool,
                impacts=None) -> dict:
    by_shot = {s["shot_num"]: s for s in (impacts or {}).get("shots", [])}
    shots = [{"n": r["shot_num"], "result": r["result"], "t": r["t_call_s"],
              "gap": r["gap_s"], "streak": r["streak_after"],
              "voided": r["voided"], "raw": r["raw_token"],
              "impact": (by_shot.get(r["shot_num"]) or {}).get("impact_t_s"),
              "lie": bool((by_shot.get(r["shot_num"]) or {}).get("no_contact"))}
             for r in rows]
    ...  # words/narrative unchanged
    return {..., "wave": ({"env": impacts["envelope"], "hz": impacts["envelope_hz"]}
                          if impacts else None)}
```

**(b)** Movie section: insert a waveform SVG between the scrubber and scrub-marks inside `#scrub-wrap`:

```html
<div id='scrub-wrap'>
  <svg id='waveform' viewBox='0 0 640 40' preserveAspectRatio='none'
       aria-label='session loudness'></svg>
  <input id='scrubber' type='range' min='0' max='100' step='0.1' value='0'>
  <div id='scrub-marks'></div>
</div>
```

CSS: `#waveform { width:100%; height:34px; display:block; }`.

**(c)** Stats grid, Fun group — add after "Words per miss":

```python
("Uncorroborated 🤥", stats.get("uncorroborated_calls", "—")),
```

**(d)** Replay JS physics. In the audio block, after `const dur = ...`:

```js
const FLIGHT_S = 0.6, FALLBACK_LEAD_S = 0.5;
live.forEach(s => {
  s.land = s.impact != null ? s.impact : Math.max(0, s.t - FALLBACK_LEAD_S);
  s.launch = Math.max(0, s.land - FLIGHT_S);
});
```

Split `fireShot` into two: `fireFlight(s)` (ball animation classes + scoreboard update, exactly the current body minus the flash lines) and `fireFlash(s)` (the `flash.*` lines; when `s.lie`, append `' 🤥'` to `flash.textContent`). Replace the single `fired` set with two:

```js
let firedFly = new Set(), firedFlash = new Set();
function sync() {
  const t = audio.currentTime;
  scrub.value = t;
  live.forEach(s => {
    if (t >= s.launch && !firedFly.has(s.n)) { firedFly.add(s.n); fireFlight(s); }
    if (t >= s.t && !firedFlash.has(s.n)) { firedFlash.add(s.n); fireFlash(s); }
    if (t < s.launch) firedFly.delete(s.n);
    if (t < s.t) firedFlash.delete(s.n);
  });
}
```

Update `audio.onseeked` to rebuild both sets (`firedFly` from `s.launch <= t`, `firedFlash` from `s.t <= t`) and keep the scoreboard recount as-is. Change the CSS animation durations from `.9s` to `.6s` so the ball lands when the impact plays.

**(e)** Waveform render + impact markers, after the scrub-marks loop:

```js
const wsvg = document.getElementById('waveform');
if (DATA.wave && wsvg) {
  const n = DATA.wave.env.length, W = 640, frag = [];
  DATA.wave.env.forEach((v, i) => {
    const h = Math.max(1, v * 34);
    frag.push(`<rect x="${(i / n * W).toFixed(1)}" y="${(36 - h).toFixed(1)}" ` +
              `width="${Math.max(0.6, W / n * 0.8).toFixed(2)}" height="${h.toFixed(1)}" fill="#c9a678"/>`);
  });
  live.filter(s => s.impact != null).forEach(s => {
    const x = (s.impact / dur * W).toFixed(1);
    frag.push(`<polygon points="${x},8 ${x - 4},0 ${Number(x) + 4},0" fill="var(--ball)"/>`);
  });
  wsvg.innerHTML = frag.join('');
} else if (wsvg) { wsvg.style.display = 'none'; }
```

**(f)** Tooltip card: append `(s.impact != null ? `<br>impact @ ${s.impact.toFixed(1)}s` : '') + (s.lie ? '<br>🤥 no impact heard' : '')`.

Update the module's internal callers of `_build_data` accordingly. `pipeline.py` is NOT touched in this task (Task 5 wires the new kwarg; the default `impacts=None` keeps it working meanwhile).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_report_html.py -v`
Expected: PASS, including the pre-existing DATA/self-containment tests.

- [ ] **Step 5: Commit**

```bash
git add src/hoops/report_html.py tests/test_report_html.py
git commit -m "feat(report): impact-aligned replay physics, waveform strip, lie markers"
```

---

### Task 4: Report — choreography, chase annotations, shot-anchored transcript

**Files:**
- Modify: `src/hoops/report_html.py`
- Test: `tests/test_report_html.py` (append)

**Interfaces:**
- Consumes: `stats["runs"]` / `stats["closed_out"]` (Task 2), DATA shots with `land`/`lie` (Task 3).
- Produces: no new Python interfaces; HTML/JS only.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_report_html.py` (the shared `STATS` should by now carry `runs`/`almost_closeouts`/`closed_out` from Task 3's fixture update; if not, add them here):

```python
def _stats_with_chase():
    return dict(STATS, runs=[
        {"result": "miss", "start_shot": 1, "end_shot": 1, "start_t": 5.0,
         "end_t": 5.0, "length": 1},
        {"result": "make", "start_shot": 2, "end_shot": 5, "start_t": 12.0,
         "end_t": 26.0, "length": 3},
    ], almost_closeouts=1, closed_out=True)

def test_timeline_has_chase_annotations():
    html = render(stats=dict(_stats_with_chase(), runs=[
        {"result": "make", "start_shot": 1, "end_shot": 2, "start_t": 5.0,
         "end_t": 12.0, "length": 2},
        {"result": "miss", "start_shot": 3, "end_shot": 3, "start_t": 15.0,
         "end_t": 15.0, "length": 1},
        {"result": "make", "start_shot": 4, "end_shot": 6, "start_t": 20.0,
         "end_t": 30.0, "length": 3}]))
    assert "so close" in html
    assert "🏁" in html

def test_transcript_is_shot_anchored():
    html = render()
    assert "#1 MISS" in html and "#2 MAKE" in html
    assert "VOIDED" in html            # row 3 is voided
    assert "gap 7.0s" in html          # shot 2's header carries its gap
    assert "Warmup" not in html        # no words before the first call in fixture
    # trailing silence: last word IS the last call -> no cooldown block either

def test_transcript_warmup_and_cooldown_blocks():
    words = [Word("morning", "morning", 1.0, 1.3, None)] + WORDS + \
            [Word("done", "done", 30.0, 30.2, None)]
    html = render(words=words)
    assert "Warmup" in html and "Cooldown" in html

def test_choreography_markup_present():
    html = render(impacts=IMPACTS)
    assert "netRipple" in html         # make: net ripple keyframes
    assert "confetti" in html          # closeout celebration
    assert "bounce" in html.lower()    # miss: rim bounce-out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_report_html.py -v`
Expected: the four new tests FAIL; everything else passes.

- [ ] **Step 3: Implement**

**(a) Timeline chase annotations.** `_timeline_svg(rows, session_len)` → `_timeline_svg(rows, session_len, stats)`. After the existing dots, using `runs = stats.get("runs") or []`:

```python
    for i, run in enumerate(runs):
        if run["result"] == "make" and run["length"] == 2 and i < len(runs) - 1:
            x1, x2 = x(run["start_t"]), x(run["end_t"])
            parts.append(f'<path d="M{x1:.1f} 30 Q {(x1 + x2) / 2:.1f} 18 {x2:.1f} 30" '
                         f'fill="none" stroke="var(--ball)" stroke-width="2"/>'
                         f'<text x="{(x1 + x2) / 2:.1f}" y="14" text-anchor="middle" '
                         f'font-size="10" fill="var(--ball)" font-weight="700">so close</text>')
    if stats.get("closed_out") and runs:
        parts.append(f'<text x="{x(runs[-1]["end_t"]) + 12:.1f}" y="66" '
                     f'font-size="13">🏁</text>')
```

(The existing green close-run underline stays; the 🏁 sits at its end.)

**(b) Choreography.** In the movie SVG give the net path `id='net'`, add hidden effect groups after the ball:

```html
<g id='splash-fx' opacity='0' font-size='11' fill='var(--make)'>
  <text x='222' y='50'>✦</text><text x='252' y='48'>✦</text>
  <text x='230' y='86'>✦</text><text x='246' y='90'>✦</text><text x='218' y='74'>✦</text>
</g>
<g id='confetti-fx' opacity='0'>
  <rect x='120' y='10' width='5' height='8' fill='#e2711d'/>
  <rect x='150' y='4' width='5' height='8' fill='#1a7f37'/>
  <rect x='180' y='12' width='5' height='8' fill='#c0392b'/>
  <rect x='210' y='6' width='5' height='8' fill='#e2b81d'/>
  <rect x='140' y='18' width='5' height='8' fill='#1a5f7f'/>
  <rect x='195' y='16' width='5' height='8' fill='#8a2be2'/>
</g>
```

CSS:

```css
#net.ripple { animation:netRipple .5s ease-out; transform-origin:236px 64px; }
@keyframes netRipple { 40% { transform:scaleY(1.3) scaleX(1.12); } }
#splash-fx.burst { animation:fxBurst .7s ease-out; }
@keyframes fxBurst { 0% { opacity:0; } 25% { opacity:1; } 100% { opacity:0; transform:translateY(-8px); } }
#confetti-fx.pop { animation:confettiFall 1.6s ease-in; }
@keyframes confettiFall { 0% { opacity:0; transform:translateY(-20px); }
  15% { opacity:1; } 100% { opacity:0; transform:translateY(150px); } }
@keyframes flyMiss { 40% { cx:180px; cy:40px; } 55% { cx:228px; cy:56px; }
  70% { cx:210px; cy:44px; } 100% { cx:186px; cy:172px; } }  /* rim bounce-out */
```

JS in `fireFlight(s)` after the ball classes:

```js
if (s.result === 'make') {
  ['net', 'splash-fx'].forEach((id, k) => {
    const el = document.getElementById(id);
    el.classList.remove('ripple', 'burst'); void el.getBBox();
    el.classList.add(k === 0 ? 'ripple' : 'burst');
  });
  const lastLive = live[live.length - 1];
  if (s.n === lastLive.n && s.streak >= 3) {
    const c = document.getElementById('confetti-fx');
    c.classList.remove('pop'); void c.getBBox(); c.classList.add('pop');
  }
}
```

(Keep `flyMake`; only `flyMiss`'s keyframes change to the bounce-out path. Both animations become `.6s` per Task 3.)

**(c) Shot-anchored transcript.** Replace `_transcript(words, rows)` wholesale:

```python
def _fmt_mmss(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"

def _transcript(words, rows) -> str:
    """Shot-anchored blocks (spec layout C): the first call's block holds only
    its call word (earlier words are Warmup); every later block holds the words
    since the previous call, inclusive of its own call word; trailing words are
    Cooldown. Clicking a block seeks the audio."""
    e = _html.escape

    def span(w):
        row = _call_row_for(w, rows)
        if row:
            cls = "call-make" if row["result"] == "make" else "call-miss"
            return f"<span class='word {cls}' data-t='{w.start}'>{e(w.text)}</span>"
        return f"<span class='word aside'>{e(w.text)}</span>"

    out = ["<section><h2>Transcript</h2>"]

    def block(head_html, chunk, t_seek):
        body = " ".join(span(w) for w in chunk) or "<span class='word aside'>—</span>"
        out.append(f"<div class='tblock' data-t='{t_seek}'>"
                   f"<div class='thead'>{head_html}</div><p>{body}</p></div>")

    first_t = rows[0]["t_call_s"] if rows else float("inf")
    warmup = [w for w in words if w.start < first_t - CALL_MATCH_TOLERANCE_S]
    if warmup:
        block("<b>Warmup</b> · 0:00", warmup, 0)
    prev_t = first_t - CALL_MATCH_TOLERANCE_S
    for r in rows:
        chunk = [w for w in words
                 if prev_t <= w.start <= r["t_call_s"] + CALL_MATCH_TOLERANCE_S]
        prev_t = r["t_call_s"] + CALL_MATCH_TOLERANCE_S
        t = r["t_call_s"]
        if r["voided"]:
            head = (f"<b style='color:var(--dim)'>#{r['shot_num']} VOIDED</b>"
                    f" · {_fmt_mmss(t)}")
        else:
            color = "var(--make)" if r["result"] == "make" else "var(--miss)"
            head = (f"<b style='color:{color}'>#{r['shot_num']} "
                    f"{r['result'].upper()}</b> · {_fmt_mmss(t)}")
            if r["gap_s"] is not None:
                head += f" · gap {r['gap_s']:.1f}s"
        block(head, chunk, t)
    cooldown = [w for w in words if w.start > prev_t]
    if cooldown:
        block(f"<b>Cooldown</b> · {_fmt_mmss(cooldown[0].start)}",
              cooldown, cooldown[0].start)
    out.append("</section>")
    return "".join(out)
```

CSS:

```css
.tblock { border-left:3px solid #eee; padding:4px 10px; margin:8px 0;
          background:#fdfbf8; border-radius:0 8px 8px 0; cursor:pointer; }
.tblock .thead { font-size:11px; color:var(--dim); margin-bottom:2px; }
.tblock p { margin:0; }
```

JS (with the other click wiring):

```js
document.querySelectorAll('.tblock[data-t]').forEach(el =>
  el.addEventListener('click', () => seekTo(parseFloat(el.dataset.t))));
```

Update `_charts_section` to pass `stats` into `_timeline_svg`.

- [ ] **Step 4: Run full report tests**

Run: `uv run pytest tests/test_report_html.py -v`
Expected: PASS including `test_self_contained`.

- [ ] **Step 5: Commit**

```bash
git add src/hoops/report_html.py tests/test_report_html.py
git commit -m "feat(report): make/miss choreography, chase annotations, shot-anchored transcript"
```

---

### Task 5: Pipeline wiring, cloud ffmpeg, docs

**Files:**
- Modify: `src/hoops/pipeline.py` (both `process_file` and `replay_session`)
- Modify: `cloud/modal_app.py` (image gets ffmpeg)
- Modify: `CLAUDE.md` (status bullet — same-change rule)
- Test: `tests/test_pipeline.py` (append)

**Interfaces:**
- Consumes: `write_impacts(sdir, audio_path, rows) -> dict | None` (Task 1); `render_interactive_report(..., impacts=...)` (Task 3).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pipeline.py`, following its existing fixtures/stub-transcriber pattern:

```python
def test_pipeline_writes_impacts_and_uncorroborated(monkeypatch, ...existing fixture args...):
    canned = {"envelope": [0.1, 0.9], "envelope_hz": 15,
              "shots": [{"shot_num": 1, "impact_t_s": 4.0, "no_contact": False},
                        {"shot_num": 2, "impact_t_s": None, "no_contact": True}]}
    def fake_write(sdir, audio_path, rows):
        (sdir / "impacts.json").write_text(json.dumps(canned))
        return canned
    monkeypatch.setattr("hoops.pipeline.write_impacts", fake_write)
    out = ...run process_file the way existing tests do...
    stats = json.loads((out.session_dir / "session.json").read_text())
    assert stats["uncorroborated_calls"] == 1
    assert (out.session_dir / "impacts.json").exists()
    assert '"wave"' in (out.session_dir / "report.html").read_text()

def test_pipeline_survives_impacts_failure(monkeypatch, ...):
    monkeypatch.setattr("hoops.pipeline.write_impacts", lambda *a: None)
    out = ...run process_file...
    assert out.status == "ok"
    stats = json.loads((out.session_dir / "session.json").read_text())
    assert "uncorroborated_calls" not in stats
```

(Adapt the `...` to the file's real fixture names — the assertions are the requirement. Real runs on the fake test audio already return `None` from `write_impacts` because ffmpeg can't decode it; the second test pins the contract regardless.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: new tests FAIL with `AttributeError: ... has no attribute 'write_impacts'`

- [ ] **Step 3: Implement**

`src/hoops/pipeline.py`:

- Import: `from .impacts import write_impacts`
- In `process_file`, immediately after `stats["vocab_map"] = vocab.surface_to_canonical` and **before** `write_shots_csv(sdir, rows)`:

```python
    impacts = write_impacts(sdir, path if path.exists() else None, rows)
    if impacts is not None:
        stats["uncorroborated_calls"] = sum(
            1 for s in impacts["shots"] if s["no_contact"])
```

- Pass it to the report call: `render_interactive_report(stats, rows, narrative, flags, words, audio_path, impacts=impacts)`.
- In `replay_session`, move the `audio_path = sdir / "audio.m4a"` line above the stats block, then after `stats["vocab_name"], stats["vocab_map"] = ...`:

```python
    impacts = write_impacts(sdir, audio_path if audio_path.exists() else None, rows)
    if impacts is not None:
        stats["uncorroborated_calls"] = sum(
            1 for s in impacts["shots"] if s["no_contact"])
```

and pass `impacts=impacts` to its `render_interactive_report` call.

`cloud/modal_app.py` — one line in the image chain, right after `debian_slim(...)`:

```python
    .apt_install("ffmpeg")
```

`CLAUDE.md` — in the "Current status" email/report bullet, extend the report description to mention: impact-aligned replay with 🤥 no-contact flags (`impacts.json` sidecar, ffmpeg-optional post-processing in `src/hoops/impacts.py`), waveform scrubber, runs/chase annotations, shot-anchored transcript.

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest`
Expected: all green (paid excluded).

- [ ] **Step 5: Deploy the cloud image change**

Run: `set -a; source .env.r2; set +a; modal deploy cloud/modal_app.py`
Expected: deploy succeeds. If credentials/environment are unavailable in your context, report DONE_WITH_CONCERNS naming this exact command for the owner instead of skipping silently.

- [ ] **Step 6: Commit**

```bash
git add src/hoops/pipeline.py cloud/modal_app.py CLAUDE.md tests/test_pipeline.py
git commit -m "feat: wire impacts stage into pipeline + cloud ffmpeg + docs"
```

---

## Final verification (main session, after all tasks)

1. `uv run pytest` — full suite green.
2. `uv run hoops score` — unchanged results (parser untouched; phantom gates still pass).
3. Byte-identical parse artifacts: snapshot `sessions/`, run `uv run hoops replay --all`, and `git diff --no-index` the snapshots — `transcript.json` and `shots.csv` must be byte-identical; `session.json`/`report.html`/`impacts.json` are expected to change (capability change).
4. Eyeball one real session's regenerated `report.html`: impact markers sit on waveform bumps, ball lands before the voice, chase annotations and transcript blocks render, 🤥 only where plausible.
