import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.catalog.transfer import export_catalog

DEFAULT = Path(settings.BASE_DIR) / "katalog" / "katalog.json"


class Command(BaseCommand):
    help = ("Uloží nastavení (sporty, testy, metriky, MDC, baterie, normy, pravidla, články, "
            "dotazníky, nabídku, genetiku) do souboru v repozitáři, aby se dalo přenést na "
            "jiný počítač nebo na server. V aplikaci totéž: Nastavení → Přenos nastavení.")

    def add_arguments(self, parser):
        parser.add_argument("--soubor", default=str(DEFAULT))

    def handle(self, *args, **opts):
        data = export_catalog()
        # Do souboru v repozitáři bez času a jména počítače – jinak by se soubor
        # „změnil“ při každém uložení, i když se v nastavení nic nezměnilo.
        data.pop("meta", None)
        path = Path(opts["soubor"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n",
                        encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Katalog uložen do {path}"))
        for key in ("sporty", "tymy", "metriky", "protokoly", "pristroje", "profily_importu",
                    "baterie", "normy", "clanky", "pravidla", "dotazniky", "nabidka"):
            self.stdout.write(f"  {key}: {len(data[key])}")
        self.stdout.write("Přeneste ho gitem (commit + push) a na druhém počítači "
                          "spusťte: python manage.py import_katalog")
