# Dual-Branch Capture (Acoustics + Fusion) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent acoustic impact-detection branch (librosa HPSS) plus a fusion step that pairs voice calls to impact clusters, replacing the voice-seeded `impacts.py`, with threshold-sweep and make/miss-separability analyses before cloud deploy.

**Architecture:** Branch A (voice: `transcribe.py` → `parse.py`) is untouched. New `src/hoops/acoustics.py` (branch B) detects impact clusters and features from audio alone; new `src/hoops/fusion.py` (pure stdlib) is the only place the branches' *outputs* meet. Pipeline gains two never-raise optional stages writing `acoustics.json` + `fusion.json`; the report consumes those sidecars instead of `impacts.json`.

**Tech Stack:** Python 3.12, uv, librosa + numpy (new), ffmpeg (present), pytest. Spec: `docs/superpowers/specs/2026-08-01-dual-capture-acoustics-design.md`. Source brief: `from_claude/claude-code-brief-dual-capture.md`; prototype: `from_claude/impact_detect.py`.

## Global Constraints

- **Branch independence (the core rule):** `acoustics.py` must not import `parse`, `transcribe`, or `fusion`; `fusion.py` must not import `acoustics`, `parse`, or `transcribe`; `parse.py`/`transcribe.py` must not import `acoustics` or `fusion`. Impact detection never uses call times; parsing never uses impact times. Enforced by a source-scanning test.
- Branch A untouched: `parse.py`, `transcribe.py`, `invariants.py`, `stats.py` unmodified. `shots.csv` columns and content unchanged. Parse artifacts (`transcript.json`, `transcript.txt`, `shots.csv`) byte-identical under `uv run hoops replay --all`; `uv run hoops score` passes unchanged.
- New pipeline stages **never raise**: any failure (librosa missing, decode error, bad params) → return `None`, sidecar absent, email still sent, report degrades to voice-only.
- All tunables live in config (`acoustics:` / `fusion:` blocks in `config.yaml` AND `cloud/config.cloud.yaml`); `acoustics.py`/`fusion.py` take every threshold as a parameter — no numeric literals except the documented defaults table in `config.py`.
- Voice is authoritative for make/miss. Fusion records disagreement; never overrides.
- Deterministic throughout; no LLM in either branch or fusion. No `random` without a fixed seed.
- Dependencies: only `librosa` + `numpy` may be added. Nothing else without asking.
- Report stays ONE self-contained HTML (zero external requests — `test_self_contained` must stay green) and must render fine with zero sidecars.
- Sidecar names exactly: `acoustics.json`, `fusion.json`. Pairing statuses exactly: `paired`, `impact_missing`, `call_missing`, `ambiguous`, `warmup`, `voided`.
- `modal deploy` happens only in Task 7, after all local gates pass. Deploy env: `set -a; source .env; set +a; uv run modal deploy cloud/modal_app.py`. Never print or commit `.env` values.
- Run tests with `uv run pytest`. Commit messages end with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

**Voice row schema (branch A input to fusion — already exists, from `stats.build_shot_rows`):**
```python
{"session_id": str, "session_date_local": str, "shot_num": int, "result": "make"|"miss",
 "t_call_s": float, "gap_s": float|None, "streak_after": int, "voided": bool,
 "isolation_s": float, "confidence": float, "raw_token": str}
```

**Acoustic event schema (branch B output, consumed by fusion + report + scripts):**
```python
{"t_start": float, "t_end": float, "n_impacts": int, "impact_times": [float],
 "burst_duration_s": float, "mean_centroid_hz": float, "max_peak_rms": float,
 "mean_decay_ratio": float,
 "impacts": [{"time": float, "centroid_hz": float, "bandwidth_hz": float,
              "peak_rms": float, "decay_ratio": float}]}
```

---

### Task 1: Dependencies + config plumbing

**Files:**
- Modify: `pyproject.toml` (dependencies list)
- Modify: `cloud/modal_app.py` (image `pip_install` list, ~line 14)
- Modify: `src/hoops/config.py`
- Modify: `config.yaml`
- Modify: `cloud/config.cloud.yaml`
- Test: `tests/test_config_blocks.py` (new)

**Interfaces:**
- Produces: `Config.acoustics: dict` and `Config.fusion: dict` (merged over `DEFAULT_ACOUSTICS` / `DEFAULT_FUSION` module constants in `config.py`). Later tasks call `cfg.acoustics` / `cfg.fusion` and read keys exactly as named below.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_blocks.py
"""acoustics:/fusion: config blocks parse, and defaults survive their absence."""
from pathlib import Path
import pytest
from hoops.config import load_config, DEFAULT_ACOUSTICS, DEFAULT_FUSION

MINIMAL = """\
timezone: America/Los_Angeles
inbox: /tmp/inbox
sessions_root: sessions
prefix: hoops
vocab_default: swish_brick
vocabularies:
  swish_brick: {make: [swish], miss: [brick]}
isolation: {low: 0.15, high: 0.4}
limits: {min_duration_s: 5, max_duration_s: 1200, min_gap_s: 1.5, max_gap_s: 120}
transcriber: {model: whisper-1}
llm: {model: claude-sonnet-5}
email: {from: a@b.c, to: a@b.c, smtp_host: h, smtp_port: 465}
"""

@pytest.mark.unit
def test_missing_blocks_fall_back_to_defaults(tmp_path):
    (tmp_path / "config.yaml").write_text(MINIMAL)
    cfg = load_config(tmp_path / "config.yaml")
    assert cfg.acoustics == DEFAULT_ACOUSTICS
    assert cfg.fusion == DEFAULT_FUSION

@pytest.mark.unit
def test_partial_block_merges_over_defaults(tmp_path):
    (tmp_path / "config.yaml").write_text(MINIMAL + "\nacoustics:\n  onset_delta: 0.3\n")
    cfg = load_config(tmp_path / "config.yaml")
    assert cfg.acoustics["onset_delta"] == 0.3
    assert cfg.acoustics["cluster_gap_s"] == DEFAULT_ACOUSTICS["cluster_gap_s"]

@pytest.mark.unit
def test_repo_configs_carry_explicit_blocks():
    # raw yaml, not load_config: cloud/config.cloud.yaml is a partial config
    import yaml
    root = Path(__file__).resolve().parents[1]
    for name in ("config.yaml", "cloud/config.cloud.yaml"):
        raw = yaml.safe_load((root / name).read_text())
        assert set(raw.get("acoustics") or {}) == set(DEFAULT_ACOUSTICS), name
        assert set(raw.get("fusion") or {}) == set(DEFAULT_FUSION), name
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_config_blocks.py -v`
Expected: FAIL — `ImportError: cannot import name 'DEFAULT_ACOUSTICS'`

- [ ] **Step 3: Implement config**

In `src/hoops/config.py`, after the imports add the defaults (this table is the ONE permitted home for numeric defaults — `acoustics.py`/`fusion.py` receive them as params):

```python
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
```

Add two fields at the END of the `Config` dataclass (frozen dataclass — defaulted fields must come last):

```python
    acoustics: dict = field(default_factory=lambda: dict(DEFAULT_ACOUSTICS))
    fusion: dict = field(default_factory=lambda: dict(DEFAULT_FUSION))
```

In `load_config(...)`, add to the `Config(...)` call:

```python
        acoustics={**DEFAULT_ACOUSTICS, **(raw.get("acoustics") or {})},
        fusion={**DEFAULT_FUSION, **(raw.get("fusion") or {})},
```

Append to `config.yaml` AND `cloud/config.cloud.yaml` (same block, both files):

```yaml
acoustics:                  # branch B — impact detection, independent of voice
  sr: 22050
  hop: 256
  n_fft: 1024
  hpss_margin_harmonic: 1.0
  hpss_margin_percussive: 4.0
  onset_delta: 0.4          # sweep-chosen — see docs/decisions/002-impact-detection-params.md
  min_spacing_frames: 15
  cluster_gap_s: 2.0
  envelope_hz: 15
  feature_win_s: 0.15

fusion:                     # pairing voice calls to impact clusters
  pair_min_s: 0.5
  pair_max_s: 4.0
