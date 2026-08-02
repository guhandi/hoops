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
import sys
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
    rms = librosa.feature.rms(S=S, frame_length=512, hop_length=128)[0]
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
    except Exception as e:
        print(f"acoustics: stage skipped ({e!r})", file=sys.stderr)
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
    except Exception as e:
        print(f"acoustics: stage skipped ({e!r})", file=sys.stderr)
        return None
