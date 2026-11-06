from datetime import date

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.analytics import charts, compare, overview, queries
from apps.core.audit import record
from apps.core.models import AuditLog
from apps.external.models import ExternalExam
from apps.genetics import services as genetics
from apps.measurements.models import TestSession

from . import accounts, goals, retest, search
from .models import AccountInvitation, Goal, Sport, Subject, Team


@login_required
def subject_list(request):
    """Seznam sportovců. Filtry přes HTMX – vrací se jen výsek tabulky."""
    qs = Subject.objects.for_user(request.user).select_related("sport", "team")
    inactive = qs.filter(is_active=False).count()
    show_inactive = bool(request.GET.get("neaktivni"))
    if not show_inactive:
        qs = qs.filter(is_active=True)
    if sport := request.GET.get("sport"):
        qs = qs.filter(sport_id=sport)
    q = request.GET.get("q", "").strip()
    subjects = (search.search(request.user, q, limit=None, base=qs) if q
                else search.annotate(qs.order_by("code"), request.user, limit=300))
    plans = {p.subject.pk: p for p in retest.plans_for(subjects)}
    for s in subjects:
        s.plan = plans.get(s.pk)
    due_count = sum(1 for p in plans.values() if p.is_due)
    show_due = bool(request.GET.get("na_rade"))
    if show_due:
        subjects = sorted((s for s in subjects if s.plan and s.plan.is_due),
                          key=lambda s: s.plan.due)

    context = {"subjects": subjects, "q": q,
               "sports": Sport.objects.for_user(request.user).order_by("name"),
               "sport_id": sport, "inactive": inactive, "show_inactive": show_inactive,
               "show_due": show_due, "due_count": due_count}
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


_both_themes = charts.both_themes


@login_required
def subject_detail(request, pk):
    """Karta sportovce – srdce aplikace: hlavní čísla, trendy, historie, zprávy."""
    subject = get_object_or_404(Subject.objects.for_user(request.user)
                                .select_related("sport", "team"), pk=pk)
    record(request, AuditLog.Action.VIEW, subject, subject_code=subject.code)

    sessions = list(
        TestSession.objects.filter(subject=subject)
        .prefetch_related("protocol_runs__protocol", "reports")
        .annotate(hodnot=Count("protocol_runs__trials__measurements"))
        .order_by("-date")
    )
    for session in sessions:
        session.protokoly = sorted({run.protocol.name for run in session.protocol_runs.all()})
    # „Poslední měření“ = poslední den, kdy se něco naměřilo; den jen
    # naplánovaný podle baterie (zatím prázdný) se nepočítá.
    measured = [s for s in sessions if s.hodnot]

    goal_progress = goals.goals_for(subject)
    goals_by_metric = goals.by_metric(goal_progress)
    trends = overview.trend_specs(subject, goals=goals_by_metric)
    posledni, asymetrie = queries.latest_asymmetries(subject)

    from apps.core.steps import next_step

    from .steps import subject_steps

    accounts_info = accounts.accounts_of(subject) if _may_edit(request.user) else None
    sharings_list = [_with_coach_label(sh) for sh in subject.sharings.select_related("coach")]
    exams = list(subject.external_exams.order_by("-date", "-pk"))
    plan = retest.plan_for(subject)
    steps = subject_steps(subject, sessions=sessions, accounts=accounts_info,
                          sharings=sharings_list, may_edit=_may_edit(request.user), exams=exams,
                          plan=plan, goals=goal_progress)

    return render(request, "subjects/subject_detail.html", {
        "steps": steps, "next_step": next_step(steps),
        "subject": subject,
        "display_name": subject.display_for(request.user),
        "sessions": sessions,
        "last_session": measured[0] if measured else None,
        "tiles": overview.kpi_tiles(subject, goals=goals_by_metric),
        "goals": goal_progress,
        "goal_metrics": goals.metric_choices(subject) if _may_edit(request.user) else [],
        "external_exams": exams, "may_edit": _may_edit(request.user),
        "plan": plan, "reminders": list(subject.retest_reminders.all()[:3]),
        "email_enabled": bool(settings.EMAIL_HOST),
        # Stejná logika jako v pravidlech: karta nesmí tvrdit něco jiného než zpráva.
        "restriction": ExternalExam.active_restriction_for(subject),
        "accounts": accounts_info,
        "sharings": sharings_list,
        "coaches": [_with_coach_label(c) for c in accounts.coaches(subject.organization)],
        "reports": subject.reports.order_by("-created_at")[:10],
        # souhrn za období: výchozí od začátku sezóny (nebo rok zpět) do dneška
        "period_from": (min(compare.season_start(timezone.localdate(), subject.sport),
                            compare.months_before(timezone.localdate()))
                        if measured else timezone.localdate()),
        "period_to": timezone.localdate(),
        "genetika": genetics.summary_for(subject, request.user),
        "trends": trends,
        "asymetrie_chart": (_both_themes(lambda theme: charts.asymmetry_chart(asymetrie, theme=theme))
                            if asymetrie else None),
        "asymetrie_rows": asymetrie,
        "asymetrie_session": posledni,
        "ma_strany": queries.has_side_data(subject),
    })


