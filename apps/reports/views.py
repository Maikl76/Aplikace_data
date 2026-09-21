from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.audit import record
from apps.core.models import AuditLog
from apps.measurements.models import TestSession
from apps.subjects.models import Consent

from . import services
from .models import Report, ReportDelivery


@login_required
def report_list(request):
    reports = (Report.objects.for_user(request.user)
               .select_related("subject", "session")[:100])
    return render(request, "reports/report_list.html", {"reports": reports})


@login_required
def report_create(request, session_pk):
    session = get_object_or_404(TestSession.objects.for_user(request.user), pk=session_pk)
    if request.method != "POST":
        return redirect("session_detail", pk=session_pk)
    try:
        report = services.build_draft(session, user=request.user)
    except services.ReportError as exc:
        messages.error(request, str(exc))
        return redirect("session_detail", pk=session_pk)

    record(request, AuditLog.Action.CREATE, report, subject_code=session.subject.code)
    return redirect("report_detail", pk=report.pk)


@login_required
def report_detail(request, pk):
    report = get_object_or_404(Report.objects.for_user(request.user), pk=pk)

    if request.method == "POST" and report.is_editable:
        report.custom_note = request.POST.get("custom_note", "")
        report.save(update_fields=["custom_note"])
        messages.success(request, "Komentář uložen.")
        return redirect("report_detail", pk=pk)

    context = services.report_context(report)
    context.update({
        "ma_souhlas": Consent.has(report.subject, Consent.Scope.REPORT_HANDOVER),
        "channels": ReportDelivery.Channel.choices,
    })
    return render(request, "reports/report_detail.html", context)


@login_required
def report_preview(request, pk):
    """Náhled přesně toho, co půjde do PDF."""
    report = get_object_or_404(Report.objects.for_user(request.user), pk=pk)
    record(request, AuditLog.Action.VIEW, report, subject_code=report.subject.code)
    return HttpResponse(services.render_html(report))


@login_required
def report_release(request, pk):
    """Vydání – vědomý krok. Vydanou zprávu už nelze změnit."""
    report = get_object_or_404(Report.objects.for_user(request.user), pk=pk)
    if request.method != "POST":
        return redirect("report_detail", pk=pk)
    try:
        services.release(report, user=request.user)
    except services.ReportError as exc:
        messages.error(request, str(exc))
        return redirect("report_detail", pk=pk)

    record(request, AuditLog.Action.RELEASE, report, subject_code=report.subject.code)
    if not report.pdf:
        messages.warning(request, "Zpráva vydána, ale PDF se nevygenerovalo "
                                  "(chybí WeasyPrint). Použijte náhled v HTML.")
    else:
        messages.success(request, f"Zpráva {report.report_number} vydána.")
    return redirect("report_detail", pk=pk)


@login_required
def report_deliver(request, pk):
    report = get_object_or_404(Report.objects.for_user(request.user), pk=pk)
    if request.method != "POST":
        return redirect("report_detail", pk=pk)
    try:
        delivery = services.deliver(
            report, recipient=request.POST.get("recipient", "").strip(),
            channel=request.POST.get("channel", ReportDelivery.Channel.SECURE_LINK),
            user=request.user, note=request.POST.get("note", ""),
        )
    except services.ReportError as exc:
        messages.error(request, str(exc))
        return redirect("report_detail", pk=pk)

    record(request, AuditLog.Action.EXPORT, report, subject_code=report.subject.code,
           prijemce=delivery.recipient)
    messages.success(request, f"Předání zaznamenáno: {delivery.recipient}.")
    return redirect("report_detail", pk=pk)


@login_required
def report_supersede(request, pk):
    report = get_object_or_404(Report.objects.for_user(request.user), pk=pk)
    if request.method != "POST":
        return redirect("report_detail", pk=pk)
    try:
        new_report = services.supersede(report, user=request.user)
    except services.ReportError as exc:
        messages.error(request, str(exc))
        return redirect("report_detail", pk=pk)

    messages.info(request, f"Vznikla nová verze {new_report.report_number}. "
                           f"Původní zpráva zůstává v dokumentaci příjemce.")
    return redirect("report_detail", pk=new_report.pk)


@login_required
def report_pdf(request, pk):
    report = get_object_or_404(Report.objects.for_user(request.user), pk=pk)
    if not report.pdf:
        raise Http404("Zpráva nemá vygenerované PDF.")
    record(request, AuditLog.Action.EXPORT, report, subject_code=report.subject.code)
    return HttpResponse(report.pdf.read(), content_type="application/pdf",
                        headers={"Content-Disposition":
                                 f'attachment; filename="{report.report_number}.pdf"'})
