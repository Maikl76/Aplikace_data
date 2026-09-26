"""Přepočítá odvozené ukazatele (DSI) u všech testovacích dnů."""

from django.core.management.base import BaseCommand

from apps.analytics.derived import recompute
from apps.measurements.models import TestSession


class Command(BaseCommand):
    help = "Dopočítá odvozené ukazatele (např. DSI z CMJ a IMTP) u všech testovacích dnů."

    def handle(self, *args, **options):
        pocet = 0
        sessions = TestSession.objects.filter(
            protocol_runs__protocol__code__in=["cmj", "imtp", "dsi"]).distinct()
        for session in sessions.iterator():
            pocet += recompute(session)
        self.stdout.write(f"Odvozené ukazatele: {pocet} hodnot.")
