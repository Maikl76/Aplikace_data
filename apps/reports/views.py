from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.audit import record
from apps.core.models import AuditLog
from apps.measurements.models import TestSession
from apps.subjects.models import Consent

from . import llm, services
from .models import Audience, Report, ReportDelivery


@login_required
def report_list(request):
    from apps.subjects.search import label

    reports = Report.objects.for_user(request.user).select_related("subject", "session")
    stav = request.GET.get("stav", "")
    if stav in Report.Status.values:
        reports = reports.filter(status=stav)
    reports = label(reports.order_by("-created_at")[:150], request.user)
    return render(request, "reports/report_list.html", {
        "can_manage_ai": can_manage_ai(request.user),
        "reports": reports, "stav": stav, "stavy": [(Report.Status.DRAFT, "Koncepty"), (Report.Status.RELEASED, "Vydané"),
                  (Report.Status.SUPERSEDED, "Nahrazené")]})


@login_required
def report_create(request, session_pk):
    session = get_object_or_404(TestSession.objects.for_user(request.user), pk=session_pk)
    if request.method != "POST":
        return redirect("session_detail", pk=session_pk)
    try:
        report = services.build_draft(session, user=request.user,
                                      audience=request.POST.get("pro"))
    except services.ReportError as exc:
        messages.error(request, str(exc))
        return redirect("session_detail", pk=session_pk)

    record(request, AuditLog.Action.CREATE, report, subject_code=session.subject.code)
    return redirect("report_detail", pk=report.pk)


@login_required
def report_detail(request, pk):
    report = get_object_or_404(Report.objects.for_user(request.user), pk=pk)

    if request.method == "POST" and report.is_editable:
        problems = services.save_edits(report, summary=request.POST.get("summary", ""),
                                       custom_note=request.POST.get("custom_note", ""))
        record(request, AuditLog.Action.UPDATE, report, subject_code=report.subject.code)
        messages.success(request, "Úpravy uloženy.")
        if problems:
            messages.warning(
                request,
                f"V souhrnu jsou čísla, která nejsou ve výsledcích měření: "
                f"{', '.join(problems)}. Pokud jsou správně, můžete je ponechat.")
        return redirect("report_detail", pk=pk)

    from apps.subjects.search import label

    label([report], request.user)
    context = services.report_context(report)
    context.update({
        "audiences": Audience.choices,
        "ratings": Report.Rating.choices,
        "variants": (Report.objects.filter(session=report.session)
                     .exclude(pk=report.pk).exclude(status=Report.Status.SUPERSEDED)
                     .order_by("audience") if report.session else []),
        "can_manage_ai": can_manage_ai(request.user),
        "llm_enabled": llm.is_enabled(),
        "ma_souhlas": Consent.has(report.subject, Consent.Scope.REPORT_HANDOVER),
        "channels": ReportDelivery.Channel.choices,
    })
    return render(request, "reports/report_detail.html", context)


@login_required
def report_suggest(request, pk):
    """Návrh doporučení od modelu – vloží se do komentáře ke kontrole."""
    report = get_object_or_404(Report.objects.for_user(request.user), pk=pk)
    if request.method != "POST":
        return redirect("report_detail", pk=pk)
    try:
        # Tlačítko je ve formuláři s úpravami – neuložený text se neztratí.
        if "summary" in request.POST:
            services.save_edits(report, summary=request.POST["summary"],
                                custom_note=request.POST.get("custom_note", ""))
        draft = services.suggest_recommendations(report)
    except services.ReportError as exc:
        messages.error(request, f"Návrh se nepodařil: {exc}")
        return redirect("report_detail", pk=pk)

    record(request, AuditLog.Action.UPDATE, report, subject_code=report.subject.code,
           navrh_od=draft.model)
    messages.info(request, f"Model {draft.model} navrhl doporučení za {draft.seconds:.0f} s. "
                           f"Projděte je v komentáři, opravte a uložte.")
    if draft.unverified_numbers:
        messages.warning(
            request,
            f"Ověřte čísla, která nejsou ve výsledcích: {', '.join(draft.unverified_numbers)} "
            f"(např. dávkování – model je navrhl sám).")
    return redirect("report_detail", pk=pk)


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


def can_manage_ai(user) -> bool:
    """Pokyny pro model a zkušební sadu spravuje správce."""
    from apps.core.models import Role

    return (user.is_superuser or getattr(user, "role", "") == Role.ADMIN
            or user.has_perm("reports.change_reportstyle"))


