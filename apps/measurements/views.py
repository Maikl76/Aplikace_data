from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.core.audit import record
from apps.core.models import AuditLog
from apps.subjects.models import Subject

from . import planning, questionnaires
from .forms import AddProtocolForm, TestSessionForm, build_grid, parse_field_name, parse_value
from .models import Measurement, ProtocolRun, QuestionnaireResponse, TestSession, Trial
from .trials import apply_trial_states, trial_states


@login_required
def session_list(request):
    from apps.subjects.search import label, search

    sessions = (TestSession.objects.for_user(request.user)
                .select_related("subject", "subject__sport", "operator")
                .prefetch_related("protocol_runs__protocol")
                .annotate(testu=Count("protocol_runs", distinct=True),
                          zmereno=Count("protocol_runs", distinct=True, filter=Q(
                              protocol_runs__trials__measurements__isnull=False)))
                .order_by("-date", "-pk"))
    q = request.GET.get("q", "").strip()
    if q:
        sessions = sessions.filter(subject__in=[s.pk for s in search(request.user, q, limit=None)])
    sessions = label(sessions[:150], request.user)
    for s in sessions:
        s.protokoly = [run.protocol.name for run in s.protocol_runs.all()]
    template = ("measurements/_session_rows.html" if request.headers.get("HX-Request")
                else "measurements/session_list.html")
    return render(request, template, {"sessions": sessions, "q": q})


