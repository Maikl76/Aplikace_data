"""
Generování a vydávání zprávy.

Zpráva vzniká ve třech krocích a jen ten poslední je nevratný:

1. **koncept** – vyhodnotí se pravidla, připojí evidence, složí text
2. **vydání** – vědomý krok s potvrzením; od té chvíle se zpráva needituje
3. **předání** – záznam o tom, co komu kdy odešlo

Vydanou zprávu nelze změnit ani stáhnout zpět: jakmile ji převezme
poskytovatel zdravotních služeb, stává se součástí jeho dokumentace.
Oprava se proto řeší vydáním nové verze, která tu starou nahrazuje.
"""

import json
import logging

from django.core.files.base import ContentFile
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from apps.rules import engine, evidence
from apps.subjects.models import Consent

from . import narrative, results, svg
from .models import Audience, ModelTrial, Report, ReportDelivery

logger = logging.getLogger(__name__)


class ReportError(Exception):
    """Zprávu nelze vydat nebo předat – uživatel se musí dozvědět proč."""


def next_report_number(organization) -> str:
    year = timezone.localdate().year
    prefix = f"FT-{year}-"
    last = (Report.objects.filter(organization=organization,
                                  report_number__startswith=prefix)
            .order_by("-report_number").values_list("report_number", flat=True).first())
    counter = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{counter:04d}"


@transaction.atomic
def build_draft(session, *, user, supersedes: Report | None = None,
                audience: str | None = None, model: str | None = None) -> Report:
    """
    Vyhodnotí pravidla a složí koncept zprávy pro zvoleného čtenáře.

    Je-li zapnutý model a psaní na pozadí, zpráva vznikne hned se souhrnem
    ze šablony a model ho přepíše, až dopíše (stránka na něj nečeká).
    """
    from django.conf import settings

    from . import llm

    if audience not in Audience.values:
        audience = supersedes.audience if supersedes else Audience.COACH
    findings = engine.evaluate_session(session)
    citations = evidence.report_citations(session, findings)
    background = llm.is_enabled() and settings.LLM_BACKGROUND
    if background:
        from . import facts as facts_module

        facts = facts_module.build(session, findings, citations, audience=audience)
        composition = narrative.Composition(
            text=narrative.compose(session, findings, citations, facts), source="šablona",
            facts=facts)
    else:
        composition = narrative.compose_report(session, findings, citations,
                                               audience=audience, model=model)
    text = composition.text

    # Poslední pojistka: kontrola čísel nad finálním textem, proti týmž
    # datům, která dostal model. Kdyby kontrolovala méně dat než model
    # viděl, odmítla by i správný text zmiňující třeba věk nebo datum.
    if problems := narrative.verify_numbers(text, findings, composition.facts):
        logger.error("Zpráva pro %s obsahuje nepodložená čísla: %s",
                     session.subject.code, problems)
        raise ReportError(
            f"Text zprávy obsahuje čísla bez opory v nálezech: {', '.join(problems)}. "
            f"Zpráva se nevydá, dokud se to nevyřeší."
        )

    report = Report(
        organization=session.organization,
        subject=session.subject,
        session=session,
        report_number=next_report_number(session.organization),
        version=(supersedes.version + 1) if supersedes else 1,
        supersedes=supersedes,
        audience=audience,
        title=TITLES[audience],
        summary=text,
        summary_generated=text,
        rules_version=_rules_fingerprint(findings),
        llm_model=composition.source,
        generation_note=composition.note,
        literature=[c["article"].pk for c in citations],
    )
    report.input_fingerprint = report.compute_fingerprint(_inputs(session, findings))
    if background:
        _mark_writing(report, model)
    report.save()
    if background:
        _start_writing(report, model, rewrite=False)
    return report


# ---------------------------------------------------------------------------
# Psaní souhrnu modelem (na pozadí) a přepsání jiným modelem
# ---------------------------------------------------------------------------

def _mark_writing(report, model):
    from .ai_models import default_model

    report.writing = Report.Writing.RUNNING
    report.writing_model = model or default_model()
    report.writing_started_at = timezone.now()


