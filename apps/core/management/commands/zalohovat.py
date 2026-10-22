"""
Záloha laboratorního počítače: databáze (SQLite), nahrané soubory a .env.

Dokumentace dřív tvrdila, že na počítačích jsou jen vymyšlená data;
v praxi se na laboratorním PC importují skutečné exporty. Bez zálohy
by výpadek disku vzal roky měření. A bez .env (šifrovací klíč) jsou
uložená jména nečitelná i ze zálohy databáze – proto se bere i on.

Databáze se kopíruje zálohovacím rozhraním SQLite, takže je kopie
konzistentní, i když aplikace zrovna běží (režim WAL).
"""

import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone


class Command(BaseCommand):
    help = "Zálohuje databázi SQLite, nahrané soubory a .env do složky (výchozí ~/Zalohy-FTVS)."

    def add_arguments(self, parser):
        parser.add_argument("--cil", default=None,
                            help="Cílová složka (flash disk, síťový disk). Výchozí ~/Zalohy-FTVS.")
        parser.add_argument("--ponechat", type=int, default=10,
                            help="Kolik posledních záloh v cílové složce nechat; starší se smažou.")
        parser.add_argument("--databaze", default=None,
                            help="Soubor databáze; výchozí je ten z nastavení (DATABASE_URL).")

    def handle(self, *args, **options):
        if connection.vendor != "sqlite":
            raise CommandError("Tahle záloha je pro SQLite (laboratorní počítač, notebook). "
                               "Server zálohuje deploy/backup.sh.")
        source = str(options["databaze"] or connection.settings_dict["NAME"])
        if source.startswith("file:") or source == ":memory:":
            raise CommandError("Databáze není v souboru – není co zálohovat.")
        source_path = Path(source)
        if not source_path.is_absolute():
            source_path = Path(settings.BASE_DIR) / source_path
        if not source_path.exists():
            raise CommandError(f"Soubor databáze {source_path} neexistuje.")

        root = Path(options["cil"] or Path.home() / "Zalohy-FTVS")
        stamp = f"ftvs-zaloha-{timezone.localtime():%Y-%m-%d-%H%M%S}"
        target, n = root / stamp, 2
        while target.exists():                  # dvě zálohy v téže sekundě
            target, n = root / f"{stamp}-{n}", n + 1
        target.mkdir(parents=True)

        import sqlite3

        # Vlastní spojení: zálohovací rozhraní si databázi přečte konzistentně,
        # i když v ní aplikace zrovna zapisuje (WAL).
        src, copy = sqlite3.connect(source_path), sqlite3.connect(target / "db.sqlite3")
        try:
            src.backup(copy)
        finally:
            copy.close()
            src.close()
        size_mb = (target / "db.sqlite3").stat().st_size / 1_000_000

        env_file = Path(settings.BASE_DIR) / ".env"
        has_env = env_file.exists()
        if has_env:
            shutil.copy2(env_file, target / ".env")

        media = Path(settings.MEDIA_ROOT)
        files = 0
        if media.is_dir():
            shutil.copytree(media, target / "media")
            files = sum(1 for p in (target / "media").rglob("*") if p.is_file())

        keep = max(options["ponechat"], 1)
        old = sorted(p for p in root.glob("ftvs-zaloha-*") if p.is_dir())[:-keep]
        for folder in old:
            shutil.rmtree(folder)

        self.stdout.write(self.style.SUCCESS(f"Záloha: {target}"))
        self.stdout.write(f"  databáze {size_mb:.1f} MB, nahraných souborů {files}, "
                          f".env {'ano' if has_env else 'NE – chybí, jména by ze zálohy nešla přečíst'}")
        if old:
            self.stdout.write(f"  smazáno starších záloh: {len(old)} (nechávám {keep})")
        self.stdout.write("Složku uložte mimo tento počítač – šifrovaný disk nebo síťové úložiště. "
                          "Obsahuje jména sportovců (.env + databáze).")
