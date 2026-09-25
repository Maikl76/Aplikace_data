"""
Ověří, že aplikace dosáhne na jazykový model a že umí česky.

    python manage.py llm_check

Pošle modelu krátké zadání se dvěma čísly a zkontroluje, že je v odpovědi
nezměnil – stejnou kontrolou, jakou prochází text zprávy.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.reports import llm
from apps.reports.narrative import NUMBER


class Command(BaseCommand):
    help = "Ověří spojení s jazykovým modelem."

    def handle(self, *args, **options):
        self.stdout.write(f"Adresa:  {settings.LLM_BASE_URL}")
        self.stdout.write(f"Model:   {settings.LLM_MODEL}")
        self.stdout.write(f"Zapnuto: {'ano' if settings.LLM_ENABLED else 'NE (LLM_ENABLED)'}\n")

        messages = [
            {"role": "system", "content":
                "Odpovídej česky, jednou větou, a používej jen čísla ze zadání."},
            {"role": "user", "content":
                "Výška výskoku se zvýšila z 38,5 cm na 41,2 cm. Shrň to jednou větou."},
        ]
        try:
            reply = llm.chat(messages, timeout=settings.LLM_TIMEOUT)
        except llm.LLMError as exc:
            self.stdout.write(self.style.ERROR(f"Nedostupné: {exc}"))
            return

        self.stdout.write(f"Odpověď za {reply.seconds:.1f} s:\n  {reply.text}\n")

        cisla = {round(abs(float(n.replace(",", "."))), 2) for n in NUMBER.findall(reply.text)}
        cizi = cisla - {38.5, 41.2, 2.7, 1}
        if cizi:
            self.stdout.write(self.style.WARNING(
                f"Model přidal čísla, která v zadání nebyla: {sorted(cizi)}. "
                f"U zpráv by takový text kontrola odmítla a použila šablonu."
            ))
        else:
            self.stdout.write(self.style.SUCCESS("Spojení funguje, čísla sedí."))

        if not settings.LLM_ENABLED:
            self.stdout.write(
                "\nModel odpovídá, ale zprávy ho zatím nepoužívají – zapněte LLM_ENABLED=True."
            )
