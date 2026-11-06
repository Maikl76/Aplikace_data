"""
Srovnání nejen s minulým měřením.

Dlaždice, zpráva i portál dosud srovnávaly jen s předchozím měřením (přes
MDC) a s normou. Tady se k řadě hodnot jedné metriky dopočítá:

* **od začátku sezóny** – změna proti prvnímu měření v sezóně (sezóna začíná
  měsícem u sportu, bez něj lednem),
* **osobní maximum** – nejlepší hodnota řady podle žádoucího směru a jak
  daleko od ní je poslední měření,
* **vývoj za období** – změna za posledních 12 měsíců a počet měření.

Všechno se posuzuje stejně jako změna proti minule: proti MDC. Bez MDC se
o zlepšení ani zhoršení nemluví.
"""

import calendar
from datetime import date

from apps.catalog.models import Direction

PERIOD_MONTHS = 12

MONTHS_GENITIVE = ["ledna", "února", "března", "dubna", "května", "června", "července", "srpna",
                   "září", "října", "listopadu", "prosince"]
MONTHS_LOCATIVE = ["lednu", "únoru", "březnu", "dubnu", "květnu", "červnu", "červenci", "srpnu",
                   "září", "říjnu", "listopadu", "prosinci"]


def season_phrase(sport, *, case: str = "od") -> str:
    """„od září“ / „v září“ podle měsíce u sportu; bez měsíce „od ledna“ (kalendářní rok)."""
    month = getattr(sport, "season_start_month", None) or 1
    return (f"v {MONTHS_LOCATIVE[month - 1]}" if case == "v"
            else f"od {MONTHS_GENITIVE[month - 1]}")


def season_start(day: date, sport=None) -> date:
    """První den sezóny, do které spadá ``day``. Měsíc začátku je u sportu, jinak leden."""
    month = getattr(sport, "season_start_month", None) or 1
    start = date(day.year, month, 1)
    return start if start <= day else date(day.year - 1, month, 1)


def months_before(day: date, months: int = PERIOD_MONTHS) -> date:
    """Totéž datum o ``months`` měsíců dřív (31. 3. → 28. 2.)."""
    month, year = day.month - months, day.year
    while month <= 0:
        month, year = month + 12, year - 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def best_label(metric) -> str:
    """U ukazatelů, kde je lepší nižší hodnota (čas), se neříká maximum."""
    return "osobní rekord" if metric.direction == Direction.LOWER else "osobní maximum"


def compare(metric, points, *, sport=None) -> dict:
    """
    Pro řadu ``points`` [(datum, hodnota)] od nejstaršího vrátí srovnání
    posledního měření se začátkem sezóny, osobním maximem a vývojem za
    období. Každý klíč je None, když není s čím srovnávat.
    """
    from apps.reports.results import change_verdict, signed

    from .charts import cz

    out = {"season": None, "season_first": False, "best": None, "period": None}
    if len(points) < 2:
        return out
    d = metric.decimals
    last_day, last = points[-1]

    def shown_delta(value):
        # rozdíl zobrazených čísel, aby seděl při kontrole (37,5 − 36,9 = 0,6)
        return round(last, d) - round(value, d)

    # od začátku sezóny
    start = season_start(last_day, sport)
    in_season = [p for p in points if p[0] >= start]
    if len(in_season) >= 2:
        first_day, first = in_season[0]
        text, kind = change_verdict(metric, last - first)
        out["season"] = {
            "from": start, "date": first_day, "value": first, "value_txt": cz(first, d),
            "delta": last - first, "delta_txt": signed(shown_delta(first), d),
            "verdict": text, "kind": kind, "count": len(in_season),
        }
    else:
        out["season_first"] = True

    # osobní maximum (jen tam, kde má ukazatel směr)
    if metric.direction in (Direction.HIGHER, Direction.LOWER):
        pick = max if metric.direction == Direction.HIGHER else min
        best_value = pick(v for _, v in points)
        # při shodě se bere nejnovější – vyrovnané maximum je také maximum
        best_day = max(day for day, v in points if v == best_value)
        delta = last - best_value
        if best_day == last_day:
            state = ("nový " if metric.direction == Direction.LOWER else "nové ") + best_label(metric)
            kind = "best"
        elif metric.mdc is not None and abs(delta) < metric.mdc:
            state, kind = "na úrovni maxima (rozdíl v pásmu chyby měření)", "noise"
        else:
            state = (f"o {cz(abs(shown_delta(best_value)), d)} "
                     f"{'' if metric.unit in ('', '-') else metric.unit + ' '}"
                     f"{'pod' if metric.direction == Direction.HIGHER else 'nad'} maximem").replace("  ", " ")
            kind = "below"
        out["best"] = {
            "label": best_label(metric), "value": best_value, "value_txt": cz(best_value, d),
            "date": best_day, "delta": delta, "delta_txt": signed(shown_delta(best_value), d),
            "is_current": best_day == last_day, "state": state, "kind": kind,
        }

    # vývoj za období
    window = [p for p in points if p[0] >= months_before(last_day)]
    if len(window) >= 2:
        first_day, first = window[0]
        delta = last - first
        pct = round(shown_delta(first) / abs(round(first, d)) * 100) if round(first, d) else None
        text, kind = change_verdict(metric, delta)
        out["period"] = {
            "months": PERIOD_MONTHS, "from": first_day, "value": first, "delta": delta,
            "delta_txt": signed(shown_delta(first), d), "pct": pct,
            "pct_txt": (signed(pct, 0) + " %") if pct is not None else "",
            "count": len(window), "verdict": text, "kind": kind,
        }
    return out
