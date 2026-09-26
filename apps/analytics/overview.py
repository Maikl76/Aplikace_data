"""
Přehled na kartě sportovce: hlavní čísla s trendem a minigrafem.

Jedna dlaždice = jedna klíčová metrika (u metrik se stranami přednostně
celek / obě strany). Stav změny se určuje stejně jako ve zprávě – proti
MDC – a vždy je napsaný slovy, ne jen barvou.
"""

from django.utils.safestring import mark_safe

from .charts import cz, qualifier_label
from .queries import primary_metric_series

VERDICTS = {
    # druh: (třída odznaku, ikona, text)
    "better": ("badge-good", "arrow-up", "zlepšení"),
    "worse": ("badge-warn", "arrow-down", "zhoršení"),
    "shift": ("badge-accent", "activity", "skutečný posun"),
    "noise": ("", "minus", "v pásmu chyby"),
    "unknown": ("", "minus", "bez MDC"),
}


def sparkline(values: list[float], *, width: int = 120, height: int = 36) -> str:
    """Minigraf vývoje. Barvu bere z CSS (třída .spark), takže sedí i v tmavém režimu."""
    if len(values) < 2:
        return ""
    low, high = min(values), max(values)
    span = (high - low) or abs(high) or 1
    pad = 5

    def x(i):
        return pad + i * (width - 2 * pad) / (len(values) - 1)

    def y(v):
        return height - pad - (v - low) / span * (height - 2 * pad)

    path = " ".join(f"{'M' if i == 0 else 'L'}{x(i):.1f},{y(v):.1f}" for i, v in enumerate(values))
    last = len(values) - 1
    return mark_safe(
        f'<svg class="spark" viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
        f'aria-hidden="true"><path d="{path}" fill="none" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
        f'<circle cx="{x(last):.1f}" cy="{y(values[last]):.1f}" r="3.5" stroke-width="2"/></svg>'
    )


def kpi_tiles(subject, *, limit: int = 6) -> list[dict]:
    from apps.reports.results import change_verdict, signed

    series = primary_metric_series(subject, limit_metrics=30)
    # jedna dlaždice na metriku: přednost má celek / oboustranně
    chosen = {}
    for s in series:
        code = s["metric"].code
        side = s["qualifiers"]["side"]
        if code not in chosen or (side in ("B", "") and chosen[code]["qualifiers"]["side"]
                                  not in ("B", "")):
            chosen[code] = s

    tiles = []
    for s in list(chosen.values())[:limit]:
        metric = s["metric"]
        d = metric.decimals
        points = s["points"]
        last_day, last = points[-1]
        tile = {
            "metric": metric,
            "label": qualifier_label(s["qualifiers"]),
            "value_txt": cz(last, d),
            "unit": "" if metric.unit in ("", "-") else metric.unit,
            "date": last_day,
            "count": len(points),
            "spark": sparkline([v for _, v in points[-8:]]),
            "delta_txt": "",
            "verdict": None,
        }
        if len(points) >= 2:
            previous = points[-2][1]
            tile["delta_txt"] = signed(round(last, d) - round(previous, d), d)
            _, kind = change_verdict(metric, last - previous)
            css, icon, text = VERDICTS.get(kind, VERDICTS["noise"])
            tile["verdict"] = {"css": css, "icon": icon, "text": text}
        tiles.append(tile)
    return tiles

