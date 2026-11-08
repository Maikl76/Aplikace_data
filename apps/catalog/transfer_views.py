"""
Nastavení → Přenos nastavení: balíček se vším, co se v aplikaci nastavuje,
ke stažení a k nahrání z jiné instance – s náhledem, co se změní, než se
něco zapíše. Jen správce.
"""

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify

from apps.core.audit import record
from apps.core.models import AuditLog

from . import transfer
from .models import SettingsTransfer

MAX_SIZE = 25 * 1024 * 1024   # balíček je JSON bez souborů; větší je omyl
STALE_DAYS = 7                 # nenačtený náhled se po týdnu zahodí


def _forget_stale(organization):
    limit = timezone.now() - timezone.timedelta(days=STALE_DAYS)
    for item in SettingsTransfer.objects.filter(organization=organization, applied_at__isnull=True,
                                                direction=SettingsTransfer.Direction.IN,
                                                created_at__lt=limit):
        item.file.delete(save=False)
        item.delete()


@login_required
def transfer_settings(request):
    org = request.user.organization
    if org is None:
        messages.error(request, "Účet nemá pracoviště – přiřadí ho superuživatel v administraci.")
        return redirect("workplace")
    _forget_stale(org)
    if request.method == "POST":
        if request.POST.get("akce") == "stahnout":
            return _download(request, org)
        if uploaded := request.FILES.get("balicek"):
            return _upload(request, org, uploaded)
        return redirect("transfer_settings")

    history = list(SettingsTransfer.objects.filter(organization=org).select_related("user")[:12])
    return render(request, "catalog/transfer.html", {
        "instance": transfer.instance_label(),
        "inventory": transfer.inventory(),
        "history": history,
        "pending": [h for h in history if h.pending],
    })


def _download(request, org):
    data = transfer.export_catalog()
    content = json.dumps(data, ensure_ascii=False, indent=1, default=str)
    name = f"nastaveni-{slugify(org.short_name) or 'ftvs'}-{timezone.localdate():%Y-%m-%d}.json"
    SettingsTransfer.objects.create(
        organization=org, direction=SettingsTransfer.Direction.OUT, user=request.user,
        original_name=name, source=transfer.instance_label(),
        counts={"polozky": transfer.describe(data)["polozky"]})
    record(request, AuditLog.Action.EXPORT, org, prenos="nastaveni", soubor=name)
    response = HttpResponse(content, content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


def _upload(request, org, uploaded):
    if uploaded.size > MAX_SIZE:
        messages.error(request, "Soubor je příliš velký na balíček nastavení.")
        return redirect("transfer_settings")
    raw = uploaded.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        messages.error(request, f"„{uploaded.name}“ není balíček nastavení – čekám soubor JSON "
                                "stažený tlačítkem Stáhnout balíček v jiné instanci.")
        return redirect("transfer_settings")
    if not isinstance(data, dict) or data.get("format") != transfer.FORMAT_VERSION:
        messages.error(request, f"„{uploaded.name}“ není balíček nastavení této aplikace "
                                f"(formát {data.get('format') if isinstance(data, dict) else '?'}).")
        return redirect("transfer_settings")

    info = transfer.describe(data)
    item = SettingsTransfer(organization=org, direction=SettingsTransfer.Direction.IN,
                            user=request.user, original_name=uploaded.name[:255],
                            source=info["instance"][:200], source_created=info["vytvoreno"][:40])
    item.file.save(f"{timezone.now():%Y%m%d-%H%M%S}.json", ContentFile(raw), save=False)
    try:
        item.counts = {"polozky": info["polozky"],
                       "nahled": transfer.preview_catalog(data, default_org=org)}
    except transfer.ImportError_ as exc:
        item.counts = {"polozky": info["polozky"]}
        item.error = str(exc)
    item.save()
    return redirect("transfer_preview", pk=item.pk)


@login_required
def transfer_preview(request, pk):
    org = request.user.organization
    item = get_object_or_404(SettingsTransfer, organization=org, pk=pk,
                             direction=SettingsTransfer.Direction.IN)
    if request.method == "POST":
        action = request.POST.get("akce", "")
        if action == "zrusit":
            item.file.delete(save=False)
            item.delete()
            messages.info(request, "Balíček zahozen, nic se nezměnilo.")
            return redirect("transfer_settings")
        if action == "nacist" and item.pending:
            return _apply(request, org, item)
        return redirect("transfer_preview", pk=pk)

    counts = item.counts.get("vysledek") or item.counts.get("nahled") or {}
    rows = sorted(((label, entry) for label, entry in counts.items()
                   if any(entry.values())), key=lambda r: r[0])
    return render(request, "catalog/transfer_preview.html", {
        "item": item, "rows": rows, "totals": transfer.totals(counts),
        "polozky": item.counts.get("polozky") or {},
        "nasucho": item.applied_at is None,
    })


def _apply(request, org, item):
    with item.file.open("rb") as f:
        data = json.loads(f.read().decode("utf-8"))
    try:
        counts = transfer.import_catalog(data, default_org=org)
    except transfer.ImportError_ as exc:
        item.error = str(exc)
        item.save(update_fields=["error", "updated_at"])
        messages.error(request, f"Balíček se nenačetl: {exc}")
        return redirect("transfer_preview", pk=item.pk)
    item.counts = {**item.counts, "vysledek": counts}
    item.applied_at = timezone.now()
    item.file.delete(save=False)
    item.file = ""
    item.save()
    total = transfer.totals(counts)
    record(request, AuditLog.Action.UPDATE, item, prenos="nastaveni", zdroj=item.source, **total)
    messages.success(request, f"Nastavení načteno z balíčku „{item.original_name}“: "
                              f"{total['nove']} nových a {total['zmenene']} změněných položek, "
                              f"{total['beze_zmeny']} beze změny.")
    return redirect("transfer_settings")
