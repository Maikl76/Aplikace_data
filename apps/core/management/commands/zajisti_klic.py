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
    help = "Doplní IDENTITY_ENCRYPTION_KEY do souboru .env, pokud chybí."

    def handle(self, *args, **options):
        from cryptography.fernet import Fernet

        env_file = Path(settings.BASE_DIR) / ".env"
        if not env_file.exists():
            self.stdout.write("Soubor .env neexistuje – nic nedělám.")
            return

        text = env_file.read_text(encoding="utf-8")
        match = re.search(r"^IDENTITY_ENCRYPTION_KEY=(.*)$", text, flags=re.MULTILINE)
        if match and match.group(1).strip():
            self.stdout.write("Šifrovací klíč už je nastavený.")
            return

        line = f"IDENTITY_ENCRYPTION_KEY={Fernet.generate_key().decode()}"
        if match:
            text = text[:match.start()] + line + text[match.end():]
        else:
            text = text.rstrip("\n") + (
                "\n\n# Klíč k šifrovaným jménům sportovců. NEMĚŇTE ho a zálohujte ho\n"
                "# spolu s databází – bez něj uložená jména nejdou přečíst.\n"
                f"{line}\n")
        env_file.write_text(text, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(
            "Do .env byl doplněn šifrovací klíč. Zálohujte ho spolu s databází."))
