"""
Výsledky testovacího dne pro zprávu.

Zpráva musí obsahovat všechno, co se naměřilo – ne jen to, co spustilo
pravidlo. Tady se to skládá: po protokolech, v pořadí z katalogu,
s hodnotou dne, jednotlivými pokusy, změnou proti minulému měření
a srovnáním s normou.

Hodnota dne je průměr platných pokusů (stejně jako v pravidlech a na kartě
sportovce), takže tabulka, graf i nález mluví o tomtéž čísle.
"""

from collections import defaultdict

from django.utils import timezone

from apps.analytics import queries
from apps.analytics.charts import cz, qualifier_label
from apps.analytics.queries import _combo_order
from apps.analytics.services import find_norm
from apps.catalog.models import Direction
from apps.measurements.models import Measurement

ASYMMETRY_THRESHOLD_PCT = 10.0


def _key(m) -> tuple:
    return (m.metric.code, m.side, m.mode, m.speed, m.segment)


def change_verdict(metric, delta: float) -> tuple[str, str]:
    """
    Slovní posouzení změny a její druh pro barevné označení.

    Bez MDC se o zlepšení ani zhoršení nemluví – změna může být jen šum.
    """
    if round(delta, metric.decimals) == 0:
        return "beze změny", "noise"
    if metric.mdc is None:
        return "nelze posoudit (chybí MDC)", "unknown"
    if not metric.change_is_real(delta):
        return "v pásmu chyby měření", "noise"
    if metric.direction == Direction.HIGHER:
        return ("zlepšení", "better") if delta > 0 else ("zhoršení", "worse")
    if metric.direction == Direction.LOWER:
        return ("zlepšení", "better") if delta < 0 else ("zhoršení", "worse")
    return "skutečný posun", "shift"


def signed(value: float, decimals: int) -> str:
    if round(value, decimals) == 0:
        return cz(0, decimals)
    return f"{'+' if value > 0 else '−'}{cz(abs(value), decimals)}"


def _run_values(run) -> tuple[dict, dict]:
    """Průměry platných pokusů jednoho provedení: {klíč: [hodnoty]}, {klíč: metrika}."""
    buckets = defaultdict(list)
    metrics = {}
    for m in (Measurement.objects
              .filter(trial__protocol_run=run, trial__is_valid=True)
              .select_related("metric", "trial").order_by("trial__number")):
        buckets[_key(m)].append(m.value)
        metrics[_key(m)] = m.metric
    return buckets, metrics


def _time(run) -> str:
    return timezone.localtime(run.started_at).strftime("%H:%M") if run.started_at else ""


def protocol_results(session) -> list[dict]:
    """
    Tabulky výsledků po protokolech.

    Když se protokol ten den měřil víckrát (před a po zátěži), hlavní
    tabulka je z prvního měření a opakovaná jsou pod ní v kompaktní
    tabulce vedle sebe – aby šlo porovnat „před“ a „po“ na jeden pohled.
    """
    previous = queries.previous_session_values(session)
    subject = session.subject
    blocks = []

    runs = list(session.protocol_runs.select_related("protocol")
                .prefetch_related("protocol__protocol_metrics"))
    runs.sort(key=lambda r: (r.protocol.name, not r.is_primary,
                             r.started_at or r.created_at))
    by_protocol: dict[int, list] = defaultdict(list)
    for run in runs:
        by_protocol[run.protocol_id].append(run)

    for protocol_runs in by_protocol.values():
        run, repeats = protocol_runs[0], protocol_runs[1:]
        order = {pm.metric_id: pm.order for pm in run.protocol.protocol_metrics.all()}
        primary = {pm.metric_id for pm in run.protocol.protocol_metrics.all() if pm.is_primary}

        trials = list(run.trials.all())
        invalid = [t for t in trials if not t.is_valid]
        buckets, metrics = _run_values(run)

        rows = []
        for key, values in buckets.items():
            metric = metrics[key]
            d = metric.decimals
            _, side, mode, speed, segment = key
            qualifiers = {"side": side, "mode": mode, "speed": speed, "segment": segment}
            value = sum(values) / len(values)
            row = {
                "key": key,
                "metric": metric,
                "qualifiers": qualifiers,
                "label": qualifier_label(qualifiers),
                "is_primary": metric.pk in primary,
                "value": value,
                "value_txt": cz(value, d),
                "trials_txt": " · ".join(cz(v, d) for v in values) if len(values) > 1 else "",
                "n": len(values),
                "previous_txt": "",
                "previous_date": None,
                "delta_txt": "",
                "verdict": "",
                "verdict_kind": "",
                "norm_txt": "",
                "z_txt": "",
            }

            if (before := previous.get(key)) is not None:
                delta = value - before["value"]
                row["previous_txt"] = cz(before["value"], d)
                row["previous_date"] = before["date"]
                # zobrazený rozdíl = rozdíl zobrazených hodnot, aby seděl při kontrole
                row["delta_txt"] = signed(round(value, d) - round(before["value"], d), d)
                row["verdict"], row["verdict_kind"] = change_verdict(metric, delta)

            norm = find_norm(metric, subject, side=side, mode=mode, speed=speed)
            if norm is not None and norm.mean is not None:
                row["norm_txt"] = cz(norm.mean, d) + (f" ± {cz(norm.sd, d)}" if norm.sd else "")
                if (z := norm.z_score(value)) is not None:
                    row["z_txt"] = signed(z, 1)

            rows.append(row)

        rows.sort(key=lambda r: (order.get(r["metric"].pk, 999), r["metric"].name,
                                 _combo_order(r)))
        # Název metriky jen u prvního řádku skupiny – izokinetika má jednu
        # metriku v osmi kombinacích a opakovaný název by tabulku zahltil.
        for i, row in enumerate(rows):
            row["first_of_metric"] = i == 0 or rows[i - 1]["metric"].pk != row["metric"].pk

        blocks.append({
            "protocol": run.protocol,
            "run": run,
            "time": _time(run),
            "conditions": _conditions_text(run.conditions),
            "rows": rows,
            "trials": len(trials),
            "invalid": invalid,
            "note": run.note,
            "repeats": _repeat_table(run, rows, repeats) if repeats else None,
        })
    return blocks


