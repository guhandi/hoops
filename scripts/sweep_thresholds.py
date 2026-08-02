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
