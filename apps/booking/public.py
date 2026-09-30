"""
Veřejná část objednávek – bez přihlášení.

Jediné stránky aplikace, které smějí být vidět z internetu (spolu se
stránkou RPE). Neukazují nic z databáze kromě nabídky a volných termínů;
stav objednávky jen tomu, kdo má odkaz s náhodným tokenem.
"""

from collections import OrderedDict
from datetime import date

from django.conf import settings
from django.core.cache import cache
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.subjects.models import Sex, Subject

from . import services
from .models import BookingRequest, Offer, Slot

MAX_PARTICIPANTS = 40
# Ochrana před zahlcením: kolik objednávek smí jedna adresa odeslat za hodinu.
MAX_PER_HOUR = 5


def _client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")


def _participants(post) -> tuple[list, list[str]]:
    """Účastníci z polí formuláře (seznamy stejné délky)."""
    rows, errors = [], []
    firsts, lasts = post.getlist("jmeno"), post.getlist("prijmeni")
    births, sexes, injuries = (post.getlist("narozeni"), post.getlist("pohlavi"),
                               post.getlist("zraneni"))
    for i, (first, last) in enumerate(zip(firsts, lasts, strict=False)):
        first, last = first.strip(), last.strip()
        birth_raw = births[i].strip() if i < len(births) else ""
        if not (first or last or birth_raw):
            continue  # prázdný řádek týmu
        label = f"{first} {last}".strip() or f"{i + 1}. účastník"
        if not first or not last:
            errors.append(f"{label}: vyplňte jméno i příjmení.")
            continue
        try:
            born = date.fromisoformat(birth_raw)
        except ValueError:
            errors.append(f"{label}: vyplňte datum narození.")
            continue
        if not (date(1920, 1, 1) <= born <= timezone.localdate()):
            errors.append(f"{label}: datum narození nevypadá správně.")
            continue
        sex = sexes[i] if i < len(sexes) and sexes[i] in Sex.values else Sex.OTHER
        injury = injuries[i].strip()[:500] if i < len(injuries) else ""
        rows.append(services.ParticipantData(first[:80], last[:80], born, sex, injury))
    return rows, errors


def _initial(post) -> dict:
    """Stav formuláře pro Alpine – po chybě se nic nevyplňuje znovu."""
    if post is None:
        return {"kdo": "jednotlivec", "vybrane": [], "termin": "",
                "ucastnici": [{"jmeno": "", "prijmeni": "", "narozeni": "", "pohlavi": "",
                               "zraneni": ""}]}
    keys = ("jmeno", "prijmeni", "narozeni", "pohlavi", "zraneni")
    columns = [post.getlist(k) for k in keys]
    rows = [dict(zip(keys, values, strict=False)) for values in zip(*columns, strict=False)]
    return {"kdo": post.get("kdo", "jednotlivec"),
            "vybrane": [int(v) for v in post.getlist("nabidka") if v.isdigit()],
            "termin": post.get("termin", ""),
            "ucastnici": rows or _initial(None)["ucastnici"]}


def _offers(org):
    offers = list(Offer.objects.filter(organization=org, is_active=True)
                  .prefetch_related("protocols"))
    return ([o for o in offers if o.kind == Offer.Kind.PACKAGE],
            [o for o in offers if o.kind == Offer.Kind.TEST])


def _slots_by_day(org) -> list[dict]:
    """Termíny po dnech; ``max_volno`` = kolik osob se vejde na nejvolnější termín dne."""
    days = OrderedDict()
    for slot in Slot.available(org):
        days.setdefault(timezone.localtime(slot.start).date(), []).append(slot)
    return [{"day": day, "slots": slots, "max_volno": max(s.volno for s in slots)}
            for day, slots in days.items()]


