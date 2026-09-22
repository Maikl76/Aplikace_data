from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.catalog.models import Protocol
from apps.core.audit import record
from apps.core.models import AuditLog

from . import services
from .adapters import registry
from .models import ImportBatch, StagedMeasurement


@login_required
def import_list(request):
    batches = (ImportBatch.objects.for_user(request.user)
               .select_related("raw_file", "uploaded_by")[:50])
    return render(request, "ingest/import_list.html", {
        "batches": batches,
        "adapters": sorted(registry.values(), key=lambda a: a.label),
        "protocols": Protocol.objects.filter(is_active=True),
    })


@login_required
def import_upload(request):
    """Nahrání souboru. Nic se neuloží – vznikne jen náhled ke kontrole."""
    if request.method != "POST" or "file" not in request.FILES:
        return redirect("import_list")

    # V ukázce se soubory nenahrávají. Je to jediné místo, kudy by se do
    # veřejně dostupné instance dostala reálná data, a stačilo by jedno
    # omylem přetažené xlsx.
    if settings.DEMO_MODE:
        messages.error(request, (
            "Toto je veřejná ukázka, nahrávání souborů je v ní vypnuté. "
            "Obrazovka kontroly importu je k vidění na již nahraném souboru."
        ))
        return redirect("import_list")

    protocol = None
    if protocol_id := request.POST.get("protocol"):
        protocol = Protocol.objects.filter(pk=protocol_id).first()

    try:
        batch = services.stage_file(
            uploaded_file=request.FILES["file"],
            user=request.user,
            organization=request.user.organization,
            adapter_code=request.POST.get("adapter", "legacy_excel"),
            protocol=protocol,
        )
    except services.ImportError_ as exc:
        messages.error(request, str(exc))
        return redirect("import_list")

    if batch.status == ImportBatch.Status.FAILED:
        messages.error(request, f"Soubor se nepodařilo zpracovat: {batch.error}")
        return redirect("import_list")

    return redirect("import_detail", pk=batch.pk)


@login_required
def import_detail(request, pk):
    """Náhled před uložením: co se našlo a na co se podívat."""
    batch = get_object_or_404(ImportBatch.objects.for_user(request.user), pk=pk)
    staged = batch.staged.select_related("metric", "protocol")
    summary = batch.summary or {}

    # Nový sportovec při prvním importu není problém, je to očekávaný stav.
    # Kdyby se míchal mezi skutečné problémy, utopil by je – u prvního
    # importu je tak označený každý řádek.
    problem_flags = [
        StagedMeasurement.Flag.OUT_OF_RANGE,
        StagedMeasurement.Flag.UNKNOWN_METRIC,
        StagedMeasurement.Flag.DUPLICATE,
    ]
    return render(request, "ingest/import_detail.html", {
        "batch": batch,
        "summary": summary,
        "dlazdice": [
            ("hodnot", summary.get("hodnot")),
            ("sportovců", summary.get("sportovcu")),
            ("z toho nových", summary.get("novych_sportovcu")),
            ("metrik", summary.get("metrik")),
            ("protokolů", summary.get("protokolu")),
            ("mimo rozsah", summary.get("mimo_rozsah")),
        ],
        "datum_od": summary.get("datum_od"),
        "datum_do": summary.get("datum_do"),
        "bez_data": summary.get("novych_hodnot_bez_data") or 0,
        "problems": staged.filter(flag__in=problem_flags)[:100],
        "sample": staged.exclude(flag__in=problem_flags)[:25],
        "dnes": timezone.localdate(),
    })


@login_required
def import_commit(request, pk):
    batch = get_object_or_404(ImportBatch.objects.for_user(request.user), pk=pk)
    if request.method != "POST":
        return redirect("import_detail", pk=pk)

    default_date = request.POST.get("default_date") or None
    try:
        result = services.commit_batch(
            batch, user=request.user, default_date=default_date,
            skip_out_of_range=bool(request.POST.get("skip_out_of_range")),
        )
    except services.ImportError_ as exc:
        messages.error(request, str(exc))
        return redirect("import_detail", pk=pk)

    record(request, AuditLog.Action.CREATE, batch, **result)
    messages.success(request, (
        f"Uloženo {result['hodnoty']} hodnot, {result['session']} testovacích dnů, "
        f"{result['sportovci']} nových sportovců."
    ))
    return redirect("import_list")


@login_required
def import_cancel(request, pk):
    batch = get_object_or_404(ImportBatch.objects.for_user(request.user), pk=pk)
    if request.method == "POST":
        batch.status = ImportBatch.Status.CANCELLED
        batch.save(update_fields=["status"])
        batch.purge_staging()
        messages.info(request, "Import zrušen, nic se neuložilo.")
    return redirect("import_list")
