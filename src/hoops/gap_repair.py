"""Transcript gap repair — recover call words whisper-1 silently drops.

Whisper decodes ~30s windows; sparse, mostly-silent stretches lose isolated
call words (see docs/superpowers/specs/2026-08-19-transcript-gap-repair-design.md).
Pure span math lives here alongside the clip/merge orchestration; the raw
API response in the envelope is never mutated — recovered words ride a
sibling "gap_repair" key.
"""
import tempfile
from pathlib import Path

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
