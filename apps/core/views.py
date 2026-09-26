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
    """Přehled laboratoře: co je nového a co čeká na mě."""
    from datetime import timedelta

    from apps.ingest.models import ImportBatch
    from apps.subjects.search import names_for

    today = timezone.localdate()
    sessions = TestSession.objects.for_user(request.user)
    recent = list(sessions.select_related("subject", "subject__sport")
                  .prefetch_related("protocol_runs__protocol").order_by("-date", "-pk")[:8])
    names = names_for([s.subject for s in recent], request.user)
    for s in recent:
        s.jmeno = names.get(s.subject_id) or s.subject.code
        s.protokoly = sorted({run.protocol.name for run in s.protocol_runs.all()})

    drafts = (Report.objects.for_user(request.user).filter(status=Report.Status.DRAFT)
              .select_related("subject").order_by("-created_at"))
    draft_names = names_for([r.subject for r in drafts[:6]], request.user)
    draft_list = list(drafts[:6])
    for r in draft_list:
        r.jmeno = draft_names.get(r.subject_id) or r.subject.code

    context = {
        "tiles": [
            ("Aktivní sportovci", Subject.objects.for_user(request.user)
             .filter(is_active=True).count(), "users"),
            ("Testovací dny za 30 dní", sessions.filter(
                date__gte=today - timedelta(days=30)).count(), "calendar"),
            ("Zprávy v konceptu", drafts.count(), "file"),
            ("Importy ke kontrole", ImportBatch.objects.for_user(request.user)
             .filter(status=ImportBatch.Status.PARSED).count(), "upload"),
        ],
        "pocet_mereni": Measurement.objects.filter(
            trial__protocol_run__session__in=sessions).count(),
        "posledni_session": recent,
        "koncepty": draft_list,
        "dnes": today,
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
