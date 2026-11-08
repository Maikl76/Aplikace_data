from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.catalog.models import Protocol
from apps.core.audit import record
from apps.core.models import AuditLog

from . import device_views, services, watch
from .adapters import registry
from .models import ImportBatch, StagedMeasurement, WatchedFile


@login_required
def import_list(request):
    # Zapomenuté náhledy drží jména ze souboru – po měsíci se uklidí samy.
    services.expire_stale()
    batches = (ImportBatch.objects.for_user(request.user)
               .select_related("raw_file", "uploaded_by")[:50])
    devices = device_views.device_cards(request.user)
    from .steps import import_list_steps

    org = request.user.organization
    files = list(WatchedFile.objects.filter(organization=org).select_related("batch")[:12]) if org else []
    watched = {
        "dir": settings.IMPORT_WATCH_DIR,
        "checked_at": org.import_checked_at if org else None,
        "running": bool(org) and watch.is_running(org),
        "files": files,
        "waiting": [w for w in files if w.status == WatchedFile.Status.WAITING],
    }
    return render(request, "ingest/import_list.html", {
        "steps": import_list_steps(request.user, batches, watched=watched),
        "watched": watched,
        "batches": batches,
        "adapters": sorted(registry.values(), key=lambda a: a.label),
        "devices": devices,
        "ready_devices": [d for d in devices if d.is_active],
        "can_edit_devices": device_views.can_edit(request.user),
        "protocols": Protocol.objects.filter(is_active=True),
    })


@login_required
def import_upload(request):
    """
    Nahrání jednoho nebo víc souborů. Nic se neuloží – vznikne jen náhled
    ke kontrole (u víc souborů jeden náhled na soubor).
    """
    files = request.FILES.getlist("file")
    if request.method != "POST" or not files:
        return redirect("import_list")

    protocol = None
    if protocol_id := request.POST.get("protocol"):
        protocol = Protocol.objects.filter(pk=protocol_id).first()

    ready = []
    for uploaded in files:
        try:
            batch = services.stage_file(
                uploaded_file=uploaded,
                user=request.user,
                organization=request.user.organization,
                adapter_code=request.POST.get("adapter", "auto"),
                protocol=protocol,
            )
        except services.ImportError_ as exc:
            messages.error(request, f"{uploaded.name}: {exc}")
            continue
        if batch.status == ImportBatch.Status.FAILED:
            messages.error(request, f"{uploaded.name}: soubor se nepodařilo zpracovat "
                                    f"({batch.error})")
            continue
        ready.append(batch)

    # Nahráno z testovacího dne nebo z Dnešního testování: náhled předvybere
    # jeho sportovce a po uložení se aplikace vrátí tam, odkud se nahrávalo.
    if ready and (target := upload_target(request)):
        for batch in ready:
            batch.summary = {**(batch.summary or {}), "cil": target}
            batch.save(update_fields=["summary"])

    if len(ready) == 1:
        return redirect("import_detail", pk=ready[0].pk)
    if ready:
        messages.info(request, f"Načteno {len(ready)} souborů. Zkontrolujte a uložte "
                               f"každý zvlášť (odkaz „zkontrolovat“ v historii).")
    return redirect("import_list")


