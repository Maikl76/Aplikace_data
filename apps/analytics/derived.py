"""
Odvozené ukazatele – dopočítané z jiných hodnot téhož dne.

Dynamic Strength Index (DSI) = koncentrická vrcholová síla v CMJ ÷
vrcholová síla v IMTP. Ukládá se jako obyčejné měření (vlastní „protokol“
dsi), takže ho grafy, pravidla, dlaždice i zpráva berou jako každou jinou
metriku. Přepočítá se, kdykoli se změní vstupy (import, ruční zadání).

Vstupem jsou hodnoty dne z hlavního měření (průměr platných pokusů).
"""

from django.db import transaction

# into: „own“ = vlastní vypočtený protokol (DSI, EUR); „measured“ = do
# hlavního měření daného protokolu, aby relativní hodnoty stály v tabulce
# hned vedle absolutních (Wingate W → W/kg).
DERIVED = [
    {"metric": "dsi", "protocol": "dsi", "into": "own", "decimals": 3,
     "numerator": ("cmj_peak_force", "B"), "denominator": ("imtp_peak_force", "B")},
    {"metric": "eur", "protocol": "eur", "into": "own", "decimals": 3,
     "numerator": ("cmj_height", "B"), "denominator": ("sj_height", "B")},
    {"metric": "wingate_pmax_th", "protocol": "wingate", "into": "measured", "decimals": 2,
     "numerator": ("wingate_pmax", "B"), "denominator": ("body_mass", "B")},
    {"metric": "wingate_pmax_ath", "protocol": "wingate", "into": "measured", "decimals": 2,
     "numerator": ("wingate_pmax", "B"), "denominator": ("lean_mass", "B")},
    {"metric": "wingate_pmin_th", "protocol": "wingate", "into": "measured", "decimals": 2,
     "numerator": ("wingate_pmin", "B"), "denominator": ("body_mass", "B")},
    {"metric": "wingate_work_th", "protocol": "wingate", "into": "measured", "decimals": 1,
     "numerator": ("wingate_work", "B"), "denominator": ("body_mass", "B"), "factor": 1000},
    {"metric": "wingate_work_ath", "protocol": "wingate", "into": "measured", "decimals": 1,
     "numerator": ("wingate_work", "B"), "denominator": ("lean_mass", "B"), "factor": 1000},
]

DERIVED_METRICS = {spec["metric"] for spec in DERIVED}

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
        numerator = _value(values, *spec["numerator"])
        denominator = _value(values, *spec["denominator"])
        metric = MetricDef.objects.filter(code=spec["metric"], organization=None).first()
        if metric is None:
            continue
        valid = numerator is not None and bool(denominator)

        if spec["into"] == "own":
            ref = f"{REF_PREFIX}{spec['metric']}"
            run = ProtocolRun.objects.filter(session=session, external_ref=ref).first()
            if not valid:
                if run:  # vstup zmizel (smazaný test) – odvozená hodnota taky
                    run.delete()
                continue
            protocol = Protocol.objects.filter(code=spec["protocol"], organization=None).first()
            if protocol is None:
                continue
            run = run or ProtocolRun.objects.create(
                session=session, protocol=protocol, external_ref=ref,
                note="Vypočteno automaticky.")
        else:
            run = (session.protocol_runs.filter(protocol__code=spec["protocol"], is_primary=True)
                   .order_by("started_at", "pk").first())
            if run is None:
                continue
            if not valid:
                Measurement.objects.filter(trial__protocol_run=run, metric=metric).delete()
                continue

        trial, _ = Trial.objects.get_or_create(protocol_run=run, number=1)
        value = numerator * spec.get("factor", 1) / denominator
        Measurement.objects.update_or_create(
            trial=trial, metric=metric, side=Side.BILATERAL, mode="", speed=None, segment="",
            defaults={"value": round(value, spec["decimals"]), "note": "vypočteno"},
        )
        saved += 1
    return saved


def recompute_many(sessions) -> int:
    return sum(recompute(s) for s in sessions)
