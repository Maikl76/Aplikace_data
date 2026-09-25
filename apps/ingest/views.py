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
    """
    Nahrání jednoho nebo víc souborů. Nic se neuloží – vznikne jen náhled
    ke kontrole (u víc souborů jeden náhled na soubor).
    """
    files = request.FILES.getlist("file")
    if request.method != "POST" or not files:
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

    if len(ready) == 1:
        return redirect("import_detail", pk=ready[0].pk)
    if ready:
        messages.info(request, f"Načteno {len(ready)} souborů. Zkontrolujte a uložte "
                               f"každý zvlášť (odkaz „zkontrolovat“ v historii).")
    return redirect("import_list")


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
    sportovci = sorted((summary.get("subjects") or {}).values(),
                       key=lambda s: (s.get("kod") is not None, s.get("hint", "")))
    return render(request, "ingest/import_detail.html", {
        "batch": batch,
        "summary": summary,
        "dlazdice": [
            ("sportovců", summary.get("sportovcu")),
            ("z toho nových", summary.get("novych_sportovcu")),
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
    text = (f"Uloženo {result['hodnoty']} hodnot, {result.get('testy', 0)} testů, "
            f"{result['session']} nových testovacích dnů, {result['sportovci']} nových sportovců.")
    if result.get("aktualizovano"):
        text += f" Aktualizováno {result['aktualizovano']} hodnot, které VALD přepočítal."
    messages.success(request, text)
    if result.get("jmena_neulozena"):
        messages.warning(request, (
            f"Jména {result['jmena_neulozena']} nových sportovců se neuložila – chybí "
            f"šifrovací klíč. Spusťte aplikaci přes spustit.bat, klíč se doplní sám; "
            f"jména pak doplníte v administraci (Identity sportovců)."))
    return redirect("import_list")


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
