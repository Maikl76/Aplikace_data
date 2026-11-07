"""
Koncept zprávy sám.

Jakmile má testovací den hodnoty u všech testů (odvozené ukazatele se
nepočítají), vznikne koncept pro čtenáře, který dává smysl: pro trenéra,
když sportovec sdílí výsledky s trenérem, jinak pro sportovce. Nic se
nevydává – diagnostik koncept zkontroluje a vydá jako dosud. Vypíná se
v Nastavení → Pracoviště a týmy.
"""

import logging

from django.db import transaction

from apps.measurements.planning import DERIVED_PROTOCOLS

from . import services
from .models import Audience, Report

logger = logging.getLogger(__name__)


def session_complete(session) -> bool:
    """Každý test dne (mimo odvozených) má aspoň jeden pokus s hodnotami."""
    runs = [r for r in session.protocol_runs.select_related("protocol").prefetch_related("trials")
            if r.protocol.code not in DERIVED_PROTOCOLS]
    return bool(runs) and all(r.trials.all() for r in runs)


def audience_for(session) -> str:
    """Pro trenéra, když sportovec sdílí výsledky s trenérem; jinak pro sportovce."""
    from apps.subjects.models import Sharing

    if Sharing.objects.filter(subject=session.subject, status=Sharing.Status.ACTIVE).exists():
        return Audience.COACH
    return Audience.ATHLETE


def ensure_draft(session, *, user):
    """
    Založí koncept, pokud je den kompletní, žádná zpráva k němu ještě není
    a pracoviště to má zapnuté. Vrací koncept, nebo None.
    """
    organization = session.organization
    if organization is None or not organization.auto_draft:
        return None
    if session.reports.exists() or not session_complete(session):
        return None
    try:
        report = services.build_draft(session, user=user, audience=audience_for(session))
    except services.ReportError as exc:
        logger.warning("Koncept zprávy pro %s nevznikl sám: %s", session.subject.code, exc)
        return None
    Report.objects.filter(pk=report.pk).update(auto_created=True)
    report.auto_created = True
    return report


def drafts_for(sessions, *, user, audience=None) -> dict:
    """
    Koncepty pro víc testovacích dnů najednou (Dnešní testování): jen pro
    kompletní dny bez zprávy. ``audience`` None = pro každého podle sdílení,
    jako u konceptu, který vzniká sám. Vrací počty: ``vytvoreno``,
    ``uz_ma``, ``nekompletni`` a kódy sportovců, u kterých koncept nevznikl.
    """
    result = {"vytvoreno": 0, "uz_ma": 0, "nekompletni": 0, "chyby": []}
    for session in sessions:
        if session.reports.exists():
            result["uz_ma"] += 1
            continue
        if not session_complete(session):
            result["nekompletni"] += 1
            continue
        try:
            with transaction.atomic():
                services.build_draft(session, user=user,
                                     audience=audience or audience_for(session))
        except services.ReportError as exc:
            logger.warning("Koncept zprávy pro %s nevznikl: %s", session.subject.code, exc)
            result["chyby"].append(session.subject.code)
            continue
        result["vytvoreno"] += 1
    return result
