"""
Hlídač sledované složky: každých pár sekund projde složku s exporty
z přístroje a nové soubory importuje (viz apps/ingest/watch.py).
Spouští ho spustit.bat ve vlastním okně; bez nastavené složky hned skončí.
"""

import logging
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core.models import default_organization
from apps.ingest import watch

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Hlídá sledovanou složku s exporty z přístroje a nové soubory importuje."

    def add_arguments(self, parser):
        parser.add_argument("--jednou", action="store_true", help="Projít složku jednou a skončit.")
        parser.add_argument("--interval", type=int, default=None,
                            help="Sekundy mezi kontrolami (výchozí IMPORT_WATCH_INTERVAL).")
        parser.add_argument("--slozka", default="", help="Jiná složka než IMPORT_WATCH_DIR.")

    def handle(self, *args, **options):
        directory = Path(options["slozka"]) if options["slozka"] else watch.folder()
        if directory is None:
            self.stdout.write("Sledovaná složka není nastavená – do .env doplňte IMPORT_WATCH_DIR "
                              "(složka, kam přístroj ukládá exporty) a spusťte spustit.bat znovu.")
            return
        organization = default_organization()
        if organization is None:
            raise CommandError("Pracoviště nejde určit (žádné, nebo víc než jedno).")
        interval = options["interval"] or settings.IMPORT_WATCH_INTERVAL
        self.stdout.write(f"Sleduji složku {directory} (pracoviště {organization.name}); "
                          f"kontrola každých {interval} s. Ukončení: Ctrl+C.")
        while True:
            try:
                for outcome in watch.scan(organization, directory=directory):
                    self.stdout.write(f"{timezone.localtime():%H:%M} {outcome.name}: "
                                      f"{outcome.label.lower()} – {outcome.message}")
            except watch.WatchError as exc:
                self.stderr.write(str(exc))
            except Exception:   # hlídač nesmí spadnout kvůli jednomu souboru
                logger.exception("Kontrola sledované složky selhala")
                self.stderr.write("Chyba při kontrole složky – pokračuji.")
            if options["jednou"]:
                break
            time.sleep(interval)
