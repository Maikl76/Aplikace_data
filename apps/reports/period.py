"""
Souhrnná zpráva za období.

Jeden druh zprávy přes víc testovacích dnů sportovce: klíčové ukazatele
od prvního k poslednímu měření v období (posouzení proti MDC jako jinde),
nejlepší hodnota v období, hodnoty po měřeních, grafy vývoje, cíle
a doporučení z vydaných zpráv v období i s tím, jak se plnila. Pravidla se
tu znovu nevyhodnocují – nálezy patří ke dnům; souhrn říká, kam se to
za období posunulo.
"""

import logging

from django.db import transaction
from django.utils import timezone

from apps.analytics import compare
from apps.analytics.charts import cz, qualifier_label
from apps.analytics.queries import primary_metric_series
from apps.catalog.models import Direction
from apps.measurements.models import TestSession

from . import followup, narrative, svg
from .models import Audience, RecommendationReview, Report
from .results import change_verdict, signed

logger = logging.getLogger(__name__)

MAX_SERIES = 12

TITLES = {
    Audience.ATHLETE: "Souhrnná zpráva z funkčního testování za období",
    Audience.COACH: "Souhrnná zpráva za období pro trenéra",
    Audience.CLINICIAN: "Souhrnná zpráva za období pro lékaře / fyzioterapeuta",
}


def sessions_in(subject, date_from, date_to) -> list:
    """Testovací dny v období, které mají hodnoty, od nejstaršího."""
    return list(TestSession.objects.filter(subject=subject, date__gte=date_from, date__lte=date_to,
                                           protocol_runs__trials__measurements__isnull=False)
                .distinct().order_by("date").prefetch_related("protocol_runs__protocol"))


def series_in(subject, date_from, date_to) -> list[dict]:
    """Řady klíčových ukazatelů s body jen z období; na ukazatel jedna (přednostně celek)."""
    chosen = {}
    for s in primary_metric_series(subject, limit_metrics=60, until=date_to):
        points = [(d, v) for d, v in s["points"] if date_from <= d <= date_to]
        if not points:
            continue
        code, side = s["metric"].code, s["qualifiers"]["side"]
        if code not in chosen or (side in ("B", "")
                                  and chosen[code]["qualifiers"]["side"] not in ("B", "")):
            chosen[code] = {**s, "points": points}
    return list(chosen.values())[:MAX_SERIES]


def overview(subject, date_from, date_to, *, goals=None) -> list[dict]:
    """Klíčové ukazatele za období: první a poslední hodnota, změna, nejlepší, cíl."""
    from apps.subjects import goals as goals_module

    if goals is None:
        goals = goals_module.by_metric(goals_module.goals_for(subject, until=date_to, today=date_to))
    rows = []
    for s in series_in(subject, date_from, date_to):
        metric, points = s["metric"], s["points"]
        d = metric.decimals
        (first_day, first), (last_day, last) = points[0], points[-1]
        row = {
            "metric": metric, "label": qualifier_label(s["qualifiers"]), "qualifiers": s["qualifiers"],
            "unit": "" if metric.unit in ("", "-") else metric.unit, "norm": s["norm"],
            "first": first, "first_day": first_day, "first_txt": cz(first, d),
            "last": last, "last_day": last_day, "last_txt": cz(last, d),
            "count": len(points), "points": points, "delta": None, "delta_txt": "",
            "verdict": "", "kind": "", "best": None, "best_txt": "", "best_day": None,
            "goal": goals.get(metric.pk),
        }
        if len(points) >= 2:
            row["delta"] = last - first
            row["delta_txt"] = signed(round(last, d) - round(first, d), d)
            row["verdict"], row["kind"] = change_verdict(metric, last - first)
        if metric.direction in (Direction.HIGHER, Direction.LOWER):
            pick = max if metric.direction == Direction.HIGHER else min
            best = pick(v for _, v in points)
            row["best"], row["best_txt"] = best, cz(best, d)
            row["best_day"] = max(day for day, v in points if v == best)
        rows.append(row)
    return rows