```

In `pyproject.toml` `dependencies`, extend to:

```toml
dependencies = [
  "openai>=1.35", "anthropic>=0.40", "matplotlib>=3.9",
  "mutagen>=1.47", "pyyaml>=6.0", "python-dotenv>=1.0",
  "librosa>=0.10", "numpy>=1.26",
]
```

In `cloud/modal_app.py`, add `"librosa>=0.10", "numpy>=1.26"` to the image's `.pip_install(...)` list (do NOT deploy yet).

- [ ] **Step 4: Sync and run tests**

Run: `uv sync && uv run pytest tests/test_config_blocks.py -v` — expect PASS.
Then `uv run pytest` — full suite green (existing tests construct `Config` without the new fields; the defaults cover them).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock cloud/modal_app.py src/hoops/config.py config.yaml cloud/config.cloud.yaml tests/test_config_blocks.py
git commit -m "feat(config): librosa/numpy deps + acoustics/fusion config blocks"
```

---

### Task 2: `src/hoops/acoustics.py` — branch B

**Files:**
- Create: `src/hoops/acoustics.py`
- Test: `tests/test_acoustics.py` (new)

**Interfaces:**
- Consumes: `Config.acoustics` dict (Task 1 keys).
- Produces (Tasks 3–6 rely on these exact names):
  - `cluster_times(times: list[float], gap_s: float) -> list[list[float]]` — pure, no numpy.
  - `analyze_samples(y, sr: int, params: dict) -> dict` — may raise; needs numpy/librosa.
  - `analyze_audio(audio_path: Path, params: dict, duration_s: float | None = None) -> dict | None` — never raises.
  - `write_acoustics(sdir: Path, audio_path: Path | None, params: dict) -> dict | None` — never raises; writes `acoustics.json` on success.
  - Return dict: `{"envelope": [float], "envelope_hz": float, "events": [event dicts per Global Constraints schema]}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_acoustics.py
"""Branch B unit tests — synthetic signals only, except one 30s fixture smoke."""
import json
from pathlib import Path
import pytest
from hoops.acoustics import (cluster_times, analyze_samples, analyze_audio,
                             write_acoustics)
from hoops.config import DEFAULT_ACOUSTICS

ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.unit
def test_cluster_times_groups_bursts():
    assert cluster_times([1.0, 1.5, 2.2, 9.0, 9.1], 2.0) == [[1.0, 1.5, 2.2], [9.0, 9.1]]

@pytest.mark.unit
def test_cluster_times_empty_and_single():
    assert cluster_times([], 2.0) == []
    assert cluster_times([3.0], 2.0) == [[3.0]]

@pytest.mark.unit
def test_cluster_gap_is_between_neighbours_not_burst_start():
    # 1.0 -> 2.5 -> 4.0: each neighbour gap <= 2.0 even though span is 3.0
    assert cluster_times([1.0, 2.5, 4.0], 2.0) == [[1.0, 2.5, 4.0]]

def _click_track(sr, dur_s, click_ts):
    """Sustained low tone ('voice-ish' harmonic energy) + seeded broadband clicks."""
    import numpy as np
    rng = np.random.default_rng(0)
    n = int(sr * dur_s)
    y = 0.05 * np.sin(2 * np.pi * 220.0 * np.arange(n) / sr)
    burst = int(0.01 * sr)
    for t in click_ts:
        i = int(t * sr)
        y[i:i + burst] += rng.standard_normal(burst) * 0.8
    return y.astype("float32")

@pytest.mark.unit
def test_synthetic_clicks_survive_hpss_and_cluster():
    sr = DEFAULT_ACOUSTICS["sr"]
    y = _click_track(sr, 8.0, click_ts=(2.0, 2.2, 5.0))
    res = analyze_samples(y, sr, DEFAULT_ACOUSTICS)
    assert len(res["events"]) == 2                       # (2.0, 2.2) cluster + 5.0
    assert abs(res["events"][0]["t_start"] - 2.0) < 0.15
    assert abs(res["events"][1]["t_start"] - 5.0) < 0.15
    assert res["events"][0]["n_impacts"] >= 2
    for e in res["events"]:
        assert set(e) >= {"t_start", "t_end", "n_impacts", "impact_times",
                          "burst_duration_s", "mean_centroid_hz", "max_peak_rms",
                          "mean_decay_ratio", "impacts"}

@pytest.mark.unit
def test_envelope_normalized_and_hz_consistent():
    sr = DEFAULT_ACOUSTICS["sr"]
    res = analyze_samples(_click_track(sr, 8.0, (2.0,)), sr, DEFAULT_ACOUSTICS)
    assert res["envelope"] and max(res["envelope"]) <= 1.0 and min(res["envelope"]) >= 0.0
    # envelope length / envelope_hz must reconstruct ~the signal duration
    assert abs(len(res["envelope"]) / res["envelope_hz"] - 8.0) < 0.5

@pytest.mark.unit
def test_analyze_audio_missing_file_returns_none(tmp_path):
    assert analyze_audio(tmp_path / "nope.m4a", DEFAULT_ACOUSTICS) is None

@pytest.mark.unit
def test_write_acoustics_none_audio_returns_none(tmp_path):
    assert write_acoustics(tmp_path, None, DEFAULT_ACOUSTICS) is None
    assert not (tmp_path / "acoustics.json").exists()

@pytest.mark.unit
def test_write_acoustics_never_raises_on_bad_params(tmp_path):
    # missing keys must not escape as KeyError
    assert write_acoustics(tmp_path, tmp_path / "nope.m4a", {}) is None

@pytest.mark.unit
def test_write_acoustics_writes_sidecar(tmp_path, monkeypatch):
    canned = {"envelope": [0.1], "envelope_hz": 14.35, "events": []}
    monkeypatch.setattr("hoops.acoustics.analyze_audio", lambda *a, **k: canned)
    out = write_acoustics(tmp_path, tmp_path / "a.m4a", DEFAULT_ACOUSTICS)
    assert out == canned
    assert json.loads((tmp_path / "acoustics.json").read_text()) == canned

def test_fixture_f01_first_30s_finds_shot_events():
    """Real-audio smoke: decode + HPSS on F01's first 30s finds >=2 events."""
    res = analyze_audio(ROOT / "fixtures" / "F01_NormalSwishBrick.m4a",
                        DEFAULT_ACOUSTICS, duration_s=30.0)
    assert res is not None
    assert len(res["events"]) >= 2
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_acoustics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hoops.acoustics'`

- [ ] **Step 3: Implement `src/hoops/acoustics.py`**

