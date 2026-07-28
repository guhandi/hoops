def make_env(words: list[tuple[str, float, float]], duration: float | None = None) -> dict:
    resp = {
        "text": " ".join(w for w, _, _ in words),
        "duration": duration if duration is not None else (words[-1][2] if words else 0.0),
        "words": [{"word": w, "start": s, "end": e} for w, s, e in words],
        "segments": [],
    }
    return {"model": "whisper-1", "response": resp}
