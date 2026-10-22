"""
Doplní do ukázky účty portálu (sportovec, rodic, trener) – bez mazání dat.

    python manage.py ukazkove_ucty

Heslo je stejné jako u správce ukázky (DEMO_ADMIN_PASSWORD v .env).
Existující účty a data nechá být; jde pouštět při každé aktualizaci.
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.core.models import Organization
from apps.portal.demo import create_demo_accounts


class Command(BaseCommand):
    help = "Ukázkové účty portálu (jen při DEMO_MODE); existující nechá být."

    def add_arguments(self, parser):
        parser.add_argument("--heslo", default=None,
                            help="Heslo účtů; výchozí DEMO_ADMIN_PASSWORD z .env.")

    def handle(self, *args, heslo=None, **options):
        if not settings.DEMO_MODE:
            self.stdout.write("Jen v ukázce (DEMO_MODE=True) – nic se nezměnilo.")
            return
        password = heslo or os.environ.get("DEMO_ADMIN_PASSWORD")
        if not password:
            self.stdout.write("Chybí heslo (DEMO_ADMIN_PASSWORD v .env) – účty se nezaložily.")
            return
        org = Organization.objects.order_by("pk").first()
        created = create_demo_accounts(org, password) if org else []
        self.stdout.write(f"Ukázkové účty portálu: založeno {', '.join(created)}." if created
                          else "Ukázkové účty portálu už jsou (nebo chybí sportovci FTVS-0001–0003).")