def _start_writing(report, model, *, rewrite: bool):
    """Na pozadí ve vlákně; bez LLM_BACKGROUND (testy) hned."""
    from django.conf import settings

    if not settings.LLM_BACKGROUND:
        write_summary(report.pk, model, rewrite=rewrite)
        return
    import threading

    def run():
        from django.db import connection

        try:
            write_summary(report.pk, model, rewrite=rewrite)
        except Exception as exc:  # nic nesmí nechat zprávu viset ve stavu „píše“
            logger.exception("Psaní souhrnu zprávy %s selhalo", report.pk)
            Report.objects.filter(pk=report.pk).update(
                writing=Report.Writing.NONE,
                generation_note=f"Psaní souhrnu selhalo: {exc}"[:500])
        finally:
            connection.close()

    transaction.on_commit(lambda: threading.Thread(target=run, daemon=True).start())


def write_summary(report_pk, model, *, rewrite: bool) -> Report:
    """
    Model napíše souhrn zprávy. Při přepsání (``rewrite``) se dosavadní text
    uloží do historie zprávy a nahradí se jen tehdy, když model uspěje –
    jinak zůstane, jak byl, a do poznámky se zapíše proč.
    """
    report = Report.objects.select_related("session", "subject").get(pk=report_pk)
    session = report.session
    findings = list(session.findings.select_related("rule"))
    citations = evidence.report_citations(session, findings, frozen=report.literature)
    composition = narrative.compose_report(session, findings, citations,
                                           audience=report.audience, model=model)
    report.refresh_from_db()
    if not report.is_editable:
        return report
    failed = composition.source == "šablona"
    if rewrite and failed:
        report.generation_note = (f"Přepsání se nepovedlo, souhrn zůstal: "
                                  f"{composition.note}")[:1000]
    else:
        if rewrite:
            ModelTrial.objects.create(
                report=report, audience=report.audience,
                model=report.llm_model + (" – upraveno diagnostikem"
                                          if report.summary_edited else ""),
                text=report.summary)
        report.summary = composition.text
        report.summary_generated = composition.text
        report.summary_edited = False
        report.llm_model = composition.source
        report.generation_note = composition.note
    report.writing = Report.Writing.NONE
    report.save(update_fields=["summary", "summary_generated", "summary_edited", "llm_model",
                               "generation_note", "writing"])
    return report


def rewrite_summary(report, *, model: str | None) -> None:
    """Napsat souhrn znovu (jiným) modelem; dosavadní text zůstane v historii."""
    from . import llm

    if not report.is_editable:
        raise ReportError("Vydanou zprávu nelze upravit – vytvořte novou verzi.")
    if not llm.is_enabled():
        raise ReportError("Jazykový model není zapnutý (LLM_ENABLED).")
    if report.is_writing:
        raise ReportError("Model už souhrn píše – počkejte, až dopíše.")
    if report.session is None:
        raise ReportError("Zpráva nemá testovací den.")
    _mark_writing(report, model)
    report.save(update_fields=["writing", "writing_model", "writing_started_at"])
    _start_writing(report, model, rewrite=True)


def clear_stalled(report) -> bool:
    """Psaní, které se nedokončilo (restart aplikace) – uvolnit zprávu."""
    if not report.writing_stalled:
        return False
    report.writing = Report.Writing.NONE
    report.generation_note = ("Psaní souhrnu modelem se nedokončilo (aplikace se mezitím "
                              "restartovala nebo model neodpověděl). Souhrn zůstal, jak byl.")
    report.save(update_fields=["writing", "generation_note"])
    return True


TITLES = {
    Audience.ATHLETE: "Zpráva z funkčního testování",
    Audience.COACH: "Zpráva z funkčního testování pro trenéra",
    Audience.CLINICIAN: "Zpráva z funkčního testování pro lékaře / fyzioterapeuta",
}


def _rules_fingerprint(findings) -> str:
    """Které verze pravidel zprávu vyrobily – kvůli rekonstrukci."""
    used = sorted({f"{f.rule.code}@{f.rule_version}" for f in findings})
    return ",".join(used)[:40]


def _inputs(session, findings) -> dict:
    return {
        "session": session.pk,
        "date": session.date,
        "subject": session.subject.code,
        "findings": sorted((f.rule.code, json.dumps(f.values, sort_keys=True))
                           for f in findings),
    }