def _cards(request, subjects):
    """Kartičky s QR kódem: naskenováním se otevře dnešní testování sportovce."""
    from apps.measurements import questionnaires

    subjects = search.label(subjects, request.user, subject=lambda s: s)
    for s in subjects:
        s.qr = questionnaires.qr_svg(
            request.build_absolute_uri(reverse("subject_today", args=[s.pk])))
    return render(request, "subjects/qr_cards.html", {
        "subjects": subjects, "reachable": questionnaires.reachable_from_phone(request)})


@login_required
def subject_qr(request, pk):
    subject = get_object_or_404(Subject.objects.for_user(request.user), pk=pk)
    return _cards(request, [subject])


@login_required
def team_qr(request):
    from apps.catalog.models import TestBattery

    battery = get_object_or_404(TestBattery.objects.filter(
        sport__in=Sport.objects.for_user(request.user)), pk=request.GET.get("baterie"))
    subjects = Subject.objects.for_user(request.user).filter(sport=battery.sport, is_active=True)
    if battery.category:
        subjects = subjects.filter(category__iexact=battery.category)
    return _cards(request, list(subjects.order_by("code")))


@login_required
def subject_today(request, pk):
    """
    Cíl QR kódu z kartičky: dnešní testovací den sportovce. Když ještě
    neexistuje, nabídne ho založit podle baterie jeho sportu.
    """
    from django.utils import timezone

    from apps.measurements import planning

    subject = get_object_or_404(Subject.objects.for_user(request.user), pk=pk)
    today = timezone.localdate()
    session = TestSession.objects.filter(subject=subject, date=today).first()
    if session:
        return redirect("session_detail", pk=session.pk)
    if request.method == "POST":
        session = TestSession.objects.create(organization=subject.organization,
                                             subject=subject, date=today,
                                             operator=request.user)
        planning.ensure_runs(session, planning.battery_protocols(subject))
        return redirect("session_detail", pk=session.pk)
    search.label([subject], request.user, subject=lambda s: s)
    return render(request, "subjects/today_confirm.html", {
        "subject": subject, "today": today, "protocols": planning.battery_protocols(subject)})


# --- ruční založení a úprava -------------------------------------------------------

def _may_edit(user) -> bool:
    return user.is_superuser or user.sees_identity


def _form_page(request, form, subject=None, duplicates=None):
    from django.conf import settings

    from .services import has_data

    categories = sorted(set(Subject.objects.for_user(request.user).exclude(category="")
                            .values_list("category", flat=True)))
    return render(request, "subjects/subject_form.html", {
        "form": form, "subject": subject, "duplicates": duplicates or {},
        "categories": categories, "has_key": bool(settings.IDENTITY_ENCRYPTION_KEY),
        "display_name": subject.display_for(request.user) if subject else "",
        "may_manage": _may_manage(request.user),
        "has_data": has_data(subject) if subject else False,
        "dokumenty": subject.consents.exclude(document="") if subject else [],
    })