def matrix(rows, sessions) -> dict:
    """Hodnoty po měřeních: ukazatel × den."""
    dates = [s.date for s in sessions]
    out = []
    for row in rows:
        by_day = dict(row["points"])
        out.append({"metric": row["metric"], "label": row["label"], "unit": row["unit"],
                    "cells": [cz(by_day[day], row["metric"].decimals) if day in by_day else ""
                              for day in dates]})
    return {"dates": dates, "rows": out}


def recommendations_in(subject, date_from, date_to, *, audience=None) -> list[dict]:
    """Vydané zprávy z měření v období, jejich doporučení a poslední posouzení plnění."""
    reports = (Report.objects.filter(subject=subject, kind=Report.Kind.TESTING,
                                     status=Report.Status.RELEASED, session__date__gte=date_from,
                                     session__date__lte=date_to)
               .select_related("session").order_by("session__date", "audience"))
    by_session = {}
    for report in reports:      # jedna zpráva na den; přednost má zpráva pro téhož čtenáře
        current = by_session.get(report.session_id)
        if current is None or (audience and report.audience == audience
                               and current.audience != audience):
            by_session[report.session_id] = report
    out = []
    for report in by_session.values():
        items = followup.items(report)
        if not items:
            continue
        reviews = {}
        for review in (RecommendationReview.objects.filter(report=report)
                       .select_related("session").order_by("session__date")):
            reviews[review.index] = review
        rows = []
        for item in items:
            review = reviews.get(item["index"])
            rows.append({"text": item["text"], "status": review.status if review else "",
                         "label": review.get_status_display() if review else "",
                         "note": review.note if review else "",
                         "reviewed_on": review.session.date if review else None})
        out.append({"report": report, "date": report.session.date, "rows": rows})
    return out


# ---------------------------------------------------------------------------
# Fakta a text
# ---------------------------------------------------------------------------

def facts(report) -> dict:
    """Fakta pro model a pro kontrolu čísel – vše zaokrouhlené tak, jak se smí objevit v textu."""
    from . import facts as facts_module

    subject = report.subject
    date_from, date_to = report.period_from, report.period_to
    sessions = sessions_in(subject, date_from, date_to)
    rows = overview(subject, date_from, date_to)
    metrics = []
    for row in rows:
        metric, d = row["metric"], row["metric"].decimals
        item = {"metrika": metric.name, "upresneni": facts_module._qualifiers(row["qualifiers"]),
                "jednotka": metric.unit,
                "prvni": {"datum": row["first_day"].strftime("%d. %m. %Y"),
                          "hodnota": round(row["first"], d)},
                "posledni": {"datum": row["last_day"].strftime("%d. %m. %Y"),
                             "hodnota": round(row["last"], d)},
                "pocet_mereni": row["count"]}
        if row["delta"] is not None:
            item["zmena"] = round(round(row["last"], d) - round(row["first"], d), d)
            item["posouzeni"] = facts_module._assessment(metric, row["delta"])
        if row["best"] is not None:
            item["nejlepsi"] = {"hodnota": round(row["best"], d),
                                "datum": row["best_day"].strftime("%d. %m. %Y")}
        metrics.append(item)
    goals = []
    from apps.subjects import goals as goals_module

    for p in goals_module.goals_for(subject, until=date_to, today=date_to):
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
        goals.append(item)
    recommendations = []
    for block in recommendations_in(subject, date_from, date_to, audience=report.audience):
        for row in block["rows"]:
            recommendations.append({"zprava": block["report"].report_number,
                                    "datum": block["date"].strftime("%d. %m. %Y"),
                                    "text": row["text"],
                                    "plneni": row["label"] if row["status"] else "neposouzeno"})
    return {
        "ctenar": Audience(report.audience).label.lower(),
        "druh": "souhrn za období",
        "sportovec": {"kod": subject.code, "sport": str(subject.sport) if subject.sport_id else "neuvedeno",
                      "pohlavi": subject.get_sex_display().lower(), "vek": subject.age_on(date_to),
                      "uroven": subject.get_level_display().lower()},
        "obdobi": {"od": date_from.strftime("%d. %m. %Y"), "do": date_to.strftime("%d. %m. %Y"),
                   "pocet_mereni": len(sessions),
                   "dny_mereni": [s.date.strftime("%d. %m. %Y") for s in sessions],
                   "testy": sorted({run.protocol.name for s in sessions
                                    for run in s.protocol_runs.all()})},
        "klicove_ukazatele": metrics,
        "cile": goals,
        "doporuceni_v_obdobi": recommendations,
    }


