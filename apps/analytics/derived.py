"""
Odvozené ukazatele – dopočítané z jiných testů téhož dne.

Dynamic Strength Index (DSI) = koncentrická vrcholová síla v CMJ ÷
vrcholová síla v IMTP. Ukládá se jako obyčejné měření (vlastní „protokol“
dsi), takže ho grafy, pravidla, dlaždice i zpráva berou jako každou jinou
metriku. Přepočítá se, kdykoli se změní vstupy (import, ruční zadání).

Vstupem jsou hodnoty dne z hlavního měření (průměr platných pokusů).
"""

from django.db import transaction

DERIVED = [
    {"metric": "dsi", "protocol": "dsi", "decimals": 3,
     "numerator": ("cmj_peak_force", "B"), "denominator": ("imtp_peak_force", "B")},
]

REF_PREFIX = "odvozeno:"


def _value(values: dict, code: str, side: str):
    for (metric_code, s, mode, speed, segment), entry in values.items():
        if metric_code == code and s == side and not mode and speed is None and not segment:
            return entry["value"]
    return None


@transaction.atomic
def recompute(session) -> int:
    """Přepočítá odvozené ukazatele jednoho testovacího dne. Vrací počet uložených."""
    from apps.catalog.models import MetricDef, Protocol
    from apps.measurements.models import Measurement, ProtocolRun, Side, Trial

    from .queries import session_metric_values

    values = session_metric_values(session)
    saved = 0
    for spec in DERIVED:
        ref = f"{REF_PREFIX}{spec['metric']}"
        numerator = _value(values, *spec["numerator"])
        denominator = _value(values, *spec["denominator"])
        existing = ProtocolRun.objects.filter(session=session, external_ref=ref).first()

        if numerator is None or not denominator:
            if existing:  # vstup zmizel (smazaný test) – odvozená hodnota taky
                existing.delete()
            continue

        metric = MetricDef.objects.filter(code=spec["metric"], organization=None).first()
        protocol = Protocol.objects.filter(code=spec["protocol"], organization=None).first()
        if metric is None or protocol is None:
            continue

        run = existing or ProtocolRun.objects.create(
            session=session, protocol=protocol, external_ref=ref,
            note="Vypočteno automaticky z CMJ a IMTP.")
        trial, _ = Trial.objects.get_or_create(protocol_run=run, number=1)
        Measurement.objects.update_or_create(
            trial=trial, metric=metric, side=Side.BILATERAL, mode="", speed=None, segment="",
            defaults={"value": round(numerator / denominator, spec["decimals"])},
        )
        saved += 1
    return saved


def recompute_many(sessions) -> int:
    return sum(recompute(s) for s in sessions)
