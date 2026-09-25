"""
Grafy na kartě sportovce.

Figura se skládá v Pythonu jako obyčejný slovník a do prohlížeče jde jako
JSON, kde ji vykreslí plotly.js. Python tedy nepotřebuje knihovnu plotly –
jen umět popsat, co se má nakreslit.

Barvy pocházejí z validované palety (kontrola na odlišitelnost při barvosleposti
a na kontrast vůči podkladu proběhla pro oba režimy). Identitu nikdy nenese
jen barva: série mají přímé popisky a překročený práh se hlásí textem
a značkou, ne červenou barvou.
"""

from dataclasses import dataclass

from apps.catalog.models import Direction

# Slot 1 a 2 kategorické palety. Tmavý režim je samostatně nakrokovaný,
# ne automaticky zesvětlený – až aplikace dostane přepínač, použije se.
PALETTE = {
    "light": {
        "series_1": "#2a78d6",   # modrá – aktuální sportovec / levá strana
        "series_2": "#eb6834",   # oranžová – pravá strana
        "surface": "#fcfcfb",
        "text_primary": "#0b0b0b",
        "text_secondary": "#52514e",
        "muted": "#898781",
        "grid": "#e1e0d9",
        "axis": "#c3c2b7",
        "band": "rgba(137,135,129,0.14)",
    },
    "dark": {
        "series_1": "#3987e5",
        "series_2": "#d95926",
        "surface": "#1a1a19",
        "text_primary": "#ffffff",
        "text_secondary": "#c3c2b7",
        "muted": "#898781",
        "grid": "#2c2c2a",
        "axis": "#383835",
        "band": "rgba(137,135,129,0.20)",
    },
}

# Stavová barva je vyhrazená – nikdy neslouží jako „další série“.
# Doprovází ji značka a text v tabulce, aby stav nenesla jen barva.
STATUS_WARNING = "#fab219"

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def cz(value: float, decimals: int = 2) -> str:
    """Číslo s desetinnou čárkou – pro popisky, které skládáme sami."""
    return f"{value:.{decimals}f}".replace(".", ",")


@dataclass
class ChartSpec:
    """Hotová figura pro plotly.js plus popisky, které patří vedle grafu."""

    element_id: str
    figure: dict
    title: str
    subtitle: str = ""
    note: str = ""


def _base_layout(colors: dict, *, height: int, y_title: str = "") -> dict:
    return {
        "height": height,
        "margin": {"l": 56, "r": 16, "t": 8, "b": 40},
        "paper_bgcolor": colors["surface"],
        "plot_bgcolor": colors["surface"],
        "font": {"family": FONT, "size": 12, "color": colors["text_secondary"]},
        # České oddělovače: desetinná čárka, tisíce mezerou. Bez tohohle
        # by graf psal 9.8 a tabulka vedle něj 9,8.
        "separators": ", ",
        "hovermode": "x unified",
        "showlegend": False,
        "xaxis": {
            "showgrid": False,
            "linecolor": colors["axis"],
            "tickcolor": colors["axis"],
            "tickfont": {"color": colors["muted"]},
        },
        "yaxis": {
            "title": {"text": y_title, "font": {"color": colors["muted"], "size": 11}},
            "gridcolor": colors["grid"],
            "zeroline": False,
            "linecolor": colors["axis"],
            "tickfont": {"color": colors["muted"]},
        },
    }


def qualifier_label(qualifiers: dict | None) -> str:
    """Čitelný popisek kvalifikátorů, např. „levá · koncentricky · 210°/s“."""
    if not qualifiers:
        return ""
    from apps.measurements.models import Mode, Side

    bits = []
    if segment := qualifiers.get("segment"):
        bits.append(segment)
    side = qualifiers.get("side")
    if side and side != Side.BILATERAL:
        bits.append(Side(side).label.lower())
    if mode := qualifiers.get("mode"):
        bits.append(Mode(mode).label.lower())
    if (speed := qualifiers.get("speed")) is not None:
        bits.append(f"{speed:g}°/s")
    return " · ".join(bits)


def _element_id(prefix: str, metric, qualifiers: dict | None) -> str:
    """
    Unikátní id figury. Jedna metrika má víc řad (strana, režim, rychlost),
    takže samotný kód metriky nestačí – dva divy se stejným id by se
    vykreslily přes sebe.
    """
    q = qualifiers or {}
    speed = "" if q.get("speed") is None else f"{q['speed']:g}"
    parts = [prefix, metric.code, q.get("side", ""), q.get("mode", ""),
             speed, q.get("segment", "")]
    return "-".join(p for p in parts if p)


