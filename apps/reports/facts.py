"""
Fakta pro jazykový model.

Model nedostane přístup k databázi ani k surovým datům – dostane tenhle
výtah. Všechno v něm je spočítané pravidly a analytikou a **zaokrouhlené
přesně tak, jak se to smí objevit v textu**. Kontrola čísel pak porovnává
text proti tomuhle výtahu; model tedy nemůže napsat číslo, které tu není.

Sportovec vystupuje pod pseudonymním kódem. Jméno model nikdy nedostane.
"""

from apps.analytics import queries
from apps.analytics.services import find_norm
from apps.catalog.models import ProtocolMetric

from . import narrative
from .results import change_verdict

MAX_METRICS = 20
MAX_ASYMMETRIES = 5


def build(session, findings, citations) -> dict:
    subject = session.subject
    return {
        "sportovec": {
            "kod": subject.code,
            "sport": str(subject.sport) if subject.sport_id else "neuvedeno",
            "pohlavi": subject.get_sex_display().lower(),
            "vek": subject.age,
            "uroven": subject.get_level_display().lower(),
        },
        "datum_mereni": session.date.strftime("%d. %m. %Y"),
        "protokoly": sorted({run.protocol.name for run in session.protocol_runs.all()}),
        "nalezy": [
            {"zavaznost": f.get_severity_display().lower(), "text": f.text}
            for f in findings if not f.suppressed
        ],
        "nalezy_bez_doporuceni": [
            {"text": f.text, "duvod": f.suppressed_reason}
            for f in findings if f.suppressed
        ],
        "doporuceni_z_pravidel": narrative.recommendations(findings),
        "klicove_metriky": _key_metrics(session),
        "asymetrie": _asymmetries(session),
        "cmj_ods": _ods(session),
        "citace": [
            {"cislo": i, "zdroj": str(c["article"]),
             "populace_odpovida": c["population_matches"]}
            for i, c in enumerate(citations, start=1)
        ],
    }


def _key_metrics(session) -> list[dict]:
    """Klíčové metriky dne: hodnota, změna proti minule a srovnání s normou."""
    primary = set(
        ProtocolMetric.objects.filter(is_primary=True).values_list("metric__code", flat=True)
    )
    current = queries.session_metric_values(session)
    previous = queries.previous_session_values(session)

    out = []
    for key, entry in sorted(current.items(), key=lambda kv: kv[1]["metric"].name):
        metric = entry["metric"]
        if metric.code not in primary:
            continue
        d = metric.decimals
        item = {
            "metrika": metric.name,
            "upresneni": _qualifiers(entry),
            "hodnota": round(entry["value"], d),
            "jednotka": metric.unit,
        }

        before = previous.get(key)
        if before is not None:
            delta = entry["value"] - before["value"]
            item["predchozi_hodnota"] = round(before["value"], d)
            # Rozdíl zaokrouhlených hodnot, ne zaokrouhlený rozdíl: čtenář
            # si ho ověří odečtením čísel, která vidí (37,5 − 36,9 = 0,6).
            item["zmena"] = round(item["hodnota"] - item["predchozi_hodnota"], d)
            if metric.mdc is None:
                item["zmena_posouzeni"] = "nelze posoudit, metrika nemá stanovenou MDC"
            elif metric.change_is_real(delta):
                smer, _ = change_verdict(metric, delta)
                smer = "posun" if smer == "skutečný posun" else smer
                item["zmena_posouzeni"] = f"{smer} přesahující chybu měření"
                item["mdc"] = round(metric.mdc, d)
            else:
                item["zmena_posouzeni"] = "v pásmu chyby měření, bez prokazatelného posunu"
                item["mdc"] = round(metric.mdc, d)

        norm = find_norm(metric, session.subject, side=entry["side"],
                         mode=entry["mode"], speed=entry["speed"])
        if norm is not None and (z := norm.z_score(entry["value"])) is not None:
            item["z_skore_vuci_norme"] = round(z, 1)
            item["norma_prumer"] = round(norm.mean, d)

        out.append(item)
        if len(out) >= MAX_METRICS:
            break
    return out


def _ods(session) -> dict | None:
    """Výsledek – příčina – strategie u CMJ, aby model uměl říct, proč se výška změnila."""
    from .results import protocol_results

    for block in protocol_results(session):
        if not block["ods"]:
            continue
        out = {"interpretace": block["ods"]["text"]}
        for group in block["ods"]["groups"]:
            items = []
            for row in group["rows"]:
                d = row["metric"].decimals
                item = {"metrika": row["metric"].name, "hodnota": round(row["value"], d),
                        "jednotka": row["metric"].unit}
                if row["verdict"]:
                    item["zmena_posouzeni"] = row["verdict"]
                    item["zmena"] = float(row["delta_txt"].replace("−", "-").replace(",", "."))
                items.append(item)
            out[group["role"]] = items
        return out
    return None


def _asymmetries(session, threshold_pct: float = 10.0) -> list[dict]:
    rows = sorted(queries.session_asymmetries(session, threshold_pct=threshold_pct),
                  key=lambda r: abs(r["index_pct"]), reverse=True)[:MAX_ASYMMETRIES]
    return [
        {
            "metrika": r["metric"].name,
            "upresneni": _qualifiers(r["qualifiers"]),
            "rozdil_procent": round(abs(r["index_pct"]), 1),
            # „vyšší“, ne „silnější“: u stability (plocha CoP) nebo časů je
            # vyšší hodnota horší, takže „silnější strana“ by lhala.
            "vyssi_hodnota": "vlevo" if r["index_pct"] > 0 else "vpravo",
            "nad_prahem": r["exceeds_threshold"],
            "prah_procent": round(threshold_pct),
        }
        for r in rows
    ]


def _qualifiers(q: dict) -> str:
    from apps.measurements.models import Mode, Side

    bits = []
    if q.get("segment"):
        bits.append(q["segment"])
    side = q.get("side")
    if side and side != Side.BILATERAL:
        bits.append(Side(side).label.lower())
    if q.get("mode"):
        bits.append(Mode(q["mode"]).label.lower())
    if q.get("speed") is not None:
        bits.append(f"{q['speed']:g} °/s")
    return ", ".join(bits)
