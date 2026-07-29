"""Metrics over cached TranscriptResults. All metric functions are pure."""
from __future__ import annotations
import csv, json, statistics
from pathlib import Path
from benchmarks.transcribers.base import BWord, TranscriptResult, normalize_token

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "benchmarks" / "out"

def detect(words, surface_to_canonical):
    out = []
    for i, w in enumerate(words):
        canon = surface_to_canonical.get(normalize_token(w.word))
        if canon is None:
            continue
        gap_b = w.start - words[i - 1].end if i > 0 else float("inf")
        gap_a = words[i + 1].start - w.end if i < len(words) - 1 else float("inf")
        out.append({"canonical": canon, "raw": w.word, "start": w.start, "end": w.end,
                    "mid": (w.start + w.end) / 2, "isolation": min(gap_b, gap_a)})
    return out

def gap_stats(mids, interval):
    if len(mids) < 2:
        return {}
    errs = [abs((b - a) - interval) for a, b in zip(mids, mids[1:])]
    errs_sorted = sorted(errs)
    p95_idx = min(len(errs_sorted) - 1, int(round(0.95 * (len(errs_sorted) - 1))))
    return {"mean": statistics.mean(errs), "median": statistics.median(errs),
            "p95": errs_sorted[p95_idx], "max": max(errs), "n_gaps": len(errs)}

def cluster(dets_by_model, window=0.75):
    flat = sorted(((m, d) for m, ds in dets_by_model.items() for d in ds),
                  key=lambda x: x[1]["mid"])
    clusters = []
    for m, d in flat:
        home = None
        for c in reversed(clusters):
            if c["canonical"] == d["canonical"] and m not in c["models"] \
                    and abs(d["mid"] - c["mid"]) <= window:
                home = c
                break
            if d["mid"] - c["mid"] > window:
                break
        if home is None:
            clusters.append({"canonical": d["canonical"], "mid": d["mid"],
                             "models": {m: d}, "consensus": False})
        else:
            home["models"][m] = d
            home["mid"] = statistics.median(x["mid"] for x in home["models"].values())
    majority = len(dets_by_model) // 2 + 1
    for c in clusters:
        c["consensus"] = len(c["models"]) >= majority
    return sorted(clusters, key=lambda c: c["mid"])

def recommend_threshold(real, bait):
    if not real or not bait:
        return {}
    candidates = sorted(set(real + bait))
    best = None
    for lo, hi in zip(candidates, candidates[1:]):
        t = (lo + hi) / 2
        score = sum(1 for r in real if r >= t) + sum(1 for b in bait if b < t)
        if best is None or score > best[0] or (score == best[0] and (hi - lo) > best[1]):
            best = (score, hi - lo, t)
    return {"threshold": round(best[2], 3), "margin": round(min(real) - max(bait), 3),
            "real_below": sum(1 for r in real if r < best[2]),
            "bait_above": sum(1 for b in bait if b >= best[2])}

def pairwise_agreement(clusters, models):
    out = {}
    for i, a in enumerate(models):
        for b in models[i + 1:]:
            deltas = [abs(c["models"][a]["mid"] - c["models"][b]["mid"])
                      for c in clusters if a in c["models"] and b in c["models"]]
            if deltas:
                out[f"{a}|{b}"] = round(statistics.median(deltas), 3)
    return out

def silence_words(words, silence_start):
    return sum(1 for w in words if w.start >= silence_start)


