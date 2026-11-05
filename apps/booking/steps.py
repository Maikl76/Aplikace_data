"""Kroky objednávek: nabídka, termíny, odkaz pro klienty, žádosti, po schválení."""

from django.urls import reverse
from django.utils import timezone

from apps.core.steps import step

from .models import BookingRequest, Offer, Slot


def booking_steps(request) -> list[dict]:
    user = request.user
    offers = Offer.objects.for_user(user).filter(is_active=True).count()
    slots = Slot.objects.for_user(user).filter(is_active=True, start__gte=timezone.now()).count()
    new = BookingRequest.objects.for_user(user).filter(status=BookingRequest.Status.NEW).count()
    approved = BookingRequest.objects.for_user(user).filter(
        status=BookingRequest.Status.APPROVED).count()
    link = request.build_absolute_uri(reverse("booking_form"))
    return [
        step(1, "Nabídka a ceny", offers > 0,
             (f"{offers} položek nabídky." if offers else
              "Balíčky a testy s cenou za osobu; po schválení se jejich testy založí."),
             url=reverse("booking_offers"), button="Nabídka a ceny"),
        step(2, "Volné termíny", slots > 0,
             (f"{slots} volných termínů dopředu." if slots else
              "Vypište termíny hromadně; pro týmy delší s větší kapacitou."),
             url=reverse("booking_slots"), button="Volné termíny"),
        step(3, "Odkaz pro klienty", offers > 0 and slots > 0,
             (f"Dejte ho na web, do e‑mailu nebo na plakát: {link}" if offers and slots else
              "Formulář má pro klienty smysl, až je nabídka a volné termíny."),
             url=reverse("booking_form"), button="Otevřít formulář"),
        step(4, "Žádosti ke schválení", new == 0,
             f"{new} nových žádostí čeká." if new else "Žádná žádost nečeká.",
             url=reverse("booking_list"), button="Vyřídit", count=new or None),
        step(5, "Po schválení", approved > 0,
             "Schválená žádost založí sportovce a testovací dny; v den testování je najdete "
             "v Dnešním testování.",
             url=reverse("today"), button="Dnešní testování", optional=True),
    ]