```python
"""Branch B — objective impact detection. INDEPENDENT of the voice branch.

Separates ball impacts from voice on one mic via HPSS (voice is harmonic —
horizontal spectrogram ridges; impacts are percussive — vertical broadband
clicks), detects onsets on the percussive residual only, clusters them into
shot events (one shot = one burst: rim, board, floor), and extracts per-impact
spectral features. Ported from from_claude/impact_detect.py.

MUST NOT import parse, transcribe, or fusion (enforced by test): call times
never seed detection — coupled labels would poison the future classifier's
training data. librosa/numpy import lazily so the voice-only pipeline works
without them. Every threshold arrives via the params dict (config.yaml
`acoustics:` block); the only defaults live in config.DEFAULT_ACOUSTICS.
"""
import json
import warnings
from pathlib import Path


def cluster_times(times: list[float], gap_s: float) -> list[list[float]]:
    """Sorted onset times -> bursts; neighbours closer than gap_s share a burst."""
    clusters: list[list[float]] = []
    for t in times:
        if clusters and t - clusters[-1][-1] <= gap_s:
            clusters[-1].append(t)
        else:
            clusters.append([t])
    return clusters


def _impact_features(y, sr: int, t: float, win_s: float):
    """Spectral character of one impact: brightness (rim rings high, board thuds
    low), bandwidth, level, and decay (rim ring sustains; a dead thud doesn't)."""
    import librosa
    import numpy as np
    i0 = int(t * sr)
    seg = y[i0:i0 + int(win_s * sr)]
    if len(seg) < 512:
        return None
    S = np.abs(librosa.stft(seg, n_fft=512, hop_length=128))
    rms = librosa.feature.rms(S=S)[0]
    return {"time": round(float(t), 3),
            "centroid_hz": round(float(librosa.feature.spectral_centroid(S=S, sr=sr).mean()), 1),
            "bandwidth_hz": round(float(librosa.feature.spectral_bandwidth(S=S, sr=sr).mean()), 1),
            "peak_rms": round(float(rms.max()), 5),
            "decay_ratio": round(float(rms[-1] / (rms.max() + 1e-9)), 4)}


def analyze_samples(y, sr: int, params: dict) -> dict:
    """Mono float samples -> {envelope, envelope_hz, events}. May raise."""
    import librosa
    import numpy as np
    hop, n_fft = int(params["hop"]), int(params["n_fft"])
    D = librosa.stft(y, n_fft=n_fft, hop_length=hop)
    _, P = librosa.decompose.hpss(D, margin=(float(params["hpss_margin_harmonic"]),
                                             float(params["hpss_margin_percussive"])))
    y_perc = librosa.istft(P, hop_length=hop)
    env = librosa.onset.onset_strength(y=y_perc, sr=sr, hop_length=hop)
    env = env / (env.max() + 1e-9)
    peaks = librosa.util.peak_pick(env, pre_max=30, post_max=30, pre_avg=60,
                                   post_avg=60, delta=float(params["onset_delta"]),
                                   wait=int(params["min_spacing_frames"]))
    times = [float(t) for t in librosa.frames_to_time(peaks, sr=sr, hop_length=hop)]

    events = []
    for c in cluster_times(times, float(params["cluster_gap_s"])):
        feats = [f for f in (_impact_features(y, sr, t, float(params["feature_win_s"]))
                             for t in c) if f]
        if not feats:
            continue
        events.append({
            "t_start": round(c[0], 3), "t_end": round(c[-1], 3),
            "n_impacts": len(c), "impact_times": [round(t, 3) for t in c],
            "burst_duration_s": round(c[-1] - c[0], 3),
            "mean_centroid_hz": round(sum(f["centroid_hz"] for f in feats) / len(feats), 1),
            "max_peak_rms": round(max(f["peak_rms"] for f in feats), 5),
            "mean_decay_ratio": round(sum(f["decay_ratio"] for f in feats) / len(feats), 4),
            "impacts": feats})

    frames_per_s = sr / hop
    step = max(1, round(frames_per_s / float(params["envelope_hz"])))
    envelope = [round(float(max(env[i:i + step])), 4) for i in range(0, len(env), step)]
    # actual rate after integer-step pooling, so length/hz == duration downstream
    return {"envelope": envelope, "envelope_hz": round(frames_per_s / step, 4),
            "events": events}


def analyze_audio(audio_path: Path, params: dict,
                  duration_s: float | None = None) -> dict | None:
    """Decode + analyze; None on ANY failure (no librosa, bad file, bad params)."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import librosa
            y, sr = librosa.load(str(audio_path), sr=int(params["sr"]), mono=True,
                                 duration=duration_s)
            if y.size == 0:
                return None
            return analyze_samples(y, sr, params)
    except Exception:
        return None


def write_acoustics(sdir: Path, audio_path: Path | None, params: dict) -> dict | None:
    """Pipeline stage: acoustics.json sidecar, or None. Never raises."""
    if audio_path is None:
        return None
    try:
        result = analyze_audio(audio_path, params)
        if result is None:
            return None
        (sdir / "acoustics.json").write_text(json.dumps(result, indent=2))
        return result
    except Exception:
        return None
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_acoustics.py -v` — expect PASS (the synthetic-click
test exercises real HPSS; if `test_synthetic_clicks...` finds 1 or 3 events instead
of 2, adjust the click amplitudes/tone level in the TEST fixture, not the module —
the detector's thresholds are Task 5's business).
Then: `uv run pytest` — full suite green.

- [ ] **Step 5: Commit**

```bash
git add src/hoops/acoustics.py tests/test_acoustics.py
git commit -m "feat(acoustics): independent HPSS impact detection branch"
```

---

### Task 3: `src/hoops/fusion.py` — pairing + branch-independence test

**Files:**
- Create: `src/hoops/fusion.py`
- Test: `tests/test_fusion.py` (new)

**Interfaces:**
- Consumes: voice rows (schema in Global Constraints) + acoustic event dicts (Task 2 schema) + `Config.fusion` (`pair_min_s`, `pair_max_s`).
- Produces (Tasks 4–6 rely on these exact names):
  - `fuse(rows, events, *, pair_min_s: float, pair_max_s: float) -> dict`
  - `write_fusion(sdir: Path, rows, events, params: dict) -> dict | None` — never raises; `None` when `events is None`; writes `fusion.json` on success.
  - Return shape:
    ```python
    {"shots": [{"session_id", "shot_num", "result", "t_call_s", "isolation_s",
                "raw_token", "voided",
                "t_impact_s", "n_impacts", "burst_duration_s", "mean_centroid_hz",
                "max_peak_rms", "decay_ratio",
                "call_latency_s", "pairing_status", "gap_call_s", "gap_impact_s"}],
     "extra_events": [{"t_start", "t_end", "n_impacts", "pairing_status"}],
     "summary": {"n_calls", "n_paired", "pairing_rate", "n_impact_missing",
                 "n_ambiguous", "n_call_missing", "n_warmup",
                 "median_latency_s", "latencies_s"}}
    ```

**Pairing semantics (pin these — the tests encode them):**
- Only non-voided rows pair. Voided rows get status `voided`, all acoustic fields null, and never claim an event.
- Candidate events for a call at `t_call`: `pair_min_s <= t_call - t_start <= pair_max_s`. The chosen event is the **nearest preceding** candidate (largest `t_start`) — no fallback to earlier unclaimed candidates (that would invent crossed pairings).
- If the nearest preceding candidate is already claimed: this call is `ambiguous` (acoustic fields null) AND the claiming shot is demoted `paired` → `ambiguous` but **keeps** its acoustic fields ("flag both").
- Unclaimed events strictly before the first live call → `warmup`; all other unclaimed events → `call_missing`. No live calls at all → everything unclaimed is `call_missing`.
- `call_latency_s = round(t_call - t_impact_s, 3)`. `gap_call_s` = call-to-previous-live-call; `gap_impact_s` = impact-to-previous-known-impact (null when either side missing).
- `pairing_rate` counts status `paired` only (post-demotion), over live calls.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fusion.py
"""Fusion pairing — all five brief cases + voided, on hand-built data.
Also enforces the core rule: branch modules never import each other."""
import json
from pathlib import Path
import pytest
from hoops.fusion import fuse, write_fusion

SRC = Path(__file__).resolve().parents[1] / "src" / "hoops"
P = dict(pair_min_s=0.5, pair_max_s=4.0)

def row(n, t, result="make", voided=False):
    return {"session_id": "s1", "session_date_local": "2026-08-01", "shot_num": n,
            "result": result, "t_call_s": t, "gap_s": None, "streak_after": 0,
            "voided": voided, "isolation_s": 1.0, "confidence": 1.0,
            "raw_token": "swish"}

def ev(t0, t1=None, n=1):
    t1 = t0 + 0.2 if t1 is None else t1
    return {"t_start": t0, "t_end": t1, "n_impacts": n,
            "impact_times": [t0], "burst_duration_s": round(t1 - t0, 3),
            "mean_centroid_hz": 3000.0, "max_peak_rms": 0.5,
            "mean_decay_ratio": 0.3, "impacts": []}

@pytest.mark.unit
def test_paired_call_gets_features_and_latency():
    out = fuse([row(1, 10.0)], [ev(8.5)], **P)
    s = out["shots"][0]
    assert s["pairing_status"] == "paired"
    assert s["t_impact_s"] == 8.5 and s["call_latency_s"] == 1.5
    assert s["mean_centroid_hz"] == 3000.0 and s["decay_ratio"] == 0.3
    assert out["summary"]["pairing_rate"] == 1.0

@pytest.mark.unit
def test_nearest_preceding_wins():
    out = fuse([row(1, 10.0)], [ev(6.5), ev(8.8)], **P)
    assert out["shots"][0]["t_impact_s"] == 8.8

@pytest.mark.unit
def test_no_candidate_is_impact_missing_voice_kept():
    out = fuse([row(1, 20.0, result="miss")], [ev(10.0)], **P)
    s = out["shots"][0]
    assert s["pairing_status"] == "impact_missing"
    assert s["result"] == "miss" and s["t_impact_s"] is None
    assert out["summary"]["n_impact_missing"] == 1

