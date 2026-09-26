"""
Týmový přehled: sportovci × klíčové ukazatele baterie testů.

Každá buňka nese dvě informace, které se nesmí plést:

* **změna proti minulému měření** téhož sportovce – posuzuje se proti MDC
  stejně jako ve zprávě (šipka a slovo),
* **postavení v týmu** – o kolik směrodatných odchylek je poslední hodnota
  nad nebo pod průměrem skupiny, s ohledem na to, zda je u ukazatele
  lepší vyšší, nebo nižší hodnota (barva pozadí).

Postavení v týmu je jen orientační: srovnává se to, co skupina naposledy
naměřila, a při malém počtu sportovců nic neříká – proto se počítá až
od MIN_GROUP hodnot.
"""

import statistics
from collections import defaultdict

from apps.catalog.models import Direction
from apps.measurements.models import Measurement

from .charts import cz, qualifier_label

MIN_GROUP = 4
# Hodnota starší než tohle se v přehledu tlumí – už nemusí platit.
STALE_DAYS = 120


def columns_for(protocols) -> list[dict]:
    """
    Sloupce přehledu: klíčové metriky protokolů baterie.

    U oboustranných metrik jeden sloupec (celek), u čistě stranových dva
    (L, P). Z víc režimů a rychlostí se bere první – přehled má být
    na jednu obrazovku, podrobnosti jsou na kartě sportovce.
    """
    cols = []
    for protocol in protocols:
        for pm in (protocol.protocol_metrics.filter(is_primary=True)
                   .select_related("metric").order_by("order")):
            mode = pm.modes[0] if pm.modes else ""
            speed = float(pm.speeds[0]) if pm.speeds else None
            segment = pm.segments[0] if pm.segments else ""
            sides = ["B"] if (not pm.sides or "B" in pm.sides) else [
                s for s in ("L", "R") if s in pm.sides]
            for side in sides:
                qualifiers = {"side": side if side != "B" else "", "mode": mode,
                              "speed": speed, "segment": segment}
                cols.append({
                    "protocol": protocol, "metric": pm.metric, "side": side,
                    "mode": mode, "speed": speed, "segment": segment,
                    "label": qualifier_label(qualifiers),
                    "unit": "" if pm.metric.unit in ("", "-") else pm.metric.unit,
                })
    return cols


def _key(metric_id, side, mode, speed, segment):
    # Oboustranná hodnota bývá uložená jako „B“ i bez strany – je to totéž.
    return (metric_id, "B" if side in ("", "B") else side, mode or "",
            float(speed) if speed is not None else None, segment or "")


def team_table(subjects, columns, *, today) -> dict:
    """Řádky (sportovec a buňky) a souhrn sloupců (průměr, SD, počet)."""
    from apps.reports.results import change_verdict, signed

    from .overview import VERDICTS

    wanted = {_key(c["metric"].pk, c["side"], c["mode"], c["speed"], c["segment"]): i
              for i, c in enumerate(columns)}
    # (sportovec, sloupec) -> {den: [hodnoty]}
    days = defaultdict(lambda: defaultdict(list))
    measurements = (Measurement.objects
                    .filter(trial__protocol_run__session__subject__in=subjects,
                            trial__protocol_run__is_primary=True, trial__is_valid=True,
                            metric__in={c["metric"].pk for c in columns})
                    .values_list("trial__protocol_run__session__subject_id",
                                 "trial__protocol_run__session__date",
                                 "metric_id", "side", "mode", "speed", "segment", "value"))
    for subject_id, day, metric_id, side, mode, speed, segment, value in measurements:
        index = wanted.get(_key(metric_id, side, mode, speed, segment))
        if index is not None:
            days[(subject_id, index)][day].append(value)

    rows = []
    for subject in subjects:
        cells = []
        for index, col in enumerate(columns):
            metric = col["metric"]
            history = sorted((d, sum(v) / len(v)) for d, v in days[(subject.pk, index)].items())
            if not history:
                cells.append(None)
                continue
            day, value = history[-1]
            cell = {"value": value, "value_txt": cz(value, metric.decimals), "date": day,
                    "stale": (today - day).days > STALE_DAYS, "verdict": None, "z": None}
            if len(history) >= 2:
                delta = round(value, metric.decimals) - round(history[-2][1], metric.decimals)
                text, kind = change_verdict(metric, value - history[-2][1])
                css, icon, _ = VERDICTS.get(kind, VERDICTS["noise"])
                cell["verdict"] = {"css": css, "icon": icon, "text": text,
                                   "delta_txt": signed(delta, metric.decimals),
                                   "previous_date": history[-2][0]}
            cells.append(cell)
        rows.append({"subject": subject, "cells": cells,
                     "measured": sum(c is not None for c in cells)})

    summary = []
    for index, col in enumerate(columns):
        values = [r["cells"][index]["value"] for r in rows if r["cells"][index]]
        info = {"n": len(values), "mean_txt": "", "sd_txt": ""}
        if len(values) >= 2:
            mean, sd = statistics.fmean(values), statistics.stdev(values)
            d = col["metric"].decimals
            info.update(mean_txt=cz(mean, d), sd_txt=cz(sd, d))
            if len(values) >= MIN_GROUP and sd > 0:
                _rank(rows, index, col["metric"], mean, sd)
        summary.append(info)
    return {"rows": rows, "summary": summary}


def _rank(rows, index, metric, mean, sd):
    """Postavení v týmu: z-skóre otočené tak, aby kladné bylo vždy „lépe“."""
    sign = {Direction.HIGHER: 1, Direction.LOWER: -1}.get(metric.direction)
    for row in rows:
        cell = row["cells"][index]
        if not cell:
            continue
        z = (cell["value"] - mean) / sd
        cell["z"] = z
        if sign is None:  # optimum / neutrální: bez hodnocení lépe–hůře
            cell["tier"] = "far" if abs(z) >= 1.5 else ""
        else:
            good = z * sign
            cell["tier"] = ("top" if good >= 1 else "low" if good <= -1 else "")
        cell["z_txt"] = f"{'+' if z > 0 else '−' if z < 0 else ''}{cz(abs(z), 1)}"
