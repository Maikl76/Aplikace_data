"""
Vydání = doručení.

Po vydání zprávy pro sportovce nebo trenéra odejde e‑mail těm, kdo si ji
mohou otevřít v portálu: účtům sportovce a zákonných zástupců, nebo
trenérům s aktivním sdílením. E‑mail nenese jméno ani výsledky, jen odkaz.
Laboratoř pak vidí, kdy byla zpráva v portálu poprvé otevřena. Zpráva pro
lékaře se předává jako dosud (záznam o předání se souhlasem).
"""

import logging

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from .models import Audience, Report

logger = logging.getLogger(__name__)


def recipients_for(report) -> list[str]:
    """Adresy účtů, které zprávu v portálu uvidí; u zprávy pro lékaře žádné."""
    from apps.subjects import accounts
    from apps.subjects.models import Sharing

    if report.audience == Audience.ATHLETE:
        users = accounts.account_users(report.subject)
    elif report.audience == Audience.COACH:
        users = [s.coach for s in Sharing.objects.filter(
            subject=report.subject, status=Sharing.Status.ACTIVE).select_related("coach")]
    else:
        return []
    out = []
    for user in users:
        if user is None or not user.is_active:
            continue
        address = (user.email or "").strip().lower()
        if address and address not in out:
            out.append(address)
    return out


def portal_link(report, base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    if not base:
        return ""
    name = "portal_report" if report.audience == Audience.ATHLETE else "coach_report"
    return base + reverse(name, args=[report.subject_id, report.pk])


def _addresses(count: int) -> str:
    return f"{count} " + ("adresa" if count == 1 else "adresy" if count < 5 else "adres")


def message(report, link: str) -> tuple[str, str]:
    """Předmět a text upozornění – bez jména a bez výsledků."""
    reader = "pro sportovce" if report.audience == Audience.ATHLETE else "pro trenéra"
    when = f" z měření {report.session.date:%d.%m.%Y}" if report.session_id else ""
    parts = [f"Dobrý den,\n\nlaboratoř FTVS UK vydala novou zprávu {reader}{when}."]
    parts.append(f"Otevřete ji ve svém účtu:\n{link}" if link
                 else "Najdete ji ve svém účtu v portálu laboratoře.")
    parts.append("Tento e‑mail neobsahuje žádné výsledky – ty jsou jen v účtu.")
    parts.append("Laboratoř funkční diagnostiky FTVS UK")
    return "Nová zpráva z funkčního testování", "\n\n".join(parts)


def notify_released(report, *, base_url: str = "") -> int:
    """Pošle upozornění a poznamená to u zprávy. Vrací počet adres (0 = neodešlo)."""
    from django.core.mail import send_mail

    if not settings.EMAIL_HOST or report.status != Report.Status.RELEASED:
        return 0
    addresses = recipients_for(report)
    if not addresses:
        return 0
    subject, body = message(report, portal_link(report, base_url))
    try:
        send_mail(subject, body, None, addresses)
    except Exception:  # poštovní server neodpovídá – laboratoř to uvidí u zprávy
        logger.exception("Upozornění na zprávu %s neodešlo.", report.report_number)
        return 0
    now = timezone.now()
    Report.objects.filter(pk=report.pk).update(notified_at=now, notified_count=len(addresses))
    report.notified_at, report.notified_count = now, len(addresses)
    return len(addresses)


def notice(report) -> str:
    """Věta pro laboratoř u vydané zprávy: kam a kdy upozornění odešlo, nebo proč ne."""
    if report.status != Report.Status.RELEASED:
        return ""
    if report.audience == Audience.CLINICIAN:
        return "Zprávu pro lékaře předáváte sami – se záznamem o předání."
    if report.notified_at:
        return (f"Upozornění e‑mailem odešlo {timezone.localtime(report.notified_at):%d.%m.%Y %H:%M} "
                f"({_addresses(report.notified_count)}).")
    if not settings.EMAIL_HOST:
        return "Upozornění e‑mailem se neposílá – poštovní server není nastavený."
    if not recipients_for(report):
        return ("Upozornění neodešlo: sportovec ani zástupce nemá účet v portálu – vystavte "
                "pozvánku na kartě sportovce." if report.audience == Audience.ATHLETE else
                "Upozornění neodešlo: žádný trenér nemá aktivní sdílení.")
    return "Upozornění e‑mailem zatím neodešlo."


def mark_opened(report, user) -> bool:
    """První otevření v portálu – jednou, dál se nic nepřepisuje."""
    if report.opened_at:
        return False
    updated = Report.objects.filter(pk=report.pk, opened_at__isnull=True).update(
        opened_at=timezone.now(), opened_by=user)
    return bool(updated)
