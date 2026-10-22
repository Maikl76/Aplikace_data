"""
Dotazy, které krmí grafy na kartě sportovce, pravidla a zprávu.

Hodnota dne jednoho ukazatele
-----------------------------
Stejný ukazatel se může měřit ve dvou testech téhož dne (tělesná hmotnost
na plošině při CMJ i ve složení těla). Do souhrnu, pravidel, dlaždic
a grafů vstupuje **jedna** hodnota dne – z testu, kde je ukazatel klíčový;
když takový není, z testu s abecedně prvním kódem (ať je to pokaždé stejné).
Hodnoty z různých testů se nikdy neprůměrují dohromady – to by dalo číslo,
které v žádné tabulce zprávy není.
"""

from collections import defaultdict

from apps.measurements.models import Measurement, Side

from .services import asymmetries_for_run, find_norm


def _primary_protocols() -> dict[int, set[int]]:
    """{metrika: {testy, kde je klíčová}} – podle toho se vybírá zdroj hodnoty dne."""
    from apps.catalog.models import ProtocolMetric

    out: dict[int, set[int]] = defaultdict(set)
    for metric_id, protocol_id in (ProtocolMetric.objects.filter(is_primary=True)
                                   .values_list("metric_id", "protocol_id")):
        out[metric_id].add(protocol_id)
    return out


def canonical_protocol(protocols, metric, primary: dict):
    """Ze testů, které ukazatel ten den měřily, ten, odkud se bere hodnota dne."""
    return min(protocols, key=lambda p: (p.pk not in primary.get(metric.pk, ()), p.code, p.pk))


def primary_metric_series(subject, *, limit_metrics: int = 6, until=None):
    """
    Pro klíčové metriky vrátí vývoj v čase.

    Z každého testovacího dne se bere hodnota dne z platných pokusů (průměr,
    nebo nejlepší pokus – podle metriky) – jeden bod
    grafu je jedna návštěva, ne jeden pokus. Kvalifikátory se rozlišují,
    takže "210°/s koncentricky levá" je vlastní řada. ``until`` omezí
    řadu na měření do daného dne včetně – zpráva nesmí ukazovat budoucnost.
    """
    measurements = (
        Measurement.objects
        .filter(trial__protocol_run__session__subject=subject, trial__is_valid=True,
                trial__protocol_run__is_primary=True,
                metric__protocol_metrics__is_primary=True)
        .select_related("metric", "trial__protocol_run__session",
                        "trial__protocol_run__protocol")
        .distinct()
        .order_by("trial__number")
    )
    if until is not None:
        measurements = measurements.filter(trial__protocol_run__session__date__lte=until)

    # klíč -> den -> test -> hodnoty pokusů
    buckets = defaultdict(lambda: defaultdict(dict))
    for m in measurements:
        key = (m.metric, m.side, m.mode, m.speed, m.segment)
        run = m.trial.protocol_run
        buckets[key][run.session.date].setdefault(run.protocol, []).append(m.value)

    primary = _primary_protocols()
    series = []
    for (metric, side, mode, speed, segment), by_date in buckets.items():
        points = sorted(
            (day, metric.day_value(by_protocol[canonical_protocol(by_protocol, metric, primary)]))
            for day, by_protocol in by_date.items())
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
    for run in session.protocol_runs.filter(is_primary=True).select_related("protocol"):
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
    jedním vybraným pokusem. Když se protokol ten den měřil víckrát (třeba
    po zátěži), bere se jen hlavní provedení – průměr přes „před“ a „po“
    by neodpovídal ničemu.
    """
    buckets: dict[tuple, dict] = defaultdict(dict)   # klíč -> test -> hodnoty pokusů
    metrics = {}
    for m in (Measurement.objects
              .filter(trial__protocol_run__session=session, trial__is_valid=True,
                      trial__protocol_run__is_primary=True)
              .select_related("metric", "trial__protocol_run__protocol")
              .order_by("trial__number")):
        key = (m.metric.code, m.side, m.mode, m.speed, m.segment)
        buckets[key].setdefault(m.trial.protocol_run.protocol, []).append(m.value)
        metrics[key] = m.metric

    primary = _primary_protocols()
    out = {}
    for key, by_protocol in buckets.items():
        metric = metrics[key]
        protocol = canonical_protocol(by_protocol, metric, primary)
        out[key] = {"metric": metric, "value": metric.day_value(by_protocol[protocol]),
                    "side": key[1], "mode": key[2], "speed": key[3], "segment": key[4],
                    "protocol": protocol.code}
    return out


def previous_session_values(session, *, protocol=None) -> dict:
    """
    Poslední dřívější hodnota každé metriky (i s kvalifikátory), kvůli změně
    v čase.

    Bere se nejbližší dřívější den, kdy se ta konkrétní metrika měřila –
    ne prostě předchozí testovací den. Izokinetika se často měří jen
    dvakrát do roka; kdyby mezi tím proběhl jen výskok, tvrdila by zpráva
    „první měření“, zatímco graf vedle ukazuje starší bod.

    S ``protocol`` jen hodnoty z toho testu – tabulka testu ve zprávě
    srovnává s minulým měřením téhož testu (hmotnost z plošiny s hmotností
    z plošiny). Bez něj hodnota dne podle testu, kde je ukazatel klíčový.
    """
    qs = (Measurement.objects
          .filter(trial__protocol_run__session__subject=session.subject,
                  trial__protocol_run__session__date__lt=session.date,
                  trial__is_valid=True, trial__protocol_run__is_primary=True)
          .select_related("metric", "trial__protocol_run__session",
                          "trial__protocol_run__protocol")
          .order_by("trial__number"))
    if protocol is not None:
        qs = qs.filter(trial__protocol_run__protocol=protocol)

    # klíč -> den -> test -> hodnoty pokusů
    buckets = defaultdict(lambda: defaultdict(dict))
    metrics = {}
    for m in qs:
        key = (m.metric.code, m.side, m.mode, m.speed, m.segment)
        run = m.trial.protocol_run
        buckets[key][run.session.date].setdefault(run.protocol, []).append(m.value)
        metrics[key] = m.metric

    primary = _primary_protocols()
    out = {}
    for key, by_date in buckets.items():
        metric = metrics[key]
        latest = max(by_date)
        by_protocol = by_date[latest]
        chosen = canonical_protocol(by_protocol, metric, primary)
        out[key] = {"metric": metric, "value": metric.day_value(by_protocol[chosen]),
                    "date": latest, "side": key[1], "mode": key[2],
                    "speed": key[3], "segment": key[4], "protocol": chosen.code}
    return out


def session_asymmetries(session, *, threshold_pct: float = 10.0) -> list[dict]:
    rows = []
    for run in session.protocol_runs.filter(is_primary=True).select_related("protocol"):
        rows.extend(asymmetries_for_run(run, threshold_pct=threshold_pct))
    return rows
