"""Self-contained HTML report generator for ASR benchmark metrics.

Consumes the REAL schema written by `benchmarks/analyze.py::assemble_metrics`
(see `tests/test_benchmark_analyze.py` for the ground-truth shape), not the
illustrative pseudo-data in the Task 7 brief. Notable adaptations, all driven
by what `metrics.json` actually contains:

- Per-model summary reads `rtf_mean`/`rtf_median`, `peak_rss_mean`/`peak_rss_max`,
  `detections_found`/`detections_matched`/`detections_extra`, and `cost_usd`.
  Boundary MAE (mean/median/p95/max) is aggregated here from each fixture's
  `gap_stats[model]` entry (n_gaps-weighted) since there is no per-model
  boundary summary in metrics.json.
- Coverage is derived, not stored: fraction of fixtures in `metrics["fixtures"]`
  where the model has a `detections_by_model` entry (meaning it was
  successfully transcribed for that fixture, regardless of hit count).
- Per-fixture data lives under `detections_by_model`, not `models[model]`.
  There is no `duration_s` on a fixture; each timeline's x-scale is derived
  from the max detection end/mid seen, with a floor.
- Isolation (F02) is a single flat dict (`threshold`, `margin`, `real_below`,
  `bait_above`) with no raw real/bait lists and no per-model breakdown.
- Boundary error distributions have no raw per-gap errors available, only the
  aggregate stats, so Section 3 renders marks at mean/median/p95/max instead
  of a dot scatter.
- Detections carry no `consensus` flag; a detection's in-consensus status is
  derived from the fixture's `clusters`, matching by (model, mid, canonical).
- `draft_truth` is not a metrics.json key; it lives in `out/draft_truth.csv`
  and is passed into `render()` separately.
- The Truth row on a timeline only appears when `accuracy_mode == "expected"`
  for that fixture (Mode A labels exist); since metrics.json does not retain
  the actual expected-call sequence, it is rendered as a per-model
  match/mismatch summary line rather than fabricated timing dots.
"""
from __future__ import annotations
import csv, html, json, statistics
from pathlib import Path
from datetime import datetime

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "benchmarks" / "out"

CHECK = "✓"
CROSS = "✗"
WARN = "⚠"

# (header, metrics key, best direction ("min"/"max"/None), decimal places)
SUMMARY_COLUMNS = [
    ("Boundary Mean (s)", "boundary_mean", "min", 3),
    ("Boundary Median (s)", "boundary_median", "min", 3),
    ("Boundary P95 (s)", "boundary_p95", "min", 3),
    ("Boundary Max (s)", "boundary_max", "min", 3),
    ("RTF Mean", "rtf_mean", "min", 3),
    ("RTF Median", "rtf_median", "min", 3),
    ("Peak RSS Mean (MB)", "peak_rss_mean", "min", 1),
    ("Peak RSS Max (MB)", "peak_rss_max", "min", 1),
    ("Cost ($)", "cost_usd", "min", 3),
    ("Coverage", "coverage_frac", "max", None),
    ("Found", "detections_found", "max", 0),
    ("Matched*", "detections_matched", "max", 0),
    ("Extra", "detections_extra", None, 0),
    ("Median Δ (s)", "median_delta", None, 3),
]


def _esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _fmt(val, prec=3) -> str:
    if val is None:
        return "—"
    if prec == 0:
        return str(int(val))
    return f"{val:.{prec}f}"


def _aggregate_boundary(fixtures: dict, model: str) -> dict:
    """n_gaps-weighted aggregate of gap_stats across all beep fixtures for a model."""
    entries = [fx["gap_stats"][model] for fx in fixtures.values()
               if model in fx.get("gap_stats", {})]
    entries = [e for e in entries if e.get("n_gaps")]
    if not entries:
        return {}
    total_n = sum(e["n_gaps"] for e in entries)

    def wavg(key):
        return sum(e[key] * e["n_gaps"] for e in entries) / total_n

    return {
        "mean": wavg("mean"), "median": wavg("median"), "p95": wavg("p95"),
        "max": max(e["max"] for e in entries), "n_gaps": total_n,
    }