def report_context(report) -> dict:
    """Podklad pro náhled i pro PDF – jedno místo, jeden obsah."""
    session = report.session
    findings = list(session.findings.select_related("rule").all()) if session else []
    findings.sort(key=engine.severity_order)
    citations = []
    if session is not None:
        citations = evidence.shown_citations(
            evidence.report_citations(session, findings, frozen=report.literature),
            report.summary, report.custom_note)
    active = [f for f in findings if not f.suppressed]

    context = {
        "report": report,
        "session": session,
        "subject": report.subject,
        "findings": active,
        "suppressed": [f for f in findings if f.suppressed],
        "recommendations": narrative.recommendations(active),
        "citations": citations,
        "population_warnings": evidence.population_warnings(citations),
        "generated_at": timezone.now(),
        "results": [],
        "trends": [],
        "asymmetries": [],
        "asymmetry_threshold": results.ASYMMETRY_THRESHOLD_PCT,
    }
    if session is None:
        return context

    context["results"] = results.protocol_results(session)
    context["conditions"] = results.session_conditions(session)
    context["trends"] = [
        {
            "title": s["metric"].name,
            "label": results.qualifier_label(s["qualifiers"]),
            "unit": s["metric"].unit,
            "svg": svg.trend_svg(s["metric"], s["points"], norm=s["norm"]),
            "caption": svg.trend_caption(s["metric"], s["points"]),
            "norm": s["norm"],
        }
        for s in results.trend_series(session)
    ]
    asymmetries = results.asymmetries(session)
    context["asymmetries"] = asymmetries
    if asymmetries:
        context["asymmetry_svg"] = svg.asymmetry_svg(
            asymmetries[:12], threshold_pct=results.ASYMMETRY_THRESHOLD_PCT)
    context["asymmetries_over"] = sum(r["exceeds_threshold"] for r in asymmetries)
    return context


def render_html(report) -> str:
    """
    Podoba zprávy. Vydaná zpráva se ukazuje ze snímku pořízeného při
    vydání – pozdější oprava dat nebo pravidel ji nesmí potichu změnit.
    """
    if report.rendered_html:
        return report.rendered_html
    return render_to_string("reports/report.html", report_context(report))


def render_pdf(report) -> bytes | None:
    """
    PDF z téhož HTML. Když WeasyPrint chybí, zpráva zůstane v HTML –
    lepší než tvrdit, že se PDF vyrobilo.
    """
    try:
        from weasyprint import HTML
    except ImportError:
        logger.warning("WeasyPrint není nainstalován, PDF se nevygenerovalo.")
        return None
    return HTML(string=render_html(report)).write_pdf()


@transaction.atomic
def release(report, *, user) -> Report:
    """Vydání. Od téhle chvíle se zpráva needituje."""
    if report.status != Report.Status.DRAFT:
        raise ReportError("Vydat lze jen koncept.")
    if report.is_writing:
        raise ReportError("Model ještě píše souhrn – počkejte, až dopíše, a zkontrolujte ho.")
    if (report.audience == Audience.CLINICIAN
            and not Consent.has(report.subject, Consent.Scope.REPORT_HANDOVER)):
        raise ReportError(
            "Zprávu pro lékaře lze vydat jen se souhlasem sportovce s předáním zprávy "
            "poskytovateli zdravotních služeb. Doplňte souhlas u sportovce (tužka na kartě), "
            "nebo vytvořte zprávu pro sportovce či trenéra.")
    if report.note_pending_review:
        raise ReportError(
            "Návrh doporučení od jazykového modelu ještě nikdo nezkontroloval. "
            "Projděte ho, opravte a uložte – teprve pak lze zprávu vydat."
        )

    report.status = Report.Status.RELEASED
    report.released_at = timezone.now()
    report.released_by = user
    report.rendered_html = render_html(report)

    if pdf := render_pdf(report):
        report.pdf.save(f"{report.report_number}.pdf", ContentFile(pdf), save=False)

    data = json.dumps(_machine_readable(report), ensure_ascii=False, indent=2)
    report.data_json.save(f"{report.report_number}.json",
                          ContentFile(data.encode()), save=False)
    report.save()

    if report.supersedes_id:
        Report.objects.filter(pk=report.supersedes_id).update(
            status=Report.Status.SUPERSEDED)
    return report


