"""Anonymizovaný výzkumný export genetiky a měření do souboru ZIP (pro offline server)."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core.models import Organization
from apps.genetics import research


class Command(BaseCommand):
    help = "Uloží anonymizovaný výzkumný export (genotypy, měření, dotazník) jako ZIP."

    def add_arguments(self, parser):
        parser.add_argument("--cil", default="", help="Cesta k výslednému ZIP (výchozí: "
                                                     "vyzkum-RRRR-MM-DD.zip v pracovní složce).")
        parser.add_argument("--organizace", default="", help="Zkratka pracoviště (jediné = netřeba).")

    def handle(self, *args, **options):
        organizations = Organization.objects.order_by("pk")
        if options["organizace"]:
            organizations = organizations.filter(short_name=options["organizace"])
        organization = organizations.first()
        if organization is None or (organizations.count() > 1 and not options["organizace"]):
            raise CommandError("Zadejte --organizace se zkratkou pracoviště.")
        try:
            content, count = research.build_export(organization)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        target = Path(options["cil"] or f"vyzkum-{timezone.localdate():%Y-%m-%d}.zip")
        target.write_bytes(content)
        self.stdout.write(self.style.SUCCESS(f"Uloženo {target} ({count} osob)."))
