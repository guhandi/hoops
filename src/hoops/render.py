import html as _html
from dataclasses import dataclass
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

@dataclass(frozen=True)
class Narrative:
    headline: str
    recap: str
    quote: str
    quote_t_s: float | None

def render_strip(rows: list[dict], out_png: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 1.6), dpi=150)
    live = [r for r in rows if not r["voided"]]
    for r in rows:
        t = r["t_call_s"]
        if r["voided"]:
            ax.plot(t, 0, marker="x", color="#999999", markersize=9)
        elif r["result"] == "make":
            ax.plot(t, 0, marker="o", color="#1a7f37", markersize=11)
        else:
            ax.plot(t, 0, marker="o", markerfacecolor="white",
                    markeredgecolor="#c0392b", markeredgewidth=2, markersize=11)
    if len(live) >= 3 and all(r["result"] == "make" for r in live[-3:]):
        ax.plot([live[-3]["t_call_s"], live[-1]["t_call_s"]], [-0.35, -0.35],
                color="#1a7f37", linewidth=3, solid_capstyle="round")
    ax.set_ylim(-0.8, 0.8)
    ax.set_yticks([])
    ax.set_xlabel("seconds")
    for side in ["left", "top", "right"]:
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_png)
    plt.close(fig)

def _stat_cells(stats: dict) -> str:
    fg = stats.get("fg_pct")
    items = [("FG%", f"{fg:.0%}" if fg is not None else "—"),
             ("Make streak", stats.get("longest_make_streak", "—")),
             ("Miss streak", stats.get("longest_miss_streak", "—")),
             ("Length", f"{stats.get('session_len_s', 0):.0f}s"),
             ("Median gap", f"{stats['median_gap_s']:.1f}s" if stats.get("median_gap_s") else "—")]
    return "".join(f"<td style='padding:6px 14px;text-align:center'>"
                   f"<div style='font-size:20px;font-weight:700'>{v}</div>"
                   f"<div style='font-size:11px;color:#666'>{k}</div></td>" for k, v in items)

def render_report(stats, rows, narrative, flags, out_html: Path, img_src: str) -> None:
    e = _html.escape
    parts = [f"<div style='font-family:-apple-system,Helvetica,sans-serif;max-width:640px;margin:auto'>"]
    if narrative:
        parts.append(f"<h2 style='margin-bottom:4px'>{e(narrative.headline)}</h2>")
    parts.append(f"<div style='font-size:64px;font-weight:800;line-height:1'>{stats['shots_to_three']}"
                 f"<span style='font-size:16px;font-weight:400;color:#666'> shots to close it out</span></div>")
    parts.append(f"<img src='{img_src}' alt='shot strip' style='max-width:100%;margin:12px 0'>")
    parts.append(f"<table style='border-collapse:collapse'><tr>{_stat_cells(stats)}</tr></table>")
    if narrative:
        parts.append(f"<p>{e(narrative.recap)}</p>")
        q_t = f" <span style='color:#999'>@{narrative.quote_t_s:.0f}s</span>" if narrative.quote_t_s is not None else ""
        parts.append(f"<blockquote style='border-left:3px solid #ccc;margin:8px 0;padding:4px 12px;"
                     f"color:#444;'>{e(narrative.quote)}{q_t}</blockquote>")
    if stats.get("notes"):
        parts.append(f"<p><b>Note:</b> {e(stats['notes'])}</p>")
    if flags:
        lis = "".join(f"<li>{e(f)}</li>" for f in flags)
        parts.append(f"<div style='background:#fff3cd;border:1px solid #ffe69c;padding:8px 12px;"
                     f"border-radius:6px'><b>Flags</b><ul style='margin:4px 0'>{lis}</ul></div>")
    parts.append(f"<p style='color:#999;font-size:11px'>Session {stats['session_id']} · "
                 f"{stats['session_date_local']}</p></div>")
    out_html.write_text("\n".join(parts))

def render_gallery(entries: list[dict], out_html: Path) -> None:
    e = _html.escape
    rows_html = []
    for en in entries:
        match = en["expected"] == en["got"] if en["expected"] else None
        badge = ("<span style='color:#1a7f37'>match</span>" if match
                 else "<span style='color:#c0392b'>mismatch</span>" if match is False
                 else "<span style='color:#999'>unlabeled</span>")
        rows_html.append(
            f"<div style='border-bottom:1px solid #ddd;padding:16px 0'>"
            f"<h3>{e(en['name'])} — {badge}</h3>"
            f"<img src='{e(en['strip_rel'])}' style='max-width:100%'>"
            f"<div>expected: <code>{e(' '.join(en['expected']) or '—')}</code></div>"
            f"<div>got: <code>{e(' '.join(en['got']))}</code></div>"
            f"<div>{''.join('<div>⚠ ' + e(f) + '</div>' for f in en['flags'])}</div>"
            f"<div style='color:#666'>{e(en.get('note', ''))}</div></div>")
    out_html.write_text("<div style='font-family:-apple-system,sans-serif;max-width:800px;"
                        "margin:auto'><h1>Fixture gallery</h1>" + "\n".join(rows_html) + "</div>")
