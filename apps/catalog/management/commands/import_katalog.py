import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.transfer import ImportError_, import_catalog
from apps.core.models import Organization

from .export_katalog import DEFAULT


class Command(BaseCommand):
    help = ("Načte katalog ze souboru (viz export_katalog). Přidává a aktualizuje, "
            "nic nemaže.")

    def add_arguments(self, parser):
        parser.add_argument("--soubor", default=str(DEFAULT))
        parser.add_argument("--organizace", default="",
                            help="Zkratka organizace pro záznamy, jejichž organizace "
                                 "v této databázi není.")

    def handle(self, *args, **opts):
        path = Path(opts["soubor"])
        if not path.exists():
            raise CommandError(f"Soubor {path} neexistuje. Stáhli jste ho (git pull)?")

        default_org = None
        if opts["organizace"]:
            default_org = Organization.objects.filter(short_name=opts["organizace"]).first()
            if default_org is None:
                raise CommandError(f"Organizace „{opts['organizace']}“ neexistuje.")
        elif Organization.objects.count() == 1:
            default_org = Organization.objects.get()

        try:
            counts = import_catalog(json.loads(path.read_text(encoding="utf-8")),
                                    default_org=default_org)
        except ImportError_ as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f"Katalog načten z {path}"))
        for label, (created, updated) in counts.items():
            self.stdout.write(f"  {label}: nových {created}, aktualizovaných {updated}")