def _in_consensus_set(fixture_data: dict) -> set:
    """(model, mid, canonical) triples that belong to a consensus cluster."""
    s = set()
    for c in fixture_data.get("clusters", []):
        if c.get("consensus"):
            for model, d in c.get("models", {}).items():
                s.add((model, d.get("mid"), d.get("canonical")))
    return s


def _fixture_span(fixture_data: dict) -> float:
    """x-scale (seconds) for a fixture's timeline: no duration_s in metrics,
    so derive from the furthest detection end/mid seen, with a sane floor."""
    ends = []
    for dets in fixture_data.get("detections_by_model", {}).values():
        for d in dets:
            ends.append(d.get("end", d.get("mid", 0)) or 0)
    if not ends:
        return 10.0
    return max(max(ends) * 1.15, 10.0)


def _summary_table(metrics: dict) -> str:
    models_data = metrics.get("models", {})
    fixtures = metrics.get("fixtures", {})
    agreement = metrics.get("agreement", {})
    models = sorted(models_data.keys())
    if not models:
        return '<p class="muted">No model data.</p>'

    total_fixtures = len(fixtures)
    rows = []
    for model in models:
        data = models_data[model]
        boundary = _aggregate_boundary(fixtures, model)
        covered = sum(1 for fx in fixtures.values()
                      if model in fx.get("detections_by_model", {}))
        coverage_frac = (covered / total_fixtures) if total_fixtures else None
        coverage_label = f"{covered}/{total_fixtures}" if total_fixtures else "—"
        if total_fixtures and covered < total_fixtures:
            coverage_label += f" {WARN}"
        deltas = [v for k, v in agreement.items() if model in k.split("|")]
        rows.append({
            "model": model,
            "boundary_mean": boundary.get("mean"),
            "boundary_median": boundary.get("median"),
            "boundary_p95": boundary.get("p95"),
            "boundary_max": boundary.get("max"),
            "rtf_mean": data.get("rtf_mean"),
            "rtf_median": data.get("rtf_median"),
            "peak_rss_mean": data.get("peak_rss_mean"),
            "peak_rss_max": data.get("peak_rss_max"),
            "cost_usd": data.get("cost_usd"),
            "coverage_frac": coverage_frac,
            "coverage_label": coverage_label,
            "detections_found": data.get("detections_found"),
            "detections_matched": data.get("detections_matched"),
            "detections_extra": data.get("detections_extra"),
            "median_delta": statistics.median(deltas) if deltas else None,
        })

    best_map = {}
    for _, key, direction, _prec in SUMMARY_COLUMNS:
        if direction is None:
            best_map[key] = None
            continue
        vals = [r[key] for r in rows if r.get(key) is not None]
        best_map[key] = (min(vals) if direction == "min" else max(vals)) if vals else None

    lines = ['<table class="summary">',
             "<tr><th>Model</th>" + "".join(f"<th>{_esc(h)}</th>" for h, *_ in SUMMARY_COLUMNS) + "</tr>"]
    for r in rows:
        cells = [f"<td>{_esc(r['model'])}</td>"]
        for _, key, direction, prec in SUMMARY_COLUMNS:
            val = r.get(key)
            display = r["coverage_label"] if key == "coverage_frac" else _fmt(val, prec if prec is not None else 3)
            best = best_map.get(key)
            is_best = (direction is not None and val is not None and best is not None
                       and abs(val - best) < 1e-9)
            cls = ' class="best"' if is_best else ""
            cells.append(f"<td{cls}>{display}</td>")
        lines.append("<tr>" + "".join(cells) + "</tr>")
    lines.append("</table>")
    lines.append('<p class="muted">* "Matched" replaces the brief\'s "missed" column: the real schema '
                 "tracks detections_found/detections_matched/detections_extra, not a directly labeled "
                 "miss count.</p>")
    return "\n".join(lines)


