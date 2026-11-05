from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from apps.measurements.models import Measurement, TestSession
from apps.reports.models import Report
from apps.subjects.models import Subject


@login_required
def dashboard(request):
    """Přehled laboratoře: co je nového a co čeká na mě."""
    from datetime import timedelta

    from django.shortcuts import redirect

    from apps.core.models import Role

    if not request.user.is_superuser:
        if request.user.role == Role.ATHLETE:
            return redirect("portal_home")
        if request.user.role == Role.COACH:
            return redirect("coach_home")

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

    objednavky = []
    if request.user.sees_identity:
        from apps.booking.models import BookingRequest

        objednavky = list(BookingRequest.objects.for_user(request.user)
                          .filter(status=BookingRequest.Status.NEW)
                          .select_related("slot").order_by("slot__start")[:5])

    context = {
        "objednavky": objednavky,
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


@login_required
def about(request):
    """O aplikaci: co umí, role a návody k ovládání."""
    from django.conf import settings

    from apps.core.models import Role
    from apps.reports import llm

    return render(request, "core/about.html", {
        "roles": Role,
        "llm_enabled": llm.is_enabled(),
        "llm_model": getattr(settings, "LLM_MODEL", ""),
    })


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


# --- kolegové --------------------------------------------------------------------

def _is_admin(user) -> bool:
    from apps.core.models import Role

    return user.is_superuser or user.role == Role.ADMIN


@login_required
def colleagues(request):
    """
    Účty kolegů: správce založí účet s rolí a dostane jednorázový odkaz,
    kterým si kolega nastaví heslo. Stejný odkaz slouží jako „zapomenuté
    heslo“; vypnutý účet se nepřihlásí, data zůstanou.
    """
    from django.contrib import messages
    from django.shortcuts import get_object_or_404, redirect

    from apps.core import colleagues as service
    from apps.core.audit import record
    from apps.core.forms import ColleagueForm
    from apps.core.models import AuditLog, User, default_organization
    from apps.core.roles import COLLEAGUE_ROLES

    if not _is_admin(request.user):
        return render(request, "core/odepreno.html", {"duvod": "Účty kolegů spravuje správce."},
                      status=403)
    org = request.user.organization or default_organization()
    people = User.objects.filter(organization=org, role__in=COLLEAGUE_ROLES)
    form = ColleagueForm(request.POST if request.POST.get("akce") == "novy" else None)
    if request.method == "POST":
        action = request.POST.get("akce")
        if action == "novy":
            if form.is_valid():
                try:
                    new = service.create_colleague(org, **form.cleaned_data)
                except service.ColleagueError as exc:
                    form.add_error(None, str(exc))
                else:
                    record(request, AuditLog.Action.CREATE, new, kolega=new.get_username(),
                           role=new.role)
                    request.session["odkaz_pro"] = new.pk
                    messages.success(request, f"Účet {new.get_username()} je založený. Předejte "
                                              "kolegovi odkaz níže.")
                    return redirect("colleagues")
        else:
            target = get_object_or_404(people, pk=request.POST.get("ucet"))
            if target.pk == request.user.pk:
                messages.error(request, "Vlastní účet si nevypnete ani neresetujete tady.")
            elif action == "odkaz":
                request.session["odkaz_pro"] = target.pk
                record(request, AuditLog.Action.UPDATE, target, kolega=target.get_username(),
                       akce="odkaz na heslo")
            elif action in ("vypnout", "zapnout"):
                target.is_active = action == "zapnout"
                target.save(update_fields=["is_active"])
                record(request, AuditLog.Action.UPDATE, target, kolega=target.get_username(),
                       akce=action)
                messages.info(request, f"Účet {target.get_username()} je "
                                       f"{'zapnutý' if target.is_active else 'vypnutý'}.")
            else:
                messages.error(request, "Neznámá akce.")
            return redirect("colleagues")
    link = link_for = None
    if pk := request.session.pop("odkaz_pro", None):
        link_for = people.filter(pk=pk, is_active=True).first()
        if link_for is not None:
            link = request.build_absolute_uri(
                reverse("password_setup", args=[service.password_link_token(link_for)]))
    return render(request, "core/colleagues.html", {
        "people": people.order_by("-is_active", "last_name", "first_name", "username"),
        "form": form, "link": link, "link_for": link_for, "link_days": service.LINK_DAYS,
    })


def password_setup(request, token):
    """Nastavení hesla z jednorázového odkazu od správce (účty kolegů)."""
    from django.contrib import messages
    from django.contrib.auth import login, logout
    from django.shortcuts import redirect

    from apps.core import colleagues as service
    from apps.core.audit import record
    from apps.core.forms import PasswordSetForm
    from apps.core.models import AuditLog

    account = service.user_from_password_link(token)
    if account is None:
        return render(request, "registration/nastavit_heslo.html", {"invalid": True}, status=410)
    if request.user.is_authenticated and request.user.pk != account.pk:
        logout(request)
    form = PasswordSetForm(account, request.POST or None)
    if request.method == "POST" and form.is_valid():
        service.set_password(account, form.cleaned_data["password1"])
        login(request, account, backend="django.contrib.auth.backends.ModelBackend")
        record(request, AuditLog.Action.UPDATE, account, kolega=account.get_username(),
               akce="heslo nastaveno odkazem")
        messages.success(request, "Heslo je nastavené. Vítejte.")
        return redirect("dashboard")
    return render(request, "registration/nastavit_heslo.html", {"form": form, "account": account})
