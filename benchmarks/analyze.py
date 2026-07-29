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


def assemble_metrics(out_root: Path, manifest_rows: list[dict], vocabs: dict[str, dict],
                    vocab_default: str = "swish_brick") -> None:
    """Load all cached transcripts and manifest, compute full metrics.

    Args:
        out_root: Root path for benchmarks output (contains transcripts/ and skips.json)
        manifest_rows: List of manifest row dicts with fixture_id, vocabulary, expected_calls, etc.
        vocabs: Dict mapping vocabulary name to surface_to_canonical dict
        vocab_default: Default vocabulary name if fixture specifies none
    """
    # Load skips
    skips_file = out_root / "skips.json"
    skips = json.loads(skips_file.read_text()) if skips_file.exists() else {}

    # Build a map of fixture_id -> row
    manifest_by_fixture = {row["fixture_id"]: row for row in manifest_rows}

    # Discover all models by scanning transcripts directory
    transcripts_dir = out_root / "transcripts"
    if not transcripts_dir.exists():
        return
    models = sorted([d.name for d in transcripts_dir.iterdir() if d.is_dir()])

    # Load all transcripts: model -> fixture -> TranscriptResult
    transcripts_by_model = {}
    load_errors = []
    for model in models:
        transcripts_by_model[model] = {}
        model_dir = transcripts_dir / model
        for json_file in model_dir.glob("*.json"):
            fixture_id = json_file.stem
            try:
                result_dict = json.loads(json_file.read_text())
                result = TranscriptResult.from_dict(result_dict)
                transcripts_by_model[model][fixture_id] = result
            except Exception as e:
                load_errors.append({"model": model, "fixture_id": fixture_id, "error": str(e)})

    # Compute metrics per fixture
    metrics_by_fixture = {}
    draft_truth_rows = []
    all_clusters_combined = []  # For pairwise agreement across all fixtures
    unknown_vocab_warnings = []

    for fixture_id, row in manifest_by_fixture.items():
        # Get vocabulary for this fixture (use default if not specified)
        vocab_name = row.get("vocabulary") or vocab_default
        if vocab_name not in vocabs:
            unknown_vocab_warnings.append({"fixture_id": fixture_id, "vocabulary": vocab_name})
            continue
        surface_to_canonical = vocabs[vocab_name]

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
        all_clusters_combined.extend(clusters)

        # Build draft truth: consensus clusters in time order
        consensus_canonicals = [c["canonical"] for c in clusters if c["consensus"]]
        draft_expected_calls = " ".join(consensus_canonicals)

        # Build disagreements: non-consensus clusters with k/n format
        disagreements = []
        n_models = len(dets_by_model)
        for c in clusters:
            if not c["consensus"]:
                n_found = len(c["models"])
                disagreements.append(f"{c['canonical']}@{c['mid']:.1f} found by {n_found}/{n_models}")

        disagreements_str = ";".join(disagreements)

        draft_truth_rows.append({
            "fixture_id": fixture_id,
            "draft_expected_calls": draft_expected_calls,
            "disagreements": disagreements_str,
        })

        # Determine reference sequence for accuracy
        expected_calls_str = row.get("expected_calls", "").strip()
        has_expected = expected_calls_str and expected_calls_str != "NEEDS_LABELING"
        if has_expected:
            reference_seq = expected_calls_str.split()
            accuracy_mode = "expected"
        else:
            reference_seq = consensus_canonicals
            accuracy_mode = "consensus"

        # Per-model accuracy: compare each model's detected sequence to reference
        per_model_accuracy = {}
        for model, dets in dets_by_model.items():
            # Get this model's canonical sequence in time order
            model_canonicals = [d["canonical"] for d in sorted(dets, key=lambda d: d["mid"])]
            # Sequence match
            accuracy = 1.0 if model_canonicals == reference_seq else 0.0
            per_model_accuracy[model] = accuracy

        # Gap stats for beep fixtures
        beep_fixture = row.get("timing_ground_truth", "").upper() in ("TRUE", "YES")
        gap_stats_by_model = {}
        if beep_fixture and row.get("beep_interval_s"):
            try:
                interval = float(row["beep_interval_s"])
                for model, dets in dets_by_model.items():
                    mids = [d["mid"] for d in dets]
                    stats = gap_stats(mids, interval)
                    if stats:
                        gap_stats_by_model[model] = stats
            except (ValueError, TypeError):
                pass

        # Build fixture detail
        metrics_by_fixture[fixture_id] = {
            "detections_by_model": {model: dets for model, dets in dets_by_model.items()},
            "clusters": clusters,
            "accuracy_mode": accuracy_mode,
            "per_model_accuracy": per_model_accuracy,
            "gap_stats": gap_stats_by_model,
        }

    # Compute per-model summary stats and detection counts
    models_summary = {}
    for model in models:
        runtimes = []
        rtfs = []
        peak_rss_list = []
        total_minutes = 0
        found_count = 0
        matched_count = 0
        extra_count = 0

        for fixture_id, transcript in transcripts_by_model[model].items():
            row = manifest_by_fixture.get(fixture_id)
            if not row:
                continue
            runtimes.append(transcript.runtime_s)
            if row.get("duration_s"):
                try:
                    duration = float(row["duration_s"])
                    rtf = transcript.runtime_s / duration
                    rtfs.append(rtf)
                    total_minutes += duration / 60.0
                except (ValueError, TypeError):
                    pass
            if transcript.peak_rss_mb is not None:
                peak_rss_list.append(transcript.peak_rss_mb)

            # Count detections for this fixture and model
            if fixture_id in metrics_by_fixture:
                dets = metrics_by_fixture[fixture_id]["detections_by_model"].get(model, [])
                found_count += len(dets)
                clusters = metrics_by_fixture[fixture_id]["clusters"]
                # Count matched for THIS fixture only
                matched_for_fixture = 0
                for c in clusters:
                    if c["consensus"] and model in c["models"]:
                        # This cluster has a detection from this model
                        matched_for_fixture += 1
                matched_count += matched_for_fixture
                # Count extra: found - matched (detections not in any consensus cluster)
                extra_count += len(dets) - matched_for_fixture

        summary = {}
        if runtimes:
            summary["runtime_mean"] = round(statistics.mean(runtimes), 3)
            summary["runtime_min"] = round(min(runtimes), 3)
            summary["runtime_max"] = round(max(runtimes), 3)
        if rtfs:
            summary["rtf_mean"] = round(statistics.mean(rtfs), 3)
            summary["rtf_median"] = round(statistics.median(rtfs), 3)
        if peak_rss_list:
            summary["peak_rss_mean"] = round(statistics.mean(peak_rss_list), 3)
            summary["peak_rss_max"] = round(max(peak_rss_list), 3)
        if model == "whisper-1" and total_minutes > 0:
            summary["cost_usd"] = round(0.006 * total_minutes, 3)

        # Add detection counts
        summary["detections_found"] = found_count
        summary["detections_matched"] = matched_count
        summary["detections_extra"] = extra_count

        models_summary[model] = summary

    # Compute pairwise agreement over all fixtures' clusters combined
    all_models = sorted(set(m for c in all_clusters_combined for m in c["models"].keys()))
    agreement = pairwise_agreement(all_clusters_combined, all_models) if all_clusters_combined else {}

    # Compute isolation split for F02 (if present)
    isolation_result = {}
    f02_row = manifest_by_fixture.get("F02")
    if f02_row and "F02" in metrics_by_fixture:
        f02_metrics = metrics_by_fixture["F02"]
        f02_clusters = f02_metrics["clusters"]
        # Real: detections in consensus clusters of same canonical
        # Bait: detections outside consensus clusters (isolation-based filtering)
        real = []
        bait = []
        for c in f02_clusters:
            if c["consensus"]:
                # All detections in this consensus cluster
                for d in c["models"].values():
                    real.append(d["isolation"])
            else:
                # All detections in non-consensus cluster
                for d in c["models"].values():
                    bait.append(d["isolation"])
        threshold_result = recommend_threshold(real, bait)
        isolation_result = threshold_result

    # Silence metric: placeholder since no recorded fixture has known silence region
    silence_metric = {"status": "pending F10"}

    # Assemble output
    metrics_output = {
        "models": models_summary,
        "fixtures": metrics_by_fixture,
        "skips": skips,
        "isolation": isolation_result,
        "agreement": agreement,
        "silence": silence_metric,
        "load_errors": load_errors,
        "unknown_vocab": unknown_vocab_warnings,
    }

    # Write draft_truth.csv
    draft_truth_file = out_root / "draft_truth.csv"
    with draft_truth_file.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["fixture_id", "draft_expected_calls", "disagreements"])
        writer.writeheader()
        writer.writerows(draft_truth_rows)

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
        vocab_default=cfg.vocab_default,
    )


if __name__ == "__main__":
    main()
