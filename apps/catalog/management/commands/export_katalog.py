import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.catalog.transfer import export_catalog

DEFAULT = Path(settings.BASE_DIR) / "katalog" / "katalog.json"


class Command(BaseCommand):
    help = ("Uloží katalog (protokoly, metriky, MDC, normy, pravidla, články) do souboru "
            "v repozitáři, aby se dal přenést na jiný počítač nebo na server.")

    def add_arguments(self, parser):
        parser.add_argument("--soubor", default=str(DEFAULT))

    def handle(self, *args, **opts):
        data = export_catalog()
        path = Path(opts["soubor"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Katalog uložen do {path}"))
        for key in ("metriky", "protokoly", "normy", "clanky", "pravidla"):
            self.stdout.write(f"  {key}: {len(data[key])}")
        self.stdout.write("Přeneste ho gitem (commit + push) a na druhém počítači "
                          "spusťte: python manage.py import_katalog")
