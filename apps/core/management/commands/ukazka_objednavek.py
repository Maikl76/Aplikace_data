"""
Doplní do existující databáze ukázkovou nabídku, volné termíny a dvě
vzorové objednávky – jako je má čerstvá ukázka. Na ostatní data nesahá.

    python manage.py ukazka_objednavek

Objednávky jsou s vymyšlenými jmény; do databáze s reálnými klienty je
nepouštějte (jde je pak zamítnout).
"""

from django.core.management.base import BaseCommand

from apps.booking.models import BookingRequest, Offer, Slot
from apps.catalog.models import Protocol
from apps.core.models import Organization

from .seed_demo import Command as SeedDemo


class Command(BaseCommand):
    help = "Doplní ukázkovou nabídku, volné termíny a vzorové objednávky."

    def handle(self, *args, **options):
        org = Organization.objects.order_by("pk").first()
        if org is None:
            self.stdout.write(self.style.ERROR("V databázi není žádná organizace."))
            return
        before = (Offer.objects.count(), Slot.objects.count(), BookingRequest.objects.count())
        protocols = {p.code: p for p in Protocol.objects.filter(organization=None)}
        SeedDemo()._demo_booking(org, protocols)
        after = (Offer.objects.count(), Slot.objects.count(), BookingRequest.objects.count())
        self.stdout.write(self.style.SUCCESS(
            f"Přidáno: {after[0] - before[0]} položek nabídky, {after[1] - before[1]} termínů, "
            f"{after[2] - before[2]} objednávek."))
        if after[2] == before[2] and before[2] == 0:
            self.stdout.write("Vzorové objednávky se nepřidaly – chybí šifrovací klíč "
                              "(spusťte spustit.bat, ten ho doplní).")