@login_required
def consent_document(request, pk):
    """
    Podepsaný souhlas. Soubor nese jméno a podpis, takže ho aplikace nedává
    jako obyčejnou adresu /media/…, ale jen tomu, kdo smí vidět jméno,
    a se záznamem v auditu – stejně jako PDF zprávy.
    """
    from pathlib import Path

    from django.http import FileResponse, Http404

    from .models import Consent

    consent = get_object_or_404(
        Consent.objects.filter(subject__in=Subject.objects.for_user(request.user))
        .select_related("subject"), pk=pk)
    if not (request.user.sees_identity or request.user.is_superuser):
        return render(request, "core/odepreno.html", {
            "duvod": "Podepsaný souhlas smí otevřít jen správce nebo laborant."}, status=403)
    if not consent.document:
        raise Http404("Souhlas nemá přiložený dokument.")
    try:
        handle = consent.document.open("rb")
    except FileNotFoundError as exc:
        raise Http404("Soubor dokumentu na disku chybí.") from exc
    record(request, AuditLog.Action.EXPORT, consent, subject_code=consent.subject.code,
           rozsah=consent.scope)
    return FileResponse(handle, filename=Path(consent.document.name).name)


def _check(request, form, organization, subject=None):
    """Formulář je v pořádku a duplicity jsou buď žádné, nebo potvrzené."""
    from . import services

    if not form.is_valid():
        return None
    data = form.cleaned_data
    exact, same_name = services.find_duplicates(
        organization, data["first_name"], data["last_name"], data["birth_date"],
        exclude=subject)
    search.label(exact + same_name, request.user, subject=lambda s: s)
    if exact and not data.get("confirm_duplicate"):
        return {"exact": exact, "same_name": same_name}
    return {"same_name": same_name} if same_name else {}


def _same_name_note(request, duplicates):
    from django.contrib import messages

    if others := duplicates.get("same_name"):
        messages.warning(request, "Pozor, stejné jméno (s jiným datem narození) má i "
                         + ", ".join(f"{s.jmeno} {s.code}" for s in others)
                         + ". Při importu je rozliší datum narození nebo ID z přístroje.")


@login_required
def subject_new(request):
    from django.conf import settings
    from django.contrib import messages

    from apps.booking import services as booking

    from . import services
    from .forms import SubjectForm

    if not _may_edit(request.user):
        messages.error(request, "Sportovce zakládá laborant nebo správce.")
        return redirect("subject_list")
    organization = request.user.organization or booking.organization()
    if organization is None:
        messages.error(request, "Účet nemá přiřazené pracoviště – v administraci "
                                "u uživatele vyberte organizaci.")
        return redirect("subject_list")
    sports = Sport.objects.for_user(request.user).order_by("name")
    teams = Team.objects.filter(organization=organization).select_related("sport").order_by("name")
    form = SubjectForm(request.POST or None, sports=sports, teams=teams)
    if request.method == "POST":
        if not settings.IDENTITY_ENCRYPTION_KEY:
            messages.error(request, "Chybí šifrovací klíč – jméno nejde uložit. Spusťte "
                                    "aplikaci přes spustit.bat, klíč se doplní sám.")
            return _form_page(request, form)
        duplicates = _check(request, form, organization)
        if duplicates is not None and "exact" not in duplicates:
            subject = services.create_subject(organization, form.cleaned_data)
            record(request, AuditLog.Action.CREATE, subject, subject_code=subject.code)
            messages.success(request, f"Sportovec založen pod kódem {subject.code}.")
            _same_name_note(request, duplicates)
            return redirect("subject_detail", pk=subject.pk)
        return _form_page(request, form, duplicates=duplicates)
    if sport := request.GET.get("sport"):
        form.initial["sport"] = sport
    return _form_page(request, form)


@login_required
def subject_edit(request, pk):
    from django.conf import settings
    from django.contrib import messages

    from . import services
    from .forms import SubjectForm

    subject = get_object_or_404(Subject.objects.for_user(request.user), pk=pk)
    if not _may_edit(request.user):
        messages.error(request, "Údaje sportovce upravuje laborant nebo správce.")
        return redirect("subject_detail", pk=pk)
    if not settings.IDENTITY_ENCRYPTION_KEY:
        messages.error(request, "Chybí šifrovací klíč – jméno nejde přečíst ani uložit.")
        return redirect("subject_detail", pk=pk)
    sports = Sport.objects.for_user(request.user).order_by("name")
    teams = (Team.objects.filter(organization=subject.organization).select_related("sport")
             .order_by("name"))
    if request.method == "POST":
        form = SubjectForm(request.POST, sports=sports, teams=teams)
        duplicates = _check(request, form, subject.organization, subject)
        if duplicates is not None and "exact" not in duplicates:
            services.update_subject(subject, form.cleaned_data)
            record(request, AuditLog.Action.UPDATE, subject, subject_code=subject.code)
            messages.success(request, "Údaje uloženy.")
            _same_name_note(request, duplicates)
            return redirect("subject_detail", pk=subject.pk)
        return _form_page(request, form, subject, duplicates)
    record(request, AuditLog.Action.VIEW, subject, subject_code=subject.code, identita=True)
    form = SubjectForm(initial=services.initial(subject), sports=sports, teams=teams)
    return _form_page(request, form, subject)