@login_required
def report_rate(request, pk):
    """Hodnocení textu od modelu a označení vzoru / zkušební sady."""
    report = get_object_or_404(Report.objects.for_user(request.user), pk=pk)
    if request.method != "POST":
        return redirect("report_detail", pk=pk)
    try:
        if "hodnoceni" in request.POST:
            services.rate(report, rating=request.POST.get("hodnoceni", ""),
                          note=request.POST.get("poznamka", ""))
            messages.success(request, "Díky – hodnocení pomůže ladit pokyny pro model.")
        if "vzor" in request.POST or "sada" in request.POST:
            if not can_manage_ai(request.user):
                raise services.ReportError("Vzory a zkušební sadu spravuje správce.")
            services.set_flags(
                report,
                example=(request.POST["vzor"] == "1") if "vzor" in request.POST else None,
                test_set=(request.POST["sada"] == "1") if "sada" in request.POST else None)
            messages.success(request, "Uloženo.")
    except services.ReportError as exc:
        messages.error(request, str(exc))
    record(request, AuditLog.Action.UPDATE, report, subject_code=report.subject.code)
    return redirect("report_detail", pk=pk)


@login_required
def ai_settings(request):
    """Nastavení AI zpráv: pokyny pro varianty, kvalita, zkušební sada."""
    from django.conf import settings

    from . import prompts
    from .models import ModelTrial, ReportStyle

    if not can_manage_ai(request.user):
        messages.error(request, "Nastavení AI zpráv je pro správce.")
        return redirect("report_list")
    organization = request.user.organization or getattr(
        Report.objects.for_user(request.user).first(), "organization", None)
    tab = request.GET.get("tab", "pokyny")

    if request.method == "POST" and request.POST.get("akce") == "pokyny":
        audience = request.POST.get("audience")
        if audience in Audience.values and organization is not None:
            text = request.POST.get("instructions", "").replace("\r\n", "\n").strip()
            if request.POST.get("vychozi") or not text:
                ReportStyle.objects.filter(organization=organization, audience=audience).delete()
                messages.info(request, "Pokyny vráceny na výchozí.")
            else:
                ReportStyle.objects.update_or_create(
                    organization=organization, audience=audience,
                    defaults={"instructions": text, "updated_by": request.user})
                messages.success(request, f"Pokyny pro variantu „{Audience(audience).label}“ "
                                          f"uloženy. Platí pro další zprávy.")
        return redirect(f"{request.path}?tab=pokyny#{audience}")

    styles = []
    custom = {s.audience: s for s in ReportStyle.objects.filter(organization=organization)}
    for value, label in Audience.choices:
        styles.append({"value": value, "label": label,
                       "text": prompts.style_for(organization, value),
                       "custom": custom.get(value),
                       "default": prompts.DEFAULT_STYLES[value]})

    from apps.subjects.search import label as name_label

    test_set = list(Report.objects.for_user(request.user).filter(in_test_set=True)
                    .select_related("subject", "session").order_by("-released_at")[:30])
    name_label(test_set, request.user)
    trials = {}
    for t in ModelTrial.objects.filter(report__in=test_set).order_by("-created_at"):
        trials.setdefault(t.report_id, []).append(t)
    for r in test_set:
        r.trials = trials.get(r.pk, [])[:4]

    models_available = []
    if llm.is_enabled():
        try:
            models_available = llm.list_models(timeout=3)
        except llm.LLMError:
            pass
    return render(request, "reports/ai_settings.html", {
        "tab": tab, "styles": styles,
        "tabs": [("pokyny", "Pokyny pro model"), ("kvalita", "Kvalita textů"),
                 ("sada", "Zkušební sada")],
        "ratings_short": [("dobry", "Dobrý"), ("pouzitelny", "Použitelný"),
                          ("prepsano", "Nepoužitelný")], "fixed_rules": prompts.FIXED_RULES,
        "stats": services.quality_stats(organization), "test_set": test_set,
        "examples": (Report.objects.for_user(request.user).filter(is_example=True)
                     .select_related("subject").order_by("-released_at")[:30]),
        "llm_enabled": llm.is_enabled(), "current_model": settings.LLM_MODEL,
        "models_available": models_available,
    })


@login_required
def ai_try(request, pk):
    """Zkušební text pro jednu zprávu ze zkušební sady (HTMX – vrátí řádek)."""
    report = get_object_or_404(Report.objects.for_user(request.user), pk=pk)
    if request.method != "POST" or not can_manage_ai(request.user):
        return redirect("report_detail", pk=pk)
    if not llm.is_enabled():
        messages.error(request, "Jazykový model není zapnutý (LLM_ENABLED).")
        return redirect("/zpravy/ai/?tab=sada")
    trial = services.try_model(report, model=request.POST.get("model", "").strip(),
                               user=request.user)
    if request.headers.get("HX-Request"):
        return render(request, "reports/_trial.html", {"t": trial})
    return redirect("/zpravy/ai/?tab=sada")