def trend_chart(metric, points, *, qualifiers=None, norm=None,
                theme: str = "light") -> ChartSpec:
    """
    Vývoj jedné metriky v čase proti normě.

    ``points`` je seznam (datum, hodnota) seřazený od nejstaršího.
    Norma se kreslí jako pásmo průměr ± SD za čarou – je to kontext,
    ne druhá série, takže zůstává neutrálně šedá a nesoupeří o pozornost.
    """
    colors = PALETTE[theme]
    dates = [d.isoformat() for d, _ in points]
    values = [v for _, v in points]
    unit = f" {metric.unit}" if metric.unit else ""

    traces = []
    note = ""

    if norm is not None and norm.mean is not None and norm.sd:
        low, high = norm.mean - norm.sd, norm.mean + norm.sd
        traces.append({
            "type": "scatter", "x": dates + dates[::-1],
            "y": [high] * len(dates) + [low] * len(dates),
            "fill": "toself", "fillcolor": colors["band"],
            "line": {"width": 0}, "hoverinfo": "skip",
            "name": "pásmo normy", "showlegend": False,
        })
        traces.append({
            "type": "scatter", "x": dates, "y": [norm.mean] * len(dates),
            "mode": "lines",
            "line": {"color": colors["muted"], "width": 1, "dash": "dot"},
            "hovertemplate": f"norma {cz(norm.mean, metric.decimals)}{unit}<extra></extra>",
            "name": "norma",
        })
        note = f"Pásmo = průměr ± SD normy. Zdroj: {norm.source_citation}"

    traces.append({
        "type": "scatter", "x": dates, "y": values, "mode": "lines+markers+text",
        "line": {"color": colors["series_1"], "width": 2},
        "marker": {"size": 9, "color": colors["series_1"],
                   "line": {"width": 2, "color": colors["surface"]}},
        # Přímý popisek jen u krajních bodů – číslo u každého bodu je šum.
        "text": [_edge_label(i, values, metric) for i in range(len(values))],
        "textposition": "top center",
        "textfont": {"color": colors["text_secondary"], "size": 11},
        "cliponaxis": False,
        "hovertemplate": "%{x}<br>%{y:." + str(metric.decimals) + "f}" + unit + "<extra></extra>",
        "name": metric.name,
    })

    layout = _base_layout(colors, height=240, y_title=metric.unit or "")
    layout["xaxis"]["tickformat"] = "%m/%Y"
    layout["yaxis"]["range"] = _y_range(metric, values, norm)
    label = qualifier_label(qualifiers)
    return ChartSpec(
        element_id=_element_id("trend", metric, qualifiers),
        figure={"data": traces, "layout": layout},
        title=f"{metric.name} — {label}" if label else metric.name,
        subtitle=_trend_subtitle(metric, values),
        note=note,
    )


def _y_range(metric, values: list, norm) -> list | None:
    """
    Rozsah svislé osy.

    Useknutá osa je nejčastější způsob, jak z grafu udělat lež: kolísání
    v řádu chyby měření vypadá jako dramatický vývoj. Osa proto pokrývá
    aspoň trojnásobek MDC – změna pod chybou měření pak i vypadá malá.
    """
    low, high = min(values), max(values)
    if norm is not None and norm.mean is not None and norm.sd:
        low = min(low, norm.mean - norm.sd)
        high = max(high, norm.mean + norm.sd)

    span = high - low
    minimum_span = (metric.mdc or 0) * 3
    if span < minimum_span:
        middle = (high + low) / 2
        low, high = middle - minimum_span / 2, middle + minimum_span / 2
        span = minimum_span
    if span == 0:
        return None

    padding = span * 0.18
    return [low - padding, high + padding]


def _edge_label(index: int, values: list, metric) -> str:
    if index not in (0, len(values) - 1):
        return ""
    return cz(values[index], metric.decimals)


def _trend_subtitle(metric, values: list) -> str:
    """Slovní shrnutí trendu. Bez MDC se nic netvrdí."""
    if len(values) < 2:
        return "jediné měření – trend zatím nelze posoudit"

    delta = values[-1] - values[0]
    if round(delta, metric.decimals) == 0:
        return "beze změny mezi prvním a posledním měřením"
    if metric.mdc is None:
        return (f"změna {_delta(delta, metric)} {metric.unit}; "
                f"metrika nemá MDC, nelze odlišit od chyby měření")
    if not metric.change_is_real(delta):
        return (f"změna {_delta(delta, metric)} {metric.unit} "
                f"nepřesahuje MDC {cz(metric.mdc, metric.decimals)}")

    if metric.direction == Direction.HIGHER:
        word = "zlepšení" if delta > 0 else "zhoršení"
    elif metric.direction == Direction.LOWER:
        word = "zlepšení" if delta < 0 else "zhoršení"
    else:
        word = "posun"
    return (f"{word} o {cz(abs(delta), metric.decimals)} {metric.unit} "
            f"(nad MDC {cz(metric.mdc, metric.decimals)})")