def upload_target(request) -> dict:
    """
    Odkud se export nahrál: z testovacího dne (jeden sportovec), nebo
    z Dnešního testování (skupina v jeden den). Drží se v souhrnu náhledu
    jako ``cil``: koho nabídnout první, kam zapsat řádky bez data a kam se
    po uložení vrátit.
    """
    from datetime import date

    from django.urls import reverse

    from apps.measurements.models import ProtocolRun, TestSession

    if run_id := request.POST.get("provedeni"):
        run = (ProtocolRun.objects.filter(pk=run_id, session__in=TestSession.objects
                                          .for_user(request.user))
               .select_related("session", "protocol").first())
        if run is None:
            return {}
        return {"subject": run.session.subject_id, "session": run.session_id, "run": run.pk,
                "protokol": run.protocol.code, "test": run.protocol.name,
                "den": run.session.date.isoformat(),
                "zpet": reverse("run_entry", args=[run.pk])}
    if session_id := request.POST.get("testovaci_den"):
        session = TestSession.objects.for_user(request.user).filter(pk=session_id).first()
        if session is None:
            return {}
        return {"subject": session.subject_id, "session": session.pk,
                "den": session.date.isoformat(),
                "zpet": reverse("session_detail", args=[session.pk])}
    if day_text := request.POST.get("testovani_datum"):
        try:
            day = date.fromisoformat(day_text)
        except ValueError:
            return {}
        from apps.catalog.models import TestBattery
        from apps.subjects.models import Sport, Subject

        battery = (TestBattery.objects.filter(pk=request.POST.get("testovani_baterie") or None,
                                              sport__in=Sport.objects.for_user(request.user))
                   .select_related("sport").first())
        subjects = Subject.objects.for_user(request.user).filter(is_active=True)
        if battery is not None:
            subjects = subjects.filter(sport=battery.sport)
            if battery.category:
                subjects = subjects.filter(category__iexact=battery.category)
        back = reverse("today") + f"?datum={day.isoformat()}"
        if battery is not None:
            back += f"&baterie={battery.pk}"
        return {"den": day.isoformat(), "skupina": battery.label if battery else "",
                "subjects": list(subjects.values_list("pk", flat=True)), "zpet": back}
    return {}


def _back_url(request, batch) -> str:
    """Kam po uložení: tam, odkud se nahrávalo (jen adresa v aplikaci), jinak seznam importů."""
    from django.urls import reverse
    from django.utils.http import url_has_allowed_host_and_scheme

    back = ((batch.summary or {}).get("cil") or {}).get("zpet") or ""
    if back.startswith("/") and url_has_allowed_host_and_scheme(back, allowed_hosts=None):
        return back
    return reverse("import_list")


@login_required
def import_detail(request, pk):
    """Náhled před uložením: co se našlo a na co se podívat."""
    batch = get_object_or_404(ImportBatch.objects.for_user(request.user), pk=pk)
    staged = batch.staged.select_related("metric", "protocol")
    summary = batch.summary or {}

    # Nový sportovec při prvním importu není problém, je to očekávaný stav.
    # Kdyby se míchal mezi skutečné problémy, utopil by je – u prvního
    # importu je tak označený každý řádek.
    # Test, který už v aplikaci je, taky není problém – při uložení se jen
    # aktualizuje. Hlásí se souhrnně nad tabulkou.
    problem_flags = [
        StagedMeasurement.Flag.OUT_OF_RANGE,
        StagedMeasurement.Flag.UNKNOWN_METRIC,
    ]
    sportovci = services.assignment_choices(batch, request.user)
    problems = list(staged.filter(flag__in=problem_flags)[:100])
    from .steps import import_detail_steps

    cil = summary.get("cil") or {}
    try:
        from datetime import date

        cil_den = date.fromisoformat(cil.get("den") or "")
    except ValueError:
        cil_den = None
    # Nahráno k jednomu testu, ale soubor nese i jiné: ty se zapíší ke svým testům dne.
    cil_jine = []
    if cil.get("protokol"):
        cil_jine = sorted({name for name in staged.exclude(protocol__code=cil["protokol"])
                           .exclude(protocol__isnull=True)
                           .values_list("protocol__name", flat=True)})

    return render(request, "ingest/import_detail.html", {
        "steps": import_detail_steps(batch, sportovci, problems),
        "batch": batch,
        "summary": summary,
        "cil": cil, "cil_den": cil_den, "cil_jine": cil_jine,
        "dlazdice": [
            ("sportovců", summary.get("sportovcu")),
            ("nepoznaných automaticky", summary.get("novych_sportovcu")),
            ("testů", summary.get("testu")),
            ("hodnot", summary.get("hodnot")),
            ("metrik", summary.get("metrik")),
            ("mimo rozsah", summary.get("mimo_rozsah")),
        ],
        "sportovci": sportovci,
        "ma_klic": bool(settings.IDENTITY_ENCRYPTION_KEY),
        "datum_od": summary.get("datum_od"),
        "datum_do": summary.get("datum_do"),
        "bez_data": summary.get("novych_hodnot_bez_data") or 0,
        "problems": problems,
        "sample": staged.exclude(flag__in=problem_flags)[:25],
        # řádky bez data: den, ze kterého se nahrávalo, jinak dnešek
        "dnes": cil_den or timezone.localdate(),
    })


