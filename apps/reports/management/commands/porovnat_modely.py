"""
Zkušební texty pro celou zkušební sadu zpráv – porovnání modelů a pokynů.

    python manage.py porovnat_modely
    python manage.py porovnat_modely --model muse-glimmer-30b

Každá zpráva ze zkušební sady (AI zprávy → Zkušební sada) dostane nový
zkušební text od zadaného modelu (bez --model od toho z nastavení).
Výsledky jsou vidět v aplikaci vedle textů, které diagnostici vydali.
Do zpráv se nic nezapisuje.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.reports import llm, services
from apps.reports.models import Report


class Command(BaseCommand):
    help = "Zkušební texty pro zkušební sadu zpráv (porovnání modelů)."

    def add_arguments(self, parser):
        parser.add_argument("--model", default="", help="Název modelu (jinak LLM_MODEL).")

    def handle(self, *args, **opts):
        if not llm.is_enabled():
            raise CommandError("Jazykový model není zapnutý (LLM_ENABLED=True v .env).")
        reports = Report.objects.filter(in_test_set=True).select_related("session")
        if not reports:
            self.stdout.write("Zkušební sada je prázdná – přidejte do ní vydané zprávy v aplikaci.")
            return
        ok = 0
        for report in reports:
            trial = services.try_model(report, model=opts["model"], user=None)
            if trial.error:
                state = f"CHYBA: {trial.error}"
            elif trial.problems:
                state = f"čísla bez opory: {', '.join(trial.problems)}"
            else:
                state, ok = "v pořádku", ok + 1
            self.stdout.write(f"  {report.report_number} ({trial.model}, {trial.seconds:.0f} s): {state}")
        self.stdout.write(self.style.SUCCESS(
            f"Hotovo: {ok} z {reports.count()} textů bez problému. Porovnejte je v aplikaci: "
            f"Zprávy → AI zprávy → Zkušební sada."))