def _delta(value: float, metric) -> str:
    return f"{'+' if value > 0 else '−'}{cz(abs(value), metric.decimals)}"


def asymmetry_chart(rows, *, threshold_pct: float = 10.0, limit: int = 10,
                    theme: str = "light") -> ChartSpec:
    """
    Rozdíl mezi stranami v procentech.

    Vynáší se INDEX, ne absolutní hodnoty. Newtony z IMTP, kilogramy
    stisku a bezrozměrný poměr IR/ER na jedné ose znamenají, že je vidět
    jen ta největší veličina a zbytek splyne s nulou. Procentní rozdíl
    je naopak společná míra pro všechny metriky.

    Směr nese poloha vůči nule (vlevo = vyšší hodnota vpravo), ne barva –
    červená by tady znamenala „pravá strana je špatně“, což není pravda.
    Barvou se hlásí jen překročení prahu, a to je navíc napsané v tabulce
    pod grafem.
    """
    colors = PALETTE[theme]
    rows = sorted(rows, key=lambda r: abs(r["index_pct"]), reverse=True)[:limit]
    rows = list(reversed(rows))   # největší odchylka nahoře

    labels = [_row_label(r) for r in rows]
    values = [r["index_pct"] for r in rows]
    over = [abs(v) > threshold_pct for v in values]

    traces = [{
        "type": "bar", "orientation": "h", "y": labels, "x": values,
        "marker": {
            "color": [STATUS_WARNING if flag else colors["series_1"] for flag in over],
            "line": {"width": 2, "color": colors["surface"]},
        },
        "text": [f"{'+' if v > 0 else '−'}{cz(abs(v), 1)} %" for v in values],
        "textposition": "outside",
        "textfont": {"color": colors["text_secondary"], "size": 11},
        "cliponaxis": False,
        "customdata": [[r["left"], r["right"]] for r in rows],
        "hovertemplate": ("levá %{customdata[0]:.2f} · pravá %{customdata[1]:.2f}"
                          "<br>rozdíl %{x:+.1f} %<extra></extra>"),
        "name": "rozdíl L−P",
    }]

    limit_span = max([abs(v) for v in values] + [threshold_pct]) * 1.45
    layout = _base_layout(colors, height=max(190, 40 * len(rows) + 70))
    layout.update({
        "bargap": 0.45,
        "hovermode": "closest",
        "margin": {"l": 210, "r": 40, "t": 16, "b": 42},
        "shapes": [
            # pásmo tolerance – co je uvnitř, není nález
            {"type": "rect", "xref": "x", "yref": "paper",
             "x0": -threshold_pct, "x1": threshold_pct, "y0": 0, "y1": 1,
             "fillcolor": colors["band"], "line": {"width": 0}, "layer": "below"},
            {"type": "line", "xref": "x", "yref": "paper",
             "x0": 0, "x1": 0, "y0": 0, "y1": 1,
             "line": {"color": colors["axis"], "width": 1}},
        ],
    })
    layout["xaxis"].update({
        "title": {"text": "rozdíl levá − pravá (%)",
                  "font": {"color": colors["muted"], "size": 11}},
        "range": [-limit_span, limit_span],
        "gridcolor": colors["grid"], "showgrid": True, "zeroline": False,
        "ticksuffix": " %",
    })
    layout["yaxis"].update({"automargin": True, "gridcolor": "rgba(0,0,0,0)"})

    pocet = sum(over)
    return ChartSpec(
        element_id="asymetrie",
        figure={"data": traces, "layout": layout},
        title="Asymetrie levá / pravá",
        subtitle=(f"{pocet} z {len(rows)} zobrazených nad prahem {threshold_pct:g} %"
                  if rows else "žádná oboustranná měření"),
        note=(f"Šedé pásmo = tolerance ±{cz(threshold_pct, 0)} %. Sloupec vlevo od nuly "
              f"znamená vyšší hodnotu vpravo."),
    )


def _row_label(row) -> str:
    label = qualifier_label(row["qualifiers"])
    return f"{row['metric'].name}<br>{label}" if label else row["metric"].name