def _machine_readable(report) -> dict:
    """
    Strojově čitelná příloha vedle PDF.

    Když ji přijímající systém neumí, nic se neděje. Když jednou umět
    bude, načte si hodnoty rovnou – a nemusíme kvůli tomu měnit formát
    zprávy ani jednat o rozhraní předem.
    """
    context = report_context(report)
    return {
        "cislo_zpravy": report.report_number,
        "verze": report.version,
        "vydano": report.released_at.isoformat() if report.released_at else None,
        "sportovec": {"kod": report.subject.code, "sport": str(report.subject.sport or "")},
        "mereni": {"datum": report.session.date.isoformat()} if report.session else None,
        "vysledky": results.machine_readable(context["results"]),
        "nalezy": [
            {"pravidlo": f.rule.code, "verze_pravidla": f.rule_version,
             "zavaznost": f.severity, "text": f.text, "hodnoty": f.values}
            for f in context["findings"]
        ],
        "potlacene_nalezy": [
            {"pravidlo": f.rule.code, "text": f.text, "duvod": f.suppressed_reason}
            for f in context["suppressed"]
        ],
        "citace": [
            {"cislo": c["number"], "nazev": c["article"].title, "doi": c["article"].doi,
             "rok": c["article"].year,
             "populace_odpovida": c["population_matches"]}
            for c in context["citations"]
        ],
        "doporuceni": context["recommendations"],
        "dolozka": report.disclaimer,
    }


@transaction.atomic
def deliver(report, *, recipient, channel, user, note="") -> ReportDelivery:
    """
    Předání poskytovateli zdravotních služeb.

    Bez platného souhlasu se zpráva nepředá. Je to jediné místo, kde data
    opouštějí FTVS, takže se tady kontroluje, ne až někde v šabloně.
    """
    if report.status != Report.Status.RELEASED:
        raise ReportError("Předat lze jen vydanou zprávu.")

    if not Consent.has(report.subject, Consent.Scope.REPORT_HANDOVER):
        raise ReportError(
            f"Sportovec {report.subject.code} nemá platný souhlas s předáním "
            f"zprávy poskytovateli zdravotních služeb. Zpráva se nepředá."
        )

    return ReportDelivery.objects.create(
        report=report, recipient=recipient, channel=channel,
        delivered_at=timezone.now(), delivered_by=user,
        consent_verified=True, note=note,
    )


def save_edits(report, *, summary: str, custom_note: str) -> list[str]:
    """
    Úpravy textu diagnostikem. Vrací čísla, která v textu nemají oporu
    v datech – jako upozornění. Člověka neblokujeme: může opravit překlep
    modelu nebo doplnit údaj, který aplikace nezná; za text odpovídá on.
    """
    if not report.is_editable:
        raise ReportError("Vydanou zprávu nelze upravit – vytvořte novou verzi.")
    if report.is_writing:
        raise ReportError("Model právě píše souhrn – úpravy uložte, až dopíše.")

    summary = summary.replace("\r\n", "\n").strip()
    custom_note = custom_note.replace("\r\n", "\n").strip()
    if not report.summary_generated:          # zprávy z doby před touto funkcí
        report.summary_generated = report.summary
    report.summary = summary
    report.summary_edited = summary != report.summary_generated.strip()
    report.custom_note = custom_note
    report.note_pending_review = False
    report.save(update_fields=["summary", "summary_generated", "summary_edited",
                               "custom_note", "note_pending_review"])
    return narrative.unsupported_numbers(report, summary)


def suggest_recommendations(report) -> narrative.RecommendationDraft:
    """Návrh doporučení od modelu vložený do komentáře – ke kontrole."""
    from . import llm

    if not report.is_editable:
        raise ReportError("Vydanou zprávu nelze upravit – vytvořte novou verzi.")
    if not llm.is_enabled():
        raise ReportError("Jazykový model není zapnutý (LLM_ENABLED).")
    try:
        draft = narrative.draft_recommendations(report)
    except llm.LLMError as exc:
        raise ReportError(str(exc)) from exc

    existing = report.custom_note.strip()
    report.custom_note = f"{existing}\n\n{draft.text}" if existing else draft.text
    report.note_ai_model = draft.model
    report.note_pending_review = True
    report.save(update_fields=["custom_note", "note_ai_model", "note_pending_review"])
    return draft


