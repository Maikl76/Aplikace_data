from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from apps.measurements.models import Measurement, TestSession
from apps.reports.models import Report
from apps.subjects.models import Subject


@login_required
def dashboard(request):
    """Přehled laboratoře. Zatím čísla, postupně přibudou akce."""
    sessions = TestSession.objects.for_user(request.user)
    context = {
        "pocet_sportovcu": Subject.objects.for_user(request.user).filter(is_active=True).count(),
        "pocet_mereni": Measurement.objects.filter(
            trial__protocol_run__session__in=sessions
        ).count(),
        "posledni_session": sessions.select_related("subject").order_by("-date")[:10],
        "reporty_koncepty": Report.objects.for_user(request.user).filter(
            status=Report.Status.DRAFT
        ).count(),
        "dnes": timezone.localdate(),
    }
    return render(request, "core/dashboard.html", context)


def health(request):
    """
    Kontrola běhu pro hosting. Nekontroluje jen to, že aplikace odpovídá,
    ale i že se dostane k databázi – bez ní je nastartovaná k ničemu.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({"stav": "ok", "databaze": "ok"})
    except Exception as exc:
        return JsonResponse(
            {"stav": "chyba", "databaze": f"{type(exc).__name__}"}, status=503,
        )
