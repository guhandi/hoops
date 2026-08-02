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
    status_counts = {"make": {"paired": 0, "impact_missing": 0},
                     "miss": {"paired": 0, "impact_missing": 0}}
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
            if s["pairing_status"] in ("paired", "impact_missing"):
                status_counts[s["result"]][s["pairing_status"]] += 1
        print(f"{path.name}: pairing_rate {fused['summary']['pairing_rate']}, "
              f"median latency {fused['summary']['median_latency_s']}s")

    make_paired, make_missing = status_counts["make"]["paired"], status_counts["make"]["impact_missing"]
    miss_paired, miss_missing = status_counts["miss"]["paired"], status_counts["miss"]["impact_missing"]
    print(f"\nimpact_missing: {make_missing} make / {miss_missing} miss "
          f"(paired: {make_paired} make / {miss_paired} miss)")

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