def _repeat_table(first_run, rows, repeats) -> dict:
    """Opakovaná měření téhož dne vedle prvního: řádek = ukazatel, sloupec = čas."""
    columns = [_run_values(r)[0] for r in repeats]
    table = []
    for row in rows:
        d = row["metric"].decimals
        cells = []
        for values in columns:
            vals = values.get(row["key"])
            if vals:
                mean = sum(vals) / len(vals)
                cells.append({"value_txt": cz(mean, d),
                              "delta_txt": signed(round(mean, d) - round(row["value"], d), d)})
            else:
                cells.append(None)
        table.append({"metric": row["metric"], "label": row["label"],
                      "first_of_metric": row["first_of_metric"],
                      "first_txt": row["value_txt"], "cells": cells})
    return {
        "first_time": _time(first_run),
        "times": [_time(r) or f"{i}. opakování" for i, r in enumerate(repeats, start=2)],
        "conditions": [_conditions_text(r.conditions) for r in repeats],
        "rows": table,
    }


CONDITION_LABELS = {"parametry": "", "zatez_kg": "zátěž {} kg",
                    "opakovani": "opakování: {}", "stitky": "štítky: {}"}


def _conditions_text(conditions: dict) -> str:
    """Podmínky testu čitelně: „Exercise Length: 30s · zátěž 20 kg“."""
    parts = []
    for key, value in (conditions or {}).items():
        template = CONDITION_LABELS.get(key, f"{key}: {{}}")
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        parts.append(template.format(value) if template else str(value))
    return " · ".join(parts)


def trend_series(session, *, limit: int = 8) -> list[dict]:
    """
    Vývoj klíčových metrik do data tohoto měření (pozdější měření do zprávy
    nepatří). Jen řady, které mají hodnotu z tohoto dne a aspoň jedno
    starší měření – jediný bod není vývoj.
    """
    series = queries.primary_metric_series(session.subject, limit_metrics=50,
                                           until=session.date)
    useful = [s for s in series
              if len(s["points"]) >= 2 and s["points"][-1][0] == session.date]
    return useful[:limit]


def asymmetries(session) -> list[dict]:
    rows = queries.session_asymmetries(session, threshold_pct=ASYMMETRY_THRESHOLD_PCT)
    rows.sort(key=lambda r: abs(r["index_pct"]), reverse=True)
    for r in rows:
        d = r["metric"].decimals
        r["label"] = qualifier_label(r["qualifiers"])
        r["left_txt"] = cz(r["left"], d)
        r["right_txt"] = cz(r["right"], d)
        r["index_txt"] = cz(abs(r["index_pct"]), 1)
        r["stronger"] = "levá" if r["index_pct"] > 0 else "pravá"
    return rows


def machine_readable(blocks) -> list[dict]:
    """Výsledky pro strojově čitelnou přílohu – čísla, ne texty."""
    return [
        {
            "protokol": b["protocol"].code,
            "nazev": b["protocol"].name,
            "hodnoty": [
                {
                    "metrika": r["metric"].code,
                    "jednotka": r["metric"].unit,
                    "strana": r["qualifiers"]["side"],
                    "rezim": r["qualifiers"]["mode"],
                    "rychlost": r["qualifiers"]["speed"],
                    "segment": r["qualifiers"]["segment"],
                    "hodnota": round(r["value"], r["metric"].decimals),
                    "pocet_pokusu": r["n"],
                }
                for r in b["rows"]
            ],
        }
        for b in blocks
    ]
