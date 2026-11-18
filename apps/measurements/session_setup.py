"""
Individuální testování: nový testovací den jednoho sportovce.

Než se začne měřit, má být vidět, kdo to je (sport, kategorie, tým), co platí
(omezení zátěže od lékaře, souhlas s testováním), kdy se měřil naposledy a z jaké
sady testů vyjít – z baterie jeho sportu, z jiné baterie, nebo ze stejných testů
jako minule. Testy zvolené sady jsou nahoře v pořadí, v jakém se měří; ostatní
testy katalogu pracoviště pod nimi po rodinách testů.
"""

from django.urls import reverse

from . import planning

MINULE = "minule"     # stejné testy jako při posledním testovacím dni
RUCNE = "rucne"       # bez předvyplnění, testy vybere operátor sám


def _plural(count: int, one: str, few: str, many: str) -> str:
    from apps.reports.narrative import plural

    return f"{count} {plural(count, one, few, many)}"


def _meta(protocol) -> str:
    """Drobný popisek testu: přístroj, počet pokusů, RPE."""
    parts = []
    if protocol.device:
        parts.append(protocol.device)
    if protocol.default_trials:
        parts.append(_plural(protocol.default_trials, "pokus", "pokusy", "pokusů"))
    if protocol.rpe_after:
        parts.append("RPE po testu")
    return " · ".join(parts)


def _battery_label(battery, *, with_sport: bool = False) -> str:
    label = battery.label
    if battery.name and battery.category and battery.category.lower() not in label.lower():
        label += f" ({battery.category})"
    if with_sport and battery.name and battery.sport.name.lower() not in label.lower():
        label = f"{battery.sport.name}: {label}"
    return label


def _measured_count(battery) -> int:
    return sum(1 for item in battery.items.all()
               if item.protocol.code not in planning.DERIVED_PROTOCOLS)


def build(user, subject, *, day, sada: str | None = None, checked=None) -> dict:
    """
    Co ukázat při zakládání dne: údaje a upozornění ke sportovci, sady testů
    k výběru (zvolená ``sada``, jinak baterie, která sportovci patří) a testy.
    ``checked`` – zaškrtnuté testy, když se formulář vrací s chybou nebo se jen
    změnilo datum (zaškrtnutí zůstane, jak ho operátor upravil).
    """
    from apps.subjects.models import Consent

    available = list(planning.protocol_choices(user.organization))
    by_pk = {p.pk: p for p in available}
    names: dict[str, int] = {}
    for p in available:
        names[p.name.lower()] = names.get(p.name.lower(), 0) + 1

    options = planning.battery_options(subject, user)
    batteries = {str(b.pk): b for b in options["own"] + options["other"]}
    default = options["default"]
    last = planning.last_session(subject, before=day) if subject is not None else None

    chosen = sada if sada in batteries or sada == RUCNE or (sada == MINULE and last) else None
    if chosen is None:
        chosen = (str(default.pk) if default is not None and str(default.pk) in batteries
                  else MINULE if last is not None else RUCNE)

    battery = batteries.get(chosen)
    notes = []
    if battery is not None:
        planned = battery.protocols()
        set_protocols = [by_pk[p.pk] for p in planned if p.pk in by_pk]
        set_title = f"Testy baterie {_battery_label(battery)}"
        if off := [p.name for p in planned if not p.is_active]:
            notes.append(f"V baterii je vypnutý test {', '.join(off)} – nenabízí se "
                         "(zapíná se ve Sportech a testech).")
        if derived := [p.name for p in planned
                       if p.is_active and p.code in planning.DERIVED_PROTOCOLS]:
            notes.append(f"Dopočítá se samo, neměří se: {', '.join(derived)}.")
    elif chosen == MINULE:
        set_protocols = [by_pk[p.pk] for p in planning.session_protocols(last) if p.pk in by_pk]
        set_title = f"Testy jako {last.date:%d.%m.%Y}"
    else:
        set_protocols, set_title = [], ""

    if checked is None:
        checked_pks = {p.pk for p in set_protocols}
    else:
        checked_pks = {int(x) for x in checked if str(x).isdigit()}

    def item(protocol, number=None):
        return {"protocol": protocol, "label": planning.protocol_label(protocol, names),
                "checked": protocol.pk in checked_pks, "meta": _meta(protocol),
                "number": number}

    groups = []
    if set_protocols:
        groups.append({"title": set_title, "main": True, "hint": "v pořadí, v jakém se měří",
                       "items": [item(p, i) for i, p in enumerate(set_protocols, start=1)]})
    in_set = {p.pk for p in set_protocols}
    from apps.catalog.models import TestFamily

    rest: dict[str, list] = {}
    for p in available:
        if p.pk not in in_set:
            rest.setdefault(p.family, []).append(p)
    first = True
    for family, label in TestFamily.choices:
        if family in rest:
            groups.append({"title": label, "main": False,
                           "section": ("Další testy z katalogu" if set_protocols else "Testy")
                           if first else "",
                           "items": [item(p) for p in sorted(rest[family],
                                                             key=lambda p: p.name.lower())]})
            first = False

    sady_own = [{"value": str(b.pk),
                 "label": _battery_label(b) + " · "
                 + _plural(_measured_count(b), "test", "testy", "testů")
                 + (" · patří sportovci" if default is not None and b.pk == default.pk else "")}
                for b in options["own"]]
    sady_other = [{"value": str(b.pk),
                   "label": _battery_label(b, with_sport=True) + " · "
                   + _plural(_measured_count(b), "test", "testy", "testů")}
                  for b in options["other"]]
    minule = None
    if last is not None:
        count = len(planning.session_protocols(last))
        minule = {"value": MINULE, "label": f"Stejné testy jako {last.date:%d.%m.%Y} · "
                                            + _plural(count, "test", "testy", "testů")}

    return {
        "subject": subject, "day": day, "sada": chosen, "battery": battery,
        "order": set_protocols, "groups": groups, "notes": notes,
        "sady_own": sady_own, "sady_other": sady_other, "minule": minule,
        "sport_name": subject.sport.name if subject is not None and subject.sport_id else "",
        "checked_protocols": [by_pk[pk] for pk in checked_pks if pk in by_pk],
        **(_about(user, subject, day=day, last=last, consent=Consent)
           if subject is not None else {"facts": "", "history": [], "warnings": []}),
    }


