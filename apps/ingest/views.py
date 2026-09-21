from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.catalog.models import Protocol
from apps.core.audit import record
from apps.core.models import AuditLog

from . import services
from .adapters import registry
from .models import ImportBatch


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
    return render(request, "ingest/import_detail.html", {
        "batch": batch,
        "summary": batch.summary or {},
        "problems": staged.exclude(flag="ok")[:100],
        "sample": staged.filter(flag="ok")[:25],
        "dnes": timezone.localdate(),
        # Klíče souhrnu, které se nezobrazují jako dlaždice.
        "skryte_klice": ["nezname_metriky", "nezmapovane_sloupce",
                         "subject_attrs", "vysledek"],
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
