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
    from .ai_models import is_offered

    model = request.POST.get("model", "").strip()
    try:
        report = services.build_draft(session, user=request.user,
                                      audience=request.POST.get("pro"),
                                      model=model if model and is_offered(model) else None)
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

    from . import ai_models

    if services.clear_stalled(report):
        messages.warning(request, "Psaní souhrnu modelem se nedokončilo – souhrn zůstal, "
                                  "jak byl. Můžete ho nechat napsat znovu.")
    label([report], request.user)
    context = services.report_context(report)
    context.update({
        "audiences": Audience.choices,
        "model_choices": ai_models.choices() if llm.is_enabled() else [],
        "writing_label": ai_models.label_for(report.writing_model),
        "history": report.model_trials.order_by("-created_at")[:6],
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
    tab = request.GET.get("tab", "modely")

    if request.method == "POST" and request.POST.get("akce", "").startswith("model"):
        _models_post(request)
        return redirect(f"{request.path}?tab=modely")

    if request.method == "POST" and request.POST.get("akce") == "pokyny":
        audience = request.POST.get("audience")
        kind = request.POST.get("kind") or ReportStyle.Kind.SUMMARY
        if (audience in Audience.values and kind in ReportStyle.Kind.values
                and organization is not None):
            text = request.POST.get("instructions", "").replace("\r\n", "\n").strip()
            what = ("Pokyny pro návrh doporučení" if kind == ReportStyle.Kind.RECOMMENDATION
                    else "Pokyny pro souhrn")
            if request.POST.get("vychozi") or not text:
                ReportStyle.objects.filter(organization=organization, audience=audience,
                                           kind=kind).delete()
                messages.info(request, f"{what} vráceny na výchozí.")
            else:
                ReportStyle.objects.update_or_create(
                    organization=organization, audience=audience, kind=kind,
                    defaults={"instructions": text, "updated_by": request.user})
                messages.success(request, f"{what} – varianta „{Audience(audience).label}“ "
                                          f"uloženy. Platí pro další zprávy.")
        return redirect(f"{request.path}?tab=pokyny#{audience}-{kind}")

    styles = []
    custom = {(s.audience, s.kind): s
              for s in ReportStyle.objects.filter(organization=organization)}
    for value, label in Audience.choices:
        styles.append({"value": value, "label": label, "parts": [
            {"kind": kind, "label": kind_label,
             "text": prompts.style_for(organization, value, kind),
             "custom": custom.get((value, kind))}
            for kind, kind_label in ReportStyle.Kind.choices]})

    from apps.subjects.search import label as name_label

    test_set = list(Report.objects.for_user(request.user).filter(in_test_set=True)
                    .select_related("subject", "session").order_by("-released_at")[:30])
    name_label(test_set, request.user)
    trials = {}
    for t in ModelTrial.objects.filter(report__in=test_set).order_by("-created_at"):
        trials.setdefault(t.report_id, []).append(t)
    for r in test_set:
        r.trials = trials.get(r.pk, [])[:4]

    from . import ai_models
    from .models import AiModel

    models_available, server_error = [], ""
    if llm.is_enabled():
        try:
            models_available = llm.list_models(timeout=3)
        except llm.LLMError as exc:
            server_error = str(exc)
    saved = {m.name: m for m in AiModel.objects.all()}
    default = ai_models.default_model()
    model_rows = []
    for name in dict.fromkeys([default, *saved, *models_available]):
        row = saved.get(name) or AiModel(name=name, timeout=settings.LLM_TIMEOUT)
        model_rows.append({"m": row, "saved": name in saved, "default": name == default,
                           "on_server": name in models_available})
    return render(request, "reports/ai_settings.html", {
        "tab": tab, "styles": styles,
        "tabs": [("modely", "Modely"), ("pokyny", "Pokyny pro model"),
                 ("kvalita", "Kvalita textů"), ("sada", "Zkušební sada")],
        "model_rows": model_rows, "server_error": server_error,
        "model_choices": ai_models.choices(),
        "ratings_short": [("dobry", "Dobrý"), ("pouzitelny", "Použitelný"),
                          ("prepsano", "Nepoužitelný")], "fixed_rules": prompts.FIXED_RULES,
        "recommendation_rules": prompts.RECOMMENDATION_RULES,
        "stats": services.quality_stats(organization), "test_set": test_set,
        "examples": (Report.objects.for_user(request.user).filter(is_example=True)
                     .select_related("subject").order_by("-released_at")[:30]),
        "llm_enabled": llm.is_enabled(), "current_model": ai_models.default_model(),
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


@login_required
def report_writing(request, pk):
    """Stav psaní na pozadí (HTMX dotaz každých pár sekund)."""
    report = get_object_or_404(Report.objects.for_user(request.user), pk=pk)
    if not report.is_writing:
        response = HttpResponse("")
        response["HX-Refresh"] = "true"
        return response
    from django.utils import timezone

    seconds = int((timezone.now() - report.writing_started_at).total_seconds())
    return HttpResponse(f"{seconds // 60} min {seconds % 60:02d} s")


@login_required
def report_rewrite(request, pk):
    """Napsat souhrn znovu (jiným) modelem – dosavadní text zůstane v historii zprávy."""
    from .ai_models import is_offered, label_for

    report = get_object_or_404(Report.objects.for_user(request.user), pk=pk)
    if request.method != "POST":
        return redirect("report_detail", pk=pk)
    model = request.POST.get("model", "").strip()
    try:
        if "summary" in request.POST and report.is_editable and not report.is_writing:
            services.save_edits(report, summary=request.POST["summary"],
                                custom_note=request.POST.get("custom_note", ""))
        services.rewrite_summary(report, model=model if model and is_offered(model) else None)
    except services.ReportError as exc:
        messages.error(request, str(exc))
        return redirect("report_detail", pk=pk)
    record(request, AuditLog.Action.UPDATE, report, subject_code=report.subject.code,
           prepsat_modelem=report.writing_model)
    report.refresh_from_db()
    if report.is_writing:
        messages.info(request, f"Model {label_for(report.writing_model)} píše nový souhrn. "
                               f"Dosavadní text zůstane v historii zprávy.")
    elif "nepovedlo" in report.generation_note:
        messages.warning(request, report.generation_note)
    else:
        messages.success(request, "Souhrn napsán znovu. Předchozí text je v historii zprávy.")
    return redirect("report_detail", pk=pk)


def _models_post(request):
    """Modely v AI zprávách: uložit čekání a název, nastavit výchozí, přidat, odebrat."""
    from .models import AiModel

    action = request.POST.get("akce")
    name = request.POST.get("name", "").strip().removeprefix("LLM_MODEL=").strip()
    if not name or len(name) > 120:
        messages.error(request, "Zadejte název modelu, jak ho uvádí LM Studio / Ollama.")
        return
    if action == "model_smazat":
        AiModel.objects.filter(name=name).delete()
        messages.info(request, f"Model {name} už se nenabízí.")
        return
    try:
        timeout = max(30, min(3600, int(request.POST.get("timeout") or 300)))
    except ValueError:
        timeout = 300
    row, _ = AiModel.objects.get_or_create(name=name, defaults={"timeout": timeout})
    if action in ("model_ulozit", "model_pridat"):
        row.label = request.POST.get("label", row.label).strip()[:80]
        row.timeout = timeout
        row.is_active = bool(request.POST.get("is_active", "on" if action == "model_pridat" else ""))
    if action == "model_vychozi":
        AiModel.objects.exclude(pk=row.pk).update(is_default=False)
        row.is_default = True
        row.is_active = True
        messages.success(request, f"Nové zprávy bude psát {row.display}.")
    else:
        messages.success(request, f"Model {row.display} uložen.")
    row.save()