def supersede(report, *, user) -> Report:
    """Oprava vydané zprávy = nová verze, ne přepis té staré."""
    if report.session is None:
        raise ReportError("Zprávu bez testovacího dne nelze přegenerovat.")
    return build_draft(report.session, user=user, supersedes=report)


# ---------------------------------------------------------------------------
# Zpětná vazba a porovnání modelů
# ---------------------------------------------------------------------------

def rate(report, *, rating: str, note: str = "") -> None:
    if rating not in Report.Rating.values and rating != "":
        raise ReportError("Neznámé hodnocení.")
    report.ai_rating = rating
    report.ai_rating_note = note.strip()[:300]
    report.save(update_fields=["ai_rating", "ai_rating_note"])


def set_flags(report, *, example: bool | None = None, test_set: bool | None = None) -> None:
    """Vzorová zpráva a zkušební sada – jen u vydaných zpráv (text už zkontroloval člověk)."""
    if report.status == Report.Status.DRAFT and (example or test_set):
        raise ReportError("Jako vzor nebo do zkušební sady lze dát jen vydanou zprávu.")
    fields = []
    if example is not None:
        report.is_example = example
        fields.append("is_example")
    if test_set is not None:
        report.in_test_set = test_set
        fields.append("in_test_set")
    report.save(update_fields=fields)


def try_model(report, *, model: str | None, user) -> ModelTrial:
    """
    Zkušební text pro zprávu ze zkušební sady – jiným modelem nebo s novými
    pokyny. Nic ve zprávě nemění; vzorem pro sebe sama zpráva není.
    """
    from . import llm

    if report.session is None:
        raise ReportError("Zpráva nemá testovací den.")
    session = report.session
    findings, facts = narrative.report_facts(report)
    trial = ModelTrial(report=report, model=model or "", audience=report.audience,
                       created_by=user)
    try:
        draft = narrative.generate(session, findings, facts, audience=report.audience,
                                   model=model or None, exclude_report=report)
    except llm.LLMError as exc:
        trial.error = str(exc)[:300]
        trial.model = trial.model or "(výchozí)"
    else:
        trial.model, trial.text = draft.model, draft.text
        trial.seconds, trial.problems = draft.seconds, draft.problems
    trial.save()
    return trial


def quality_stats(organization) -> dict:
    """Jak si model vede: hodnocení, kolik textu se přepisuje, odmítnuté texty."""
    from collections import Counter, defaultdict

    reports = list(Report.objects.filter(organization=organization)
                   .exclude(llm_model="").order_by("-created_at")[:500])
    by_model = defaultdict(lambda: {"zprav": 0, "prepis": [], "hodnoceni": Counter()})
    rejected = unavailable = 0
    for r in reports:
        if not r.written_by_model:
            rejected += "odmítnut" in r.generation_note
            unavailable += "nepoužil" in r.generation_note
            continue
        row = by_model[(r.llm_model, r.get_audience_display())]
        row["zprav"] += 1
        if r.status != Report.Status.DRAFT and (share := r.rewrite_share) is not None:
            row["prepis"].append(share)
        if r.ai_rating:
            row["hodnoceni"][r.ai_rating] += 1
    rows = []
    for (model, audience), row in sorted(by_model.items()):
        rows.append({
            "model": model, "audience": audience, "zprav": row["zprav"],
            "prepis_pct": (round(100 * sum(row["prepis"]) / len(row["prepis"]))
                           if row["prepis"] else None),
            "hodnoceni": [(row["hodnoceni"].get(v, 0), label)
                          for v, label in Report.Rating.choices],
        })
    notes = [r for r in reports if r.ai_rating_note][:15]
    return {"rows": rows, "odmitnuto": rejected, "nedostupny": unavailable,
            "celkem": len(reports), "poznamky": notes}
