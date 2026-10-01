"""
Založí ukázkový přístroj DEXA (průvodce „Nový přístroj“) – jen v ukázce.

    python manage.py ukazkovy_pristroj

Ve veřejné ukázce se soubory nenahrávají, takže by průvodce nešel vidět.
Ukázkový přístroj je nastavený z vymyšleného exportu
demo/ukazkovy-export-dexa.csv. Když už existuje, nic se nestane.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.core.models import Organization
from apps.ingest.device_setup import create_demo_device


class Command(BaseCommand):
    help = "Ukázkový přístroj DEXA pro veřejnou ukázku."

    def handle(self, *args, **options):
        if not settings.DEMO_MODE:
            self.stdout.write("Jen v ukázce (DEMO_MODE=True) – nic se nezměnilo.")
            return
        org = Organization.objects.order_by("pk").first()
        device = create_demo_device(org) if org else None
        self.stdout.write(f"Ukázkový přístroj {device.name} založen." if device
                          else "Ukázkový přístroj už je (nebo chybí test Složení těla).")
