"""
Kontrola po aktualizaci: je databáze v pořádku, jde do ní zapisovat,
má každý účet pracoviště? Na PythonAnywhere navíc ukáže poslední chybu
webové aplikace z jejího logu.

    python manage.py kontrola_ukazky

Výpis je pro člověka: co je v pořádku, co ne a co s tím udělat.
"""

from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from apps.core.models import AuditLog, Organization, User


class _Zpet(Exception):
    """Zkušební zápis se vždy vrátí."""


class Command(BaseCommand):
    help = "Zkontroluje databázi, zápis a účty bez pracoviště; ukáže poslední chybu webu."

    def handle(self, *args, **options):
        from apps.reports.models import Report
        from apps.subjects.models import Sport, Subject

        problems = 0
        if connection.vendor == "sqlite":
            result = connection.cursor().execute("PRAGMA integrity_check").fetchone()[0]
            if result == "ok":
                self.stdout.write("Databáze: v pořádku.")
            else:
                problems += 1
                self.stdout.write(self.style.ERROR(f"Databáze je poškozená: {result[:300]}"))
                self.stdout.write("  Obnovte zálohu (bash deploy/pa-update.sh --obnovit).")

        try:
            with transaction.atomic():
                AuditLog.objects.create(action=AuditLog.Action.VIEW, object_type="kontrola",
                                        object_id="", detail={})
                raise _Zpet
        except _Zpet:
            self.stdout.write("Zápis do databáze: funguje.")
        except Exception as exc:  # zámek, jen pro čtení, poškození – ukázat přesně
            problems += 1
            self.stdout.write(self.style.ERROR(f"Zápis do databáze NEJDE: {exc}"))

        organizations = Organization.objects.count()
        if organizations == 0:
            problems += 1
            self.stdout.write(self.style.ERROR("Není založené žádné pracoviště (organizace)."))
        missing = list(User.objects.filter(organization__isnull=True, is_active=True)
                       .values_list("username", flat=True))
        if missing:
            problems += 1
            self.stdout.write(self.style.ERROR(
                f"Účty bez pracoviště – v aplikaci neuvidí nic: {', '.join(missing)}. "
                f"V administraci u nich vyberte organizaci."))
        self.stdout.write(f"Obsah: sportovci {Subject.objects.count()}, sporty "
                          f"{Sport.objects.count()}, zprávy {Report.objects.count()}, účty "
                          f"{User.objects.filter(is_active=True).count()}.")

        for log in sorted(Path("/var/log").glob("*.error.log")):
            last = _last_error(log)
            if last:
                self.stdout.write(f"Poslední chyba webu ({log.name}): {last}")

        if problems:
            self.stdout.write(self.style.ERROR(f"Výsledek: problémů {problems} – viz výše."))
        else:
            self.stdout.write(self.style.SUCCESS("Výsledek: vše v pořádku."))


def _last_error(path: Path) -> str:
    """Poslední řádek s výjimkou z logu chyb (stačí konec souboru)."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(handle.tell() - 64_000, 0))
            lines = handle.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        text = line.strip()
        if ("Error:" in text or "Exception:" in text) and not text.startswith("File "):
            return text[:300]
    return ""