@pytest.mark.unit
def test_event_closer_than_pair_min_does_not_pair():
    # guards against the caller's own voice onset being taken as the impact
    out = fuse([row(1, 10.0)], [ev(9.7)], **P)
    assert out["shots"][0]["pairing_status"] == "impact_missing"

@pytest.mark.unit
def test_two_calls_one_event_flags_both():
    out = fuse([row(1, 10.0), row(2, 11.0)], [ev(8.5)], **P)
    a, b = out["shots"]
    assert a["pairing_status"] == "ambiguous" and a["t_impact_s"] == 8.5  # keeps data
    assert b["pairing_status"] == "ambiguous" and b["t_impact_s"] is None
    assert out["summary"]["n_paired"] == 0 and out["summary"]["n_ambiguous"] == 2

@pytest.mark.unit
def test_warmup_and_call_missing_events_kept():
    out = fuse([row(1, 10.0)], [ev(2.0), ev(8.5), ev(30.0)], **P)
    assert out["shots"][0]["t_impact_s"] == 8.5
    statuses = {e["t_start"]: e["pairing_status"] for e in out["extra_events"]}
    assert statuses == {2.0: "warmup", 30.0: "call_missing"}
    assert out["summary"]["n_warmup"] == 1 and out["summary"]["n_call_missing"] == 1

@pytest.mark.unit
def test_voided_rows_never_pair_and_free_the_event():
    out = fuse([row(1, 10.0, voided=True), row(2, 11.5)], [ev(9.0)], **P)
    a, b = out["shots"]
    assert a["pairing_status"] == "voided" and a["t_impact_s"] is None
    assert b["pairing_status"] == "paired" and b["t_impact_s"] == 9.0
    assert out["summary"]["n_calls"] == 1        # live calls only

@pytest.mark.unit
def test_gap_call_and_gap_impact():
    out = fuse([row(1, 10.0), row(2, 20.0), row(3, 30.0)],
               [ev(8.5), ev(18.0)], **P)
    s1, s2, s3 = out["shots"]
    assert s1["gap_call_s"] is None and s2["gap_call_s"] == 10.0
    assert s2["gap_impact_s"] == 9.5             # 18.0 - 8.5
    assert s3["pairing_status"] == "impact_missing" and s3["gap_impact_s"] is None

@pytest.mark.unit
def test_summary_median_latency():
    out = fuse([row(1, 10.0), row(2, 20.0)], [ev(8.5), ev(18.9)], **P)
    assert out["summary"]["median_latency_s"] == pytest.approx(1.3)
    assert out["summary"]["latencies_s"] == [1.1, 1.5]

@pytest.mark.unit
def test_write_fusion_none_events_returns_none(tmp_path):
    assert write_fusion(tmp_path, [row(1, 10.0)], None, P) is None
    assert not (tmp_path / "fusion.json").exists()

@pytest.mark.unit
def test_write_fusion_writes_sidecar_and_never_raises(tmp_path):
    out = write_fusion(tmp_path, [row(1, 10.0)], [ev(8.5)], P)
    assert json.loads((tmp_path / "fusion.json").read_text()) == out
    assert write_fusion(tmp_path, [row(1, 10.0)], [ev(8.5)], {}) is None  # bad params

@pytest.mark.unit
def test_branch_modules_never_import_each_other():
    """The core architectural rule, enforced on source text."""
    banned = {
        "acoustics.py": ["parse", "transcribe", "fusion"],
        "fusion.py": ["acoustics", "parse", "transcribe"],
        "parse.py": ["acoustics", "fusion"],
        "transcribe.py": ["acoustics", "fusion"],
    }
    for fname, mods in banned.items():
        src = (SRC / fname).read_text()
        for m in mods:
            assert f"from .{m}" not in src, f"{fname} imports {m}"
            assert f"from hoops.{m}" not in src, f"{fname} imports {m}"
            assert f"import {m}\n" not in src, f"{fname} imports {m}"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_fusion.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hoops.fusion'`

- [ ] **Step 3: Implement `src/hoops/fusion.py`**

```python
"""Fusion — the ONLY place branch A (voice rows) meets branch B (acoustic events).

Pure stdlib over two plain lists; imports neither branch module (enforced by
test). Voice is authoritative for make/miss — acoustics records what it
independently observed and never overrides. Disagreement is data, not an error.

Pairing: each live call takes the nearest PRECEDING event whose latency
(t_call - t_start) lies in [pair_min_s, pair_max_s]. Preceding, never
nearest-absolute: shoot first, call second. Every unpaired thing is kept and
labelled — impact_missing (the 🤥 flag), call_missing (uncalled shots, F09),
ambiguous (two calls, one impact: both flagged), warmup (impacts before the
first call), voided (scratch-that rows never pair).
"""
import json
from pathlib import Path
from statistics import median

ACOUSTIC_NULLS = {"t_impact_s": None, "n_impacts": None, "burst_duration_s": None,
                  "mean_centroid_hz": None, "max_peak_rms": None, "decay_ratio": None}


def _identity(r: dict) -> dict:
    return {"session_id": r["session_id"], "shot_num": r["shot_num"],
            "result": r["result"], "t_call_s": r["t_call_s"],
            "isolation_s": r["isolation_s"], "raw_token": r["raw_token"],
            "voided": r["voided"]}


def _acoustic_fields(e: dict) -> dict:
    return {"t_impact_s": e["t_start"], "n_impacts": e["n_impacts"],
            "burst_duration_s": e["burst_duration_s"],
            "mean_centroid_hz": e["mean_centroid_hz"],
            "max_peak_rms": e["max_peak_rms"], "decay_ratio": e["mean_decay_ratio"]}


def fuse(rows: list[dict], events: list[dict], *,
         pair_min_s: float, pair_max_s: float) -> dict:
    events = sorted(events, key=lambda e: e["t_start"])
    claimed: dict[int, int] = {}          # event index -> claiming shot_num
    ambiguous: set[int] = set()           # shot_nums demoted paired -> ambiguous
    shots: list[dict] = []
    prev_call_t = prev_impact_t = None

    for r in rows:
        if r["voided"]:
            shots.append({**_identity(r), **ACOUSTIC_NULLS, "call_latency_s": None,
                          "pairing_status": "voided",
                          "gap_call_s": None, "gap_impact_s": None})
            continue
        t_call = r["t_call_s"]
        cands = [i for i, e in enumerate(events)
                 if pair_min_s <= t_call - e["t_start"] <= pair_max_s]
        if not cands:
            status, chosen = "impact_missing", None
        elif cands[-1] in claimed:        # nearest preceding already taken
            status, chosen = "ambiguous", None
            ambiguous.add(claimed[cands[-1]])
        else:
            status, chosen = "paired", cands[-1]
            claimed[chosen] = r["shot_num"]

        e = events[chosen] if chosen is not None else None
        t_impact = e["t_start"] if e else None
        shots.append({**_identity(r),
                      **(_acoustic_fields(e) if e else ACOUSTIC_NULLS),
                      "call_latency_s": round(t_call - t_impact, 3) if t_impact is not None else None,
                      "pairing_status": status,
                      "gap_call_s": round(t_call - prev_call_t, 3) if prev_call_t is not None else None,
                      "gap_impact_s": (round(t_impact - prev_impact_t, 3)
                                       if t_impact is not None and prev_impact_t is not None
                                       else None)})
        prev_call_t = t_call
        if t_impact is not None:
            prev_impact_t = t_impact

    for s in shots:                       # "flag both": demote, keep data
        if s["shot_num"] in ambiguous and s["pairing_status"] == "paired":
            s["pairing_status"] = "ambiguous"

    live = [r for r in rows if not r["voided"]]
    first_call_t = live[0]["t_call_s"] if live else None
    extra = []                            # claimed events are never re-listed here —
    for i, e in enumerate(events):        # an ambiguous pairing still existed
        if i in claimed:
            continue
        status = ("warmup" if first_call_t is not None and e["t_start"] < first_call_t
                  else "call_missing")
        extra.append({"t_start": e["t_start"], "t_end": e["t_end"],
                      "n_impacts": e["n_impacts"], "pairing_status": status})

    latencies = sorted(s["call_latency_s"] for s in shots
                       if s["pairing_status"] == "paired")
    n_live = len(live)
    summary = {"n_calls": n_live, "n_paired": len(latencies),
               "pairing_rate": round(len(latencies) / n_live, 3) if n_live else None,
               "n_impact_missing": sum(1 for s in shots if s["pairing_status"] == "impact_missing"),
               "n_ambiguous": sum(1 for s in shots if s["pairing_status"] == "ambiguous"),
               "n_call_missing": sum(1 for e in extra if e["pairing_status"] == "call_missing"),
               "n_warmup": sum(1 for e in extra if e["pairing_status"] == "warmup"),
               "median_latency_s": round(median(latencies), 3) if latencies else None,
               "latencies_s": latencies}
    return {"shots": shots, "extra_events": extra, "summary": summary}


def write_fusion(sdir: Path, rows: list[dict], events: list[dict] | None,
                 params: dict) -> dict | None:
    """Pipeline stage: fusion.json sidecar, or None. Never raises."""
    if events is None:
        return None
    try:
        fused = fuse(rows, events, pair_min_s=float(params["pair_min_s"]),
                     pair_max_s=float(params["pair_max_s"]))
        (sdir / "fusion.json").write_text(json.dumps(fused, indent=2))
        return fused
    except Exception:
        return None
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_fusion.py -v` — expect PASS. Then full `uv run pytest`.