def _about(user, subject, *, day, last, consent) -> dict:
    """Sportovec v jedné větě, poslední měření a plán, upozornění před měřením."""
    from apps.core import access
    from apps.external.models import ExternalExam
    from apps.subjects.retest import plan_for

    from .models import Measurement, TestSession

    facts = [subject.sport.name if subject.sport_id else "bez sportu"]
    if subject.category:
        facts.append(f"kategorie {subject.category}")
    if subject.team_id:
        facts.append(f"tým {subject.team.name}")

    history = []
    if last is not None:
        tests = ", ".join(p.name for p in planning.session_protocols(last))
        measured = Measurement.objects.filter(trial__protocol_run__session=last).exists()
        history.append(f"Poslední testovací den {last.date:%d.%m.%Y}"
                       + (f": {tests}" if tests else "")
                       + ("" if measured else " (bez hodnot)") + ".")
    elif TestSession.objects.filter(subject=subject, date__gte=day).exists():
        history.append(f"Před {day:%d.%m.%Y} žádný testovací den.")
    else:
        history.append("Zatím žádný testovací den – tohle bude první měření.")
    plan = plan_for(subject)
    if plan.status not in ("none",):
        history.append(plan.text())

    may_edit = access.can(user, "subjects_edit")
    edit_url = reverse("subject_edit", args=[subject.pk]) if may_edit else ""
    warnings = []
    restriction = ExternalExam.active_restriction_for(subject)
    if restriction is not None:
        full = restriction.load_restriction == ExternalExam.Restriction.FULL
        warnings.append({
            "tone": "bad" if full else "warn",
            "text": (f"Platné omezení zátěže ({restriction.get_load_restriction_display().lower()})"
                     f" z {restriction.date:%d.%m.%Y}, {restriction.provider}"
                     + (f", platí do {restriction.restriction_valid_until:%d.%m.%Y}"
                        if restriction.restriction_valid_until else "") + "."
                     + (f" {restriction.note.rstrip('.')}." if restriction.note else "")
                     + " Před zátěžovými testy (výskoky, sprint, IMTP, Wingate, "
                       "spiroergometrie) ověřte, co lékař dovolil."),
            "url": reverse("subject_detail", args=[subject.pk]) + "#vysetreni",
            "link": "Vyšetření na kartě sportovce"})
    if not consent.has(subject, consent.Scope.TESTING):
        warnings.append({
            "tone": "warn",
            "text": "Sportovec nemá platný souhlas s funkčním testováním – zapište ho "
                    "v údajích sportovce.",
            "url": edit_url, "link": "Upravit údaje" if edit_url else ""})
    if not subject.sport_id:
        warnings.append({
            "tone": "accent",
            "text": "Sportovec nemá zadaný sport, proto se nenabízí baterie jeho sportu.",
            "url": edit_url, "link": "Doplnit sport" if edit_url else ""})
    existing = TestSession.objects.filter(subject=subject, date=day).first()
    if existing is not None:
        count = existing.protocol_runs.count()
        warnings.append({
            "tone": "accent",
            "text": (f"Na {day:%d.%m.%Y} už testovací den existuje "
                     f"({_plural(count, 'test', 'testy', 'testů')}). Nový se nezaloží – "
                     "zaškrtnuté testy, které v něm ještě nejsou, se do něj přidají."),
            "url": reverse("session_detail", args=[existing.pk]), "link": "Otevřít ho"})
    return {"facts": " · ".join(facts), "history": history, "warnings": warnings}