def assemble_metrics(out_root: Path, manifest_rows: list[dict], vocabs: dict[str, dict]) -> None:
    """Load all cached transcripts and manifest, compute metrics, write JSON + CSV.

    Args:
        out_root: Root path for benchmarks output (contains transcripts/ and skips.json)
        manifest_rows: List of manifest row dicts with fixture_id, vocabulary, expected_calls, etc.
        vocabs: Dict mapping vocabulary name to surface_to_canonical dict
    """
    # Load skips
    skips_file = out_root / "skips.json"
    skips = json.loads(skips_file.read_text()) if skips_file.exists() else {}

    # Invert vocabs: vocab_name -> surface_to_canonical
    vocab_by_name = {}
    for name, surface_to_canonical in vocabs.items():
        vocab_by_name[name] = surface_to_canonical

    # Build a map of fixture_id -> row
    manifest_by_fixture = {row["fixture_id"]: row for row in manifest_rows}

    # Discover all models by scanning transcripts directory
    transcripts_dir = out_root / "transcripts"
    models = sorted([d.name for d in transcripts_dir.iterdir() if d.is_dir()])

    # Load all transcripts: model -> fixture -> TranscriptResult
    transcripts_by_model = {}
    for model in models:
        transcripts_by_model[model] = {}
        model_dir = transcripts_dir / model
        for json_file in model_dir.glob("*.json"):
            fixture_id = json_file.stem
            try:
                result_dict = json.loads(json_file.read_text())
                result = TranscriptResult.from_dict(result_dict)
                transcripts_by_model[model][fixture_id] = result
            except Exception:
                # Skip files that can't be parsed
                pass

    # Compute metrics per fixture
    metrics_by_fixture = {}
    draft_truth_rows = []

    for fixture_id, row in manifest_by_fixture.items():
        # Get vocabulary for this fixture
        vocab_name = row.get("vocabulary") or "swish_brick"
        if vocab_name not in vocab_by_name:
            continue
        surface_to_canonical = vocab_by_name[vocab_name]

        # Load transcripts for this fixture from all models
        dets_by_model = {}
        for model in models:
            if fixture_id in transcripts_by_model.get(model, {}):
                transcript = transcripts_by_model[model][fixture_id]
                dets = detect(transcript.words, surface_to_canonical)
                dets_by_model[model] = dets

        # Skip if no transcripts for this fixture
        if not dets_by_model:
            continue

        # Cluster detections across models
        clusters = cluster(dets_by_model)

        # Build draft truth: consensus clusters in time order
        consensus_canonicals = [c["canonical"] for c in clusters if c["consensus"]]
        draft_expected_calls = " ".join(consensus_canonicals)

        # Build disagreements: non-consensus clusters
        disagreements = []
        for c in clusters:
            if not c["consensus"]:
                # Format: canonical@mid found by model1/n, model2/n, ...
                n_models = len(dets_by_model)
                n_found = len(c["models"])
                model_list = ",".join(sorted(c["models"].keys()))
                disagreements.append(f"{c['canonical']}@{c['mid']:.1f} found by {model_list}/{n_models}")

        disagreements_str = ";".join(disagreements)

        draft_truth_rows.append({
            "fixture_id": fixture_id,
            "draft_expected_calls": draft_expected_calls,
            "disagreements": disagreements_str,
        })

        metrics_by_fixture[fixture_id] = {
            "detections_by_model": {model: dets for model, dets in dets_by_model.items()},
            "clusters": clusters,
        }

    # Write draft_truth.csv
    draft_truth_file = out_root / "draft_truth.csv"
    with draft_truth_file.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["fixture_id", "draft_expected_calls", "disagreements"])
        writer.writeheader()
        writer.writerows(draft_truth_rows)

    # Compute summary metrics
    metrics_output = {
        "models": models,
        "fixtures": metrics_by_fixture,
        "skips": skips,
    }

    # Write metrics.json
    metrics_file = out_root / "metrics.json"
    with metrics_file.open("w") as f:
        json.dump(metrics_output, f, indent=2)


def main() -> None:
    """Load config and manifest, compute all metrics, write output files."""
    from hoops.config import load_config
    from hoops.fixtures import read_manifest

    # Load config to get vocabularies
    cfg = load_config(REPO / "config.yaml")

    # Build vocab map: vocab_name -> surface_to_canonical
    vocabs = {name: vocab.surface_to_canonical for name, vocab in cfg.vocabularies.items()}

    # Load manifest
    manifest_path = REPO / "fixtures" / "manifest.csv"
    manifest_rows = read_manifest(manifest_path)

    # Assemble metrics
    assemble_metrics(
        out_root=OUT,
        manifest_rows=manifest_rows,
        vocabs=vocabs,
    )


if __name__ == "__main__":
    main()
