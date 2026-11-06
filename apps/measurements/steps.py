"""Kroky testovacího dne: testy podle baterie, prostředí, hodnoty, RPE, kontrola, zpráva."""

from django.urls import reverse

from apps.core.steps import step

from . import planning
from .models import Measurement
from .questionnaires import RPE


def session_steps(session, runs, unstable, reports) -> list[dict]:
    """``runs`` jsou měřené testy dne s anotací ``hodnot`` (počet hodnot)."""
    from apps.reports.models import Report

    runs = [r for r in runs if r.protocol.code not in planning.DERIVED_PROTOCOLS]
    battery = planning.battery_for(session.subject)
    wanted = ([p for p in battery.protocols() if p.code not in planning.DERIVED_PROTOCOLS]
              if battery else [])
    have = {r.protocol_id for r in runs}
    missing = [p for p in wanted if p.pk not in have]
    measured = [r for r in runs if r.hodnot]
    empty = [r for r in runs if not r.hodnot]
    rpe_done = set(session.responses.filter(questionnaire__code=RPE)
                   .values_list("protocol_run_id", flat=True))
    rpe_needed = [r for r in measured if r.protocol.rpe_after and r.pk not in rpe_done]
    rpe_any = any(r.protocol.rpe_after for r in runs)
    suspicious = (Measurement.objects.filter(trial__protocol_run__session=session)
                  .exclude(quality=Measurement.Quality.OK).count())
    released = [r for r in reports if r.status == Report.Status.RELEASED]
    drafts = [r for r in reports if r.status == Report.Status.DRAFT]
    conditions = (session.temperature_c is not None or session.humidity_pct is not None
                  or bool(session.fatigue_rating))

    checks = []
    if unstable:
        checks.append(f"{len(unstable)}× pokusy se liší víc, než je obvyklé")
    if suspicious:
        checks.append(f"{suspicious}× hodnota mimo věrohodný rozsah")
    return [
        step(1, "Testy podle baterie", bool(runs) and not missing,
             (f"{len(runs)} testů" + (f"; z baterie chybí {', '.join(p.name for p in missing)}."
                                     if missing else ".") if runs else
              ("Z baterie chybí " + ", ".join(p.name for p in missing) + "." if missing else
               "Sportovec nemá baterii testů (sport bez baterie) – testy přidejte ručně.")),
             url="#nahrat", button="Přidat test"),
        step(2, "Prostředí a únava", conditions,
             ("Vyplněno." if conditions else "Teplota, vlhkost a subjektivní únava – objeví se "
                                             "ve zprávě."),
             url="#prostredi", button="Doplnit", optional=True),
        step(3, "Hodnoty", bool(runs) and not empty,
             (f"{len(empty)} testů čeká na hodnoty – u přístroje, nebo nahráním exportu."
              if empty else ("Všechny testy mají hodnoty." if runs else "Nejdřív testy.")),
             url=reverse("run_entry", args=[empty[0].pk]) if empty else "#nahrat",
             button="Zadat hodnoty", count=len(empty) or None),
        step(4, "RPE", not rpe_needed,
             (f"{len(rpe_needed)}× chybí RPE po zátěžovém testu: "
              + ", ".join(r.protocol.name for r in rpe_needed) + "." if rpe_needed else
              ("RPE zapsáno." if rpe_any else "Žádný dnešní test RPE nevyžaduje; zapsat jde "
                                              "i za celý den.")),
             url="#dotazniky", button="Zapsat RPE", optional=not rpe_any,
             count=len(rpe_needed) or None),
        step(5, "Kontrola", bool(measured) and not empty and not checks,
             ("; ".join(checks) + ". Pokud je sportovec ještě tady, test zopakujte."
              if checks else ("Nic k zopakování." if measured else "Po zadání hodnot.")),
             url="#pokusy" if unstable else "#nahrat", button="Zkontrolovat",
             count=(len(unstable) + suspicious) or None),
        step(6, "Zpráva", bool(released),
             (f"Vydáno: {', '.join(r.report_number for r in released)}." if released else
              f"{len(drafts)} konceptů čeká na kontrolu a vydání." if drafts else
              "Koncept vznikne sám, jakmile mají všechny testy hodnoty; ručně ho založíte pro "
              "sportovce, trenéra nebo lékaře. Nic se tím nevydává."
              if getattr(session.organization, "auto_draft", False) else
              "Vytvořte koncept pro sportovce, trenéra nebo lékaře; nic se tím nevydává."),
             url=reverse("report_detail", args=[drafts[0].pk]) if drafts else "#nova-zprava",
             button="Ke konceptu" if drafts else "Vytvořit zprávu"),
    ]
