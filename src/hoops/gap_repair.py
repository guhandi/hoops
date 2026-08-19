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