def _may_manage(user) -> bool:
    """Smazat a anonymizovat sportovce smí jen správce."""
    from apps.core.models import Role

    return user.is_superuser or getattr(user, "role", "") == Role.ADMIN


@login_required
def subject_action(request, pk):
    """Deaktivace, smazání a anonymizace (výmaz osobních údajů) sportovce."""
    from django.contrib import messages

    from . import services

    subject = get_object_or_404(Subject.objects.for_user(request.user), pk=pk)
    if request.method != "POST":
        return redirect("subject_edit", pk=pk)
    action = request.POST.get("akce", "")
    if action in ("deaktivovat", "aktivovat"):
        if not _may_edit(request.user):
            messages.error(request, "Sportovce deaktivuje laborant nebo správce.")
            return redirect("subject_detail", pk=pk)
        services.set_active(subject, action == "aktivovat")
        record(request, AuditLog.Action.UPDATE, subject, subject_code=subject.code,
               akce=action)
        messages.success(request, f"Sportovec {subject.code} "
                                  + ("je znovu aktivní." if action == "aktivovat" else
                                     "je deaktivovaný – nenabízí se ve výběrech, data zůstala."))
        return redirect("subject_detail", pk=pk)

    if action not in ("smazat", "anonymizovat"):
        return redirect("subject_edit", pk=pk)
    if not _may_manage(request.user):
        messages.error(request, "Smazat nebo anonymizovat sportovce smí jen správce.")
        return redirect("subject_edit", pk=pk)
    if request.POST.get("potvrzeni", "").strip().upper() != subject.code.upper():
        messages.error(request, f"Pro potvrzení opište kód sportovce ({subject.code}).")
        return redirect(reverse("subject_edit", args=[pk]) + "#dalsi-akce")
    code = subject.code
    try:
        if action == "smazat":
            record(request, AuditLog.Action.DELETE, subject, subject_code=code)
            services.delete_subject(subject)
            messages.success(request, f"Sportovec {code} smazán.")
            return redirect("subject_list")
        done = services.anonymize(subject)
    except services.SubjectError as exc:
        messages.error(request, str(exc))
        return redirect("subject_edit", pk=pk)
    record(request, AuditLog.Action.DELETE, subject, subject_code=code, anonymizace=done)
    messages.success(request, f"Osobní údaje sportovce {code} vymazány"
                              + (f" ({', '.join(done)})" if done else "")
                              + ". Měření a zprávy zůstaly pod kódem.")
    return redirect("subject_detail", pk=pk)


def _with_coach_label(obj):
    user = obj.coach if hasattr(obj, "coach") else obj
    obj.trener = accounts.coach_label(user)
    return obj


@login_required
def subject_invite(request, pk):
    """Pozvánka k účtu sportovce nebo zákonného zástupce – odkaz a QR k předání."""
    subject = get_object_or_404(Subject.objects.for_user(request.user), pk=pk)
    if request.method != "POST" or not _may_edit(request.user):
        return redirect("subject_detail", pk=pk)
    kind = request.POST.get("druh")
    if kind not in AccountInvitation.Kind.values:
        return redirect("subject_detail", pk=pk)
    invitation = accounts.create_invitation(subject, kind, user=request.user)
    record(request, AuditLog.Action.CREATE, invitation, subject_code=subject.code, druh=kind)
    return redirect("subject_invitation", pk=pk, inv_pk=invitation.pk)