def _unit(item: dict) -> str:
    return f" {item['jednotka']}" if item["jednotka"] and item["jednotka"] != "-" else ""


def compose(data: dict) -> str:
    """Souhrn za období ze šablony – bez jazykového modelu."""
    cz_ = narrative._cz
    period = data["obdobi"]
    n = period["pocet_mereni"]
    parts = [f"Souhrn za období od {period['od']} do {period['do']}: {n} "
             f"{narrative.plural(n, 'měření', 'měření', 'měření')}"
             + (f" ({', '.join(period['testy'])})" if period["testy"] else "") + "."]
    lines = []
    for m in data["klicove_ukazatele"]:
        name = m["metrika"] + (f" ({m['upresneni']})" if m["upresneni"] else "")
        unit = _unit(m)
        if "zmena" in m:
            sign = "+" if m["zmena"] > 0 else ""
            line = (f"• {name}: {cz_(m['prvni']['hodnota'])}{unit} ({m['prvni']['datum']}) → "
                    f"{cz_(m['posledni']['hodnota'])}{unit} ({m['posledni']['datum']}), změna "
                    f"{sign}{cz_(m['zmena'])}{unit} – {m['posouzeni']}")
            if "nejlepsi" in m and m["nejlepsi"]["datum"] != m["posledni"]["datum"]:
                line += f"; nejlepší v období {cz_(m['nejlepsi']['hodnota'])}{unit} ({m['nejlepsi']['datum']})"
        else:
            line = (f"• {name}: jediné měření v období, {cz_(m['posledni']['hodnota'])}{unit} "
                    f"({m['posledni']['datum']})")
        lines.append(line)
    if lines:
        parts.append("Klíčové ukazatele od prvního k poslednímu měření v období:\n" + "\n".join(lines))
    if data["cile"]:
        parts.append("Cíle:\n" + "\n".join(narrative._goal_line(c) for c in data["cile"]))
    if data["doporuceni_v_obdobi"]:
        parts.append("Doporučení z vydaných zpráv v období a jejich plnění:\n" + "\n".join(
            f"• {r['zprava']} ({r['datum']}): {r['text']} – {r['plneni']}"
            for r in data["doporuceni_v_obdobi"]))
    parts.append("Hodnoty po jednotlivých měřeních a grafy vývoje jsou v tabulkách níže.")
    return "\n\n".join(parts)


def compose_report(report, *, model=None) -> narrative.Composition:
    """Text souhrnu: model, když je zapnutý a nenapíše číslo bez opory; jinak šablona."""
    from . import llm, prompts

    data = facts(report)
    fallback = compose(data)
    if not llm.is_enabled():
        return narrative.Composition(text=fallback, source="šablona", facts=data)
    try:
        draft = narrative.generate(
            None, [], data, audience=report.audience, model=model,
            system=prompts.period_system_prompt(report.organization, report.audience))
    except llm.LLMError as exc:
        logger.warning("Model se pro souhrn %s nepoužil: %s", report.subject.code, exc)
        return narrative.Composition(text=fallback, source="šablona", facts=data,
                                     note=f"Jazykový model se nepoužil: {exc}")
    if not draft.problems:
        return narrative.Composition(
            text=draft.text, source=draft.model, facts=data,
            note=(f"Text sestavil model {draft.model} za {draft.seconds:.0f} s"
                  + (" (na druhý pokus)." if draft.attempts == 2 else ".")))
    reason = f"obsahoval čísla, která v datech nejsou ({', '.join(draft.problems[:5])})"
    return narrative.Composition(
        text=fallback, source="šablona", facts=data,
        note=f"Text od modelu {draft.model} byl odmítnut: {reason}. Použita šablona.")


# ---------------------------------------------------------------------------
# Koncept a podklad pro zobrazení
# ---------------------------------------------------------------------------

