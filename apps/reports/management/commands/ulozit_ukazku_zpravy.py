"""
Uloží vydanou zprávu od jazykového modelu jako ukázku pro PythonAnywhere.

    python manage.py ulozit_ukazku_zpravy            # poslední vydaná zpráva od modelu
    python manage.py ulozit_ukazku_zpravy FT-2026-0003
"""

from django.core.management.base import BaseCommand, CommandError

from apps.reports import demo_reports
from apps.reports.models import Report


class Command(BaseCommand):
    help = "Uloží vydanou zprávu od AI (z ukázkových dat) do demo/ukazkove_zpravy/."

    def add_arguments(self, parser):
        parser.add_argument("cislo", nargs="?", help="Číslo zprávy; bez něj poslední vydaná od AI.")

    def handle(self, *args, cislo=None, **options):
        reports = Report.objects.filter(status=Report.Status.RELEASED).select_related("subject")
        if cislo:
            report = reports.filter(report_number=cislo).first()
            if report is None:
                raise CommandError(f"Vydaná zpráva {cislo} neexistuje.")
        else:
            report = (reports.exclude(llm_model__in=["", "šablona"])
                      .filter(subject__identity__isnull=True).order_by("-released_at").first())
            if report is None:
                raise CommandError(
                    "Není žádná vydaná zpráva od jazykového modelu z ukázkových dat. "
                    "Zapněte LM Studio, u ukázkového sportovce (FTVS-00xx) vytvořte "
                    "zprávu a vydejte ji.")
        try:
            path = demo_reports.export(report)
        except demo_reports.DemoReportError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"Uloženo: {report.report_number} ({report.llm_model}) → {path.name}"))
