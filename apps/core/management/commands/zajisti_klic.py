"""
Doplní do .env šifrovací klíč pro jména sportovců, pokud tam chybí.

Bez klíče aplikace jména neukládá (identita je šifrovaná). Klíč se
vygeneruje jednou a pak se NESMÍ měnit ani ztratit – bez něj už uložená
jména nejdou přečíst. Proto ho příkaz nikdy nepřepíše, jen doplní chybějící.
"""

import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Doplní do .env šifrovací klíč jmen a tajný klíč Djanga, pokud chybí."

    # Ukázkové hodnoty z .env.example – chovají se jako chybějící klíč.
    PLACEHOLDERS = {"zmente-me-na-nahodny-retezec", "VLOZTE_VYGENEROVANY_KLIC", "__SECRET__",
                    "pouze-pro-vyvoj-nikdy-v-produkci"}

    def handle(self, *args, **options):
        import secrets

        from cryptography.fernet import Fernet

        env_file = Path(settings.BASE_DIR) / ".env"
        if not env_file.exists():
            self.stdout.write("Soubor .env neexistuje – nic nedělám.")
            return

        text = env_file.read_text(encoding="utf-8")
        text, added = self._ensure(
            text, "IDENTITY_ENCRYPTION_KEY", lambda: Fernet.generate_key().decode(),
            "# Klíč k šifrovaným jménům sportovců. NEMĚŇTE ho a zálohujte ho\n"
            "# spolu s databází – bez něj uložená jména nejdou přečíst.")
        if added:
            self.stdout.write(self.style.SUCCESS(
                "Do .env byl doplněn šifrovací klíč. Zálohujte ho spolu s databází."))
        else:
            self.stdout.write("Šifrovací klíč už je nastavený.")
        text, added = self._ensure(
            text, "DJANGO_SECRET_KEY", lambda: secrets.token_urlsafe(50),
            "# Tajný klíč Djanga (podpis přihlášení). Neměňte ho.")
        if added:
            self.stdout.write(self.style.SUCCESS("Do .env byl doplněn DJANGO_SECRET_KEY."))
        env_file.write_text(text, encoding="utf-8")

    def _ensure(self, text: str, name: str, generate, comment: str) -> tuple[str, bool]:
        match = re.search(rf"^{name}=(.*)$", text, flags=re.MULTILINE)
        current = match.group(1).strip() if match else ""
        if current and current not in self.PLACEHOLDERS:
            return text, False
        line = f"{name}={generate()}"
        if match:
            return text[:match.start()] + line + text[match.end():], True
        return text.rstrip("\n") + f"\n\n{comment}\n{line}\n", True
