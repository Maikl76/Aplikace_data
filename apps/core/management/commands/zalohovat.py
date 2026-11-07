"""
Záloha laboratorního počítače: databáze (SQLite), nahrané soubory a .env.
Samotnou zálohu dělá apps/core/backup.py – stejnou používá denní údržba.
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core import backup


class Command(BaseCommand):
    help = "Zálohuje databázi SQLite, nahrané soubory a .env do složky (výchozí ~/Zalohy-FTVS)."

    def add_arguments(self, parser):
        parser.add_argument("--cil", default=None,
                            help="Cílová složka (flash disk, síťový disk). Výchozí ~/Zalohy-FTVS.")
        parser.add_argument("--ponechat", type=int, default=10,
                            help="Kolik posledních záloh v cílové složce nechat; starší se smažou.")
        parser.add_argument("--databaze", default=None,
                            help="Soubor databáze; výchozí je ten z nastavení (DATABASE_URL).")
        parser.add_argument("--popis", default="",
                            help="Připojí se k názvu složky, např. pred-aktualizaci.")

    def handle(self, *args, **options):
        try:
            result = backup.backup_sqlite(
                root=Path(options["cil"]) if options["cil"] else None,
                keep=options["ponechat"], label=options["popis"], database=options["databaze"])
        except backup.BackupError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f"Záloha: {result.path}"))
        self.stdout.write(f"  databáze {result.size_mb:.1f} MB, nahraných souborů {result.files}, "
                          f".env {'ano' if result.has_env else 'NE – chybí, jména by ze zálohy nešla přečíst'}")
        if result.removed:
            self.stdout.write(f"  smazáno starších záloh: {result.removed} "
                              f"(nechávám {max(options['ponechat'], 1)})")
        self.stdout.write("Složku uložte mimo tento počítač – šifrovaný disk nebo síťové úložiště. "
                          "Obsahuje jména sportovců (.env + databáze).")
