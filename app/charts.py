"""Reusable server-rendered inline-SVG charts (no JS, no CDN)."""
from __future__ import annotations

import html
import math

INDIGO = "#1B365D"
SAFFRON = "#E8873A"
PALETTE = ["#1B365D", "#E8873A", "#2e7d32", "#8e44ad", "#c0392b", "#16a085",
           "#2980b9", "#d35400", "#7f8c8d", "#27ae60", "#b3261e"]


def hbar(pairs, *, width=460, bar_h=20, color=INDIGO, maxv=None, label_w=140, value_fmt="{:.3f}"):
    pairs = list(pairs)
    if not pairs:
        return "<svg width='10' height='10'></svg>"
    maxv = maxv or max((v for _, v in pairs), default=1.0) or 1.0
    gap, pad = 6, 56
    height = len(pairs) * (bar_h + gap) + 8
    plot_w = width - label_w - pad
    parts = [f"<svg width='{width}' height='{height}' font-family='sans-serif' font-size='12'>"]
    for i, (label, value) in enumerate(pairs):
        y = i * (bar_h + gap) + 4
        w = max(1, int(plot_w * (value / maxv)))
        parts.append(f"<text x='0' y='{y + bar_h - 5}' fill='#333'>{html.escape(str(label))}</text>")
        parts.append(f"<rect x='{label_w}' y='{y}' width='{w}' height='{bar_h}' fill='{color}' rx='3'/>")
        parts.append(f"<text x='{label_w + w + 5}' y='{y + bar_h - 5}' fill='#556'>{value_fmt.format(value)}</text>")
    parts.append("</svg>")
    return "".join(parts)


def threshold_hbar(pairs, threshold, *, width=460, bar_h=20, color=INDIGO, maxv=1.0):
    """Horizontal bars with a vertical threshold line (for the fused chart)."""
    pairs = list(pairs)
    label_w, pad, gap = 140, 56, 6
    height = len(pairs) * (bar_h + gap) + 8
    plot_w = width - label_w - pad
    tx = label_w + int(plot_w * (threshold / maxv))
    parts = [f"<svg width='{width}' height='{height}' font-family='sans-serif' font-size='12'>"]
    for i, (label, value) in enumerate(pairs):
        y = i * (bar_h + gap) + 4
        w = max(1, int(plot_w * (value / maxv)))
        c = SAFFRON if value >= threshold else color
        parts.append(f"<text x='0' y='{y + bar_h - 5}' fill='#333'>{html.escape(str(label))}</text>")
        parts.append(f"<rect x='{label_w}' y='{y}' width='{w}' height='{bar_h}' fill='{c}' rx='3'/>")
        parts.append(f"<text x='{label_w + w + 5}' y='{y + bar_h - 5}' fill='#556'>{value:.3f}</text>")
    parts.append(f"<line x1='{tx}' y1='0' x2='{tx}' y2='{height}' stroke='#b3261e' stroke-width='2' stroke-dasharray='4 3'/>")
    parts.append(f"<text x='{tx + 3}' y='12' fill='#b3261e' font-size='10'>thr {threshold:.2f}</text>")
    parts.append("</svg>")
    return "".join(parts)


def donut(pairs, *, size=180, thickness=34):
    pairs = [(k, v) for k, v in pairs if v > 0]
    total = sum(v for _, v in pairs) or 1
    r = size / 2
    inner = r - thickness
    cx = cy = r
    parts = [f"<svg width='{size + 150}' height='{size}' font-family='sans-serif' font-size='12'>"]
    angle = -math.pi / 2
    for i, (label, value) in enumerate(pairs):
        frac = value / total
        end = angle + frac * 2 * math.pi
        large = 1 if frac > 0.5 else 0
        x1, y1 = cx + r * math.cos(angle), cy + r * math.sin(angle)
        x2, y2 = cx + r * math.cos(end), cy + r * math.sin(end)
        color = PALETTE[i % len(PALETTE)]
        parts.append(
            f"<path d='M {cx} {cy} L {x1:.2f} {y1:.2f} A {r} {r} 0 {large} 1 {x2:.2f} {y2:.2f} Z' fill='{color}'/>"
        )
        angle = end
    parts.append(f"<circle cx='{cx}' cy='{cy}' r='{inner}' fill='#fff'/>")
    parts.append(f"<text x='{cx}' y='{cy}' text-anchor='middle' dy='4' font-size='16' fill='{INDIGO}'>{total}</text>")
    ly = 14
    for i, (label, value) in enumerate(pairs):
        color = PALETTE[i % len(PALETTE)]
        parts.append(f"<rect x='{size + 6}' y='{ly - 10}' width='11' height='11' fill='{color}' rx='2'/>")
        parts.append(f"<text x='{size + 22}' y='{ly}' fill='#333'>{html.escape(str(label))} ({value})</text>")
        ly += 18
    parts.append("</svg>")
    return "".join(parts)


def line(points, *, width=560, height=160, color=SAFFRON, label=""):
    points = list(points)
    if not points:
        return "<svg width='10' height='10'></svg>"
    maxv = max((v for _, v in points), default=1) or 1
    pad_l, pad_b, pad_t = 30, 20, 10
    plot_w = width - pad_l - 10
    plot_h = height - pad_b - pad_t
    n = len(points)
    step = plot_w / max(1, n - 1)
    coords = []
    for i, (_x, v) in enumerate(points):
        px = pad_l + i * step
        py = pad_t + plot_h * (1 - v / maxv)
        coords.append((px, py))
    path = " ".join(f"{'M' if i == 0 else 'L'} {x:.1f} {y:.1f}" for i, (x, y) in enumerate(coords))
    parts = [f"<svg width='{width}' height='{height}' font-family='sans-serif' font-size='10'>"]
    parts.append(f"<line x1='{pad_l}' y1='{pad_t + plot_h}' x2='{width - 10}' y2='{pad_t + plot_h}' stroke='#dce0e6'/>")
    parts.append(f"<path d='{path}' fill='none' stroke='{color}' stroke-width='2'/>")
    for x, y in coords:
        parts.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='2' fill='{color}'/>")
    parts.append(f"<text x='{pad_l}' y='{pad_t - 0}' fill='#556'>max {maxv}</text>")
    parts.append("</svg>")
    return "".join(parts)


def highlight_keywords(text: str, hits: list[dict], dept_colors: dict[str, str]) -> str:
    """Return HTML with matched keyword spans highlighted by department colour.

    Offsets are into the folded matching text stored on the trace.
    """
    if not text:
        return ""
    spans = sorted([h for h in hits if h.get("start") is not None], key=lambda h: h["start"])
    out = []
    cursor = 0
    for h in spans:
        s, e = h["start"], h["end"]
        if s < cursor or s > len(text):
            continue
        out.append(html.escape(text[cursor:s]))
        color = dept_colors.get(h["department_code"], SAFFRON)
        title = f"{h['term']} → {h['department_code']} (w={h.get('weight',1)}, tok={h.get('token_count',1)})"
        out.append(
            f"<mark class='kw' style='background:{color}33;border-bottom:2px solid {color}' "
            f"title='{html.escape(title)}'>{html.escape(text[s:e])}</mark>"
        )
        cursor = e
    out.append(html.escape(text[cursor:]))
    return "".join(out)
