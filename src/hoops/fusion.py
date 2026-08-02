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
