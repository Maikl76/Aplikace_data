"""
Grafy do zprávy jako statické SVG.

Karta sportovce kreslí grafy v prohlížeči (plotly.js). Zpráva ale musí
vypadat stejně na obrazovce, na papíře i v PDF – a WeasyPrint JavaScript
nespouští. Proto se tu grafy skládají přímo jako SVG na serveru.

Pravidla jsou stejná jako u grafů na kartě (apps.analytics.charts): stejná
paleta, osa pokrývá aspoň trojnásobek MDC, norma je šedé pásmo za čarou,
číslo jen u krajních bodů, překročení prahu hlásí i text, ne jen barva.
Najetí myší na bod ukáže hodnotu (element <title>).
"""

import math

from django.utils.html import escape
from django.utils.safestring import mark_safe

from apps.analytics.charts import PALETTE, STATUS_WARNING, _trend_subtitle, _y_range, cz

C = PALETTE["light"]
FONT = 'system-ui, -apple-system, &quot;Segoe UI&quot;, sans-serif'


def nice_ticks(low: float, high: float, count: int = 4) -> list[float]:
    """Kulaté hodnoty na ose (1, 2, 2,5, 5 × 10^n)."""
    span = high - low
    if span <= 0:
        return [low]
    raw = span / count
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    start = math.ceil(low / step) * step
    ticks = []
    value = start
    while value <= high + step * 1e-9:
        ticks.append(round(value, 10))
        value += step
    return ticks


def _tick_decimals(ticks: list[float]) -> int:
    for d in range(0, 4):
        if all(abs(t * 10**d - round(t * 10**d)) < 1e-6 for t in ticks):
            return d
    return 3


def _text(x, y, content, *, size=11, color=None, anchor="start", weight="normal") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{color or C["muted"]}" '
            f'text-anchor="{anchor}" font-weight="{weight}">{escape(content)}</text>')


def trend_svg(metric, points, *, norm=None) -> str:
    """Vývoj jedné metriky v čase; poslední bod je měření, o kterém je zpráva."""
    width, height = 340, 180
    left, right, top, bottom = 46, 16, 20, 28
    plot_w, plot_h = width - left - right, height - top - bottom

    values = [v for _, v in points]
    low, high = _y_range(metric, values, norm) or [min(values) - 1, max(values) + 1]

    first, last = points[0][0], points[-1][0]
    days = max((last - first).days, 1)

    def x(day):
        return left + (day - first).days / days * plot_w

    def y(value):
        return top + (high - value) / (high - low) * plot_h

    parts = [f'<rect x="0" y="0" width="{width}" height="{height}" fill="{C["surface"]}"/>']

    # mřížka a popisky osy y
    ticks = [t for t in nice_ticks(low, high) if low <= t <= high]
    decimals = _tick_decimals(ticks)
    for t in ticks:
        parts.append(f'<line x1="{left}" x2="{width - right}" y1="{y(t):.1f}" y2="{y(t):.1f}" '
                     f'stroke="{C["grid"]}" stroke-width="1"/>')
        parts.append(_text(left - 6, y(t) + 4, cz(t, decimals), size=10, anchor="end"))

    # norma: pásmo průměr ± SD a tečkovaný průměr – kontext, ne série
    if norm is not None and norm.mean is not None and norm.sd:
        band_top = y(min(norm.mean + norm.sd, high))
        band_bottom = y(max(norm.mean - norm.sd, low))
        parts.append(f'<rect x="{left}" y="{band_top:.1f}" width="{plot_w}" '
                     f'height="{band_bottom - band_top:.1f}" fill="{C["band"]}"/>')
        parts.append(f'<line x1="{left}" x2="{width - right}" y1="{y(norm.mean):.1f}" '
                     f'y2="{y(norm.mean):.1f}" stroke="{C["muted"]}" stroke-width="1" '
                     f'stroke-dasharray="2 3"/>')

    # osa x: data měření
    parts.append(f'<line x1="{left}" x2="{width - right}" y1="{top + plot_h}" '
                 f'y2="{top + plot_h}" stroke="{C["axis"]}" stroke-width="1"/>')
    shown = points if len(points) <= 5 else [points[0], points[-1]]
    for day, _ in shown:
        anchor = "start" if day == first and len(points) > 1 else \
                 "end" if day == last and len(points) > 1 else "middle"
        parts.append(_text(x(day), height - 8, day.strftime("%d.%m.%y"), size=10, anchor=anchor))

    # řada
    path = " ".join(f"{'M' if i == 0 else 'L'}{x(d):.1f},{y(v):.1f}"
                    for i, (d, v) in enumerate(points))
    parts.append(f'<path d="{path}" fill="none" stroke="{C["series_1"]}" stroke-width="2" '
                 f'stroke-linejoin="round" stroke-linecap="round"/>')
    unit = f" {metric.unit}" if metric.unit and metric.unit != "-" else ""
    for i, (d, v) in enumerate(points):
        is_last = i == len(points) - 1
        parts.append(
            f'<circle cx="{x(d):.1f}" cy="{y(v):.1f}" r="{5 if is_last else 4}" '
            f'fill="{C["series_1"]}" stroke="{C["surface"]}" stroke-width="2">'
            f'<title>{d.strftime("%d.%m.%Y")}: {escape(cz(v, metric.decimals))}{escape(unit)}'
            f'</title></circle>'
        )
        if i in (0, len(points) - 1):
            anchor = "start" if i == 0 else "end"
            parts.append(_text(x(d) + (4 if i == 0 else -4), y(v) - 9, cz(v, metric.decimals),
                               size=11, color=C["text_secondary"], anchor=anchor,
                               weight="600" if is_last else "normal"))

    return _svg(width, height, parts, label=f"Vývoj: {metric.name}")


