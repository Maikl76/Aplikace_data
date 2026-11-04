"""
Načte genové karty z Wordu (podklady „Genové karty – úplné podklady
k odborné revizi“) do katalogu genetiky.

Každá karta vznikne jako verze 1 „původní znění“ (jen ke čtení) a verze 2
„návrh“ k revizi v administraci. Varianty, které v katalogu už jsou, se
nechají být – příkaz nic nepřepisuje.
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.models import Organization
from apps.genetics.cards_import import import_cards
from apps.genetics.seed import seed_domains


class Command(BaseCommand):
    help = "Načte genové karty z .docx do katalogu genetiky (jako původní znění + návrh)."

    def add_arguments(self, parser):
        parser.add_argument("soubor", help="Cesta k .docx s genovými kartami.")
        parser.add_argument("--organizace", dest="org", default="",
                            help="Zkratka pracoviště (prázdné = sdílený katalog).")

    def handle(self, *args, **options):
        path = Path(options["soubor"])
        if not path.is_file():
            raise CommandError(f"Soubor {path} neexistuje.")
        organization = None
        if options["org"]:
            organization = Organization.objects.filter(short_name=options["org"]).first()
            if organization is None:
                raise CommandError(f"Pracoviště „{options['org']}“ v databázi není.")
        seed_domains()
        try:
            result = import_cards(path, organization=organization)
        except (KeyError, ValueError, OSError) as exc:
            raise CommandError(f"Soubor nejde načíst: {exc}") from exc
        for line in result.lines():
            self.stdout.write(line)
        if not result.created and not result.skipped:
            self.stdout.write(self.style.WARNING(
                "V souboru nebyla nalezena žádná karta (nadpis 1 ve tvaru „GEN / rsID“)."))
        else:
            self.stdout.write(self.style.SUCCESS(
                "Hotovo. Karty jsou v administraci (Genetika → Genové karty) jako návrhy "
                "k revizi; schvaluje je garant oblasti."))