- [ ] **Step 5: Commit**

```bash
git add src/hoops/fusion.py tests/test_fusion.py
git commit -m "feat(fusion): voice-acoustics pairing with explicit statuses"
```

---

### Task 4: The swap — pipeline + report re-wire, `impacts.py` retires

**Files:**
- Modify: `src/hoops/pipeline.py` (imports; both stage call sites; report calls; stale-sidecar cleanup)
- Modify: `src/hoops/report_html.py` (`_build_data` ~line 86; `render_interactive_report` ~line 514; waveform JS ~line 415)
- Delete: `src/hoops/impacts.py`, `tests/test_impacts.py`
- Modify: `tests/test_report_html.py` (replace the `IMPACTS` block, ~lines 219–260 + `test_choreography_markup_present`)
- Modify: `tests/test_pipeline.py` (rewrite the three impacts tests, ~lines 204–238)
- Modify: `CLAUDE.md` (status bullet describing the report/impacts stack)

**Interfaces:**
- Consumes: `write_acoustics(sdir, audio_path, params)` (Task 2), `write_fusion(sdir, rows, events, params)` (Task 3), `cfg.acoustics`/`cfg.fusion` (Task 1).
- Produces: `render_interactive_report(stats, rows, narrative, flags, words, audio_path, acoustics=None, fusion=None)` — the `impacts=` parameter is GONE. `stats["uncorroborated_calls"]` sourced from `fused["summary"]["n_impact_missing"]`.

- [ ] **Step 1: Re-wire `report_html.py`**

`_build_data` (currently takes `impacts=None`) becomes:

```python
def _build_data(stats, rows, narrative, flags, words, has_audio: bool,
                acoustics=None, fusion=None) -> dict:
    by_shot = {s["shot_num"]: s for s in (fusion or {}).get("shots", [])}
    shots = []
    for r in rows:
        f = by_shot.get(r["shot_num"]) or {}
        shots.append({"n": r["shot_num"], "result": r["result"], "t": r["t_call_s"],
                      "gap": r["gap_s"], "streak": r["streak_after"],
                      "voided": r["voided"], "raw": r["raw_token"],
                      "impact": f.get("t_impact_s"),
                      "lie": f.get("pairing_status") == "impact_missing"})
    def call_num(w):
        r = _call_row_for(w, rows)
        return r["shot_num"] if r else 0
    return {"stats": stats, "shots": shots, "flags": flags,
            "words": [{"t": w.start, "text": w.text, "call": call_num(w)} for w in words],
            "narrative": ({"headline": narrative.headline, "recap": narrative.recap,
                           "quote": narrative.quote, "quote_t_s": narrative.quote_t_s}
                          if narrative else None),
            "has_audio": has_audio,
            "wave": ({"env": acoustics["envelope"], "hz": acoustics["envelope_hz"]}
                     if acoustics else None),
            "extra": [{"t": e["t_start"], "status": e["pairing_status"]}
                      for e in (fusion or {}).get("extra_events", [])]}
```

`render_interactive_report` signature + body:

```python
def render_interactive_report(stats: dict, rows: list[dict], narrative,
                              flags: list[str], words,
                              audio_path: Path | None,
                              acoustics=None, fusion=None) -> str:
    audio_html, has_audio = _audio_tag(audio_path)
    data = json.dumps(_build_data(stats, rows, narrative, flags, words, has_audio,
                                  acoustics, fusion)
                      ).replace("<", "\\u003c")
```

and in the section list: `_movie_section(has_audio, bool(acoustics))`.

In the JS waveform block, directly after the existing paired-marker loop
(`live.filter(s => s.impact != null).forEach(...)`), add ghost markers for
unclaimed clusters (gray, with a native tooltip via `<title>` — no new JS):

```js
  (DATA.extra || []).forEach(e => {
    const x = (e.t / waveDur * W).toFixed(1);
    frag.push(`<polygon points="${x},8 ${Number(x) - 4},0 ${Number(x) + 4},0" ` +
              `fill="#999" opacity="0.7"><title>${e.status} impact @ ${e.t.toFixed(1)}s</title></polygon>`);
  });
```

The rest of the JS (physics `s.land = s.impact ?? t - FALLBACK_LEAD_S`, 🤥 in
tooltip/flash, scoreboard) already keys off `s.impact`/`s.lie` and needs no change.

- [ ] **Step 2: Re-wire `pipeline.py`**

Replace `from .impacts import write_impacts` with:

```python
from .acoustics import write_acoustics
from .fusion import write_fusion
```

In `process_file`, replace the `impacts = write_impacts(...)` block (currently
after the vocab stats lines, before `write_shots_csv`) with:

```python
    acoustics = write_acoustics(sdir, path if path.exists() else None, cfg.acoustics)
    fused = write_fusion(sdir, rows, acoustics["events"] if acoustics else None,
                         cfg.fusion)
    if fused is not None:
        stats["uncorroborated_calls"] = fused["summary"]["n_impact_missing"]
```

and the report call becomes:

```python
    (sdir / "report.html").write_text(render_interactive_report(
        stats, rows, narrative, flags, words, audio_path,
        acoustics=acoustics, fusion=fused))
```

In `replay_session`, replace the `impacts = write_impacts(...)` block with:

```python
    (sdir / "impacts.json").unlink(missing_ok=True)      # retired sidecar
    acoustics = write_acoustics(sdir, audio_path if audio_path.exists() else None,
                                cfg.acoustics)
    fused = write_fusion(sdir, rows, acoustics["events"] if acoustics else None,
                         cfg.fusion)
    if fused is not None:
        stats["uncorroborated_calls"] = fused["summary"]["n_impact_missing"]
    if acoustics is None:
        (sdir / "acoustics.json").unlink(missing_ok=True)  # stale from a prior run
    if fused is None:
        (sdir / "fusion.json").unlink(missing_ok=True)
```

and its report call likewise passes `acoustics=acoustics, fusion=fused`.

- [ ] **Step 3: Delete the retired module and update tests**

```bash
git rm src/hoops/impacts.py tests/test_impacts.py
```

In `tests/test_report_html.py`, replace the `IMPACTS = {...}` constant and the six
tests that use `render(impacts=...)` with sidecar-shaped fixtures and equivalents
(keep the file's existing `render()` / `data_blob()` helpers and its `ROWS` —
match `shot_num` values to that fixture):