def _svg_timeline(fixture_data: dict, models: list[str]) -> str:
    detections_by_model = fixture_data.get("detections_by_model", {})
    consensus_set = _in_consensus_set(fixture_data)
    span = _fixture_span(fixture_data)
    row_h = 26
    width = 900
    height = row_h * max(len(models), 1) + 20

    parts = [f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">']
    for i, model in enumerate(models):
        y = 16 + i * row_h
        parts.append(f'<line x1="90" y1="{y}" x2="{width - 10}" y2="{y}" stroke="#ddd"/>')
        parts.append(f'<text x="4" y="{y + 4}" font-size="11">{_esc(model)}</text>')
        for d in detections_by_model.get(model, []):
            mid = d.get("mid", 0) or 0
            x = 90 + (mid / span) * (width - 100)
            key = (model, d.get("mid"), d.get("canonical"))
            fill = "#2ecc71" if key in consensus_set else "#e67e22"
            title = (f'{_esc(d.get("raw", ""))} @ {d.get("start", 0):.1f}–{d.get("end", 0):.1f}s, '
                     f'isolation {d.get("isolation", 0):.2f}s')
            parts.append(f'<circle cx="{x:.1f}" cy="{y}" r="4" fill="{fill}"><title>{title}</title></circle>')
    parts.append("</svg>")

    truth_html = ""
    if fixture_data.get("accuracy_mode") == "expected":
        acc = fixture_data.get("per_model_accuracy", {})
        marks = " &nbsp; ".join(f"{_esc(m)} {CHECK if a == 1.0 else CROSS}" for m, a in sorted(acc.items()))
        truth_html = f'<p class="truth">Truth (Mode A labeled): {marks}</p>'
    return truth_html + "\n".join(parts)


def _svg_boundary_marks(stats: dict) -> str:
    if not stats:
        return '<p class="muted">no beep-fixture data.</p>'
    width, height = 420, 50
    max_v = max(stats["max"], 1e-6)

    def x(v):
        return 30 + (v / max_v) * (width - 60)

    marks = [("mean", stats["mean"], "#3498db"), ("median", stats["median"], "#2ecc71"),
              ("p95", stats["p95"], "#e67e22"), ("max", stats["max"], "#e74c3c")]
    parts = [f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">']
    parts.append(f'<line x1="30" y1="30" x2="{width - 30}" y2="30" stroke="#ccc"/>')
    for i, (label, v, color) in enumerate(marks):
        xp = x(v)
        y_label = 12 if i % 2 == 0 else 46
        parts.append(f'<line x1="{xp:.1f}" y1="18" x2="{xp:.1f}" y2="42" stroke="{color}" stroke-width="2">'
                      f'<title>{label} {v:.3f}s</title></line>')
        parts.append(f'<text x="{xp:.1f}" y="{y_label}" font-size="9" text-anchor="middle" '
                      f'fill="{color}">{label}</text>')
    parts.append("</svg>")
    return "\n".join(parts) + f'<p class="muted">n_gaps={stats["n_gaps"]}</p>'


def _svg_isolation(iso: dict) -> str:
    if not iso:
        return '<p class="muted">No isolation split available (F02 not transcribed by 2+ models).</p>'
    threshold = iso.get("threshold", 0.0)
    margin = iso.get("margin", 0.0)
    real_below = iso.get("real_below", 0)
    bait_above = iso.get("bait_above", 0)

    width, height = 420, 70
    span = max(abs(margin) * 3, 1.0)
    lo, hi = threshold - span / 2, threshold + span / 2

    def x(v):
        return 30 + (v - lo) / (hi - lo) * (width - 60)

    band_lo, band_hi = x(threshold - margin / 2), x(threshold + margin / 2)
    tx = x(threshold)
    parts = [f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">']
    parts.append(f'<line x1="30" y1="35" x2="{width - 30}" y2="35" stroke="#ccc"/>')
    parts.append(f'<rect x="{min(band_lo, band_hi):.1f}" y="25" width="{abs(band_hi - band_lo):.1f}" '
                  f'height="20" fill="#3498db" opacity="0.15"><title>margin {margin:.3f}s</title></rect>')
    parts.append(f'<line x1="{tx:.1f}" y1="15" x2="{tx:.1f}" y2="55" stroke="#e74c3c" stroke-width="2">'
                  f'<title>threshold {threshold:.3f}s, margin {margin:.3f}s</title></line>')
    parts.append(f'<text x="{tx:.1f}" y="12" font-size="11" text-anchor="middle">threshold {threshold:.3f}s</text>')
    parts.append(f'<text x="{tx:.1f}" y="68" font-size="11" text-anchor="middle">margin {margin:.3f}s</text>')
    parts.append("</svg>")
    counts = f'<p>real_below threshold: {real_below} &nbsp;&middot;&nbsp; bait_above threshold: {bait_above}</p>'
    return "\n".join(parts) + counts


def _heat_table(agreement: dict, models: list[str]) -> str:
    if not models:
        return '<p class="muted">No agreement data.</p>'
    lines = ['<table class="heat"><tr><th></th>' +
             "".join(f"<th>{_esc(m)}</th>" for m in models) + "</tr>"]
    for m1 in models:
        cells = [f"<th>{_esc(m1)}</th>"]
        for m2 in models:
            if m1 == m2:
                cells.append('<td class="diag">—</td>')
                continue
            key = f"{m1}|{m2}" if models.index(m1) < models.index(m2) else f"{m2}|{m1}"
            delta = agreement.get(key)
            if delta is None:
                cells.append('<td>—</td>')
            else:
                alpha = min(delta / 0.5, 1.0) * 0.6
                cells.append(f'<td style="background:rgba(200,0,0,{alpha:.2f})">{delta:.3f}</td>')
        lines.append("<tr>" + "".join(cells) + "</tr>")
    lines.append("</table>")
    return "\n".join(lines)


def _fixture_detail(fixture_id: str, fixture_data: dict) -> str:
    detections_by_model = fixture_data.get("detections_by_model", {})
    consensus_set = _in_consensus_set(fixture_data)
    models = sorted(detections_by_model.keys())

    lines = [f"<details><summary>{_esc(fixture_id)} ({len(models)} models)</summary>",
             "<table class='detail'><tr><th>Model</th><th>Raw</th><th>Canonical</th>"
             "<th>Start</th><th>End</th><th>Isolation</th><th>In-consensus</th></tr>"]
    for model in models:
        for d in sorted(detections_by_model[model], key=lambda d: d.get("mid", 0)):
            key = (model, d.get("mid"), d.get("canonical"))
            in_consensus = key in consensus_set
            lines.append(
                "<tr>"
                f"<td>{_esc(model)}</td>"
                f"<td>{_esc(d.get('raw', '?'))}</td>"
                f"<td>{_esc(d.get('canonical', '?'))}</td>"
                f"<td>{d.get('start', 0):.1f}</td>"
                f"<td>{d.get('end', 0):.1f}</td>"
                f"<td>{d.get('isolation', 0):.2f}</td>"
                f"<td>{CHECK if in_consensus else CROSS}</td>"
                "</tr>"
            )
    lines.append("</table></details>")
    return "\n".join(lines)


_STYLE = """
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       margin: 20px; background: #fafafa; color: #333; }
h1 { border-bottom: 2px solid #333; padding-bottom: 10px; }
h2 { margin-top: 30px; border-left: 4px solid #3498db; padding-left: 10px; }
h3 { margin-top: 20px; }
table { border-collapse: collapse; margin: 10px 0; }
td, th { border: 1px solid #ccc; padding: 6px 8px; text-align: left; font-size: 12px; }
th { background: #f0f0f0; }
.best { background: #d7f5d7; }
.diag { background: #f5f5f5; }
pre { background: #f5f5f5; padding: 10px; overflow-x: auto; border: 1px solid #ddd; }
details { margin: 10px 0; }
summary { cursor: pointer; padding: 8px; background: #f9f9f9; border: 1px solid #ddd; }
summary:hover { background: #f0f0f0; }
.warning { color: #e74c3c; font-weight: bold; }
.muted { color: #999; }
.truth { font-weight: bold; margin-bottom: 4px; }
"""


def render(metrics: dict, draft_truth_rows: list[dict] | None = None) -> str:
    """Render metrics (real analyze.py schema) + draft_truth.csv rows as self-contained HTML."""
    draft_truth_rows = draft_truth_rows or []
    models_data = metrics.get("models", {})
    fixtures = metrics.get("fixtures", {})
    isolation = metrics.get("isolation", {})
    agreement = metrics.get("agreement", {})
    skips = metrics.get("skips", [])
    silence = metrics.get("silence", {})

    models = sorted(models_data.keys())
    fixture_ids = sorted(fixtures.keys())

    lines = [
        "<!doctype html>", "<html>", "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>ASR Benchmark Report</title>",
        f"<style>{_STYLE}</style>",
        "</head>", "<body>",
        "<h1>ASR Benchmark Report</h1>",
    ]

    # 1. Summary table
    lines.append("<h2>Summary</h2>")
    lines.append(_summary_table(metrics))

    # 2. Per-fixture timelines
    lines.append("<h2>Per-Fixture Timelines</h2>")
    if not fixture_ids:
        lines.append('<p class="muted">No fixtures transcribed.</p>')
    for fixture_id in fixture_ids:
        lines.append(f"<h3>{_esc(fixture_id)}</h3>")
        lines.append(_svg_timeline(fixtures[fixture_id], models))

    # 3. Boundary error distribution (aggregate marks; no raw gap errors in metrics.json)
    lines.append("<h2>Boundary Error Distribution</h2>")
    lines.append('<p class="muted">Raw per-gap errors are not retained in metrics.json &mdash; '
                 "marks below are the n_gaps-weighted mean/median/p95/max from each model's "
                 "beep-fixture gap_stats.</p>")
    any_boundary = False
    for model in models:
        stats = _aggregate_boundary(fixtures, model)
        if stats:
            any_boundary = True
        lines.append(f"<h3>{_esc(model)}</h3>")
        lines.append(_svg_boundary_marks(stats))
    if not any_boundary:
        lines.append('<p class="muted">No beep fixtures with gap data.</p>')

    # 4. Isolation separation (F02) — one flat dict, no per-model breakdown
    lines.append("<h2>Isolation Separation (F02)</h2>")
    lines.append(_svg_isolation(isolation))

    # 5. Agreement heatmap
    lines.append("<h2>Agreement Heatmap</h2>")
    lines.append(_heat_table(agreement, models))

    # 6. Per-fixture detail tables
    lines.append("<h2>Per-Fixture Details</h2>")
    for fixture_id in fixture_ids:
        lines.append(_fixture_detail(fixture_id, fixtures[fixture_id]))

    # 7. Draft ground truth
    lines.append("<h2>Draft ground truth</h2>")
    if draft_truth_rows:
        raw_lines = ["fixture_id,draft_expected_calls,disagreements"]
        for row in draft_truth_rows:
            fid = row.get("fixture_id", "")
            calls = row.get("draft_expected_calls", "")
            disagree = row.get("disagreements", "")
            if disagree:
                raw_lines.append(f"{WARN} {disagree}")
            raw_lines.append(f"{fid},{calls},{disagree}")
        block = "\n".join(raw_lines)
        lines.append(f"<pre>{_esc(block)}</pre>")
    else:
        lines.append('<p class="muted">No draft ground truth available (out/draft_truth.csv missing or empty).</p>')

    # 8. Footer
    lines.append("<h2>Metadata</h2>")
    if skips:
        lines.append("<h3>Skips</h3><ul>")
        for skip in skips:
            lines.append(f'<li>{_esc(skip.get("model", "?"))} / {_esc(skip.get("fixture", "?"))}: '
                         f'{_esc(skip.get("reason", "?"))}</li>')
        lines.append("</ul>")
    if silence:
        lines.append(f'<p class="muted">Silence metric: {_esc(silence.get("status", ""))}</p>')
    lines.append(f'<p class="muted">Generated: {_esc(datetime.now().isoformat())}</p>')

    lines.append("</body></html>")
    return "\n".join(lines)


def main() -> None:
    """Read metrics.json + draft_truth.csv and write report.html."""
    metrics_file = OUT / "metrics.json"
    if not metrics_file.exists():
        print(f"Error: {metrics_file} not found")
        return

    metrics = json.loads(metrics_file.read_text())

    draft_truth_rows: list[dict] = []
    draft_truth_file = OUT / "draft_truth.csv"
    if draft_truth_file.exists():
        with draft_truth_file.open(newline="") as f:
            draft_truth_rows = list(csv.DictReader(f))

    html_content = render(metrics, draft_truth_rows)
    OUT.mkdir(parents=True, exist_ok=True)
    report_file = OUT / "report.html"
    report_file.write_text(html_content)
    print(f"Report written to {report_file}")


if __name__ == "__main__":
    main()
