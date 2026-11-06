"""
Fakta pro jazykový model.

Model nedostane přístup k databázi ani k surovým datům – dostane tenhle
výtah. Všechno v něm je spočítané pravidly a analytikou a **zaokrouhlené
přesně tak, jak se to smí objevit v textu**. Kontrola čísel pak porovnává
text proti tomuhle výtahu; model tedy nemůže napsat číslo, které tu není.

Sportovec vystupuje pod pseudonymním kódem. Jméno model nikdy nedostane.
"""

from apps.analytics import queries
from apps.analytics.services import NormIndex, find_norm
from apps.catalog.models import ProtocolMetric

from . import narrative
from .results import change_verdict

MAX_METRICS = 20
MAX_ASYMMETRIES = 5


def build(session, findings, citations, *, audience=None) -> dict:
    from .models import Audience

    subject = session.subject
    return {
        "ctenar": Audience(audience or Audience.COACH).label.lower(),
        "kontext": _context(session),
        "sportovec": {
            "kod": subject.code,
            "sport": str(subject.sport) if subject.sport_id else "neuvedeno",
            "pohlavi": subject.get_sex_display().lower(),
            "vek": subject.age_on(session.date),
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
        "cile": _goals(session),
        "vyvoj": _trends(session),
        "asymetrie": _asymmetries(session),
        "cmj_ods": _ods(session),
        "podminky": _conditions(session),
        "rpe": _rpe(session),
        "citace": [_citation(c, i) for i, c in enumerate(citations, start=1)],
    }


def _citation(item: dict, index: int) -> dict:
    """
    Článek pro model: co zjistil a s jakými omezeními – shrnutí, které
    ověřil člověk, ne celý abstrakt. Jen vyplněná pole.
    """
    article = item["article"]
    out = {"cislo": item.get("number", index), "zdroj": str(article)}
    if reason := item.get("reason"):
        out["proc_je_tu"] = reason
    if article.evidence_level:
        out["uroven_dukazu"] = article.get_evidence_level_display().lower()
    if finding := (article.key_finding or article.curator_note).strip():
        out["hlavni_zjisteni"] = finding
    if article.limitations.strip():
        out["omezeni"] = article.limitations.strip()
    if population := article.population_text():
        out["populace_studie"] = population
    out["populace_odpovida"] = item["population_matches"]
    return out


def _context(session) -> dict:
    """
    Proč se testovalo: cíl a období z objednávky (nebo z testovacího dne)
    a zranění, které uvedl klient. Jen to, co je vyplněné.
    """
    from django.conf import settings

    out = {}
    if session.season_phase:
        out["treninkove_obdobi"] = session.get_season_phase_display().lower()
    try:
        from apps.booking.models import Participant
    except ImportError:  # objednávky nejsou nainstalované
        return out
    participant = (Participant.objects.filter(session=session).select_related("request")
                   .first())
    if participant is None:
        return out
    request = participant.request
    out["cil_testovani"] = request.get_goal_display().lower()
    if request.goal_note.strip():
        out["cil_upresneni"] = request.goal_note.strip()
    if request.season_phase and "treninkove_obdobi" not in out:
        out["treninkove_obdobi"] = request.get_season_phase_display().lower()
    if settings.IDENTITY_ENCRYPTION_KEY:
        try:
            if injury := participant.injury.strip():
                out["zraneni_uvedene_klientem"] = injury
        except Exception:  # jiný klíč – raději bez zranění než pád zprávy
            pass
    return out


def _norm_words(z: float, metric) -> str:
    """Slovně, ať model nemusí z-skóre vykládat sám (a vykládá ho stejně)."""
    from apps.catalog.models import Direction

    if -1 <= z <= 1:
        return "v pásmu běžném pro srovnatelnou populaci"
    above = z > 1
    if metric.direction == Direction.HIGHER:
        return "nad normou (příznivě)" if above else "pod normou (nepříznivě)"
    if metric.direction == Direction.LOWER:
        return "nad normou (nepříznivě)" if above else "pod normou (příznivě)"
    return "nad normou" if above else "pod normou"


MAX_TREND_POINTS = 5


def _trends(session) -> list[dict]:
    """Vývoj klíčových metrik za víc měření (jen řady se třemi a víc body)."""
    from .results import trend_series

    out = []
    for series in trend_series(session, limit=8):
        points = series["points"][-MAX_TREND_POINTS:]
        if len(points) < 3:
            continue
        metric = series["metric"]
        out.append({
            "metrika": metric.name,
            "upresneni": _qualifiers(series["qualifiers"]),
            "jednotka": metric.unit,
            "mereni": [{"datum": day.strftime("%d. %m. %Y"),
                        "hodnota": round(value, metric.decimals)} for day, value in points],
        })
    return out


def _conditions(session) -> dict:
    """Prostředí a stav sportovce – jen to, co je vyplněné."""
    out = {}
    if session.temperature_c is not None:
        out["teplota_c"] = round(session.temperature_c, 1)
    if session.humidity_pct is not None:
        out["vlhkost_procent"] = round(session.humidity_pct)
    if session.fatigue_rating:
        out["subjektivni_unava_1_10"] = session.fatigue_rating
    if session.season_phase:
        out["faze_sezony"] = session.get_season_phase_display().lower()
    return out


def _rpe(session) -> list[dict]:
    """Vnímané úsilí (RPE) po testech nebo za celý den."""
    from apps.measurements import questionnaires

    out = []
    for item in questionnaires.summary(session):
        if item["questionnaire"].code != questionnaires.RPE:
            continue
        for a in item["answers"]:
            out.append({"po_testu": item["after"] or "celý testovací den",
                        "hodnota": a["value"], "skala": f"0–{a['max']}",
                        "slovne": a["label"]})
    return out


def _assessment(metric, delta: float) -> str:
    """Slovní posouzení změny proti MDC – stejná slova pro minule, sezónu i období."""
    if metric.mdc is None:
        return "nelze posoudit, metrika nemá stanovenou MDC"
    if metric.change_is_real(delta):
        smer, _ = change_verdict(metric, delta)
        smer = "posun" if smer == "skutečný posun" else smer
        return f"{smer} přesahující chybu měření"
    return "v pásmu chyby měření, bez prokazatelného posunu"


def _series_of_day(session) -> dict:
    """Řady klíčových metrik končící tímto dnem – pro srovnání se sezónou a maximem."""
    out = {}
    for s in queries.primary_metric_series(session.subject, limit_metrics=50, until=session.date):
        if s["points"][-1][0] != session.date:
            continue
        q = s["qualifiers"]
        out[(s["metric"].code, q["side"], q["mode"], q["speed"], q["segment"])] = s["points"]
    return out


def _long_term(metric, points, value, sport) -> dict:
    """Od začátku sezóny, osobní maximum a vývoj za 12 měsíců – do položky klíčové metriky."""
    from apps.analytics.compare import compare

    d = metric.decimals
    cmp = compare(metric, points, sport=sport)
    item = {}
    if cmp["season"]:
        c = cmp["season"]
        item["od_zacatku_sezony"] = {
            "prvni_mereni": c["date"].strftime("%d. %m. %Y"), "hodnota": round(c["value"], d),
            "zmena": round(round(value, d) - round(c["value"], d), d),
            "posouzeni": _assessment(metric, value - c["value"]),
        }
    elif cmp["season_first"]:
        item["od_zacatku_sezony"] = "první měření v sezóně"
    if cmp["best"]:
        b = cmp["best"]
        item["osobni_maximum"] = {"hodnota": round(b["value"], d),
                                  "datum": b["date"].strftime("%d. %m. %Y"), "stav": b["state"]}
    if cmp["period"]:
        pr = cmp["period"]
        item["za_12_mesicu"] = {
            "zmena": round(round(value, d) - round(pr["value"], d), d), "procent": pr["pct"],
            "pocet_mereni": pr["count"], "posouzeni": _assessment(metric, value - pr["value"]),
        }
    return item


def _goals(session) -> list[dict]:
    """Cíle sportovce k datu měření: cíl, aktuální hodnota, kolik zbývá a posouzení proti MDC."""
    from apps.subjects import goals as goals_module

    out = []
    for p in goals_module.goals_for(session.subject, until=session.date, today=session.date):
        if p.current is None:
            continue
        d = p.metric.decimals
        item = {"metrika": p.metric.name, "jednotka": p.metric.unit, "cil": round(p.target, d),
                "aktualni": round(p.current, d), "zbyva": p.remaining_shown,
                "posouzeni": p.verdict()}
        if p.goal.due_date:
            item["do"] = p.goal.due_date.strftime("%d. %m. %Y")
        if p.reached_on:
            item["splneno"] = p.reached_on.strftime("%d. %m. %Y")
        out.append(item)
    return out


def _key_metrics(session) -> list[dict]:
    """Klíčové metriky dne: hodnota, změna proti minule, sezóna a maximum, srovnání s normou."""
    primary = set(
        ProtocolMetric.objects.filter(is_primary=True).values_list("metric__code", flat=True)
    )
    current = queries.session_metric_values(session)
    previous = queries.previous_session_values(session)
    series = _series_of_day(session)
    norms = NormIndex()

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
            item["zmena_posouzeni"] = _assessment(metric, delta)
            if metric.mdc is not None:
                item["mdc"] = round(metric.mdc, d)
        if (points := series.get(key)) and len(points) > 1:
            item.update(_long_term(metric, points, entry["value"], session.subject.sport))

        norm = find_norm(metric, session.subject, side=entry["side"],
                         mode=entry["mode"], speed=entry["speed"], day=session.date,
                         norms=norms)
        if norm is not None and (z := norm.z_score(entry["value"])) is not None:
            item["z_skore_vuci_norme"] = round(z, 1)
            item["norma_prumer"] = round(norm.mean, d)
            item["vuci_norme"] = _norm_words(z, metric)

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
