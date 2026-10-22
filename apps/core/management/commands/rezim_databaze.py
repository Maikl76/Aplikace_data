"""
Ukáže režim deníku SQLite a převede ho na nastavený.

    python manage.py rezim_databaze --opakovat 10

Na PythonAnywhere se pouští po restartu webové aplikace (pa-update.sh):
přechod z WAL jde, jen když databázi nemá otevřenou nikdo jiný, proto
se zkouší opakovaně. Když se to nepovede, převede ji později aplikace
sama při některém z dalších připojení.
"""

import time

from django.core.management.base import BaseCommand
from django.db import connection

from apps.core.sqlite import set_journal_mode, wanted_mode


class Command(BaseCommand):
    help = "Ukáže režim deníku SQLite (wal/delete) a převede ho na nastavený."

    def add_arguments(self, parser):
        parser.add_argument("--opakovat", type=int, default=1,
                            help="Kolikrát zkusit převod (po 3 s), když je databáze otevřená jinde.")

    def handle(self, *args, **options):
        if connection.vendor != "sqlite":
            self.stdout.write("Databáze není SQLite – režim deníku se neřeší.")
            return
        wanted = wanted_mode()
        mode = ""
        for attempt in range(max(options["opakovat"], 1)):
            if attempt:
                time.sleep(3)
            connection.ensure_connection()
            mode = set_journal_mode(connection.connection)
            if mode in (wanted, "memory"):
                break
            connection.close()
        if mode in (wanted, "memory"):
            self.stdout.write(f"Režim databáze: {mode}.")
        else:
            self.stdout.write(f"Režim databáze: {mode} (má být {wanted}) – je otevřená "
                              f"i jinde; aplikace ji převede sama při dalším připojení.")
