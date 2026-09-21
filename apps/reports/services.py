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

from . import narrative
from .models import Report, ReportDelivery

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
def build_draft(session, *, user, supersedes: Report | None = None) -> Report:
    """Vyhodnotí pravidla a složí koncept zprávy."""
    findings = engine.evaluate_session(session)
    citations = evidence.articles_for(findings)
    text = narrative.compose(session, findings, citations)

    # Pojistka i pro deterministický text: kdyby ho někdy psal jazykový
    # model, tahle kontrola odhalí číslo, které nemá oporu v nálezech.
    if problems := narrative.verify_numbers(text, findings):
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
        summary=text,
        rules_version=_rules_fingerprint(findings),
    )
    report.input_fingerprint = report.compute_fingerprint(_inputs(session, findings))
    report.save()
    return report


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
    findings = list(report.session.findings.select_related("rule").all()) \
        if report.session else []
    findings.sort(key=engine.severity_order)
    citations = evidence.articles_for(findings)
    return {
        "report": report,
        "session": report.session,
        "subject": report.subject,
        "findings": [f for f in findings if not f.suppressed],
        "suppressed": [f for f in findings if f.suppressed],
        "citations": citations,
        "population_warnings": evidence.population_warnings(citations),
        "generated_at": timezone.now(),
    }


def render_html(report) -> str:
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

    if pdf := render_pdf(report):
        report.pdf.save(f"{report.report_number}.pdf", ContentFile(pdf), save=False)

    data = json.dumps(_machine_readable(report), ensure_ascii=False, indent=2)
    report.data_json.save(f"{report.report_number}.json",
                          ContentFile(data.encode()), save=False)

    report.status = Report.Status.RELEASED
    report.released_at = timezone.now()
    report.released_by = user
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
            {"nazev": c["article"].title, "doi": c["article"].doi,
             "rok": c["article"].year,
             "populace_odpovida": c["population_matches"]}
            for c in context["citations"]
        ],
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


def supersede(report, *, user) -> Report:
    """Oprava vydané zprávy = nová verze, ne přepis té staré."""
    if report.session is None:
        raise ReportError("Zprávu bez testovacího dne nelze přegenerovat.")
    return build_draft(report.session, user=user, supersedes=report)