@transaction.atomic
def build_draft(subject, *, date_from, date_to, user, audience=None, model=None,
                supersedes=None) -> Report:
    """Koncept souhrnu za období; potřebuje aspoň dvě měření s hodnotami."""
    from django.conf import settings

    from . import llm, services

    if audience not in Audience.values:
        audience = supersedes.audience if supersedes else Audience.COACH
    if date_from > date_to:
        raise services.ReportError("Období: datum „od“ musí být před datem „do“.")
    sessions = sessions_in(subject, date_from, date_to)
    if len(sessions) < 2:
        raise services.ReportError(
            f"V období {date_from:%d.%m.%Y} – {date_to:%d.%m.%Y} má sportovec "
            f"{len(sessions)} měření s hodnotami; souhrn za období potřebuje aspoň dvě.")
    type(subject.organization).objects.select_for_update().get(pk=subject.organization_id)

    report = Report(
        organization=subject.organization, subject=subject, kind=Report.Kind.PERIOD,
        period_from=date_from, period_to=date_to,
        report_number=services.next_report_number(subject.organization),
        version=(supersedes.version + 1) if supersedes else 1, supersedes=supersedes,
        audience=audience, show_name=supersedes.show_name if supersedes else False,
        title=TITLES[audience], literature=[],
    )
    background = llm.is_enabled() and settings.LLM_BACKGROUND
    if background:
        data = facts(report)
        composition = narrative.Composition(text=compose(data), source="šablona", facts=data)
    else:
        composition = compose_report(report, model=model)
    if problems := narrative.verify_numbers(composition.text, [], composition.facts):
        raise services.ReportError(
            f"Text souhrnu obsahuje čísla bez opory ve výsledcích: {', '.join(problems)}.")
    report.summary = report.summary_generated = composition.text
    report.llm_model, report.generation_note = composition.source, composition.note
    report.input_fingerprint = report.compute_fingerprint({
        "subject": subject.code, "od": date_from.isoformat(), "do": date_to.isoformat(),
        "sessions": [s.pk for s in sessions]})
    if background:
        services._mark_writing(report, model)
    report.save()
    if background:
        services._start_writing(report, model, rewrite=False)
    return report


def context(report) -> dict:
    """Podklad pro náhled, PDF i stránku zprávy (stejné klíče jako zpráva z měření)."""
    from apps.subjects import goals as goals_module

    from . import services

    subject = report.subject
    date_from, date_to = report.period_from, report.period_to
    sessions = sessions_in(subject, date_from, date_to)
    progress = goals_module.goals_for(subject, until=date_to, today=date_to)
    rows = overview(subject, date_from, date_to, goals=goals_module.by_metric(progress))
    season_from = compare.season_start(date_to, subject.sport)
    trends = [{
        "title": r["metric"].name, "label": r["label"], "unit": r["metric"].unit,
        "svg": svg.trend_svg(r["metric"], r["points"], norm=r["norm"],
                             goal=r["goal"].target if r["goal"] else None, season_from=season_from),
        "caption": svg.trend_caption(r["metric"], r["points"]), "norm": r["norm"],
    } for r in rows if len(r["points"]) >= 2]
    texts, seen = [], set()
    if report.audience != Audience.CLINICIAN:
        for r in rows:
            metric = r["metric"]
            text = (metric.athlete_text if report.audience == Audience.ATHLETE
                    else metric.coach_text or metric.athlete_text)
            if text and metric.pk not in seen:
                seen.add(metric.pk)
                texts.append((metric.name, text))
    return {
        "report": report, "session": None, "subject": subject,
        "display_name": services.subject_name(report), "age": subject.age_on(date_to),
        "genetic_context": None, "findings": [], "suppressed": [], "recommendations": [],
        "citations": [], "population_warnings": [], "generated_at": timezone.now(),
        "results": [], "trends": trends, "asymmetries": [], "asymmetry_threshold": 0,
        "period": {"from": date_from, "to": date_to, "sessions": sessions,
                   "protocols": sorted({run.protocol.name for s in sessions
                                        for run in s.protocol_runs.all()})},
        "overview": rows, "matrix": matrix(rows, sessions),
        "goals": [p for p in progress if p.current is not None],
        "period_recommendations": recommendations_in(subject, date_from, date_to,
                                                     audience=report.audience),
        "season_phrase": compare.season_phrase(subject.sport), "metric_texts": texts,
    }