```python
ACOUSTICS = {"envelope": [0.02] * 500 + [0.9] + [0.02] * 30, "envelope_hz": 14.35,
             "events": [{"t_start": 33.0, "t_end": 33.4, "n_impacts": 2,
                         "impact_times": [33.0, 33.4], "burst_duration_s": 0.4,
                         "mean_centroid_hz": 3100.0, "max_peak_rms": 0.6,
                         "mean_decay_ratio": 0.3, "impacts": []}]}
def _fshot(n, status, t_impact):
    return {"session_id": "s", "shot_num": n, "result": "make", "t_call_s": 0.0,
            "isolation_s": 1.0, "raw_token": "swish", "voided": False,
            "t_impact_s": t_impact, "n_impacts": 2, "burst_duration_s": 0.4,
            "mean_centroid_hz": 3100.0, "max_peak_rms": 0.6, "decay_ratio": 0.3,
            "call_latency_s": None, "pairing_status": status,
            "gap_call_s": None, "gap_impact_s": None}
FUSION = {"shots": [_fshot(<first ROWS shot_num>, "paired", 33.0),
                    _fshot(<second ROWS shot_num>, "impact_missing", None)],
          "extra_events": [{"t_start": 5.0, "t_end": 5.2, "n_impacts": 1,
                            "pairing_status": "call_missing"}],
          "summary": {"n_calls": 2, "n_paired": 1, "pairing_rate": 0.5,
                      "n_impact_missing": 1, "n_ambiguous": 0, "n_call_missing": 1,
                      "n_warmup": 0, "median_latency_s": 1.2, "latencies_s": [1.2]}}
```

Test replacements (same coverage as before, plus ghost markers):

```python
def test_data_carries_impacts():
    d = data_blob(render(acoustics=ACOUSTICS, fusion=FUSION))
    paired = [s for s in d["shots"] if s["impact"] is not None]
    assert paired and paired[0]["impact"] == 33.0
    assert any(s["lie"] for s in d["shots"])
    assert d["wave"]["hz"] == 14.35

def test_data_without_sidecars_degrades():
    d = data_blob(render())
    assert all(s["impact"] is None and s["lie"] is False for s in d["shots"])
    assert d["wave"] is None and d["extra"] == []

def test_waveform_svg_present():
    assert "id='waveform'" in render(acoustics=ACOUSTICS, fusion=FUSION)

def test_ghost_markers_for_unclaimed_events():
    d = data_blob(render(acoustics=ACOUSTICS, fusion=FUSION))
    assert d["extra"] == [{"t": 5.0, "status": "call_missing"}]
    assert "DATA.extra" in render(acoustics=ACOUSTICS, fusion=FUSION)

def test_uncorroborated_stat_shown():        # keep the existing body — it reads
    ...                                       # stats["uncorroborated_calls"], unchanged

def test_replay_physics_constants_in_js():
    html = render(acoustics=ACOUSTICS, fusion=FUSION)
    assert "FLIGHT_S = 0.6" in html and "FALLBACK_LEAD_S = 0.5" in html

def test_self_contained_with_sidecars():
    html = render(acoustics=ACOUSTICS, fusion=FUSION)
    # reuse the file's existing self-containment assertions on this html
```

`test_choreography_markup_present` just swaps `render(impacts=IMPACTS)` for
`render(acoustics=ACOUSTICS, fusion=FUSION)`.

In `tests/test_pipeline.py`, rewrite the three impacts tests:

```python
def test_pipeline_writes_sidecars_and_uncorroborated(tmp_path, cfg, monkeypatch):
    canned_ac = {"envelope": [0.1], "envelope_hz": 14.35, "events": []}
    def fake_ac(sdir, audio, params):
        (sdir / "acoustics.json").write_text(json.dumps(canned_ac)); return canned_ac
    canned_fu = {"shots": [], "extra_events": [],
                 "summary": {"n_calls": 2, "n_paired": 1, "pairing_rate": 0.5,
                             "n_impact_missing": 1, "n_ambiguous": 0,
                             "n_call_missing": 0, "n_warmup": 0,
                             "median_latency_s": 1.2, "latencies_s": [1.2]}}
    def fake_fu(sdir, rows, events, params):
        (sdir / "fusion.json").write_text(json.dumps(canned_fu)); return canned_fu
    monkeypatch.setattr("hoops.pipeline.write_acoustics", fake_ac)
    monkeypatch.setattr("hoops.pipeline.write_fusion", fake_fu)
    out = process_file(...)                    # same invocation the old test used
    assert (out.session_dir / "acoustics.json").exists()
    assert (out.session_dir / "fusion.json").exists()
    assert out.stats["uncorroborated_calls"] == 1

def test_pipeline_survives_acoustics_failure(tmp_path, cfg, monkeypatch):
    monkeypatch.setattr("hoops.pipeline.write_acoustics", lambda *a: None)
    out = process_file(...)                    # same invocation the old test used
    assert out.status == "ok"
    assert "uncorroborated_calls" not in out.stats
    assert not (out.session_dir / "fusion.json").exists()   # fusion got events=None

def test_replay_removes_stale_sidecars_when_stages_yield_none(tmp_path, cfg, monkeypatch):
    out = process_file(...)                    # produce a session as the old test did
    for name in ("impacts.json", "acoustics.json", "fusion.json"):
        (out.session_dir / name).write_text("{}")            # plant stale sidecars
    monkeypatch.setattr("hoops.pipeline.write_acoustics", lambda *a: None)
    replay_session(out.session_dir, cfg)
    for name in ("impacts.json", "acoustics.json", "fusion.json"):
        assert not (out.session_dir / name).exists()
```

(Keep each test's existing `process_file(...)` invocation style from the file —
only the monkeypatch targets and assertions change.)

- [ ] **Step 4: Update `CLAUDE.md`**

In the status bullet describing the report (the one mentioning `impacts.json` /
`src/hoops/impacts.py`), replace the impacts-sidecar description with:

> impact-aligned replay with 🤥 flags now sourced from the independent dual-capture
> branch (`src/hoops/acoustics.py` HPSS detection → `acoustics.json`,
> `src/hoops/fusion.py` pairing → `fusion.json`; voice branch untouched and
> authoritative — see `docs/superpowers/specs/2026-08-01-dual-capture-acoustics-design.md`)

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest` — everything green, including `test_self_contained`.
Also grep for leftovers: `grep -rn "write_impacts\|impacts.json\|impacts=" src/ tests/ cloud/` —
only `pipeline.py`'s stale-cleanup `impacts.json` line and historical docs may remain.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: swap voice-seeded impacts for independent acoustics+fusion sidecars"
```

---

### Task 5: `scripts/sweep_thresholds.py` + parameter decision

