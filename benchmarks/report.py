"""Self-contained HTML report generator for ASR benchmark metrics."""
from __future__ import annotations
import json, html, statistics
from pathlib import Path
from datetime import datetime

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "benchmarks" / "out"


def _svg_timeline(fixture_id: str, fixture_data: dict, models: list[str]) -> str:
    """Generate SVG timeline for a fixture showing detections across models."""
    width, height = 900, 30 * (len(models) + 1)
    duration = fixture_data.get("duration_s", 100)
    if duration == 0:
        duration = 100

    detections_by_model = fixture_data.get("models", {})
    clusters = fixture_data.get("clusters", [])

    # Build a map of (mid) to consensus flag
    consensus_map = {}
    for cluster in clusters:
        consensus_map[cluster["mid"]] = cluster.get("consensus", False)

    lines = [f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">']
    lines.append('<defs><style>.tl-label { font-size: 12px; font-family: sans-serif; } '
                 '.tl-consensus { fill: #2ecc71; } .tl-bait { fill: #e67e22; } '
                 '.tl-axis { stroke: #ccc; stroke-width: 1; }</style></defs>')

    # Ground truth row (if labels exist, placeholder)
    y = 20
    lines.append(f'<line x1="50" y1="{y}" x2="{width}" y2="{y}" class="tl-axis" />')
    lines.append(f'<text x="5" y="{y + 5}" class="tl-label">Truth</text>')

    # Model rows
    for model_idx, model in enumerate(models):
        y = 50 + model_idx * 30
        lines.append(f'<line x1="50" y1="{y}" x2="{width}" y2="{y}" class="tl-axis" />')
        lines.append(f'<text x="5" y="{y + 5}" class="tl-label">{html.escape(model)}</text>')

        dets = detections_by_model.get(model, {}).get("detections", [])
        for det in dets:
            mid = det.get("mid", 0)
            canonical = det.get("canonical", "?")
            raw = det.get("raw", "?")
            start = det.get("start", 0)
            end = det.get("end", 0)
            isolation = det.get("isolation", 0)
            is_consensus = det.get("consensus", False)

            x = 50 + (mid / duration) * (width - 50)
            fill_class = "tl-consensus" if is_consensus else "tl-bait"
            title = f"{html.escape(raw)} @ {start:.1f}–{end:.1f}s, isolation {isolation:.2f}s"
            lines.append(f'<circle cx="{x}" cy="{y}" r="4" class="{fill_class}"><title>{title}</title></circle>')

    lines.append('</svg>')
    return "\n".join(lines)


def _svg_strip_gaps(errors: list[float]) -> str:
    """Generate SVG horizontal strip for gap error distribution."""
    if not errors:
        return '<div style="color: #999; font-style: italic;">No gap data</div>'

    width, height = 400, 40

    # Calculate q1, median, q3
    sorted_errs = sorted(errors)
    median = statistics.median(sorted_errs)
    q1 = sorted_errs[len(sorted_errs) // 4]
    q3 = sorted_errs[3 * len(sorted_errs) // 4]

    min_err = min(errors)
    max_err = max(errors)
    range_err = max_err - min_err if max_err > min_err else 1

    lines = [f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">']
    lines.append('<defs><style>.gap-dot { fill: #3498db; } .gap-box { fill: none; stroke: #3498db; stroke-width: 2; } '
                 '.gap-median { stroke: #e74c3c; stroke-width: 2; }</style></defs>')

    # Draw axis
    lines.append(f'<line x1="30" y1="30" x2="{width - 10}" y2="30" stroke="#ccc" stroke-width="1" />')

    # Draw dots for each error
    for err in errors:
        x = 30 + ((err - min_err) / range_err) * (width - 40) if range_err > 0 else 30
        lines.append(f'<circle cx="{x}" cy="30" r="2" class="gap-dot" />')

    # Draw box for q1-q3
    x1 = 30 + ((q1 - min_err) / range_err) * (width - 40) if range_err > 0 else 30
    x3 = 30 + ((q3 - min_err) / range_err) * (width - 40) if range_err > 0 else 30
    lines.append(f'<rect x="{x1}" y="20" width="{x3 - x1}" height="20" class="gap-box" />')

    # Draw median line
    x_med = 30 + ((median - min_err) / range_err) * (width - 40) if range_err > 0 else 30
    lines.append(f'<line x1="{x_med}" y1="15" x2="{x_med}" y2="45" class="gap-median" />')

    lines.append('</svg>')
    return "\n".join(lines)


def _svg_strip_isolation(real: list[float], bait: list[float], threshold: float) -> str:
    """Generate SVG 1-D strip for isolation real vs bait with threshold line."""
    if not real and not bait:
        return '<div style="color: #999; font-style: italic;">No isolation data</div>'

    width, height = 400, 40

    all_vals = real + bait
    min_val = min(all_vals) if all_vals else 0
    max_val = max(all_vals) if all_vals else 1
    range_val = max_val - min_val if max_val > min_val else 1

    lines = [f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">']
    lines.append('<defs><style>.iso-real { fill: #2ecc71; } .iso-bait { fill: #e67e22; } '
                 '.iso-threshold { stroke: #e74c3c; stroke-width: 2; }</style></defs>')

    # Draw axis
    lines.append(f'<line x1="30" y1="30" x2="{width - 10}" y2="30" stroke="#ccc" stroke-width="1" />')

    # Draw real dots (green)
    for val in real:
        x = 30 + ((val - min_val) / range_val) * (width - 40) if range_val > 0 else 30
        lines.append(f'<circle cx="{x}" cy="30" r="3" class="iso-real" />')

    # Draw bait dots (orange)
    for val in bait:
        x = 30 + ((val - min_val) / range_val) * (width - 40) if range_val > 0 else 30
        lines.append(f'<circle cx="{x}" cy="30" r="2" class="iso-bait" />')

    # Draw threshold line
    x_thresh = 30 + ((threshold - min_val) / range_val) * (width - 40) if range_val > 0 else 30
    lines.append(f'<line x1="{x_thresh}" y1="15" x2="{x_thresh}" y2="45" class="iso-threshold"><title>Threshold: {threshold:.3f}</title></line>')

    lines.append('</svg>')
    return "\n".join(lines)


def _svg_heatmap(agreement: dict, models: list[str]) -> str:
    """Generate HTML heatmap table for pairwise agreement."""
    if not models or not agreement:
        return '<div style="color: #999; font-style: italic;">No agreement data</div>'

    lines = ['<table style="border-collapse: collapse; font-size: 12px; font-family: monospace;">']

    # Header row
    lines.append('<tr><th style="border: 1px solid #ddd; padding: 4px;"></th>')
    for m in models:
        lines.append(f'<th style="border: 1px solid #ddd; padding: 4px; text-align: center;">{html.escape(m)}</th>')
    lines.append('</tr>')

    # Data rows
    for i, m1 in enumerate(models):
        lines.append(f'<tr><th style="border: 1px solid #ddd; padding: 4px; text-align: right;">{html.escape(m1)}</th>')
        for j, m2 in enumerate(models):
            if i == j:
                cell_content = "—"
                bg = "#f9f9f9"
            elif i < j:
                key = f"{m1}|{m2}"
                delta = agreement.get(key, None)
                if delta is not None:
                    cell_content = f"{delta:.3f}"
                    # Scale alpha by delta (0-1 range, max around 0.5)
                    alpha = min(delta / 0.5, 1.0)
                    bg = f"rgba(200, 0, 0, {alpha * 0.5})"
                else:
                    cell_content = "—"
                    bg = "#f9f9f9"
            else:
                key = f"{m2}|{m1}"
                delta = agreement.get(key, None)
                if delta is not None:
                    cell_content = f"{delta:.3f}"
                    alpha = min(delta / 0.5, 1.0)
                    bg = f"rgba(200, 0, 0, {alpha * 0.5})"
                else:
                    cell_content = "—"
                    bg = "#f9f9f9"

            lines.append(f'<td style="border: 1px solid #ddd; padding: 4px; text-align: center; background: {bg};">{cell_content}</td>')
        lines.append('</tr>')

    lines.append('</table>')
    return "\n".join(lines)


def _summary_table(metrics: dict) -> str:
    """Generate summary table with one row per model."""
    models_data = metrics.get("models", {})
    fixtures = metrics.get("fixtures", {})
    isolation = metrics.get("isolation", {})
    agreement = metrics.get("agreement", {})

    if not models_data:
        return '<div style="color: #999; font-style: italic;">No model data</div>'

    models = sorted(models_data.keys())

    lines = ['<table style="border-collapse: collapse; font-size: 12px; width: 100%;">']

    # Header row
    headers = ["Model", "Boundary Mean", "Boundary Median", "Boundary P95", "Boundary Max",
               "RTF", "Peak RSS MB", "Cost USD", "Found", "Matched", "Extra", "Median Δ", "Coverage"]
    lines.append('<tr style="background: #f0f0f0;">')
    for h in headers:
        lines.append(f'<th style="border: 1px solid #ccc; padding: 6px; text-align: left;">{h}</th>')
    lines.append('</tr>')

    # Data rows
    for model in models:
        data = models_data[model]
        boundary = data.get("boundary", {})

        cells = [html.escape(model)]

        # Boundary stats
        for key in ["mean", "median", "p95", "max"]:
            val = boundary.get(key)
            cells.append(f"{val:.3f}" if val is not None else "—")

        # RTF
        rtf = data.get("rtf")
        cells.append(f"{rtf:.3f}" if rtf is not None else "—")

        # Peak RSS
        peak_rss = data.get("peak_rss_mb")
        cells.append(f"{peak_rss:.1f}" if peak_rss is not None else "—")

        # Cost
        cost = data.get("cost_usd")
        cells.append(f"{cost:.3f}" if cost is not None else "—")

        # Detection counts
        detection = data.get("detection", {})
        cells.append(str(detection.get("found", 0)))
        cells.append(str(detection.get("matched", 0)))
        cells.append(str(detection.get("extra", 0)))

        # Median delta (pairwise)
        deltas = [agreement[key] for key in agreement if model in key]
        cells.append(f"{statistics.median(deltas):.3f}" if deltas else "—")

        # Coverage
        coverage = data.get("coverage", "—")
        cells.append(coverage)

        lines.append('<tr>')
        for i, cell in enumerate(cells):
            lines.append(f'<td style="border: 1px solid #ccc; padding: 6px;">{cell}</td>')
        lines.append('</tr>')

    lines.append('</table>')
    return "\n".join(lines)


def render(metrics: dict) -> str:
    """Render metrics as self-contained HTML report."""
    models_data = metrics.get("models", {})
    fixtures = metrics.get("fixtures", {})
    isolation = metrics.get("isolation", {})
    agreement = metrics.get("agreement", {})
    draft_truth = metrics.get("draft_truth", [])
    skips = metrics.get("skips", [])
    silence = metrics.get("silence", {})

    models = sorted(models_data.keys())
    fixture_ids = sorted(fixtures.keys())

    lines = [
        '<!doctype html>',
        '<html>',
        '<head>',
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<title>ASR Benchmark Report</title>',
        '<style>',
        'body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; '
        'margin: 20px; background: #fafafa; color: #333; }',
        'h1 { border-bottom: 2px solid #333; padding-bottom: 10px; }',
        'h2 { margin-top: 30px; border-left: 4px solid #3498db; padding-left: 10px; }',
        'table { border-collapse: collapse; margin: 10px 0; }',
        'td, th { border: 1px solid #ccc; padding: 8px; text-align: left; }',
        'th { background: #f0f0f0; }',
        '.best { background: #d7f5d7; }',
        'pre { background: #f5f5f5; padding: 10px; overflow-x: auto; border: 1px solid #ddd; }',
        'details { margin: 10px 0; }',
        'summary { cursor: pointer; padding: 8px; background: #f9f9f9; border: 1px solid #ddd; }',
        'summary:hover { background: #f0f0f0; }',
        '.warning { color: #e74c3c; font-weight: bold; }',
        '.muted { color: #999; }',
        '</style>',
        '</head>',
        '<body>',
        '<h1>ASR Benchmark Report</h1>',
    ]

    # Section 1: Summary table
    lines.append('<h2>Summary</h2>')
    lines.append(_summary_table(metrics))

    # Section 2: Per-fixture timelines
    lines.append('<h2>Per-Fixture Timelines</h2>')
    for fixture_id in fixture_ids:
        fixture_data = fixtures[fixture_id]
        lines.append(f'<h3>{html.escape(fixture_id)}</h3>')
        lines.append(_svg_timeline(fixture_id, fixture_data, models))

    # Section 3: Boundary error distribution (for models with gap data)
    lines.append('<h2>Boundary Error Distribution</h2>')
    has_gaps = False
    for fixture_id in fixture_ids:
        gap_stats = fixtures[fixture_id].get("gap_stats", {})
        if gap_stats:
            has_gaps = True
            lines.append(f'<h3>{html.escape(fixture_id)} (Beep Fixture)</h3>')
            for model in models:
                if model in gap_stats:
                    lines.append(f'<div><strong>{html.escape(model)}:</strong></div>')
                    stats = gap_stats[model]
                    errors = [abs(e) for e in (stats.get("_errors", []) if "_errors" in stats else [])]
                    if not errors:
                        # Reconstruct errors if not present (simplified: use median)
                        errors = []
                    lines.append(_svg_strip_gaps(errors))
    if not has_gaps:
        lines.append('<div class="muted">No beep fixtures with gap data</div>')

    # Section 4: Isolation separation (F02)
    lines.append('<h2>Isolation Separation (F02)</h2>')
    if isolation:
        for model in models:
            if model in isolation:
                iso_data = isolation[model]
                lines.append(f'<div><strong>{html.escape(model)}:</strong></div>')
                real = iso_data.get("real", [])
                bait = iso_data.get("bait", [])
                threshold = iso_data.get("threshold", 0)
                lines.append(_svg_strip_isolation(real, bait, threshold))
    else:
        lines.append('<div class="muted">No isolation data</div>')

    # Section 5: Agreement heatmap
    lines.append('<h2>Agreement Heatmap</h2>')
    lines.append(_svg_heatmap(agreement, models))

    # Section 6: Per-fixture detail tables
    lines.append('<h2>Per-Fixture Details</h2>')
    for fixture_id in fixture_ids:
        fixture_data = fixtures[fixture_id]
        detections_by_model = fixture_data.get("models", {})

        lines.append(f'<details>')
        lines.append(f'<summary>{html.escape(fixture_id)} ({len(detections_by_model)} models)</summary>')
        lines.append('<table style="border-collapse: collapse; font-size: 11px; width: 100%;">')
        lines.append('<tr style="background: #f0f0f0;">')
        lines.append('<th style="border: 1px solid #ccc; padding: 4px;">Model</th>')
        lines.append('<th style="border: 1px solid #ccc; padding: 4px;">Raw</th>')
        lines.append('<th style="border: 1px solid #ccc; padding: 4px;">Canonical</th>')
        lines.append('<th style="border: 1px solid #ccc; padding: 4px;">Start</th>')
        lines.append('<th style="border: 1px solid #ccc; padding: 4px;">End</th>')
        lines.append('<th style="border: 1px solid #ccc; padding: 4px;">Isolation</th>')
        lines.append('<th style="border: 1px solid #ccc; padding: 4px;">Consensus</th>')
        lines.append('</tr>')

        for model in models:
            if model in detections_by_model:
                dets = detections_by_model[model].get("detections", [])
                for det in dets:
                    lines.append('<tr>')
                    lines.append(f'<td style="border: 1px solid #ccc; padding: 4px;">{html.escape(model)}</td>')
                    lines.append(f'<td style="border: 1px solid #ccc; padding: 4px;">{html.escape(det.get("raw", "?"))}</td>')
                    lines.append(f'<td style="border: 1px solid #ccc; padding: 4px;">{html.escape(det.get("canonical", "?"))}</td>')
                    lines.append(f'<td style="border: 1px solid #ccc; padding: 4px;">{det.get("start", 0):.1f}</td>')
                    lines.append(f'<td style="border: 1px solid #ccc; padding: 4px;">{det.get("end", 0):.1f}</td>')
                    lines.append(f'<td style="border: 1px solid #ccc; padding: 4px;">{det.get("isolation", 0):.2f}</td>')
                    lines.append(f'<td style="border: 1px solid #ccc; padding: 4px;">{"✓" if det.get("consensus") else "✗"}</td>')
                    lines.append('</tr>')

        lines.append('</table>')
        lines.append('</details>')

    # Section 7: Draft ground truth
    lines.append('<h2>Draft ground truth</h2>')
    if draft_truth:
        csv_lines = ["fixture_id,draft_expected_calls,disagreements"]
        for row in draft_truth:
            fixture_id = html.escape(row.get("fixture_id", ""))
            calls = html.escape(row.get("draft_expected_calls", ""))
            disagree = html.escape(row.get("disagreements", ""))
            csv_lines.append(f'{fixture_id},{calls},{disagree}')

            # Highlight disagreements
            if disagree:
                csv_lines.insert(len(csv_lines) - 1, f'⚠ {disagree}')

        lines.append('<pre>')
        lines.append(html.escape("\n".join(csv_lines)))
        lines.append('</pre>')
    else:
        lines.append('<div class="muted">No draft truth data</div>')

    # Section 8: Footer
    lines.append('<h2>Metadata</h2>')

    # Skips
    if skips:
        lines.append('<h3>Skips</h3>')
        lines.append('<ul>')
        for skip in skips:
            model = html.escape(skip.get("model", "?"))
            fixture = html.escape(skip.get("fixture", "?"))
            reason = html.escape(skip.get("reason", "?"))
            lines.append(f'<li>{model} / {fixture}: {reason}</li>')
        lines.append('</ul>')

    # Silence metric
    if silence:
        status = silence.get("status", "")
        lines.append(f'<p class="muted">Silence metric: {html.escape(status)}</p>')

    # Timestamp
    timestamp = datetime.now().isoformat()
    lines.append(f'<p class="muted">Generated: {timestamp}</p>')

    lines.append('</body>')
    lines.append('</html>')

    return "\n".join(lines)


def main() -> None:
    """Read metrics.json and write report.html."""
    metrics_file = OUT / "metrics.json"
    if not metrics_file.exists():
        print(f"Error: {metrics_file} not found")
        return

    metrics = json.loads(metrics_file.read_text())
    html_content = render(metrics)

    OUT.mkdir(parents=True, exist_ok=True)
    report_file = OUT / "report.html"
    report_file.write_text(html_content)
    print(f"Report written to {report_file}")


if __name__ == "__main__":
    main()