def trend_caption(metric, points) -> str:
    return _trend_subtitle(metric, [v for _, v in points])


def asymmetry_svg(rows, *, threshold_pct: float) -> str:
    """
    Rozdíl stran v procentech – společná míra pro všechny metriky.
    Směr nese poloha vůči nule, barvou se hlásí jen překročení prahu.
    """
    label_w, width = 230, 680
    row_h, top, bottom = 34, 10, 40
    height = top + row_h * len(rows) + bottom
    plot_left, plot_right = label_w + 10, width - 50
    plot_w = plot_right - plot_left
    center = plot_left + plot_w / 2

    # tolerance nesmí zabrat celou šířku, jinak z ní není poznat pásmo
    reach = max(max(abs(r["index_pct"]) for r in rows) * 1.15, threshold_pct * 1.6)
    ticks = [t for t in nice_ticks(0, reach, 3) if t > 0]
    reach = max(reach, ticks[-1] if ticks else reach)

    def x(pct):
        return center + pct / reach * (plot_w / 2)

    plot_bottom = top + row_h * len(rows)
    parts = [f'<rect x="0" y="0" width="{width}" height="{height}" fill="{C["surface"]}"/>']

    # pásmo tolerance – co je uvnitř, není nález
    parts.append(f'<rect x="{x(-threshold_pct):.1f}" y="{top}" '
                 f'width="{x(threshold_pct) - x(-threshold_pct):.1f}" '
                 f'height="{plot_bottom - top}" fill="{C["band"]}"/>')
    for t in ticks:
        for sign in (-1, 1):
            parts.append(f'<line x1="{x(sign * t):.1f}" x2="{x(sign * t):.1f}" y1="{top}" '
                         f'y2="{plot_bottom}" stroke="{C["grid"]}" stroke-width="1"/>')
            parts.append(_text(x(sign * t), plot_bottom + 14, f"{cz(t, _tick_decimals(ticks))} %",
                               size=10, anchor="middle"))
    parts.append(f'<line x1="{center:.1f}" x2="{center:.1f}" y1="{top}" y2="{plot_bottom}" '
                 f'stroke="{C["axis"]}" stroke-width="1"/>')
    parts.append(_text(center - 8, height - 6, "← vyšší vpravo", size=10, anchor="end"))
    parts.append(_text(center + 8, height - 6, "vyšší vlevo →", size=10))

    for i, r in enumerate(rows):
        mid = top + row_h * i + row_h / 2
        pct = r["index_pct"]
        over = abs(pct) > threshold_pct
        color = STATUS_WARNING if over else C["series_1"]

        name = r["metric"].name
        parts.append(_text(label_w, mid - (2 if r["label"] else -4), name, size=11,
                           color=C["text_primary"], anchor="end"))
        if r["label"]:
            parts.append(_text(label_w, mid + 11, r["label"], size=10, anchor="end"))

        # sloupec: rovný u nuly, zaoblený na konci s hodnotou
        bar_h, radius = 12, 4
        x0, x1 = center, x(pct)
        length = abs(x1 - x0)
        rr = min(radius, length / 2)
        y0 = mid - bar_h / 2
        if pct >= 0:
            d = (f"M{x0:.1f},{y0:.1f} H{x1 - rr:.1f} Q{x1:.1f},{y0:.1f} {x1:.1f},{y0 + rr:.1f} "
                 f"V{y0 + bar_h - rr:.1f} Q{x1:.1f},{y0 + bar_h:.1f} {x1 - rr:.1f},{y0 + bar_h:.1f} "
                 f"H{x0:.1f} Z")
        else:
            d = (f"M{x0:.1f},{y0:.1f} H{x1 + rr:.1f} Q{x1:.1f},{y0:.1f} {x1:.1f},{y0 + rr:.1f} "
                 f"V{y0 + bar_h - rr:.1f} Q{x1:.1f},{y0 + bar_h:.1f} {x1 + rr:.1f},{y0 + bar_h:.1f} "
                 f"H{x0:.1f} Z")
        tooltip = (f"{name}{' · ' + r['label'] if r['label'] else ''}: levá {r['left_txt']}, "
                   f"pravá {r['right_txt']}, rozdíl {r['index_txt']} %")
        parts.append(f'<path d="{d}" fill="{color}"><title>{escape(tooltip)}</title></path>')

        value = f"{r['index_txt']} %" + (" ▲" if over else "")
        if pct >= 0:
            parts.append(_text(x1 + 6, mid + 4, value, size=11, color=C["text_secondary"]))
        else:
            parts.append(_text(x1 - 6, mid + 4, value, size=11, color=C["text_secondary"],
                               anchor="end"))

    return _svg(width, height, parts, label="Stranové rozdíly")


def _svg(width, height, parts, *, label) -> str:
    return mark_safe(
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="{escape(label)}" font-family="{FONT}" '
        f'xmlns="http://www.w3.org/2000/svg">' + "".join(parts) + "</svg>"
    )
