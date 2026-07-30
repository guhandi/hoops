"""Curated showcase dashboard: the model-selection story for a portfolio audience.

Unlike `benchmarks/report.py` (a full dump of every metric for every fixture,
meant for the person doing the work), this page is a *curated* narrative for
someone skimming once: the decision, the evidence for it, and the gates that
back it up. It consumes the same `benchmarks/out/metrics.json` schema as
report.py (see that module's docstring for the real shape) for the live model
comparison table, but the gate table and disqualifier evidence are NOT
recomputed from metrics.json — `hoops score` reads a different input
(fixtures/manifest.csv labels) that this module has no access to, and the
disqualifier quotes are curated prose, not a mechanical transform of a data
file. Both are hardcoded snapshots below, dated and sourced, per the
2026-07-30 packaging-golden-dataset plan's Evidence reference.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

from benchmarks.report import _esc

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "benchmarks" / "out"
SHOWCASE_DIR = REPO / "docs" / "showcase"

# Snapshot date for the hardcoded constants below — these are NOT derived from
# metrics.json at render time; they come from `uv run hoops score` against the
# 10 labeled fixtures as of this date. Re-run `hoops score` and update by hand
# if the labeled dataset changes.
SNAPSHOT_DATE = "2026-07-30"

# Gate table (source: `uv run hoops score`, 10 labeled fixtures, snapshot 2026-07-30).
# Each row: (metric, value, verdict, gate).
GATES = [
    ("recall", "0.565", "FAIL", "0.99"),
    ("precision", "1.000", "PASS", "0.99"),
    ("classification", "1.000", "PASS", "0.98"),
    ("exact_fraction", "0.000", "FAIL", "0.9"),
    ("gap_mae", "n/a", "PASS", "0.5"),
    ("phantom_on_traps", "0", "PASS", "0 (hard)"),
    ("invariant_mismatches", "1", "FAIL", "0 (hard)"),
]

# Disqualifier evidence (source: benchmarks/out/transcripts/*, benchmarks/out/skips.json,
# snapshot 2026-07-30). Each: (model, one-line verdict, verbatim quote/number, source path).
DISQUALIFIERS = [
    (
        "mlx-whisper",
        "Hallucination loop on quiet audio",
        '"make. make. make. make. make. make. make. make. make. make. make. make. '
        'make. make. make. I guess I\'ll stop there." (15 phantom makes; whisper-1\'s '
        "transcript of the same audio has no loop)",
        "benchmarks/out/transcripts/mlx-whisper/D02.json",
    ),
    (
        "parakeet-mlx",
        "Quiet-audio collapse",
        '"This make this" — full transcript text (whisper-1 heard 10 calls on the same audio)',
        "benchmarks/out/transcripts/parakeet-mlx/R02.json",
    ),
    (
        "whisperx",
        "Forced alignment silently drops words",
        "27 detections total vs 122-184 for peers; 0 detections on R02, D02, F02",
        "benchmarks/out/metrics.json (models.whisperx)",
    ),
    (
        "faster-whisper",
        "Impractical latency for a morning loop",
        "381 s to transcribe 33.6 s of audio (F08); RTF ≈ 11 including model load",
        "benchmarks/out/metrics.json (models['faster-whisper'])",
    ),
]

DECISION_TEXT = "Stay on whisper-1."
DECISION_SOURCE = "docs/decisions/001-transcriber-selection.md"

_MODEL_COLUMNS = [
    ("RTF Median", "rtf_median", 3),
    ("Peak RSS Max (MB)", "peak_rss_max", 1),
    ("Cost ($)", "cost_usd", 3),
    ("Found", "detections_found", 0),
    ("Matched", "detections_matched", 0),
    ("Extra", "detections_extra", 0),
]


def _fmt(val, prec) -> str:
    if val is None:
        return "—"
    if prec == 0:
        return str(int(val))
    return f"{val:.{prec}f}"


def _model_table(metrics: dict) -> str:
    models_data = metrics.get("models", {})
    models = sorted(models_data.keys())
    if not models:
        return '<p class="muted">No model data.</p>'
    lines = ['<table class="models">',
             "<tr><th>Model</th>" + "".join(f"<th>{_esc(h)}</th>" for h, _, _ in _MODEL_COLUMNS) + "</tr>"]
    for model in models:
        data = models_data[model]
        cells = [f"<td>{_esc(model)}</td>"]
        for _, key, prec in _MODEL_COLUMNS:
            cells.append(f"<td>{_esc(_fmt(data.get(key), prec))}</td>")
        lines.append("<tr>" + "".join(cells) + "</tr>")
    lines.append("</table>")
    return "\n".join(lines)


def _disqualifier_cards() -> str:
    cards = []
    for model, verdict, quote, source in DISQUALIFIERS:
        cards.append(
            '<div class="card">'
            f"<h3>{_esc(model)}</h3>"
            f'<p class="verdict">{_esc(verdict)}</p>'
            f"<blockquote>{_esc(quote)}</blockquote>"
            f'<p class="source">{_esc(source)}</p>'
            "</div>"
        )
    return "\n".join(cards)


def _gate_table() -> str:
    lines = ['<table class="gates">',
             "<tr><th>Gate</th><th>Value</th><th>Verdict</th><th>Threshold</th></tr>"]
    for metric, value, verdict, gate in GATES:
        cls = "pass" if verdict == "PASS" else "fail"
        lines.append(
            "<tr>"
            f"<td>{_esc(metric)}</td>"
            f"<td>{_esc(value)}</td>"
            f'<td class="{cls}">{_esc(verdict)}</td>'
            f"<td>{_esc(gate)}</td>"
            "</tr>"
        )
    lines.append("</table>")
    return "\n".join(lines)


def _loop_svg() -> str:
    """Hand-written inline SVG: record -> label -> gate -> build -> score -> improve,
    six rounded rects joined by arrows, wrapping into two rows of three."""
    steps = ["record", "label", "gate", "build", "score", "improve"]
    box_w, box_h, gap = 130, 46, 30
    row_h = box_h + 70
    width = box_w * 3 + gap * 2 + 20
    height = row_h * 2 + 20

    parts = [f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
             'xmlns="http://www.w3.org/2000/svg">',
             '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" '
             'orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#8a8378"/></marker></defs>']

    positions = []
    for i, step in enumerate(steps):
        row, col = divmod(i, 3)
        x = 10 + col * (box_w + gap)
        y = 10 + row * row_h
        positions.append((x, y))
        parts.append(
            f'<rect x="{x}" y="{y}" width="{box_w}" height="{box_h}" rx="10" '
            'fill="#f4f1ec" stroke="#8a8378" stroke-width="1.5"/>'
        )
        parts.append(
            f'<text x="{x + box_w / 2}" y="{y + box_h / 2 + 5}" font-size="14" '
            'text-anchor="middle" fill="#3a362f">' + _esc(step) + "</text>"
        )

    # Arrows: 0->1, 1->2 (row 1); 2->3 (wrap down); 3->4, 4->5 (row 2); 5->0 (loop back, improve->record)
    for a, b in [(0, 1), (1, 2)]:
        (x1, y1), (x2, y2) = positions[a], positions[b]
        y = y1 + box_h / 2
        parts.append(f'<line x1="{x1 + box_w}" y1="{y}" x2="{x2 - 6}" y2="{y}" '
                      'stroke="#8a8378" stroke-width="1.5" marker-end="url(#arrow)"/>')
    # 2 (gate) -> 3 (build): wraps to next row, curve down and left
    (x2, y2), (x3, y3) = positions[2], positions[3]
    mx, my = x2 + box_w / 2, y2 + box_h + 30
    parts.append(f'<path d="M{x2 + box_w / 2},{y2 + box_h} C {mx},{my} {x3 + box_w / 2},{my} '
                 f'{x3 + box_w / 2},{y3 - 6}" fill="none" stroke="#8a8378" stroke-width="1.5" '
                 'marker-end="url(#arrow)"/>')
    for a, b in [(3, 4), (4, 5)]:
        (x1, y1), (x2, y2) = positions[a], positions[b]
        y = y1 + box_h / 2
        parts.append(f'<line x1="{x1 + box_w}" y1="{y}" x2="{x2 - 6}" y2="{y}" '
                      'stroke="#8a8378" stroke-width="1.5" marker-end="url(#arrow)"/>')
    # 5 (improve) -> 0 (record): loop back, curve above both rows
    (x5, y5), (x0, y0) = positions[5], positions[0]
    parts.append(
        f'<path d="M{x5 + box_w / 2},{y5} C {x5 + box_w / 2},{y5 - 40} '
        f'{x0 + box_w / 2},{y0 - 40} {x0 + box_w / 2},{y0 - 6}" '
        'fill="none" stroke="#b0a89a" stroke-width="1.5" stroke-dasharray="4,3" '
        'marker-end="url(#arrow)"/>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


_STYLE = """
:root { color-scheme: light dark; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  margin: 0; padding: 48px 24px 80px; background: #fbfaf8; color: #2b2925;
  line-height: 1.55;
}
.page { max-width: 880px; margin: 0 auto; }
h1 { font-size: 1.9rem; font-weight: 600; margin: 0 0 8px; letter-spacing: -0.01em; }
h2 { font-size: 1.2rem; font-weight: 600; margin: 56px 0 16px; color: #2b2925;
     border-top: 1px solid #e4e0d8; padding-top: 32px; }
h3 { font-size: 1rem; font-weight: 600; margin: 0 0 6px; }
.subtitle { color: #6b6659; font-size: 1rem; margin: 0 0 40px; }
.banner {
  background: #f4f1ec; border: 1px solid #e4e0d8; border-radius: 12px;
  padding: 24px 28px; margin-bottom: 8px;
}
.banner .decision { font-size: 1.15rem; font-weight: 600; margin: 0 0 6px; }
.banner .source { color: #6b6659; font-size: 0.85rem; margin: 0; }
table { border-collapse: collapse; width: 100%; font-size: 0.88rem; margin: 12px 0; }
th, td { text-align: left; padding: 9px 14px; border-bottom: 1px solid #e4e0d8; }
th { color: #6b6659; font-weight: 600; font-size: 0.78rem; text-transform: uppercase;
     letter-spacing: 0.03em; }
td.pass { color: #3d7a4f; font-weight: 600; }
td.fail { color: #ad3d33; font-weight: 600; }
.cards { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; margin-top: 16px; }
.card { background: #f4f1ec; border: 1px solid #e4e0d8; border-radius: 10px; padding: 18px 20px; }
.card .verdict { color: #6b6659; font-size: 0.85rem; margin: 0 0 10px; }
.card blockquote { margin: 0 0 10px; padding-left: 12px; border-left: 3px solid #b0a89a;
                    font-style: italic; font-size: 0.9rem; color: #3a362f; }
.card .source { font-size: 0.75rem; color: #93897a; margin: 0; font-family: ui-monospace,
                SFMono-Regular, Menlo, monospace; }
.loop-wrap { display: flex; justify-content: center; margin-top: 12px; }
.muted { color: #93897a; font-size: 0.85rem; }
footer { margin-top: 64px; padding-top: 24px; border-top: 1px solid #e4e0d8;
         color: #6b6659; font-size: 0.85rem; }
footer a { color: #3a362f; }
a { color: #3a362f; }
@media (max-width: 640px) { .cards { grid-template-columns: 1fr; } }
@media (prefers-color-scheme: dark) {
  body { background: #1c1a17; color: #e8e4da; }
  h2 { border-top-color: #38352d; }
  .subtitle, .muted, footer { color: #a39a89; }
  .banner, .card { background: #262319; border-color: #38352d; }
  .banner .source, .card .source { color: #8f8672; }
  th { color: #a39a89; }
  th, td { border-bottom-color: #38352d; }
  td.pass { color: #6fbf82; }
  td.fail { color: #e0685c; }
  a, footer a { color: #e8e4da; }
}
"""


def render_showcase(metrics: dict) -> str:
    """Render the curated showcase dashboard for the whisper-1 model-selection
    decision. Takes only `metrics` (benchmarks/out/metrics.json schema) — the
    decision, gate, and disqualifier text live in this module's constants."""
    parts = [
        "<!doctype html>", "<html>", "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Model Selection: whisper-1</title>",
        f"<style>{_STYLE}</style>",
        "</head>", "<body>",
        '<div class="page">',
        "<h1>Picking an ASR model for a morning free-throw voice log</h1>",
        '<p class="subtitle">An empirical model-selection case study &mdash; '
        f"golden-dataset evidence, snapshot {_esc(SNAPSHOT_DATE)}.</p>",
    ]

    # 1. Headline decision banner
    parts.append(
        '<div class="banner">'
        f'<p class="decision">Decision: {_esc(DECISION_TEXT)}</p>'
        f'<p class="source">Full rationale: {_esc(DECISION_SOURCE)}</p>'
        "</div>"
    )

    # 2. Model comparison table
    parts.append("<h2>Model comparison</h2>")
    parts.append(_model_table(metrics))

    # 3. Disqualifier evidence cards
    parts.append("<h2>Why the alternatives were disqualified</h2>")
    parts.append('<div class="cards">')
    parts.append(_disqualifier_cards())
    parts.append("</div>")

    # 4. Gate table
    parts.append("<h2>Gate results</h2>")
    parts.append(
        '<p class="muted">Source: <code>uv run hoops score</code> against the 10 labeled '
        f"fixtures, snapshot {_esc(SNAPSHOT_DATE)}. Precision and phantom-on-traps are the "
        "load-bearing passes for this domain (a phantom shot is a hard failure; a missed "
        "shot is a tuning problem).</p>"
    )
    parts.append(_gate_table())

    # 5. The loop diagram
    parts.append("<h2>The loop</h2>")
    parts.append('<div class="loop-wrap">')
    parts.append(_loop_svg())
    parts.append("</div>")

    # 6. Footer
    parts.append(
        "<footer>"
        '<p><a href="../decisions/001-transcriber-selection.md">Decision record</a> &nbsp;&middot;&nbsp; '
        '<a href="../methodology.md">Methodology</a></p>'
        "</footer>"
    )

    parts.append("</div>")
    parts.append("</body></html>")
    return "\n".join(parts)


def main() -> None:
    metrics_file = OUT / "metrics.json"
    if not metrics_file.exists():
        sys.exit(
            f"Error: {metrics_file} not found. Run `uv run python -m benchmarks.analyze` first."
        )

    metrics = json.loads(metrics_file.read_text())
    html_content = render_showcase(metrics)

    SHOWCASE_DIR.mkdir(parents=True, exist_ok=True)
    out_file = SHOWCASE_DIR / "model-selection.html"
    out_file.write_text(html_content)
    print(f"Showcase written to {out_file}")


if __name__ == "__main__":
    main()
