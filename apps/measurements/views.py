from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.audit import record
from apps.core.models import AuditLog

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
    form = TestSessionForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        session = form.save(commit=False)
        session.organization = request.user.organization
        session.operator = request.user
        session.save()
        record(request, AuditLog.Action.CREATE, session, subject_code=session.subject.code)
        return redirect("session_detail", pk=session.pk)
    return render(request, "measurements/session_form.html", {"form": form})


@login_required
def session_detail(request, pk):
    session = get_object_or_404(
        TestSession.objects.for_user(request.user).select_related("subject"), pk=pk)
    return render(request, "measurements/session_detail.html", {
        "session": session,
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
    return saved, flagged
