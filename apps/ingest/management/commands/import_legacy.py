"""
Hromadná migrace dat z původní Streamlit aplikace.

    python manage.py import_legacy data/historical_data.xlsx --date 2024-03-12

Prochází stejnou pipeline jako import přes webové rozhraní: staging,
kontrola, uložení. Rozdíl je jen v tom, že potvrzení nahrazuje přepínač
``--commit`` – bez něj se vypíše jen náhled.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from apps.core.models import Organization
from apps.ingest import services
from apps.ingest.models import ImportBatch


class Command(BaseCommand):
    help = "Naimportuje Excel z původní aplikace."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--organization", default="ftvs",
                            help="Zkratka organizace (výchozí: ftvs).")
        parser.add_argument("--user", default=None,
                            help="Uživatelské jméno operátora. Výchozí: první superuživatel.")
        parser.add_argument("--date", default=None,
                            help="Datum měření pro řádky bez DatumMereni (YYYY-MM-DD).")
        parser.add_argument("--commit", action="store_true",
                            help="Bez tohoto přepínače se jen vypíše náhled.")

    def handle(self, *args, **options):
        try:
            organization = Organization.objects.get(short_name=options["organization"])
        except Organization.DoesNotExist as exc:
            raise CommandError(
                f"Organizace „{options['organization']}“ neexistuje. "
                f"Založte ji v administraci nebo spusťte seed_demo."
            ) from exc

        User = get_user_model()
        user = (User.objects.get(username=options["user"]) if options["user"]
                else User.objects.filter(is_superuser=True).first())
        if user is None:
            raise CommandError("Není k dispozici žádný uživatel – vytvořte správce.")

        default_date = date.fromisoformat(options["date"]) if options["date"] else None

        with open(options["path"], "rb") as handle:
            batch = services.stage_file(
                uploaded_file=File(handle, name=options["path"].rsplit("/", 1)[-1]),
                user=user, organization=organization, adapter_code="legacy_excel",
            )

        if batch.status == ImportBatch.Status.FAILED:
            raise CommandError(f"Import selhal: {batch.error}")

        s = batch.summary
        self.stdout.write(
            f"\nNáhled importu „{batch.raw_file.original_name}“:\n"
            f"  hodnot:            {s['hodnot']}\n"
            f"  sportovců:         {s['sportovcu']} (z toho nových {s['novych_sportovcu']})\n"
            f"  metrik:            {s['metrik']}\n"
            f"  protokolů:         {s['protokolu']}\n"
            f"  mimo rozsah:       {s['mimo_rozsah']}\n"
            f"  rozsah dat:        {s['datum_od'] or '—'} až {s['datum_do'] or '—'}\n"
        )
        if s.get("nezmapovane_sloupce"):
            self.stdout.write(self.style.WARNING(
                f"  nezmapované sloupce: {', '.join(s['nezmapovane_sloupce'])}\n"
                f"  Tyto sloupce se NEIMPORTUJÍ. Pokud je chcete, doplňte je do\n"
                f"  LEGACY_COLUMN_MAP v apps/catalog/seed_data.py."
            ))
        if s["nezname_metriky"]:
            self.stdout.write(self.style.WARNING(
                f"  neznámé sloupce:   {', '.join(s['nezname_metriky'])}\n"
                f"  (doplňte je do LEGACY_COLUMN_MAP nebo do katalogu)"
            ))

        if not options["commit"]:
            self.stdout.write(self.style.WARNING(
                "\nNic se neuložilo. Pro uložení spusťte znovu s --commit."
            ))
            return

        result = services.commit_batch(batch, user=user, default_date=default_date)
        self.stdout.write(self.style.SUCCESS(
            f"\nUloženo:\n"
            f"  hodnot:            {result['hodnoty']}\n"
            f"  testovacích dnů:   {result['session']}\n"
            f"  nových sportovců:  {result['sportovci']}\n"
            f"  přeskočeno:        {result['preskoceno']}"
        ))
        self.stdout.write(
            "Jména se neuložila – sportovci mají pseudonymní kódy a hash pro "
            "spárování při příštím importu."
        )