@login_required
def import_commit(request, pk):
    batch = get_object_or_404(ImportBatch.objects.for_user(request.user), pk=pk)
    if request.method != "POST":
        return redirect("import_detail", pk=pk)

    default_date = request.POST.get("default_date") or None
    # Ruční přiřazení sportovců z náhledu (pole „prirazeni_<klíč>“).
    assignments = {name.removeprefix("prirazeni_"): value or None
                   for name, value in request.POST.items() if name.startswith("prirazeni_")}
    if assignments and batch.status == ImportBatch.Status.PARSED:
        services.apply_assignments(batch, assignments, request.user)
    if problem := services.scope_problem(batch, request.user):
        messages.error(request, problem)
        return redirect("import_detail", pk=pk)
    try:
        result = services.commit_batch(
            batch, user=request.user, default_date=default_date,
            skip_out_of_range=bool(request.POST.get("skip_out_of_range")),
        )
    except services.ImportError_ as exc:
        messages.error(request, str(exc))
        return redirect("import_detail", pk=pk)

    record(request, AuditLog.Action.CREATE, batch, **result)
    text = (f"Uloženo {result['hodnoty']} hodnot, {result.get('testy', 0)} testů, "
            f"{result['session']} nových testovacích dnů, {result['sportovci']} nových sportovců.")
    if result.get("aktualizovano"):
        text += f" Aktualizováno {result['aktualizovano']} hodnot, které VALD přepočítal."
    if result.get("koncepty"):
        text += (f" Koncepty zpráv ke kontrole: {', '.join(result['koncepty'])}.")
    messages.success(request, text)
    if result.get("jmena_neulozena"):
        messages.warning(request, (
            f"Jména {result['jmena_neulozena']} nových sportovců se neuložila – chybí "
            f"šifrovací klíč. Spusťte aplikaci přes spustit.bat, klíč se doplní sám; "
            f"jména pak doplníte v administraci (Identity sportovců)."))
    return redirect(_back_url(request, batch))


@login_required
def import_restage(request, pk):
    """Znovu načte uložený soubor – např. po doplnění profilu importu."""
    batch = get_object_or_404(ImportBatch.objects.for_user(request.user), pk=pk)
    if request.method != "POST":
        return redirect("import_list")
    try:
        new_batch = services.restage(batch.raw_file, user=request.user,
                                     organization=request.user.organization)
    except services.ImportError_ as exc:
        messages.error(request, str(exc))
        return redirect("import_list")
    if new_batch.status == ImportBatch.Status.FAILED:
        messages.error(request, f"Soubor se nepodařilo zpracovat ({new_batch.error})")
        return redirect("import_list")
    return redirect("import_detail", pk=new_batch.pk)


@login_required
def import_cancel(request, pk):
    batch = get_object_or_404(ImportBatch.objects.for_user(request.user), pk=pk)
    if request.method == "POST":
        batch.status = ImportBatch.Status.CANCELLED
        services.clear_personal_data(batch)
        batch.save(update_fields=["status", "summary"])
        batch.purge_staging()
        messages.info(request, "Import zrušen, nic se neuložilo.")
    return redirect("import_list")