**Files:**
- Create: `scripts/sweep_thresholds.py`
- Create: `docs/decisions/002-impact-detection-params.md` (written from the sweep's output)
- Modify: `config.yaml` + `cloud/config.cloud.yaml` (only if the sweep picks values ≠ current)

**Interfaces:**
- Consumes: `analyze_audio` (Task 2), `fuse` (Task 3), `load_config`, `transcript_cache_path` (`hoops.fixtures`), `words_from_envelope` (`hoops.transcribe`), `parse_words`, `build_shot_rows`.
- Produces: `out/sweep/results.json`, `out/sweep/debug_<stem>.html` (out/ is gitignored), and the committed decision doc.

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Sweep acoustics thresholds against recorded fixtures; render debug HTML.

For every (onset_delta, min_spacing_frames, cluster_gap_s) combo × fixture:
event count + median inter-event gap, compared against the brief's empirical
baseline. For the current config values it also computes the pairing rate
against the cached voice transcript and renders a per-fixture debug page:
percussive envelope, detected clusters, voice-call markers, pairing lines.

F05 (music) is EXCLUDED from tuning and reported separately — impact detection
failing under music is a finding to document, not a bug to tune around.

Usage:  uv run python scripts/sweep_thresholds.py [--full-grid]
"""
import argparse, itertools, json
from pathlib import Path
from statistics import median

from hoops.acoustics import analyze_audio
from hoops.config import load_config
from hoops.fixtures import transcript_cache_path
from hoops.fusion import fuse
from hoops.parse import parse_words
from hoops.stats import build_shot_rows
from hoops.transcribe import words_from_envelope

ROOT = Path(__file__).resolve().parents[1]
BASELINE = {  # from the brief's prototype run — large deviation = broken port
    "F01_NormalSwishBrick.m4a": 17, "F04_SwishBrickQuiet.m4a": 14,
    "F06_SwishBrick10secBeep.m4a": 16, "F02_SwishBrickChatty.m4a": 8}
MUSIC = "F05_SwishBrickMusic.m4a"
GRID = {"onset_delta": [0.2, 0.3, 0.4, 0.5],
        "min_spacing_frames": [10, 15, 20],
        "cluster_gap_s": [1.5, 2.0, 2.5]}


def voice_rows(cfg, fname):
    cache = transcript_cache_path(ROOT, fname)
    if not cache.exists():
        return None
    env = json.loads(cache.read_text())
    parsed = parse_words(words_from_envelope(env), cfg.vocab(None),
                         cfg.isolation_low, cfg.isolation_high)
    return build_shot_rows(parsed.calls, fname, "")


def summarize(res):
    starts = [e["t_start"] for e in res["events"]]
    gaps = [round(b - a, 1) for a, b in zip(starts, starts[1:])]
    return {"n_events": len(res["events"]),
            "median_gap_s": round(median(gaps), 1) if gaps else None,
            "impacts_per_event": [e["n_impacts"] for e in res["events"]]}


def debug_html(stem, res, rows, fused):
    W, H, PLOT = 1000, 260, 170
    env, hz = res["envelope"], res["envelope_hz"]
    dur = len(env) / hz
    X = lambda t: t / dur * W
    parts = [f"<rect x='{i/len(env)*W:.1f}' y='{H-40-v*PLOT:.1f}' "
             f"width='{W/len(env):.2f}' height='{v*PLOT:.1f}' fill='#ccc'/>"
             for i, v in enumerate(env)]
    for e in res["events"]:
        parts.append(f"<rect x='{X(e['t_start']):.1f}' y='20' "
                     f"width='{max(2, X(e['t_end']) - X(e['t_start'])):.1f}' "
                     f"height='{H-60}' fill='#e2711d' opacity='0.25'>"
                     f"<title>{e['n_impacts']} impacts, {e['mean_centroid_hz']:.0f} Hz</title></rect>")
    for r in (rows or []):
        col = "#1a7f37" if r["result"] == "make" else "#c0392b"
        parts.append(f"<circle cx='{X(r['t_call_s']):.1f}' cy='12' r='5' fill='{col}'>"
                     f"<title>#{r['shot_num']} {r['result']} @ {r['t_call_s']:.1f}s</title></circle>")
    for s in (fused or {}).get("shots", []):
        if s["t_impact_s"] is not None:
            parts.append(f"<line x1='{X(s['t_impact_s']):.1f}' y1='30' "
                         f"x2='{X(s['t_call_s']):.1f}' y2='14' stroke='#555' stroke-dasharray='3'/>")
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{stem}</title></head>"
            f"<body style='font-family:sans-serif'><h2>{stem}</h2>"
            f"<svg viewBox='0 0 {W} {H}' style='width:100%;border:1px solid #ddd'>"
            + "".join(parts) + "</svg>"
            "<p>gray = percussive envelope · orange = clusters · dots = calls · dashes = pairings</p>"
            "</body></html>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full-grid", action="store_true",
                    help="sweep the whole grid (default: current config only)")
    args = ap.parse_args()
    cfg = load_config(ROOT / "config.yaml")
    outdir = ROOT / "out" / "sweep"
    outdir.mkdir(parents=True, exist_ok=True)
    results = []

    combos = ([dict(zip(GRID, vs)) for vs in itertools.product(*GRID.values())]
              if args.full_grid else [{}])
    for fname in [*BASELINE, MUSIC]:
        path = ROOT / "fixtures" / fname
        if not path.exists():
            print(f"skip {fname} (not recorded)"); continue
        rows = voice_rows(cfg, fname)
        for combo in combos:
            params = {**cfg.acoustics, **combo}
            res = analyze_audio(path, params)
            if res is None:
                print(f"{fname} {combo}: FAILED"); continue
            s = summarize(res)
            fused = (fuse(rows, res["events"], pair_min_s=cfg.fusion["pair_min_s"],
                          pair_max_s=cfg.fusion["pair_max_s"]) if rows else None)
            rec = {"fixture": fname, **combo, **s,
                   "baseline_n": BASELINE.get(fname),
                   "pairing_rate": fused["summary"]["pairing_rate"] if fused else None,
                   "median_latency_s": fused["summary"]["median_latency_s"] if fused else None,
                   "is_music": fname == MUSIC}
            results.append(rec)
            print(f"{fname:38s} {combo or 'config'} -> {s['n_events']:3d} events "
                  f"(baseline {rec['baseline_n']}), gap {s['median_gap_s']}, "
                  f"pair {rec['pairing_rate']}")
            if not combo:  # debug page at current config values
                (outdir / f"debug_{path.stem}.html").write_text(
                    debug_html(path.stem, res, rows, fused))
    (outdir / "results.json").write_text(json.dumps(results, indent=2))
    print(f"\nwrote {outdir}/results.json and debug_*.html")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run at current config values**

Run: `uv run python scripts/sweep_thresholds.py`
Expected: per-fixture lines; F01/F02/F04/F06 event counts in the neighborhood of
the baseline (17/8/14/16 — within ±3 counts as "neighborhood"). If wildly off,
the port is broken — debug before proceeding (compare against
`from_claude/impact_detect.py` step by step).

- [ ] **Step 3: Run the full grid and pick values**

Run: `uv run python scripts/sweep_thresholds.py --full-grid`
Pick the combo that (1) lands nearest the baseline counts on the four tuning
fixtures and (2) maximizes pairing rate — tie-break toward the middle of the
grid. If the winner differs from the current `config.yaml` values, update the
`acoustics:` block in BOTH `config.yaml` and `cloud/config.cloud.yaml`.

- [ ] **Step 4: Write the decision doc**

Create `docs/decisions/002-impact-detection-params.md` recording: the chosen
values, the sweep table for the four tuning fixtures (n_events vs baseline,
median gap, pairing rate), the runner-up combos, and the F05 music findings
(what the detector did under music — event count, pairing rate — as a finding,
explicitly NOT tuned for). Open the debug HTMLs and note anything visually
wrong (missed clusters, voice leakage) in the doc.

- [ ] **Step 5: Verify suite still green, commit**

```bash
uv run pytest
git add scripts/sweep_thresholds.py docs/decisions/002-impact-detection-params.md config.yaml cloud/config.cloud.yaml
git commit -m "feat(scripts): threshold sweep + debug views; record chosen params"
```

---

### Task 6: `scripts/analyze_separability.py` + the honest answer

**Files:**
- Create: `scripts/analyze_separability.py`
- Create: `docs/decisions/003-acoustic-separability.md`

**Interfaces:**
- Consumes: same helpers as Task 5 (`analyze_audio`, `fuse`, `voice_rows` pattern, `load_config`).
- Produces: `out/separability.html`, printed stats table, committed decision doc.

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Do the acoustic features separate makes from misses AT ALL?

Pools paired (voice-labelled) shot events across recorded fixtures — the
supervised dataset that exists TODAY — and for each feature computes AUC
(rank-based, P(make > miss)) and Cohen's d, ranked by |AUC - 0.5|.
A null result is a valuable finding: it kills the classifier idea cheaply.
F05 (music) is excluded — its detection findings live in decision doc 002.

Usage:  uv run python scripts/analyze_separability.py
"""
import json
from pathlib import Path
from statistics import mean, stdev

from hoops.acoustics import analyze_audio
from hoops.config import load_config
from hoops.fixtures import transcript_cache_path
from hoops.fusion import fuse
from hoops.parse import parse_words
from hoops.stats import build_shot_rows
from hoops.transcribe import words_from_envelope

ROOT = Path(__file__).resolve().parents[1]
EXCLUDE = {"F05_SwishBrickMusic.m4a"}
FEATURES = ["n_impacts", "mean_centroid_hz", "max_peak_rms", "decay_ratio",
            "burst_duration_s"]


def auc(makes, misses):
    """Rank-based AUC: P(feature(make) > feature(miss)); ties count half."""
    pairs = wins = 0
    for x in makes:
        for y in misses:
            wins += 1 if x > y else 0.5 if x == y else 0
            pairs += 1
    return round(wins / pairs, 3) if pairs else None


def cohens_d(makes, misses):
    if len(makes) < 2 or len(misses) < 2:
        return None
    n1, n2 = len(makes), len(misses)
    s = (((n1 - 1) * stdev(makes) ** 2 + (n2 - 1) * stdev(misses) ** 2)
         / (n1 + n2 - 2)) ** 0.5
    return round((mean(makes) - mean(misses)) / s, 3) if s else None


def hist_svg(makes, misses, title, W=420, H=140, bins=12):
    lo = min(makes + misses); hi = max(makes + misses) or 1
    span = (hi - lo) or 1
    def counts(xs):
        c = [0] * bins
        for x in xs:
            c[min(bins - 1, int((x - lo) / span * bins))] += 1
        return c
    cm, cx = counts(makes), counts(misses)
    peak = max(*cm, *cx, 1)
    bars = []
    for i in range(bins):
        x = i / bins * W; bw = W / bins - 2
        for c, col in ((cm[i], "#1a7f37"), (cx[i], "#c0392b")):
            h = c / peak * (H - 30)
            bars.append(f"<rect x='{x:.0f}' y='{H-20-h:.0f}' width='{bw:.0f}' "
                        f"height='{h:.0f}' fill='{col}' opacity='0.55'/>")
    return (f"<div><h3>{title}</h3><svg viewBox='0 0 {W} {H}' "
            f"style='width:{W}px'>{''.join(bars)}"
            f"<text x='2' y='{H-4}' font-size='10'>{lo:.2f}</text>"
            f"<text x='{W-60}' y='{H-4}' font-size='10'>{hi:.2f}</text></svg></div>")


def main():
    cfg = load_config(ROOT / "config.yaml")
    by_label = {"make": [], "miss": []}
    for path in sorted((ROOT / "fixtures").glob("*.m4a")):
        if path.name in EXCLUDE:
            continue
        cache = transcript_cache_path(ROOT, path.name)
        if not cache.exists():
            print(f"skip {path.name} (no cached transcript)"); continue
        env = json.loads(cache.read_text())
        parsed = parse_words(words_from_envelope(env), cfg.vocab(None),
                             cfg.isolation_low, cfg.isolation_high)
        rows = build_shot_rows(parsed.calls, path.name, "")
        res = analyze_audio(path, cfg.acoustics)
        if res is None:
            print(f"skip {path.name} (acoustics failed)"); continue
        fused = fuse(rows, res["events"], pair_min_s=cfg.fusion["pair_min_s"],
                     pair_max_s=cfg.fusion["pair_max_s"])
        for s in fused["shots"]:
            if s["pairing_status"] == "paired":
                by_label[s["result"]].append(s)
        print(f"{path.name}: pairing_rate {fused['summary']['pairing_rate']}, "
              f"median latency {fused['summary']['median_latency_s']}s")

    makes, misses = by_label["make"], by_label["miss"]
    print(f"\n{len(makes)} labelled makes, {len(misses)} labelled misses\n")
    print(f"{'feature':20s} {'AUC':>6s} {'|AUC-.5|':>8s} {'Cohen d':>8s}")
    rows_out, sections = [], []
    for f in FEATURES:
        mk = [s[f] for s in makes if s[f] is not None]
        ms = [s[f] for s in misses if s[f] is not None]
        a, d = auc(mk, ms), cohens_d(mk, ms)
        rows_out.append({"feature": f, "auc": a, "cohens_d": d,
                         "n_make": len(mk), "n_miss": len(ms)})
        if mk and ms:
            sections.append(hist_svg(mk, ms, f"{f} — AUC {a}, d {d}"))
        print(f"{f:20s} {a!s:>6s} {abs((a or .5)-.5):8.3f} {d!s:>8s}")
    rows_out.sort(key=lambda r: abs((r["auc"] or 0.5) - 0.5), reverse=True)

    out = ROOT / "out"; out.mkdir(exist_ok=True)
    (out / "separability.html").write_text(
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>make/miss separability</title></head><body style='font-family:sans-serif'>"
        "<h1>Acoustic make/miss separability</h1>"
        "<p><span style='color:#1a7f37'>■</span> make · "
        "<span style='color:#c0392b'>■</span> miss</p>"
        + "".join(sections) + "</body></html>")
    (out / "separability.json").write_text(json.dumps(rows_out, indent=2))
    print(f"\nwrote {out}/separability.html and separability.json")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it**

Run: `uv run python scripts/analyze_separability.py`
Expected: per-fixture pairing rates, then the ranked feature table. Sanity: total
labelled examples should be substantial (the brief estimates ~100+ across the
recorded fixtures); if it's tiny, check pairing rates first — a low pairing rate
is a Task 5 problem, not a separability finding.

- [ ] **Step 3: Write the honest decision doc**

Create `docs/decisions/003-acoustic-separability.md`: dataset size (n makes / n
misses, which fixtures), the ranked AUC/Cohen's d table, per-fixture pairing
rates + median latencies, and the verdict — one of:
- "Features X, Y separate (AUC ≥ ~0.7): classifier work is justified, start with X."
- "Nothing separates (all AUC ≈ 0.5): the audio-only classifier idea is dead in
  this setup. Recorded honestly; do not build the classifier."
- Something in between, stated plainly with which features carry weak signal.

Include the caveat that a swish may produce NO detectable transient — absence as
signal — so `impact_missing` counts by label are worth reporting too (add them
to the doc from the fusion summaries).

- [ ] **Step 4: Commit**

```bash
uv run pytest
git add scripts/analyze_separability.py docs/decisions/003-acoustic-separability.md
git commit -m "feat(scripts): make/miss separability analysis + honest verdict"
```

---

### Task 7: Gates, deploy, docs

**Files:**
- Modify: `CLAUDE.md` (status + pending work)
- No code changes expected — this task is verification + deploy.

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Parse-artifact byte-identity gate**

```bash
SNAP=$(mktemp -d)
cp -r sessions "$SNAP/sessions"
uv run hoops replay --all
for f in transcript.json transcript.txt shots.csv; do
  find sessions -name "$f" | while read p; do
    diff -q "$SNAP/$p" "$p" >/dev/null || echo "DIFF: $p"
  done
done
```

Expected: zero `DIFF:` lines for the three parse artifacts. (`session.json`,
`report.html`, `fusion.json`, `acoustics.json` differ by design; `impacts.json`
disappears — also by design.) If `sessions/` is empty locally, pull first:
`set -a; source .env; set +a; uv run modal run cloud/modal_app.py::pull_sessions`.

- [ ] **Step 2: Score gate + full suite**

```bash
uv run hoops score        # must pass — phantom shots on trap fixtures = hard failure
uv run pytest             # green
```

- [ ] **Step 3: Deploy + smoke**

```bash
set -a; source .env; set +a
uv run modal deploy cloud/modal_app.py
```

Expected: deploy succeeds (image rebuild will be slow — librosa/numpy install).
Then re-run one pulled real session locally as the end-to-end check:
`uv run hoops replay <one real session dir>` and confirm `acoustics.json` +
`fusion.json` exist, `report.html` shows the percussive waveform with orange
paired markers, and `session.json` carries `uncorroborated_calls`.

- [ ] **Step 4: Update `CLAUDE.md`**

- Status section: note the dual-capture branch is live (acoustics + fusion
  sidecars cloud-side, thresholds per decision doc 002, separability verdict in
  doc 003).
- Pending work: add "shadow-period eyeball: percussive-waveform impact markers
  + pairing rate per emailed session; classifier build gated on
  docs/decisions/003 verdict".

- [ ] **Step 5: Final commit**

```bash
git add CLAUDE.md
git commit -m "docs: dual-capture live — status, shadow-watch items"
```

---

## Self-review notes (already applied)

- Spec coverage: §branch B → Task 2; §fusion → Task 3; §artifacts/pipeline/report/retirement → Task 4; §config/cloud/deps → Task 1; §sweep + decision 002 → Task 5; §separability + decision 003 → Task 6; §verification/deploy → Task 7. F05 handling in Tasks 5–6. Import-independence test in Task 3.
- Type consistency: event fields named identically in Task 2 output, Task 3 `_acoustic_fields`, Task 4 report fixtures, Tasks 5–6 scripts (`mean_decay_ratio` on events maps to `decay_ratio` on fusion shots — that rename happens exactly once, inside `_acoustic_fields`).
