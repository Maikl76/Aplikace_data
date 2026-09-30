"""Načte ukázkové zprávy od AI z demo/ukazkove_zpravy/ – jen ve veřejné ukázce."""

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.core.models import Organization
from apps.reports import demo_reports


class Command(BaseCommand):
    help = "Načte ukázkové zprávy od jazykového modelu (jen při DEMO_MODE)."

    def add_arguments(self, parser):
        parser.add_argument("--i-mimo-ukazku", action="store_true", dest="force",
                            help="Načíst i mimo ukázkový režim (vývoj).")

    def handle(self, *args, force=False, **options):
        if not settings.DEMO_MODE and not force:
            self.stdout.write("Není ukázkový režim – ukázkové zprávy se nenačítají.")
            return
        org = Organization.objects.order_by("pk").first()
        if org is None:
            return
        created = demo_reports.load_all(org)
        self.stdout.write(f"Ukázkové zprávy od AI: načteno {created} nových.")
