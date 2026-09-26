from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.analytics import charts, overview, queries
from apps.core.audit import record
from apps.core.models import AuditLog
from apps.measurements.models import TestSession

from . import search
from .models import Sport, Subject


@login_required
def subject_list(request):
    """Seznam sportovců. Filtry přes HTMX – vrací se jen výsek tabulky."""
    qs = Subject.objects.for_user(request.user).select_related("sport", "team")
    if sport := request.GET.get("sport"):
        qs = qs.filter(sport_id=sport)
    q = request.GET.get("q", "").strip()
    subjects = (search.search(request.user, q, limit=None, base=qs) if q
                else search.annotate(qs.order_by("code"), request.user, limit=300))

    context = {"subjects": subjects, "q": q,
               "sports": Sport.objects.for_user(request.user).order_by("name"),
               "sport_id": sport}
    if request.headers.get("HX-Request"):
        return render(request, "subjects/_subject_rows.html", context)
    return render(request, "subjects/subject_list.html", context)


@login_required
def subject_search(request):
    """Našeptávač v horní liště: pár nejlepších shod, nebo naposledy měření."""
    q = request.GET.get("q", "")
    return render(request, "subjects/_search_results.html", {
        "results": search.search(request.user, q, limit=8), "q": q.strip(),
    })


def _both_themes(build):
    """Graf pro světlý i tmavý režim – prohlížeč si vybere podle přepínače."""
    spec = build("light")
    spec.figure_dark = build("dark").figure
    return spec


@login_required
def subject_detail(request, pk):
    """Karta sportovce – srdce aplikace: hlavní čísla, trendy, historie, zprávy."""
    subject = get_object_or_404(Subject.objects.for_user(request.user)
                                .select_related("sport", "team"), pk=pk)
    record(request, AuditLog.Action.VIEW, subject, subject_code=subject.code)

    sessions = list(
        TestSession.objects.filter(subject=subject)
        .prefetch_related("protocol_runs__protocol", "reports")
        .order_by("-date")
    )
    for session in sessions:
        session.protokoly = sorted({run.protocol.name for run in session.protocol_runs.all()})

    trends = [
        _both_themes(lambda theme, s=s: charts.trend_chart(
            s["metric"], s["points"], qualifiers=s["qualifiers"], norm=s["norm"], theme=theme))
        for s in queries.primary_metric_series(subject)
    ]
    posledni, asymetrie = queries.latest_asymmetries(subject)

    return render(request, "subjects/subject_detail.html", {
        "subject": subject,
        "display_name": subject.display_for(request.user),
        "sessions": sessions,
        "last_session": sessions[0] if sessions else None,
        "tiles": overview.kpi_tiles(subject),
        "external_exams": subject.external_exams.order_by("-date"),
        "reports": subject.reports.order_by("-created_at")[:10],
        "trends": trends,
        "asymetrie_chart": (_both_themes(lambda theme: charts.asymmetry_chart(asymetrie, theme=theme))
                            if asymetrie else None),
        "asymetrie_rows": asymetrie,
        "asymetrie_session": posledni,
        "ma_strany": queries.has_side_data(subject),
    })
