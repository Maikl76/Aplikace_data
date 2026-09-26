from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.audit import record
from apps.core.models import AuditLog
from apps.subjects.models import Subject

from . import planning
from .forms import AddProtocolForm, TestSessionForm, build_grid, parse_field_name
from .models import Measurement, ProtocolRun, TestSession, Trial


@login_required
def session_list(request):
    sessions = (TestSession.objects.for_user(request.user)
                .select_related("subject", "operator")
                .prefetch_related("protocol_runs__protocol")[:100])
    return render(request, "measurements/session_list.html", {"sessions": sessions})


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


@login_required
def today(request):
    """Dnešní testování: skupina sportovců × testy baterie, co je hotové a co chybí."""
    from datetime import date as date_cls

    from apps.catalog.models import TestBattery
    from apps.subjects.models import Sport
    from apps.subjects.search import names_for

    batteries = list(TestBattery.objects.filter(sport__in=Sport.objects.for_user(request.user))
                     .select_related("sport").prefetch_related("items__protocol"))
    try:
        day = date_cls.fromisoformat(request.GET.get("datum") or request.POST.get("datum") or "")
    except ValueError:
        day = timezone.localdate()
    battery_id = request.GET.get("baterie") or request.POST.get("baterie")
    battery = next((b for b in batteries if str(b.pk) == str(battery_id)), None)
    if battery is None and batteries:
        battery = batteries[0]

    rows, protocols = [], []
    if battery:
        protocols = [p for p in battery.protocols() if p.code not in planning.DERIVED_PROTOCOLS]
        subjects = Subject.objects.for_user(request.user).filter(sport=battery.sport,
                                                                 is_active=True)
        if battery.category:
            subjects = subjects.filter(category__iexact=battery.category)
        subjects = list(subjects.order_by("code"))

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

    done = sum(r["hotovo"] for r in rows)
    return render(request, "measurements/today.html", {
        "batteries": batteries, "battery": battery, "protocols": protocols, "rows": rows,
        "day": day, "hotovo": done, "celkem": len(rows) * len(protocols),
    })


@login_required
def session_detail(request, pk):
    session = get_object_or_404(
        TestSession.objects.for_user(request.user).select_related("subject"), pk=pk)
    from apps.reports.results import protocol_results

    unstable = [(block, row) for block in protocol_results(session) for row in block["unstable"]]
    return render(request, "measurements/session_detail.html", {
        "session": session,
        "unstable": unstable,
        "runs": session.protocol_runs.select_related("protocol"),
        "add_form": AddProtocolForm(),
    })


@login_required
def session_add_protocol(request, pk):
    session = get_object_or_404(TestSession.objects.for_user(request.user), pk=pk)
    form = AddProtocolForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        run, _ = ProtocolRun.objects.get_or_create(
            session=session, protocol=form.cleaned_data["protocol"])
        return redirect("run_entry", pk=run.pk)
    return redirect("session_detail", pk=pk)


@login_required
def run_entry(request, pk):
    """
    Zadávání u přístroje. Mřížka vzniká z definice protokolu, takže
    pro nový protokol není potřeba psát nový formulář.
    """
    run = get_object_or_404(
        ProtocolRun.objects.select_related("protocol", "session__subject"), pk=pk)
    if run.session.organization_id != request.user.organization_id and not request.user.is_superuser:
        return redirect("session_list")

    if request.method == "POST":
        saved, flagged = _save_grid(request, run)
        message = f"Uloženo {saved} hodnot."
        if flagged:
            message += (f" {flagged} mimo věrohodný rozsah – hodnoty jsou uložené "
                        f"a označené, zkontrolujte je.")
            messages.warning(request, message)
        else:
            messages.success(request, message)
        if request.headers.get("HX-Request"):
            return render(request, "measurements/_entry_grid.html", {
                "run": run,
                "rows": build_grid(run),
                "trials": range(1, run.protocol.default_trials + 1),
                "saved": saved,
            })
        return redirect("session_detail", pk=run.session_id)

    return render(request, "measurements/run_entry.html", {
        "run": run,
        "rows": build_grid(run),
        "trials": range(1, run.protocol.default_trials + 1),
    })


@transaction.atomic
def _save_grid(request, run) -> tuple[int, int]:
    metrics = {pm.pk: pm.metric
               for pm in run.protocol.protocol_metrics.select_related("metric")}
    trials: dict[int, Trial] = {}
    saved = flagged = 0

    for name, raw in request.POST.items():
        parsed = parse_field_name(name)
        if parsed is None or not str(raw).strip():
            continue
        metric = metrics.get(parsed["protocol_metric_id"])
        if metric is None:
            continue
        try:
            value = float(str(raw).replace(",", "."))
        except ValueError:
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

    record(request, AuditLog.Action.UPDATE, run,
           subject_code=run.session.subject.code, hodnot=saved)
    # Nové hodnoty CMJ nebo IMTP mění i odvozené ukazatele (DSI).
    from apps.analytics.derived import recompute

    recompute(run.session)
    return saved, flagged
