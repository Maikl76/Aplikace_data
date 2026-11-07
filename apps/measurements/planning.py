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
    protocols = list({r.protocol_id: r.protocol for r in source.protocol_runs
                      .select_related("protocol").order_by("started_at", "pk")
                      if r.protocol.is_active and r.protocol.code not in DERIVED_PROTOCOLS}
                     .values())
    session, created = TestSession.objects.get_or_create(
        organization=source.organization, subject=source.subject, date=day,
        defaults={"operator": user, "location": source.location,
                  "season_phase": source.season_phase})
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