def booking_form(request):
    org = services.organization()
    if not services.enabled():
        return render(request, "booking/public_closed.html", status=503)

    packages, tests = _offers(org)
    context = {"packages": packages, "tests": tests, "days": _slots_by_day(org),
               "ceny": {o.pk: o.price for o in packages + tests},
               "goals": BookingRequest.Goal.choices, "levels": Subject.Level.choices,
               "phases": BookingRequest._meta.get_field("season_phase").choices,
               "sexes": [c for c in Sex.choices if c[0] != Sex.OTHER],
               "demo_mode": settings.DEMO_MODE, "post": {}, "errors": [],
               "max_participants": MAX_PARTICIPANTS}

    context["initial"] = _initial(request.POST if request.method == "POST" else None)
    if request.method != "POST":
        return render(request, "booking/public_form.html", context)

    post = request.POST
    context["post"] = post
    # Past na roboty: pole, které člověk nevidí a nevyplní.
    if post.get("web"):
        return render(request, "booking/public_done.html", {"booking": None})

    key = f"objednavky:{_client_ip(request)}"
    if cache.get(key, 0) >= MAX_PER_HOUR:
        context["errors"] = ["Z této adresy už přišlo víc objednávek. Zkuste to prosím později, "
                             "nebo nás kontaktujte."]
        return render(request, "booking/public_form.html", context, status=429)

    participants, errors = _participants(post)
    kind = (BookingRequest.Kind.TEAM if post.get("kdo") == BookingRequest.Kind.TEAM
            else BookingRequest.Kind.INDIVIDUAL)
    if kind == BookingRequest.Kind.INDIVIDUAL:
        participants = participants[:1]
    if not participants and not errors:
        errors.append("Vyplňte prosím údaje účastníka.")
    if len(participants) > MAX_PARTICIPANTS:
        errors.append(f"Najednou lze objednat nejvýš {MAX_PARTICIPANTS} osob.")
    contact = post.get("kontakt", "").strip()
    email = post.get("email", "").strip()
    if kind == BookingRequest.Kind.INDIVIDUAL and not contact and participants:
        contact = f"{participants[0].first_name} {participants[0].last_name}"
    if not contact:
        errors.append("Vyplňte prosím kontaktní osobu.")
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        errors.append("Vyplňte prosím platný e-mail – pošleme na něj potvrzení.")
    if kind == BookingRequest.Kind.TEAM and not post.get("tym", "").strip():
        errors.append("Vyplňte prosím název týmu nebo klubu.")
    try:
        slot_id = int(post.get("termin", ""))
    except ValueError:
        slot_id = 0
        errors.append("Vyberte prosím termín.")
    offer_ids = [int(v) for v in post.getlist("nabidka") if v.isdigit()]
    if not offer_ids:
        errors.append("Vyberte prosím aspoň jeden test nebo balíček.")

    if errors:
        context["errors"] = errors
        return render(request, "booking/public_form.html", context, status=400)

    data = services.RequestData(
        kind=kind, slot_id=slot_id, offer_ids=offer_ids, participants=participants,
        contact_name=contact[:120], email=email[:200], phone=post.get("telefon", "").strip()[:40],
        team_name=post.get("tym", "").strip()[:120] if kind == BookingRequest.Kind.TEAM else "",
        sport_name=post.get("sport", "").strip()[:100],
        category=post.get("kategorie", "").strip()[:60],
        goal=(post.get("cil") if post.get("cil") in BookingRequest.Goal.values
              else BookingRequest.Goal.OTHER),
        goal_note=post.get("cil_popis", "").strip()[:1000],
        level=post.get("uroven") if post.get("uroven") in Subject.Level.values
        else Subject.Level.TRAINED,
        season_phase=post.get("obdobi") if post.get("obdobi") in dict(context["phases"]) else "",
        consent_testing=bool(post.get("souhlas")),
        consent_handover=bool(post.get("souhlas_lekar")),
        consent_guardian=bool(post.get("souhlas_zastupce")),
    )
    try:
        booking = services.submit(data, org)
    except services.BookingError as exc:
        context["errors"] = [str(exc)]
        context["days"] = _slots_by_day(org)
        return render(request, "booking/public_form.html", context, status=400)

    cache.set(key, cache.get(key, 0) + 1, 3600)
    event = "overit" if booking.status == BookingRequest.Status.VERIFY else "prijata"
    sent = services.notify(request, booking, event)
    return render(request, "booking/public_done.html", {"booking": booking, "sent": sent})


def booking_verify(request, token):
    booking = get_object_or_404(BookingRequest, token=token)
    error = ""
    try:
        if services.verify(booking):
            services.notify(request, booking, "prijata")
    except services.BookingError as exc:
        error = str(exc)
    return render(request, "booking/public_status.html", {"booking": booking, "error": error,
                                                          "just_verified": not error})


def booking_status(request, token):
    booking = get_object_or_404(BookingRequest.objects.select_related("slot"), token=token)
    return render(request, "booking/public_status.html", {"booking": booking})
