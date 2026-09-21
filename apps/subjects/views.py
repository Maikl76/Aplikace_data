from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.analytics import charts, queries
from apps.core.audit import record
from apps.core.models import AuditLog
from apps.measurements.models import TestSession

from .models import Subject


@login_required
def subject_list(request):
    """Seznam sportovců. Filtry přes HTMX – vrací se jen výsek tabulky."""
    qs = Subject.objects.for_user(request.user).select_related("sport", "team")
    if q := request.GET.get("q", "").strip():
        qs = qs.filter(code__icontains=q)
    if sport := request.GET.get("sport"):
        qs = qs.filter(sport_id=sport)

    context = {"subjects": qs[:200], "q": q}
    if request.headers.get("HX-Request"):
        return render(request, "subjects/_subject_rows.html", context)
    return render(request, "subjects/subject_list.html", context)


@login_required
def subject_detail(request, pk):
    """Karta sportovce – srdce aplikace: časová osa, trendy, zprávy."""
    subject = get_object_or_404(Subject.objects.for_user(request.user), pk=pk)
    record(request, AuditLog.Action.VIEW, subject, subject_code=subject.code)

    sessions = (
        TestSession.objects.filter(subject=subject)
        .prefetch_related("protocol_runs__protocol")
        .order_by("-date")
    )

    trends = [
        charts.trend_chart(s["metric"], s["points"],
                           qualifiers=s["qualifiers"], norm=s["norm"])
        for s in queries.primary_metric_series(subject)
    ]
    posledni, asymetrie = queries.latest_asymmetries(subject)

    return render(request, "subjects/subject_detail.html", {
        "subject": subject,
        "display_name": subject.display_for(request.user),
        "sessions": sessions,
        "external_exams": subject.external_exams.order_by("-date"),
        "reports": subject.reports.order_by("-created_at"),
        "trends": trends,
        "asymetrie_chart": charts.asymmetry_chart(asymetrie) if asymetrie else None,
        "asymetrie_rows": asymetrie,
        "asymetrie_session": posledni,
        "ma_strany": queries.has_side_data(subject),
    })
