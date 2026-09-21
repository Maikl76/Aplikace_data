"""Dotazy, které krmí grafy na kartě sportovce."""

from collections import defaultdict

from apps.measurements.models import Measurement, Side

from .services import asymmetries_for_run, find_norm


def primary_metric_series(subject, *, limit_metrics: int = 6):
    """
    Pro klíčové metriky vrátí vývoj v čase.

    Z každého testovacího dne se bere průměr platných pokusů – jeden bod
    grafu je jedna návštěva, ne jeden pokus. Kvalifikátory se rozlišují,
    takže "210°/s koncentricky levá" je vlastní řada.
    """
    measurements = (
        Measurement.objects
        .filter(trial__protocol_run__session__subject=subject, trial__is_valid=True,
                metric__protocol_metrics__is_primary=True)
        .select_related("metric", "trial__protocol_run__session")
        .distinct()
    )

    buckets = defaultdict(list)
    for m in measurements:
        key = (m.metric, m.side, m.mode, m.speed, m.segment)
        buckets[key].append((m.trial.protocol_run.session.date, m.value))

    series = []
    for (metric, side, mode, speed, segment), values in buckets.items():
        by_date = defaultdict(list)
        for day, value in values:
            by_date[day].append(value)
        points = sorted((day, sum(v) / len(v)) for day, v in by_date.items())
        if not points:
            continue
        series.append({
            "metric": metric,
            "qualifiers": {"side": side, "mode": mode, "speed": speed, "segment": segment},
            "points": points,
            "norm": find_norm(metric, subject, side=side, mode=mode, speed=speed),
        })

    return _spread_across_metrics(series, limit=limit_metrics)


def _spread_across_metrics(series, *, limit: int, per_metric: int = 2):
    """
    Vybere, co ukázat.

    Jedna metrika má často mnoho kombinací (strana × režim × rychlost).
    Bez tohohle kroku by kartu zaplnilo pět grafů téže rotace ramene
    a na zbytek by nezbylo místo. Proto nejvýš dvě kombinace na metriku
    a pak se střídá.
    """
    from collections import OrderedDict

    by_metric = OrderedDict()
    for item in sorted(series, key=lambda s: (s["metric"].name, _combo_order(s))):
        by_metric.setdefault(item["metric"].code, []).append(item)

    vybrano = []
    for round_index in range(per_metric):
        for items in by_metric.values():
            if round_index < len(items):
                vybrano.append(items[round_index])
            if len(vybrano) >= limit:
                return vybrano
    return vybrano


def _combo_order(item) -> tuple:
    """Napřed oboustranné a nejnižší rychlost – to je typicky to hlavní."""
    q = item["qualifiers"]
    return (
        0 if q["side"] in ("B", "") else 1,
        q["side"],
        q["speed"] if q["speed"] is not None else -1,
        q["mode"],
        q["segment"],
    )


def latest_asymmetries(subject, *, threshold_pct: float = 10.0):
    """Asymetrie z posledního testovacího dne, přes všechny protokoly."""
    session = subject.sessions.order_by("-date").first()
    if session is None:
        return None, []

    rows = []
    for run in session.protocol_runs.select_related("protocol"):
        rows.extend(asymmetries_for_run(run, threshold_pct=threshold_pct))
    rows.sort(key=lambda r: abs(r["index_pct"]), reverse=True)
    return session, rows


def has_side_data(subject) -> bool:
    """Nese sportovec vůbec data se stranou? Historická data ji nemají."""
    return Measurement.objects.filter(
        trial__protocol_run__session__subject=subject,
        side__in=[Side.LEFT, Side.RIGHT],
    ).exists()


def session_metric_values(session) -> dict:
    """
    Hodnoty jednoho testovacího dne pro vyhodnocení pravidel.

    Klíč je metrika i s kvalifikátory, hodnota průměr platných pokusů –
    pravidlo se tedy vyhodnocuje nad tím, co se ten den naměřilo, ne nad
    jedním vybraným pokusem.
    """
    from apps.measurements.models import Measurement

    buckets = defaultdict(list)
    for m in (Measurement.objects
              .filter(trial__protocol_run__session=session, trial__is_valid=True)
              .select_related("metric")):
        key = (m.metric.code, m.side, m.mode, m.speed, m.segment)
        buckets[key].append((m.metric, m.value))

    return {
        key: {"metric": values[0][0],
              "value": sum(v for _, v in values) / len(values),
              "side": key[1], "mode": key[2], "speed": key[3], "segment": key[4]}
        for key, values in buckets.items()
    }


def previous_session_values(session) -> dict:
    """Totéž pro nejbližší předchozí testovací den, kvůli změně v čase."""
    previous = (session.subject.sessions
                .filter(date__lt=session.date).order_by("-date").first())
    return session_metric_values(previous) if previous else {}


def session_asymmetries(session, *, threshold_pct: float = 10.0) -> list[dict]:
    rows = []
    for run in session.protocol_runs.select_related("protocol"):
        rows.extend(asymmetries_for_run(run, threshold_pct=threshold_pct))
    return rows
