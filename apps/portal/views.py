"""
Portál sportovce a zákonného zástupce: vlastní výsledky, zprávy pro
sportovce, dotazníky, souhlasy a sdílení s trenérem, kdo se na data díval.

Sportovec je subjektem údajů – má nárok na všechno o sobě, včetně toho,
kdo si jeho data zobrazil. Laboratoř tu nic nezadává; portál jen čte
a mění souhlasy.
"""

from functools import wraps

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.views import PasswordChangeView
from django.db.models import Count
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone

from apps.analytics import charts, overview, queries
from apps.core.audit import record
from apps.core.models import AuditLog, Role
from apps.measurements import questionnaires
from apps.measurements.models import TestSession
from apps.reports.models import Audience, Report
from apps.subjects import accounts
from apps.subjects.access import subjects_for
from apps.subjects.models import Sharing

from .forms import RegistrationForm


def athlete_required(view):
    """Jen účet sportovce / zástupce (správce se podívat může)."""
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if request.user.role != Role.ATHLETE and not request.user.is_superuser:
            return redirect("dashboard")
        return view(request, *args, **kwargs)
    return wrapper


def _subject(request, pk):
    subject = get_object_or_404(subjects_for(request.user), pk=pk)
    subject.jmeno = subject.display_for(request.user)
    return subject


def _subjects(request):
    rows = list(subjects_for(request.user).filter(is_active=True)
                .annotate(pocet_mereni=Count("sessions", distinct=True)).order_by("code"))
    for s in rows:
        s.jmeno = s.display_for(request.user)
        s.cekajici = s.sharings.filter(status=Sharing.Status.REQUESTED).count()
    return rows


@athlete_required
def home(request):
    rows = _subjects(request)
    if len(rows) == 1:
        return redirect("portal_subject", pk=rows[0].pk)
    return render(request, "portal/home.html", {"subjects": rows})


@athlete_required
def consents_home(request):
    rows = _subjects(request)
    if len(rows) == 1:
        return redirect("portal_consents", pk=rows[0].pk)
    return render(request, "portal/home.html", {"subjects": rows, "souhlasy": True})


@athlete_required
def subject(request, pk):
    from apps.subjects.views import _both_themes

    subject = _subject(request, pk)
    record(request, AuditLog.Action.VIEW, subject, subject_code=subject.code)
    sessions = list(TestSession.objects.filter(subject=subject)
                    .prefetch_related("protocol_runs__protocol")
                    .annotate(hodnot=Count("protocol_runs__trials__measurements"))
                    .order_by("-date"))
    for s in sessions:
        s.protokoly = sorted({run.protocol.name for run in s.protocol_runs.all()})
    trends = [
        _both_themes(lambda theme, s=s: charts.trend_chart(
            s["metric"], s["points"], qualifiers=s["qualifiers"], norm=s["norm"], theme=theme))
        for s in queries.primary_metric_series(subject)
    ]
    reports = (Report.objects.filter(subject=subject, status=Report.Status.RELEASED,
                                     audience=Audience.ATHLETE)
               .select_related("session").order_by("-released_at"))
    today = timezone.localdate()
    return render(request, "portal/subject.html", {
        "subject": subject,
        "tiles": overview.kpi_tiles(subject),
        "trends": trends,
        "sessions": sessions,
        "reports": reports,
        "today_session": TestSession.objects.filter(subject=subject, date=today).first(),
        "pending": subject.sharings.filter(status=Sharing.Status.REQUESTED)
                                   .select_related("coach"),
        "subjects_count": subjects_for(request.user).count(),
    })


def _released_report(subject, report_pk):
    return get_object_or_404(Report, pk=report_pk, subject=subject,
                             status=Report.Status.RELEASED, audience=Audience.ATHLETE)


@athlete_required
def report(request, pk, report_pk):
    from apps.reports.services import render_html

    subject = _subject(request, pk)
    report = _released_report(subject, report_pk)
    record(request, AuditLog.Action.VIEW, report, subject_code=subject.code)
    return HttpResponse(render_html(report))


@athlete_required
def report_pdf(request, pk, report_pk):
    subject = _subject(request, pk)
    report = _released_report(subject, report_pk)
    if not report.pdf:
        raise Http404("Zpráva nemá PDF.")
    record(request, AuditLog.Action.EXPORT, report, subject_code=subject.code)
    return FileResponse(report.pdf.open("rb"), as_attachment=True,
                        filename=f"{report.report_number}.pdf")


@athlete_required
def questionnaire(request, pk):
    """Dotazník (RPE) k dnešnímu měření – stejný formulář jako přes QR."""
    subject = _subject(request, pk)
    session = TestSession.objects.filter(subject=subject, date=timezone.localdate()).first()
    rpe = questionnaires.questionnaire(questionnaires.RPE, subject.organization)
    if session is None or rpe is None:
        messages.info(request, "Dnes nemáte žádné měření, ke kterému by se dotazník vyplňoval.")
        return redirect("portal_subject", pk=pk)
    run = session.protocol_runs.filter(protocol__rpe_after=True).order_by("pk").last()
    return redirect("questionnaire_fill", token=questionnaires.make_token(session, rpe, run))


