"""
Úvodní naplnění ukázkové instance.

Pouští se při každém nasazení, ale pracuje jen jednou: když v databázi
ještě nikdo není. Díky tomu je nasazení ukázky jedno kliknutí a další
nasazení už do dat nesahají.

Běží výhradně při zapnutém DEMO_MODE. V ostrém provozu se katalog zakládá
vědomě příkazem seed_catalog, a vygenerovaní sportovci tam nemají co dělat.
"""

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Naplní prázdnou ukázkovou instanci daty (jen při DEMO_MODE)."

    def add_arguments(self, parser):
        parser.add_argument("--subjects", type=int, default=25)
        parser.add_argument("--sessions", type=int, default=4)

    def handle(self, *args, **options):
        if not settings.DEMO_MODE:
            self.stdout.write("DEMO_MODE je vypnutý, úvodní naplnění se přeskakuje.")
            return

        from apps.subjects.models import Subject

        if Subject.objects.exists():
            self.stdout.write("Data už v databázi jsou, naplnění se přeskakuje.")
            return

        self.stdout.write("Prázdná ukázková instance – zakládám katalog, role a data.")
        call_command("seed_catalog", verbosity=0)
        call_command("seed_roles", verbosity=0)
        call_command("seed_demo", subjects=options["subjects"],
                     sessions=options["sessions"], verbosity=1)
        self.stdout.write(self.style.SUCCESS("Ukázková instance je připravená."))