@login_required
def subject_retest(request, pk):
    """Plán opakování u sportovce: podle baterie, vlastní interval, konkrétní termín; připomínka hned."""
    from django.contrib import messages

    subject = get_object_or_404(Subject.objects.for_user(request.user), pk=pk)
    back = reverse("subject_detail", args=[pk]) + "#plan"
    if request.method != "POST" or not _may_edit(request.user):
        return redirect(back)
    if request.POST.get("akce") == "pripomenout":
        plan = retest.plan_for(subject)
        if plan.due is None:
            messages.error(request, "Bez termínu dalšího měření není co připomínat – nastavte "
                                    "interval u baterie sportu, nebo plán u sportovce.")
            return redirect(back)
        link = retest.booking_link(request.build_absolute_uri("/"))
        sent = retest.remind(plan, user=request.user, booking_url=link, manual=True)
        if sent is not None:
            record(request, AuditLog.Action.UPDATE, subject, subject_code=subject.code,
                   akce="pripominka_mereni")
            messages.success(request, f"Připomínka dalšího měření odešla ({sent.recipients} "
                                      f"{'adresa' if sent.recipients == 1 else 'adresy'}).")
        elif not settings.EMAIL_HOST:
            messages.error(request, "Poštovní server není nastavený (EMAIL_HOST v .env) – "
                                    "připomínku předejte sami.")
        else:
            messages.error(request, "Sportovec nemá uložený e‑mail ani zástupce s účtem; "
                                    "doplňte kontakt v Upravit údaje.")
        return redirect(back)
    mode = request.POST.get("rezim", "baterie")
    try:
        if mode == "vlastni":
            weeks = int(request.POST.get("tydny", "").strip() or 0)
            if not 1 <= weeks <= 104:
                raise ValueError
            subject.retest_weeks, subject.next_test_date = weeks, None
        elif mode == "datum":
            subject.next_test_date = date.fromisoformat(request.POST.get("datum", "").strip())
        else:
            subject.retest_weeks, subject.next_test_date = None, None
    except ValueError:
        messages.error(request, "Interval zadejte v týdnech (1 až 104), termín jako datum.")
        return redirect(back)
    subject.save(update_fields=["retest_weeks", "next_test_date", "updated_at"])
    record(request, AuditLog.Action.UPDATE, subject, subject_code=subject.code, plan=mode)
    messages.success(request, "Plán opakování je uložený. " + retest.plan_for(subject).text())
    return redirect(back)


@login_required
def subject_goal(request, pk):
    """Nový cíl klíčového ukazatele: cílová hodnota, dokdy, poznámka."""
    from django.contrib import messages

    subject = get_object_or_404(Subject.objects.for_user(request.user), pk=pk)
    back = reverse("subject_detail", args=[pk]) + "#cile"
    if request.method != "POST" or not _may_edit(request.user):
        return redirect(back)
    choices = {m.pk: m for m in goals.metric_choices(subject)}
    try:
        metric = choices[int(request.POST.get("metrika", ""))]
        target = float(request.POST.get("cil", "").strip().replace(",", ".").replace(" ", ""))
        raw = request.POST.get("do", "").strip()
        due = date.fromisoformat(raw) if raw else None
    except (KeyError, ValueError):
        messages.error(request, "Vyberte klíčový ukazatel a zadejte cílovou hodnotu jako číslo "
                                "(dokdy jako datum).")
        return redirect(back)
    if not metric.is_plausible(target):
        messages.error(request, f"Cíl {target:g} je mimo věrohodný rozsah ukazatele {metric.name}.")
        return redirect(back)
    if Goal.objects.filter(subject=subject, metric=metric, is_active=True).exists():
        messages.error(request, f"Ukazatel {metric.name} už cíl má – nejdřív ho zrušte.")
        return redirect(back)
    goal = goals.create(subject, metric, target, due_date=due,
                        note=request.POST.get("poznamka", "").strip(), user=request.user)
    record(request, AuditLog.Action.CREATE, goal, subject_code=subject.code, ukazatel=metric.code,
           cil=target)
    progress = goals.Progress(goal, goals.series_for(subject, metric))
    messages.success(request, f"Cíl uložen: {metric.name} {progress.target_txt}. {progress.text()}")
    return redirect(back)