@athlete_required
def consents(request, pk):
    subject = _subject(request, pk)
    if request.method == "POST":
        _consent_action(request, subject)
        return redirect("portal_consents", pk=pk)
    sharings = list(subject.sharings.select_related("coach").order_by("-created_at"))
    for s in sharings:
        s.trener = accounts.coach_label(s.coach)
    used = {s.coach_id for s in sharings if s.status in (Sharing.Status.ACTIVE,
                                                        Sharing.Status.REQUESTED)}
    available = [c for c in accounts.coaches(subject.organization) if c.pk not in used]
    for c in available:
        c.label = accounts.coach_label(c)
    audit = (AuditLog.objects.filter(subject_code=subject.code)
             .exclude(user=request.user).select_related("user")
             .order_by("-timestamp")[:40])
    return render(request, "portal/consents.html", {
        "subject": subject,
        "consents": subject.consents.order_by("-granted_on"),
        "sharings": sharings,
        "coaches": available,
        "audit": audit,
        "subjects_count": subjects_for(request.user).count(),
    })


def _consent_action(request, subject):
    action = request.POST.get("akce")
    if action == "sdilet":
        coach = accounts.coaches(subject.organization).filter(pk=request.POST.get("trener")).first()
        if coach is None:
            messages.error(request, "Vyberte trenéra ze seznamu.")
            return
        accounts.start_sharing(subject, coach, by=request.user)
        record(request, AuditLog.Action.UPDATE, subject, subject_code=subject.code,
               sdileni="zapnuto", trener=coach.get_username())
        messages.success(request, f"Výsledky sdílíte s trenérem {accounts.coach_label(coach)}. "
                                  "Kdykoli to tady můžete odvolat.")
        return
    sharing = subject.sharings.filter(pk=request.POST.get("sdileni")).select_related("coach").first()
    if sharing is None:
        return
    label = accounts.coach_label(sharing.coach)
    if action == "potvrdit" and sharing.status == Sharing.Status.REQUESTED:
        accounts.confirm_sharing(sharing, by=request.user)
        messages.success(request, f"Sdílení s trenérem {label} je potvrzené.")
    elif action == "odmitnout" and sharing.status == Sharing.Status.REQUESTED:
        accounts.decline_sharing(sharing, by=request.user)
        messages.info(request, f"Žádost trenéra {label} jste odmítli.")
    elif action == "odvolat" and sharing.status == Sharing.Status.ACTIVE:
        accounts.revoke_sharing(sharing, by=request.user)
        messages.info(request, f"Sdílení s trenérem {label} je odvolané – od teď vaše "
                               "výsledky nevidí.")
    else:
        return
    record(request, AuditLog.Action.UPDATE, subject, subject_code=subject.code,
           sdileni=action, trener=sharing.coach.get_username())


class AccountView(PasswordChangeView):
    template_name = "portal/account.html"
    success_url = reverse_lazy("portal_account")
    form_class = PasswordChangeForm

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for field in form.fields.values():
            field.widget.attrs["class"] = "input mt-1"
        return form

    def form_valid(self, form):
        messages.success(self.request, "Heslo je změněné.")
        return super().form_valid(form)


account = athlete_required(AccountView.as_view())


def register(request, token):
    """
    Založení účtu z pozvánky (odkaz nebo QR od laboratoře). Přihlášený
    účet sportovce pozvánku jen přijme – rodič tak přidá druhé dítě.
    """
    invitation = accounts.valid_invitation(token)
    if invitation is None:
        return render(request, "portal/register.html", {"invalid": True}, status=410)

    if request.user.is_authenticated:
        if request.user.role != Role.ATHLETE:
            messages.warning(request, "Pozvánka je pro účet sportovce. Odhlaste se "
                                      "z pracovního účtu a otevřete ji znovu.")
            return redirect("dashboard")
        if request.method == "POST" and request.POST.get("akce") == "prijmout":
            try:
                subject = accounts.accept_invitation(invitation, request.user)
            except accounts.AccountError as exc:
                messages.error(request, str(exc))
                return redirect("portal_home")
            messages.success(request, f"Sportovec {subject.code} je připojený k vašemu účtu.")
            return redirect("portal_subject", pk=subject.pk)
        return render(request, "portal/register.html", {"invitation": invitation,
                                                        "attach": True})

    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            user = accounts.register(invitation, email=form.cleaned_data["email"],
                                     password=form.cleaned_data["password1"])
        except accounts.AccountError as exc:
            form.add_error("email", str(exc))
        else:
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(request, "Účet je založený. Vítejte.")
            return redirect("portal_home")
    return render(request, "portal/register.html", {"invitation": invitation, "form": form})


def portal_home_url(user) -> str:
    """Kam patří účet po přihlášení."""
    return reverse("portal_home") if user.role == Role.ATHLETE else reverse("dashboard")
