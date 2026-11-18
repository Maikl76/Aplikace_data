"""
Plánování testovacího dne podle baterie testů sportu.

Baterie předvyplní, co se má měřit; tady se z ní zakládají provedení
protokolů (zatím prázdná) a počítá stav: co je změřené, co čeká.
"""

from django.db.models import Count, Q

from .models import ProtocolRun, TestSession

# Odvozené ukazatele se neměří, dopočítávají se (DSI).
DERIVED_PROTOCOLS = {"dsi", "eur"}


def battery_for(subject):
    from apps.catalog.models import TestBattery

    return TestBattery.for_subject(subject)


def battery_protocols(subject) -> list:
    battery = battery_for(subject)
    if battery is None:
        return []
    return [p for p in battery.protocols() if p.code not in DERIVED_PROTOCOLS]


def protocol_choices(organization):
    """
    Testy, které jde zařadit do testovacího dne: aktivní, měřené (odvozené
    ukazatele se dopočítají samy), sdílené z katalogu nebo vlastní tohoto
    pracoviště – vlastní testy jiného pracoviště se nenabízejí.
    """
    from django.db.models import Q

    from apps.catalog.models import Protocol

    scope = Q(organization__isnull=True)
    if organization is not None:
        scope |= Q(organization=organization)
    return (Protocol.objects.filter(scope, is_active=True).exclude(code__in=DERIVED_PROTOCOLS)
            .order_by("family", "name", "version"))


def protocol_label(protocol, names_seen: dict) -> str:
    """Název testu; když se v nabídce opakuje (dvě verze, vlastní kopie), s verzí a původem."""
    if names_seen.get(protocol.name.lower(), 0) < 2:
        return protocol.name
    origin = "" if protocol.organization_id is None else ", vlastní"
    return f"{protocol.name} (v{protocol.version}{origin})"


def battery_options(subject, user) -> dict:
    """
    Baterie, ze kterých jde nový testovací den předvyplnit: nejdřív baterie
    sportu sportovce (ta, která mu podle kategorie patří, první), pak baterie
    ostatních sportů v rozsahu účtu – třeba pro hosta z jiného sportu.
    """
    from apps.catalog.models import TestBattery
    from apps.subjects.models import Sport

    batteries = list(TestBattery.objects.filter(sport__in=Sport.objects.for_user(user))
                     .select_related("sport").prefetch_related("items__protocol"))
    default = battery_for(subject) if subject is not None else None
    sport_id = subject.sport_id if subject is not None else None
    own = sorted((b for b in batteries if sport_id and b.sport_id == sport_id),
                 key=lambda b: (b.pk != getattr(default, "pk", None), b.category.lower(),
                                b.label.lower()))
    other = sorted((b for b in batteries if not (sport_id and b.sport_id == sport_id)),
                   key=lambda b: (b.sport.name.lower(), b.category.lower(), b.label.lower()))
    return {"default": default, "own": own, "other": other}


def session_protocols(session) -> list:
    """Testy dne v pořadí, v jakém se měřily (bez vypnutých a odvozených)."""
    runs = (session.protocol_runs.select_related("protocol")
            .order_by("started_at", "pk"))
    return list({r.protocol_id: r.protocol for r in runs
                 if r.protocol.is_active and r.protocol.code not in DERIVED_PROTOCOLS}.values())


def last_session(subject, *, before=None):
    """Poslední testovací den sportovce s aspoň jedním testem (před datem ``before``)."""
    sessions = (TestSession.objects.filter(subject=subject)
                .annotate(testu=Count("protocol_runs")).filter(testu__gt=0))
    if before is not None:
        sessions = sessions.filter(date__lt=before)
    return sessions.order_by("-date", "-pk").first()


def in_order(protocols, preferred) -> list:
    """Testy seřazené podle ``preferred`` (pořadí baterie); ostatní za nimi podle rodiny a názvu."""
    rank = {p.pk: i for i, p in enumerate(preferred)}
    return sorted(protocols, key=lambda p: (rank.get(p.pk, len(rank)), p.family, p.name.lower()))


def ensure_runs(session, protocols) -> int:
    """Založí chybějící provedení protokolů. Existující nechá být. Vrací počet nových."""
    have = set(session.protocol_runs.values_list("protocol_id", flat=True))
    new = [ProtocolRun(session=session, protocol=p) for p in protocols if p.pk not in have
           and p.code not in DERIVED_PROTOCOLS]
    ProtocolRun.objects.bulk_create(new)
    return len(new)


def repeat_session(source, *, day, user):
    """
    Zopakovat testovací den: pro téhož sportovce vznikne den ``day`` se
    stejnými testy (místo a fáze sezóny se přenesou; hodnoty ne). Když den
    už existuje, jen se do něj doplní chybějící testy.
    Vrací (den, nový?, počet přidaných testů).
    """
    protocols = session_protocols(source)
    session, created = TestSession.objects.get_or_create(
        organization=source.organization, subject=source.subject, date=day,
        defaults={"operator": user, "location": source.location,
                  "season_phase": source.season_phase, "battery": source.battery})
    return session, created, ensure_runs(session, protocols)


def empty_run(session, protocol):
    """Prázdné (založené, ale nezměřené) provedení – import ho vyplní místo nového."""
    return (session.protocol_runs.filter(protocol=protocol, external_ref="")
            .annotate(n=Count("trials__measurements")).filter(n=0).first())


def day_overview(subjects, protocols, day) -> list[dict]:
    """
    Stav testovacího dne: pro každého sportovce a test „hotovo“, „založeno“
    nebo nic. Hotovo = provedení s aspoň jednou hodnotou.
    """
    sessions = {s.subject_id: s for s in TestSession.objects.filter(subject__in=subjects,
                                                                     date=day)}
    runs = (ProtocolRun.objects.filter(session__in=sessions.values(),
                                       protocol__in=protocols)
            .annotate(n=Count("trials__measurements", filter=Q(trials__is_valid=True))))
    state: dict[tuple, dict] = {}
    for run in runs:
        key = (run.session.subject_id, run.protocol_id)
        best = state.get(key)
        if best is None or run.n > best["n"]:
            state[key] = {"run": run, "n": run.n}

    rows = []
    for subject in subjects:
        cells = []
        for protocol in protocols:
            entry = state.get((subject.pk, protocol.pk))
            cells.append({
                "protocol": protocol,
                "run": entry["run"] if entry else None,
                "stav": ("hotovo" if entry and entry["n"] else
                         "zalozeno" if entry else "nic"),
            })
        rows.append({"subject": subject, "session": sessions.get(subject.pk), "cells": cells,
                     "hotovo": sum(c["stav"] == "hotovo" for c in cells)})
    return rows