@login_required
def subject_goal_delete(request, pk, gpk):
    """Zrušení cíle – zůstane v databázi jako neplatný, kvůli historii."""
    from django.contrib import messages

    subject = get_object_or_404(Subject.objects.for_user(request.user), pk=pk)
    back = reverse("subject_detail", args=[pk]) + "#cile"
    if request.method == "POST" and _may_edit(request.user):
        goal = get_object_or_404(Goal, pk=gpk, subject=subject)
        goal.is_active = False
        goal.save(update_fields=["is_active", "updated_at"])
        record(request, AuditLog.Action.DELETE, goal, subject_code=subject.code)
        messages.success(request, f"Cíl {goal.metric.name} zrušen.")
    return redirect(back)


@login_required
def subject_account_remove(request, pk):
    """Odpojí účet sportovce nebo zákonného zástupce (např. po dosažení plnoletosti)."""
    from django.contrib import messages

    from apps.core.models import User

    subject = get_object_or_404(Subject.objects.for_user(request.user), pk=pk)
    if request.method != "POST" or not _may_edit(request.user):
        return redirect("subject_detail", pk=pk)
    kind = request.POST.get("druh", "")
    user = User.objects.filter(pk=request.POST.get("uzivatel") or 0).first()
    if user is None:
        messages.error(request, "Takový účet tu není.")
        return redirect(reverse("subject_detail", args=[pk]) + "#ucet")
    try:
        deactivated = accounts.unlink(subject, kind, user)
    except accounts.AccountError as exc:
        messages.error(request, str(exc))
        return redirect(reverse("subject_detail", args=[pk]) + "#ucet")
    record(request, AuditLog.Action.UPDATE, subject, subject_code=subject.code,
           akce="odebrat_ucet", druh=kind, ucet=user.get_username())
    messages.success(request, f"Účet {user.get_username()} už k sportovci {subject.code} nepatří"
                     + (" a je vypnutý – nezbyl mu žádný sportovec." if deactivated else "."))
    return redirect(reverse("subject_detail", args=[pk]) + "#ucet")


@login_required
def subject_invitation(request, pk, inv_pk):
    from django.conf import settings

    from apps.measurements.questionnaires import qr_svg

    subject = get_object_or_404(Subject.objects.for_user(request.user), pk=pk)
    if not _may_edit(request.user):
        return redirect("subject_detail", pk=pk)
    invitation = get_object_or_404(subject.invitations, pk=inv_pk)
    url = request.build_absolute_uri(reverse("portal_register", args=[invitation.token]))
    identity = getattr(subject, "identity", None)
    try:
        email = identity.email if identity is not None else ""
    except Exception:  # bez klíče
        email = ""
    if request.method == "POST" and request.POST.get("akce") == "email":
        if accounts.send_invitation(invitation, url):
            from django.contrib import messages

            messages.success(request, f"Pozvánka odeslána na {email}.")
            record(request, AuditLog.Action.UPDATE, invitation, subject_code=subject.code,
                   odeslano="e-mail")
        return redirect("subject_invitation", pk=pk, inv_pk=inv_pk)
    search.label([subject], request.user, subject=lambda s: s)
    return render(request, "subjects/invitation.html", {
        "subject": subject, "invitation": invitation, "url": url, "qr": qr_svg(url),
        "email": email, "can_email": bool(settings.EMAIL_HOST and email),
    })


@login_required
def subject_sharing(request, pk):
    """Laboratoř požádá o sdílení s trenérem; platit začne, až ho sportovec potvrdí v účtu."""
    from django.contrib import messages

    subject = get_object_or_404(Subject.objects.for_user(request.user), pk=pk)
    if request.method == "POST" and _may_edit(request.user):
        coach = accounts.coaches(subject.organization).filter(pk=request.POST.get("trener")).first()
        if coach is not None:
            sharing = accounts.request_sharing(subject, coach, by=request.user)
            record(request, AuditLog.Action.UPDATE, subject, subject_code=subject.code,
                   sdileni="zadost", trener=coach.get_username())
            if sharing.status == sharing.Status.ACTIVE:
                messages.info(request, "Sdílení s tímto trenérem už je aktivní.")
            else:
                messages.success(request, f"Žádost o sdílení s trenérem "
                                          f"{accounts.coach_label(coach)} čeká na potvrzení "
                                          f"sportovce v jeho účtu.")
    return redirect(f"{reverse('subject_detail', args=[pk])}#ucet")
