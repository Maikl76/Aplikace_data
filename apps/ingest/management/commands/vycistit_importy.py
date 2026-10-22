"""Smaže nedokončené importy starší než 30 dní (na serveru z cronu; aplikace to dělá i sama)."""

from django.core.management.base import BaseCommand

from apps.ingest import services


class Command(BaseCommand):
    help = "Smaže nedokončené a zrušené importy starší než zadaný počet dní, i se souborem."

    def add_arguments(self, parser):
        parser.add_argument("--dny", type=int, default=services.STALE_DAYS)

    def handle(self, *args, **options):
        count = services.expire_stale(days=options["dny"])
        self.stdout.write(f"Smazáno nedokončených importů: {count}.")
