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
    hi = max(0, int((t_word - GUARD_BEFORE_S) * hz))
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