@login_required
def session_create(request):
    initial = {"date": timezone.localdate()}
    subject = None
    if subject_id := request.GET.get("sportovec"):
        subject = Subject.objects.for_user(request.user).filter(pk=subject_id).first()
        if subject:
            initial.update(subject=subject.pk, protocols=planning.battery_protocols(subject))
    form = TestSessionForm(request.POST or None, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        session = form.save(commit=False)
        session.organization = request.user.organization
        session.operator = request.user
        session.save()
        planning.ensure_runs(session, form.cleaned_data["protocols"])
        record(request, AuditLog.Action.CREATE, session, subject_code=session.subject.code)
        return redirect("session_detail", pk=session.pk)
    if request.method == "POST" and form.existing is not None and len(form.errors) == 1:
        # Den už existuje: druhý se nezakládá, zvolené testy se přidají do něj.
        session = form.existing
        added = planning.ensure_runs(session, form.cleaned_data.get("protocols") or [])
        messages.info(request, f"Testovací den {session.date:%d.%m.%Y} pro "
                               f"{session.subject.code} už existoval – otevřen"
                               + (f", přidáno testů: {added}." if added else "."))
        return redirect("session_detail", pk=session.pk)
    return render(request, "measurements/session_form.html", {
        "form": form, "battery": planning.battery_for(subject) if subject else None})


@login_required
def session_battery(request):
    """Po výběru sportovce: zaškrtne testy podle baterie jeho sportu (HTMX)."""
    subject = Subject.objects.for_user(request.user).filter(pk=request.GET.get("subject")).first()
    form = TestSessionForm(user=request.user, initial={
        "protocols": planning.battery_protocols(subject) if subject else []})
    return render(request, "measurements/_protocol_choices.html", {
        "form": form, "battery": planning.battery_for(subject) if subject else None,
        "subject": subject})


def _pick_battery(request):
    """Baterie, ze kterých lze vybírat, a ta vybraná (?baterie=, jinak první)."""
    from apps.catalog.models import TestBattery
    from apps.subjects.models import Sport

    batteries = list(TestBattery.objects.filter(sport__in=Sport.objects.for_user(request.user))
                     .select_related("sport").prefetch_related("items__protocol"))
    battery_id = request.GET.get("baterie") or request.POST.get("baterie")
    battery = next((b for b in batteries if str(b.pk) == str(battery_id)), None)
    if battery is None and batteries:
        battery = batteries[0]
    return batteries, battery


def _battery_subjects(request, battery):
    subjects = Subject.objects.for_user(request.user).filter(sport=battery.sport, is_active=True)
    if battery.category:
        subjects = subjects.filter(category__iexact=battery.category)
    return list(subjects.order_by("code"))


@login_required
def today(request):
    """Dnešní testování: skupina sportovců × testy baterie, co je hotové a co chybí."""
    from datetime import date as date_cls

    from apps.subjects.search import names_for

    batteries, battery = _pick_battery(request)
    try:
        day = date_cls.fromisoformat(request.GET.get("datum") or request.POST.get("datum") or "")
    except ValueError:
        day = timezone.localdate()

    rows, protocols = [], []
    if battery:
        protocols = [p for p in battery.protocols() if p.code not in planning.DERIVED_PROTOCOLS]
        subjects = _battery_subjects(request, battery)

        if request.method == "POST":
            chosen = [s for s in subjects if str(s.pk) in request.POST.getlist("sportovec")]
            created = runs = 0
            for subject in chosen:
                session, is_new = TestSession.objects.get_or_create(
                    organization=subject.organization, subject=subject, date=day,
                    defaults={"operator": request.user})
                created += int(is_new)
                runs += planning.ensure_runs(session, protocols)
            messages.success(request, f"Založeno {created} testovacích dnů a {runs} testů "
                                      f"pro {len(chosen)} sportovců.")
            return redirect(f"{request.path}?datum={day.isoformat()}&baterie={battery.pk}")

        names = names_for(subjects, request.user)
        for s in subjects:
            s.zobrazeni = names.get(s.pk) or s.code
        subjects.sort(key=lambda s: s.zobrazeni.lower())
        rows = planning.day_overview(subjects, protocols, day)
        from apps.reports.models import Report

        reports = {r.session_id: r for r in Report.objects.filter(
            session__in=[row["session"] for row in rows if row["session"]])
            .order_by("created_at")}
        for row in rows:
            # vstup do režimu u přístroje: první založený test bez hodnot
            pending = [c["run"] for c in row["cells"] if c["stav"] == "zalozeno"]
            row["pristroj"] = pending[0] if pending else None
            # den je hotový, když má hodnoty u všech testů baterie
            row["kompletni"] = bool(protocols) and row["hotovo"] == len(protocols)
            row["zprava"] = reports.get(row["session"].pk) if row["session"] else None

    from apps.core import access

    done = sum(r["hotovo"] for r in rows)
    return render(request, "measurements/today.html", {
        "batteries": batteries, "battery": battery, "protocols": protocols, "rows": rows,
        "day": day, "hotovo": done, "celkem": len(rows) * len(protocols),
        "bez_zpravy": [r for r in rows if r["kompletni"] and r["zprava"] is None],
        "may_draft": access.can(request.user, "reports_draft"),
        "may_measure": access.can(request.user, "measure"),
    })


@login_required
def today_drafts(request):
    """Koncepty zpráv pro všechny hotové testovací dny skupiny v jednom dni."""
    from datetime import date as date_cls

    from apps.reports import auto
    from apps.reports.models import Audience

    batteries, battery = _pick_battery(request)
    try:
        day = date_cls.fromisoformat(request.POST.get("datum") or "")
    except ValueError:
        day = timezone.localdate()
    back = f"{reverse('today')}?datum={day.isoformat()}" + (f"&baterie={battery.pk}" if battery
                                                             else "")
    if request.method != "POST" or battery is None:
        return redirect(back)
    audience = request.POST.get("pro") or None
    if audience not in Audience.values:
        audience = None   # podle sdílení, jako u konceptu, který vzniká sám
    sessions = list(TestSession.objects.for_user(request.user)
                    .filter(date=day, subject__in=_battery_subjects(request, battery))
                    .select_related("subject"))
    result = auto.drafts_for(sessions, user=request.user, audience=audience)
    record(request, AuditLog.Action.CREATE, battery, baterie=battery.label, datum=day.isoformat(),
           koncepty=result["vytvoreno"])
    from apps.reports.narrative import plural

    n = result["vytvoreno"]
    parts = [f"{plural(n, 'Vznikl', 'Vznikly', 'Vzniklo')} {n} "
             f"{plural(n, 'koncept zprávy', 'koncepty zpráv', 'konceptů zpráv')} ke kontrole."]
    if n := result["uz_ma"]:
        parts.append(f"{n} {plural(n, 'den už zprávu má', 'dny už zprávu mají', 'dnů už zprávu má')}.")
    if n := result["nekompletni"]:
        parts.append(f"{n} {plural(n, 'den ještě nemá', 'dny ještě nemají', 'dnů ještě nemá')} "
                     "hodnoty u všech testů.")
    if result["chyby"]:
        parts.append("Koncept nevznikl u: " + ", ".join(result["chyby"]) + " – otevřete den "
                     "a zkuste to ručně.")
    (messages.success if result["vytvoreno"] else messages.info)(request, " ".join(parts))
    return redirect(back)


@login_required
def week(request):
    """Přehled na týden: den po dni testovací dny, objednávky, kdo je na řadě, zprávy."""
    from apps.core import access

    from . import week as week_overview

    today = timezone.localdate()
    monday = week_overview.parse_monday(request.GET.get("od"), today)
    return render(request, "measurements/week.html", {
        **week_overview.overview(request.user, monday, today=today),
        "may_measure": access.can(request.user, "measure"),
    })


@login_required
def team(request):
    """Týmový přehled: sportovci skupiny × klíčové ukazatele její baterie testů."""
    from apps.analytics.reference import ReferenceIndex
    from apps.analytics.team import MIN_GROUP, STALE_DAYS, columns_for, team_table
    from apps.subjects.search import label

    batteries, battery = _pick_battery(request)
    context = {"batteries": batteries, "battery": battery, "rows": [], "columns": [],
               "min_group": MIN_GROUP, "stale_days": STALE_DAYS, "reference": None}
    if battery:
        subjects = label(_battery_subjects(request, battery), request.user, subject=lambda s: s)
        subjects.sort(key=lambda s: s.jmeno.lower())
        columns = columns_for(battery.protocols())
        reference = ReferenceIndex(request.user.organization)
        table = team_table(subjects, columns, today=timezone.localdate(), reference=reference)
        summary = list(zip(columns, table["summary"], strict=True))
        bands = [s["ref"] for _, s in summary if s["ref"] is not None]
        context.update(columns=columns, rows=table["rows"], summary=summary,
                       reference=bands[0] if bands else None)
        if request.GET.get("format") == "csv":
            from apps.core import access

            if not access.can(request.user, "exports"):
                return render(request, "core/odepreno.html", {"duvod": access.reason("exports")},
                              status=403)
            # Tabulka odchází z aplikace (se jmény, pokud je uživatel vidí) – do auditu.
            record(request, AuditLog.Action.EXPORT, battery, baterie=battery.label,
                   sportovci=[r["subject"].code for r in table["rows"]])
            return _team_csv(battery, columns, table["rows"])
    return render(request, "measurements/team.html", context)


def _team_csv(battery, columns, rows):
    """Tabulka pro Excel: středník a desetinná čárka, jak je v Česku zvykem."""
    import csv

    from django.utils.text import slugify

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (f'attachment; filename="tym-{slugify(battery.label)}-'
                                       f'{timezone.localdate():%Y-%m-%d}.csv"')
    response.write("\ufeff")  # ať Excel pozná UTF-8
    writer = csv.writer(response, delimiter=";")
    header = ["Sportovec"]
    for c in columns:
        name = f"{c['metric'].name}{' – ' + c['label'] if c['label'] else ''}"
        header += [f"{name} [{c['unit']}]" if c["unit"] else name, f"{name} – datum"]
    writer.writerow(header)
    for row in rows:
        line = [row["subject"].jmeno]
        for cell in row["cells"]:
            line += ([cell["value_txt"], f"{cell['date']:%d.%m.%Y}"]
                     if cell else ["", ""])
        writer.writerow(line)
    return response


@login_required
def session_detail(request, pk):
    session = get_object_or_404(
        TestSession.objects.for_user(request.user).select_related("subject"), pk=pk)
    from apps.reports.results import protocol_results
    from apps.subjects.search import label

    label([session], request.user)
    unstable = [(block, row) for block in protocol_results(session) for row in block["unstable"]]
    runs = _in_battery_order(session, session.protocol_runs.select_related("protocol").annotate(
        hodnot=Count("trials__measurements"), pokusu=Count("trials", distinct=True)))
    sources = import_sources([r.protocol for r in runs], session.organization)
    for run in runs:
        run.import_zdroje = sources.get(run.protocol_id, [])
    rpe = questionnaires.questionnaire(questionnaires.RPE, session.organization)
    from apps.core.steps import next_step
    from apps.reports import followup

    from .steps import session_steps

    reports = list(session.reports.order_by("-created_at"))
    previous = followup.state(session)
    steps = session_steps(session, runs, unstable, reports, followup=previous)
    return render(request, "measurements/session_detail.html", {
        "session": session,
        "je_minuly": session.date < timezone.localdate(),
        "unstable": unstable,
        "runs": runs,
        "device_url": device_url(runs),
        "followup": previous,
        "followup_statuses": followup.RecommendationReview.Status.choices,
        "reports": reports,
        "steps": steps, "next_step": next_step(steps),
        "add_form": AddProtocolForm(),
        "rpe": rpe,
        "rpe_question": rpe.questions.first() if rpe else None,
        "rpe_runs": [r for r in runs if r.protocol.code not in planning.DERIVED_PROTOCOLS],
        "responses": questionnaires.summary(session),
        "other_questionnaires": questionnaires.available(session.organization),
    })


@login_required
def session_repeat(request, pk):
    """Zopakovat testovací den: dnes (nebo zvolený den) se stejnými testy jako tenkrát."""
    from datetime import date as date_cls

    source = get_object_or_404(TestSession.objects.for_user(request.user)
                               .select_related("subject"), pk=pk)
    if request.method != "POST":
        return redirect("session_detail", pk=pk)
    try:
        day = date_cls.fromisoformat(request.POST.get("datum") or "")
    except ValueError:
        day = timezone.localdate()
    session, created, added = planning.repeat_session(source, day=day, user=request.user)
    record(request, AuditLog.Action.CREATE, session, subject_code=session.subject.code,
           podle=source.date.isoformat(), testu=added)
    if created:
        messages.success(request, f"Založen testovací den {day:%d.%m.%Y} s {added} testy podle "
                                  f"{source.date:%d.%m.%Y}. Hodnoty zadáte tady, nebo nahrajete "
                                  "export.")
    else:
        messages.info(request, f"Testovací den {day:%d.%m.%Y} už existoval – otevřen"
                               + (f", doplněno testů: {added}." if added else "."))
    return redirect("session_detail", pk=session.pk)


@login_required
def session_followup(request, pk):
    """Plnění doporučení z minulé zprávy – jedním klikem u každého doporučení."""
    from apps.reports import followup

    session = get_object_or_404(TestSession.objects.for_user(request.user), pk=pk)
    back = reverse("session_detail", args=[pk]) + "#doporuceni-minule"
    if request.method != "POST":
        return redirect(back)
    report = followup.previous_report(session)
    if report is None:
        messages.error(request, "Před tímto dnem není vydaná zpráva s doporučením.")
        return redirect(back)
    saved = followup.save(session, report, request.POST, user=request.user)
    record(request, AuditLog.Action.UPDATE, session, subject_code=session.subject.code,
           plneni_doporuceni=saved, zprava=report.report_number)
    state = followup.state(session, report=report)
    messages.success(request, f"Plnění doporučení z {report.report_number} uloženo "
                              f"({state['reviewed']} z {state['total']} posouzeno). "
                              "Nová zpráva na ně naváže.")
    return redirect(back)


@login_required
def session_conditions(request, pk):
    """Prostředí testovacího dne (teplota, vlhkost) – zadává se až na místě."""
    session = get_object_or_404(TestSession.objects.for_user(request.user), pk=pk)
    if request.method == "POST":
        for field in ("temperature_c", "humidity_pct"):
            setattr(session, field, parse_value(request.POST.get(field, "")))
        session.save(update_fields=["temperature_c", "humidity_pct"])
        messages.success(request, "Prostředí uloženo.")
    return redirect("session_detail", pk=pk)


def _session_questionnaire(request, session):
    """Dotazník a test z formuláře nebo parametrů (?beh=)."""
    questionnaire = questionnaires.questionnaire(
        request.POST.get("dotaznik") or request.GET.get("dotaznik") or questionnaires.RPE,
        session.organization)
    run_id = request.POST.get("beh") or request.GET.get("beh")
    run = session.protocol_runs.filter(pk=run_id).first() if run_id else None
    return questionnaire, run


@login_required
def session_questionnaire(request, pk):
    """Operátor zapíše odpověď za sportovce (např. RPE nahlas)."""
    session = get_object_or_404(TestSession.objects.for_user(request.user), pk=pk)
    questionnaire, run = _session_questionnaire(request, session)
    if request.method == "POST" and questionnaire:
        answers = questionnaires.parse_answers(questionnaire, request.POST)
        if answers:
            questionnaires.save(session, questionnaire, answers, run=run,
                                source=QuestionnaireResponse.Source.OPERATOR)
            record(request, AuditLog.Action.UPDATE, session,
                   subject_code=session.subject.code, dotaznik=questionnaire.code)
            messages.success(request, f"{questionnaire.name}: uloženo.")
        else:
            messages.warning(request, "Vyberte hodnotu na škále.")
    return redirect(f"{reverse('session_detail', args=[pk])}#dotazniky")


@login_required
def session_questionnaire_qr(request, pk):
    """QR kód s odkazem, přes který dotazník vyplní sportovec na svém telefonu."""
    session = get_object_or_404(TestSession.objects.for_user(request.user), pk=pk)
    questionnaire, run = _session_questionnaire(request, session)
    if questionnaire is None:
        return HttpResponse(status=404)
    token = questionnaires.make_token(session, questionnaire, run)
    url = request.build_absolute_uri(reverse("questionnaire_fill", args=[token]))
    return render(request, "measurements/_questionnaire_qr.html", {
        "qr": questionnaires.qr_svg(url), "url": url, "run": run,
        "questionnaire": questionnaire,
        "reachable": questionnaires.reachable_from_phone(request),
        "hours": questionnaires.TOKEN_MAX_AGE // 3600,
    })


@login_required
def session_questionnaire_form(request, pk, code):
    """Vlastní dotazník k testovacímu dni vyplněný v laboratoři (za sportovce nebo s ním)."""
    session = get_object_or_404(TestSession.objects.for_user(request.user), pk=pk)
    questionnaire = next((q for q in questionnaires.available(session.organization)
                          if q.code == code), None)
    if questionnaire is None:
        messages.error(request, "Takový dotazník se v testovacím dni nenabízí.")
        return redirect("session_detail", pk=pk)
    previous = session.responses.filter(questionnaire=questionnaire, protocol_run=None).first()
    missing = []
    if request.method == "POST":
        values = questionnaires.parse_answers(questionnaire, request.POST)
        missing = questionnaires.missing_required(questionnaire, values)
        if not missing:
            source = (QuestionnaireResponse.Source.SUBJECT
                      if request.POST.get("vyplnil") == "sportovec"
                      else QuestionnaireResponse.Source.OPERATOR)
            questionnaires.save(session, questionnaire, values, run=None, source=source)
            record(request, AuditLog.Action.UPDATE, session,
                   subject_code=session.subject.code, dotaznik=questionnaire.code)
            messages.success(request, f"{questionnaire.name}: uloženo.")
            return redirect(f"{reverse('session_detail', args=[pk])}#dotazniky")
        messages.error(request, "Doplňte povinné otázky, nebo u nich zvolte „nevím“ / „netýká se“.")
    return render(request, "measurements/questionnaire_form.html", {
        "questionnaire": questionnaire, "previous": previous, "missing": missing,
        "sections": questionnaires.sections(questionnaire, previous), "overwrite": True,
        "back_url": f"{reverse('session_detail', args=[pk])}#dotazniky",
        "back_label": f"Testovací den {session.date:%d.%m.%Y}", "who": True,
    })


def questionnaire_fill(request, token):
    """
    Vyplnění dotazníku sportovcem – bez přihlášení, jen s podepsaným odkazem.
    Neukazuje jméno ani výsledky, jen otázku.
    """
    from apps.catalog.models import Question, Questionnaire

    data = questionnaires.read_token(token)
    session = TestSession.objects.filter(pk=(data or {}).get("s")).first()
    questionnaire = (Questionnaire.objects.filter(pk=data.get("q")).first()
                     if data and session else None)
    if questionnaire is None:
        return render(request, "measurements/questionnaire_fill.html",
                      {"invalid": True}, status=410)
    run = session.protocol_runs.filter(pk=data.get("r")).select_related("protocol").first()
    questions = list(questionnaire.questions.all())
    simple = all(q.kind == Question.Kind.SCALE for q in questions)   # RPE: jen škála
    done, missing = False, []
    if request.method == "POST":
        answers = questionnaires.parse_answers(questionnaire, request.POST)
        missing = questionnaires.missing_required(questionnaire, answers)
        if answers and not missing:
            questionnaires.save(session, questionnaire, answers, run=run,
                                source=QuestionnaireResponse.Source.SUBJECT)
            done = True
    return render(request, "measurements/questionnaire_fill.html", {
        "questionnaire": questionnaire, "run": run, "session": session, "done": done,
        "questions": questions, "simple": simple, "missing": missing,
        "sections": [] if simple else questionnaires.sections(questionnaire),
    })


@login_required
def session_add_protocol(request, pk):
    session = get_object_or_404(TestSession.objects.for_user(request.user), pk=pk)
    form = AddProtocolForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        protocol = form.cleaned_data["protocol"]
        existing = session.protocol_runs.filter(protocol=protocol).order_by("pk").first()
        if existing is not None and form.cleaned_data["repeat"]:
            # Opakované měření (po zátěži): vlastní provedení s časem, hlavní zůstává.
            run = ProtocolRun.objects.create(session=session, protocol=protocol,
                                             is_primary=False, started_at=timezone.now())
            messages.info(request, f"{protocol.name}: založeno opakované měření. Do trendů "
                                   "a pravidel jde dál první měření dne.")
        elif existing is not None:
            run = existing
        else:
            run = ProtocolRun.objects.create(session=session, protocol=protocol)
        return redirect("run_entry", pk=run.pk)
    return redirect("session_detail", pk=pk)


@login_required
def run_entry(request, pk):
    """
    Zadávání u přístroje. Mřížka vzniká z definice protokolu, takže
    pro nový protokol není potřeba psát nový formulář.
    """
    return _run_entry(request, pk, device=False)


@login_required
def run_device(request, pk):
    """
    Režim u přístroje: táž mřížka na jedné obrazovce bez menu, s postupem
    baterií a velkými tlačítky – test za testem až po shrnutí dne.
    """
    return _run_entry(request, pk, device=True)


def _run_entry(request, pk, *, device: bool):
    run = get_object_or_404(
        ProtocolRun.objects.select_related("protocol", "session__subject"), pk=pk)
    if run.session.organization_id != request.user.organization_id and not request.user.is_superuser:
        return redirect("session_list")
    from apps.subjects.search import label

    label([run.session], request.user)
    try:
        columns = int(request.GET.get("pokusy") or 0)
    except ValueError:
        columns = 0

    if request.method == "POST":
        saved, flagged, deleted, invalid = _save_grid(request, run)
        message = f"Uloženo {saved} hodnot."
        if unstable := sum(1 for row in build_grid(run) if row["warnings"]):
            from apps.reports.narrative import plural

            message += (f" U {unstable} {plural(unstable, 'ukazatele', 'ukazatelů', 'ukazatelů')} "
                        "se pokusy liší víc než obvykle, nebo je hodnota mimo rozsah – viz "
                        "upozornění v mřížce.")
        if saved:
            from apps.reports import auto as report_auto

            draft = report_auto.ensure_draft(run.session, user=request.user)
            if draft is not None:
                record(request, AuditLog.Action.CREATE, draft,
                       subject_code=run.session.subject.code, automaticky=True)
                message += (f" Koncept zprávy {draft.report_number} je připravený ke kontrole "
                            "(Zprávy).")
        if deleted:
            message += f" Smazáno {deleted} vymazaných hodnot."
        if invalid:
            message += (" Neplatný pokus: " + ", ".join(str(n) for n in invalid)
                        + " – do výsledků se nepočítá.")
        if flagged:
            message += (f" {flagged} mimo věrohodný rozsah – hodnoty jsou uložené "
                        f"a označené, zkontrolujte je.")
        if flagged or unstable:
            messages.warning(request, message)
        else:
            messages.success(request, message)
        if "dalsi" in request.POST:
            target = _next_run_url(run, device=device)
            if request.headers.get("HX-Request"):
                response = HttpResponse(status=204)
                response["HX-Redirect"] = target
                return response
            return redirect(target)
        if request.headers.get("HX-Request"):
            return render(request, "measurements/_entry_grid.html",
                          {**_entry_context(run, device=device), "saved": saved})
        if device:
            return redirect("run_device", pk=run.pk)
        return redirect("session_detail", pk=run.session_id)

    template = "measurements/device_entry.html" if device else "measurements/run_entry.html"
    return render(request, template, _entry_context(run, columns=columns, device=device))


@login_required
def session_device_done(request, pk):
    """Shrnutí dne po posledním testu v režimu u přístroje; nabídne dalšího sportovce."""
    session = get_object_or_404(
        TestSession.objects.for_user(request.user).select_related("subject"), pk=pk)
    from apps.reports.results import protocol_results
    from apps.subjects.search import label

    label([session], request.user)
    runs = _session_runs(session)
    for run in runs:
        run.rpe_chybi = run.protocol.rpe_after and run.hodnot and not questionnaires.rpe_for_run(run)
    unstable = [(block, row) for block in protocol_results(session) for row in block["unstable"]]
    out_of_range = Measurement.objects.filter(
        trial__protocol_run__session=session).exclude(quality=Measurement.Quality.OK).count()
    pending = [r for r in runs if not r.hodnot]
    following = _next_subject_run(session, request.user)
    from apps.reports.narrative import plural

    return render(request, "measurements/device_done.html", {
        "session": session, "runs": runs, "pending": pending, "unstable": unstable,
        "pending_text": (f"zbývá {len(pending)} {plural(len(pending), 'test', 'testy', 'testů')}"
                         if pending else ""),
        "out_of_range": out_of_range, "rpe_missing": [r for r in runs if r.rpe_chybi],
        "reports": list(session.reports.order_by("-created_at")),
        "next_session": following[0] if following else None,
        "next_run": following[1] if following else None,
    })


def _next_subject_run(session, user):
    """Další sportovec téhož dne s testem bez hodnot: (jeho den, první takový test)."""
    from apps.subjects.search import label

    others = list(TestSession.objects.for_user(user).filter(date=session.date)
                  .exclude(pk=session.pk).select_related("subject"))
    label(others, user)
    for other in sorted(others, key=lambda s: str(getattr(s, "jmeno", s.subject.code)).lower()):
        for run in _session_runs(other):
            if not run.hodnot:
                return other, run
    return None


@login_required
def run_conditions(request, pk):
    """
    Podmínky provedení testu (kofein před testem, poznámka). Dávka kofeinu
    se ukládá do podmínek provedení jako ``kofein_mg_kg`` – genetická zpráva
    z ní pozná pokus s kofeinem a porovná ho s provedením bez kofeinu.
    """
    run = get_object_or_404(
        ProtocolRun.objects.select_related("session"), pk=pk)
    if run.session.organization_id != request.user.organization_id and not request.user.is_superuser:
        return redirect("session_list")
    if request.method == "POST":
        conditions = dict(run.conditions or {})
        dose = parse_value(request.POST.get("kofein_mg_kg", ""))
        if dose:
            conditions["kofein_mg_kg"] = dose
        else:
            conditions.pop("kofein_mg_kg", None)
        run.conditions = conditions
        run.note = request.POST.get("poznamka", "").strip()[:1000]
        run.save(update_fields=["conditions", "note"])
        record(request, AuditLog.Action.UPDATE, run, subject_code=run.session.subject.code,
               podminky=conditions)
        messages.success(request, "Podmínky provedení uloženy.")
    return redirect("run_entry", pk=pk)


def import_sources(protocols, organization):
    from apps.ingest.capabilities import import_sources as sources

    return sources(protocols, organization)


def _entry_context(run, *, columns: int | None = None, device: bool = False) -> dict:
    rpe = (questionnaires.questionnaire(questionnaires.RPE, run.session.organization)
           if run.protocol.rpe_after else None)
    answer = questionnaires.rpe_for_run(run) if rpe else None
    context = {
        "run": run,
        "import_zdroje": import_sources([run.protocol], run.session.organization)
        .get(run.protocol_id, []),
        # export k testu jen dokud je prázdný – jinak by vedle ručních hodnot vzniklo druhé provedení
        "ma_hodnoty": Measurement.objects.filter(trial__protocol_run=run).exists(),
        "rows": build_grid(run, columns=columns),
        "trials": trial_states(run, columns),
        "rpe_question": rpe.questions.first() if rpe else None,
        "rpe_value": int(answer.value) if answer and answer.value is not None else None,
        "next_run": _next_run(run),
        "device": device,
    }
    if device:
        runs = _session_runs(run.session)
        context["progress"] = [
            {"run": r, "state": ("current" if r.pk == run.pk else "done" if r.hodnot else "todo")}
            for r in runs]
        context["position"] = next((i for i, r in enumerate(runs, start=1) if r.pk == run.pk), 0)
    return context


def _in_battery_order(session, runs) -> list:
    """Testy v pořadí baterie sportu (tak se obvykle měří), ostatní podle názvu."""
    battery = planning.battery_for(session.subject)
    order = ({item.protocol_id: item.order for item in battery.items.all()}
             if battery else {})
    return sorted(runs, key=lambda r: (order.get(r.protocol_id, 10_000), r.protocol.name,
                                       r.started_at or r.created_at, r.pk))


def _session_runs(session):
    """Měřené testy dne v pořadí, v jakém se zobrazují (a měří), s počtem hodnot."""
    return _in_battery_order(session, session.protocol_runs.select_related("protocol")
                             .exclude(protocol__code__in=planning.DERIVED_PROTOCOLS)
                             .annotate(hodnot=Count("trials__measurements")))


def _next_run(run):
    runs = _session_runs(run.session)
    ids = [r.pk for r in runs]
    if run.pk in ids and ids.index(run.pk) + 1 < len(runs):
        return runs[ids.index(run.pk) + 1]
    return None


def _next_run_url(run, *, device: bool = False) -> str:
    following = _next_run(run)
    if following:
        return reverse("run_device" if device else "run_entry", args=[following.pk])
    return reverse("session_device_done" if device else "session_detail", args=[run.session_id])


def device_url(runs) -> str:
    """Vstup do režimu u přístroje: první test bez hodnot, jinak první test dne."""
    runs = [r for r in runs if r.protocol.code not in planning.DERIVED_PROTOCOLS]
    if not runs:
        return ""
    first = next((r for r in runs if not getattr(r, "hodnot", 0)), runs[0])
    return reverse("run_device", args=[first.pk])


@transaction.atomic
def _save_grid(request, run) -> tuple[int, int, int, list[int]]:
    metrics = {pm.pk: pm.metric
               for pm in run.protocol.protocol_metrics.select_related("metric")}
    trials: dict[int, Trial] = {}
    saved = flagged = deleted = 0

    for name, raw in request.POST.items():
        parsed = parse_field_name(name)
        if parsed is None:
            continue
        metric = metrics.get(parsed["protocol_metric_id"])
        if metric is None:
            continue
        if not str(raw).strip():
            # Vymazané pole = hodnota pryč. Špatně zapsané číslo tak jde
            # opravit smazáním, ne jen přepsáním.
            deleted += Measurement.objects.filter(
                trial__protocol_run=run, trial__number=parsed["trial_number"], metric=metric,
                side=parsed["side"], mode=parsed["mode"], speed=parsed["speed"],
                segment=parsed["segment"]).delete()[0]
            continue
        value = parse_value(raw)
        if value is None:
            continue

        number = parsed["trial_number"]
        if number not in trials:
            trials[number], _ = Trial.objects.get_or_create(protocol_run=run, number=number)

        quality = (Measurement.Quality.OK if metric.is_plausible(value)
                   else Measurement.Quality.OUT_OF_RANGE)
        flagged += int(quality != Measurement.Quality.OK)

        Measurement.objects.update_or_create(
            trial=trials[number], metric=metric, side=parsed["side"],
            mode=parsed["mode"], speed=parsed["speed"], segment=parsed["segment"],
            defaults={"value": value, "quality": quality},
        )
        saved += 1

    if run.protocol.rpe_after and (rpe := questionnaires.questionnaire(
            questionnaires.RPE, run.session.organization)):
        if answers := questionnaires.parse_answers(rpe, request.POST):
            questionnaires.save(run.session, rpe, answers, run=run,
                                source=QuestionnaireResponse.Source.OPERATOR)

    invalid = apply_trial_states(run, request.POST)
    record(request, AuditLog.Action.UPDATE, run,
           subject_code=run.session.subject.code, hodnot=saved, smazano=deleted,
           neplatne_pokusy=invalid)
    # Nové hodnoty CMJ nebo IMTP mění i odvozené ukazatele (DSI).
    from apps.analytics.derived import recompute

    recompute(run.session)
    return saved, flagged, deleted, invalid
