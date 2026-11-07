"""
Denní údržba z příkazové řádky (apps/core/maintenance.py): záloha, úklid
starých importů, připomínky měření a týdenní stav správci. Bez --jednou běží
dokola a každý den to udělá jednou – tak ho spouští spustit.bat ve vlastním
okně; na serveru (PythonAnywhere) je to plánovaná úloha s --jednou.
"""

import logging
import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core import maintenance
from apps.core.models import Organization
from apps.subjects import retest

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Denní údržba: záloha, úklid starých importů, připomínky měření, týdenní stav správci."

    def add_arguments(self, parser):
        parser.add_argument("--jednou", action="store_true", help="Proběhnout jednou a skončit.")
        parser.add_argument("--interval", type=int, default=30,
                            help="Minuty mezi kontrolami, zda už dnes údržba proběhla (výchozí 30).")
        parser.add_argument("--znovu", action="store_true", dest="force",
                            help="Spustit i dnes podruhé (např. po opravě zálohy).")
        parser.add_argument("--stav", action="store_true",
                            help="Jen poslat správci e-mail se stavem pracoviště a skončit.")

    def handle(self, *args, **options):
        orgs = list(Organization.objects.filter(is_active=True))
        if options["stav"]:
            for org in orgs:
                sent = maintenance.send_status(org, force=True)
                self.stdout.write(f"{org.short_name}: stav správci "
                                  + (f"odeslán ({sent} adres)" if sent
                                     else "neodeslán – bez poštovního serveru, nebo správce bez e-mailu"))
            return
        link = retest.booking_link("")
        if not options["jednou"]:
            self.stdout.write(f"Denní údržba běží; kontrola každých {options['interval']} min. "
                              "Ukončení: Ctrl+C.")
        while True:
            for org in orgs:
                try:
                    out = maintenance.daily(org, booking_url=link, force=options["force"])
                except Exception:   # údržba nesmí spadnout kvůli jednomu kroku
                    logger.exception("Denní údržba pracoviště %s selhala", org.short_name)
                    self.stderr.write(f"{org.short_name}: údržba selhala – podrobnosti v logu.")
                    continue
                if out is None:
                    if options["jednou"]:
                        self.stdout.write(f"{org.short_name}: dnes už údržba proběhla.")
                    continue
                self.stdout.write(f"{timezone.localtime():%d.%m. %H:%M} {org.short_name}: "
                                  + self._describe(out.log))
            if options["jednou"]:
                break
            options["force"] = False
            time.sleep(options["interval"] * 60)

    @staticmethod
    def _describe(log: dict) -> str:
        z = log.get("zaloha", {})
        parts = [("záloha " + (z.get("cesta", "ok") if z.get("ok") else f"NEPROBĚHLA ({z.get('chyba', '')})"))]
        if log.get("importy_smazano"):
            parts.append(f"smazáno starých importů {log['importy_smazano']}")
        p = log.get("pripominky")
        if isinstance(p, dict):
            parts.append(f"připomínek odesláno {p['odeslano']} (na řadě {p['na_rade']})")
        if "stav_spravci" in log:
            s = log["stav_spravci"]
            parts.append("stav správci " + (f"odeslán ({s['odeslano']} adres)" if isinstance(s, dict) else s))
        return "; ".join(parts) + "."
