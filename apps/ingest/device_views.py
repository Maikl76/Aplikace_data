"""
Průvodce „Nový přístroj“ – přidání exportu z dalšího přístroje bez programování.

1. ukázkový soubor, název a test,
2. kdo a kdy (sloupec se jménem a datem),
3. které sloupce jsou které metriky,
4. uložit – od té chvíle Import soubory z přístroje pozná sám.

Ukázkové řádky (jsou v nich jména) se drží jen v session pro náhled
a po uložení se zahodí. Přístroj si pamatuje jen názvy sloupců.
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.catalog.models import DeviceFormat, Direction, ImportProfile, Protocol
from apps.core.audit import record
from apps.core.models import AuditLog

from . import device_setup as setup

IDENTITY_LABELS = [
    ("name_column", "Jméno a příjmení", "v jednom sloupci"),
    ("first_name_column", "Křestní jméno", "když je zvlášť"),
    ("last_name_column", "Příjmení", "když je zvlášť"),
    ("id_column", "ID člověka v přístroji", "nepovinné – páruje spolehlivěji než jméno"),
    ("date_column", "Datum měření", "povinné"),
    ("time_column", "Čas měření", "nepovinné"),
    ("birth_column", "Datum narození", "nepovinné – pomůže rozlišit stejná jména"),
    ("sex_column", "Pohlaví", "nepovinné"),
]
SEGMENTS = ["paze", "noha", "trup", "hlava"]


def can_edit(user) -> bool:
    """Přístroje nastavuje správce – role Správce nebo oprávnění ke katalogu."""
    from apps.core.models import Role

    return getattr(user, "role", "") == Role.ADMIN or user.has_perm("catalog.change_importprofile")


def _devices(user):
    return DeviceFormat.objects.filter(
        Q(organization=user.organization) | Q(organization__isnull=True))


def _session_key(device) -> str:
    return f"pristroj_vzorek_{device.pk}"


def _denied(request):
    messages.error(request, "Přístroje nastavuje správce (role Správce).")
    return redirect("import_list")


@login_required
def device_new(request):
    if not can_edit(request.user):
        return _denied(request)
    protocols = Protocol.objects.filter(is_active=True).order_by("name")
    form = {"name": request.POST.get("name", "").strip(),
            "protocol": request.POST.get("protocol", "")}
    if request.method == "POST":
        upload = request.FILES.get("file")
        protocol = protocols.filter(pk=form["protocol"]).first()
        error = None
        if settings.DEMO_MODE:
            error = "V ukázce se soubory nenahrávají. Prohlédněte si ukázkový přístroj DEXA."
        elif not form["name"]:
            error = "Napište název přístroje."
        elif protocol is None:
            error = "Vyberte, který test přístroj měří."
        elif upload is None:
            error = "Vyberte ukázkový soubor z přístroje."
        else:
            try:
                sample = setup.read_sample(upload)
            except Exception as exc:  # poškozený soubor, jiný formát…
                error = f"Soubor se nepodařilo přečíst: {exc}"
        if error:
            messages.error(request, error)
        else:
            device = setup.create_device(name=form["name"], protocol=protocol,
                                         organization=request.user.organization, sample=sample)
            request.session[_session_key(device)] = sample.rows
            record(request, AuditLog.Action.CREATE, device)
            return redirect("device_edit", pk=device.pk)
    return render(request, "ingest/device_new.html", {"protocols": protocols, "form": form})


def _metric_label(metric) -> str:
    return f"{metric.name} [{metric.unit}]" if metric.unit else metric.name


@login_required
def device_edit(request, pk):
    if not can_edit(request.user):
        return _denied(request)
    device = get_object_or_404(_devices(request.user), pk=pk)
    header = list(device.columns_seen)
    rows = request.session.get(_session_key(device)) or []
    protocol_metrics, other_metrics = setup.metric_choices(device.protocol,
                                                           request.user.organization)
    metrics = {m.pk: m for m in protocol_metrics + other_metrics}

    if request.method == "POST":
        identity = {f: request.POST.get(f, "") for f, _, _ in IDENTITY_LABELS
                    if request.POST.get(f, "") in header}
        mappings, errors = _read_mappings(request.POST, header, identity, metrics)
        errors = _check_identity(identity) + errors
        if not errors and not mappings:
            errors.append("Přiřaďte aspoň jeden sloupec k metrice (krok 3).")
        if not errors:
            result = setup.save_device(device, identity=identity, mappings=mappings,
                                       organization=request.user.organization)
            request.session.pop(_session_key(device), None)
            record(request, AuditLog.Action.UPDATE, device, **result)
            text = f"Přístroj „{device.name}“ je připravený – importuje {result['sloupcu']} sloupců"
            if result["novych_metrik"]:
                text += f", nových metrik v katalogu: {result['novych_metrik']}"
            messages.success(request, text + ". Soubory z něj teď stačí nahrát tady v Importu, "
                                             "aplikace je pozná sama.")
            return redirect("import_list")
        for error in errors:
            messages.error(request, error)
        current_identity = identity
        current = _posted_columns(request.POST, header)
    else:
        current_identity = {f: getattr(device, f) for f, _, _ in IDENTITY_LABELS}
        current = _saved_columns(device, header, list(metrics.values()))

    columns = []
    for i, name in enumerate(header):
        if not name:
            continue
        samples = [r[i] for r in rows if i < len(r) and r[i]]
        numeric = any(setup.is_number(v) for v in samples)
        columns.append({"i": i, "name": name, "samples": samples, "numeric": numeric or not rows,
                        "unit": setup.column_unit(name),
                        "bare": setup.UNIT_RE.sub("", name).strip(),
                        **current.get(i, {})})
    return render(request, "ingest/device_edit.html", {
        "device": device,
        "identity_fields": [(f, label, hint, current_identity.get(f, ""))
                            for f, label, hint in IDENTITY_LABELS],
        "header": [h for h in header if h],
        "first_row": dict(zip(header, rows[0], strict=False)) if rows else {},
        "columns": columns,
        "protocol_metrics": [(m.pk, _metric_label(m)) for m in protocol_metrics],
        "other_metrics": [(m.pk, _metric_label(m)) for m in other_metrics],
        "directions": Direction.choices,
        "segments": SEGMENTS,
        "has_sample": bool(rows),
        "demo_mode": settings.DEMO_MODE,
    })


def _check_identity(identity: dict) -> list[str]:
    errors = []
    if not identity.get("date_column"):
        errors.append("Vyberte sloupec s datem měření (krok 2).")
    has_name = identity.get("name_column") or (identity.get("first_name_column")
                                               and identity.get("last_name_column"))
    if not has_name and not identity.get("id_column"):
        errors.append("Vyberte sloupec se jménem (nebo s ID člověka v přístroji) – "
                      "podle něj se pozná, komu měření patří (krok 2).")
    if bool(identity.get("first_name_column")) != bool(identity.get("last_name_column")):
        errors.append("Křestní jméno a příjmení vyberte obě, nebo použijte „Jméno a příjmení“.")
    return errors


def _read_mappings(post, header, identity, metrics) -> tuple[list, list[str]]:
    used = set(identity.values())
    mappings, errors = [], []
    for i, column in enumerate(header):
        if not column or column in used:
            continue
        choice = post.get(f"c{i}_metric", "")
        if not choice:
            continue
        item = setup.Mapping(column=column, side=post.get(f"c{i}_side", ""),
                             segment=post.get(f"c{i}_segment", ""),
                             factor=setup.parse_factor(post.get(f"c{i}_factor")))
        if item.side not in ("", "B", "L", "R"):
            item.side = ""
        if choice == "nova":
            item.new_name = post.get(f"c{i}_new_name", "").strip()
            item.new_unit = post.get(f"c{i}_new_unit", "").strip()
            item.new_direction = post.get(f"c{i}_new_dir") or Direction.NEUTRAL
            if item.new_direction not in Direction.values:
                item.new_direction = Direction.NEUTRAL
            if not item.new_name:
                errors.append(f"Sloupec „{column}“: napište název nové metriky.")
                continue
        else:
            item.metric = metrics.get(int(choice)) if choice.isdigit() else None
            if item.metric is None:
                continue
        mappings.append(item)
    return mappings, errors


def _posted_columns(post, header) -> dict:
    return {i: {"metric": post.get(f"c{i}_metric", ""), "side": post.get(f"c{i}_side", ""),
                "segment": post.get(f"c{i}_segment", ""),
                "factor": post.get(f"c{i}_factor", "1"),
                "new_name": post.get(f"c{i}_new_name", ""),
                "new_unit": post.get(f"c{i}_new_unit", ""),
                "new_dir": post.get(f"c{i}_new_dir", "")}
            for i in range(len(header))}


def _saved_columns(device, header, metrics) -> dict:
    """Uložené přiřazení; u nedokončeného přístroje návrhy z názvů sloupců."""
    profile = device.profile()
    out = {}
    if profile and device.is_active:
        saved = {c.column: c for c in profile.columns.all()}
        for i, column in enumerate(header):
            if c := saved.get(column):
                out[i] = {"metric": str(c.metric_id), "side": c.side, "segment": c.segment,
                          "factor": _factor_text(c.factor)}
        return out
    suggestions = setup.suggest_columns(header, device.protocol, metrics,
                                        skip=device.identity_columns)
    for i, column in enumerate(header):
        if (s := suggestions.get(column)) and s.metric:
            out[i] = {"metric": str(s.metric.pk), "side": s.side, "segment": s.segment,
                      "factor": _factor_text(s.factor), "navrh": True}
        elif s:
            out[i] = {"side": s.side, "segment": s.segment}
    return out


def _factor_text(value: float) -> str:
    return f"{value:g}".replace(".", ",")


@login_required
@require_POST
def device_sample(request, pk):
    """Nový ukázkový soubor – výrobce přidal nebo přejmenoval sloupce."""
    if not can_edit(request.user):
        return _denied(request)
    device = get_object_or_404(_devices(request.user), pk=pk)
    upload = request.FILES.get("file")
    if settings.DEMO_MODE or upload is None:
        messages.error(request, "V ukázce se soubory nenahrávají." if settings.DEMO_MODE
                       else "Vyberte soubor.")
        return redirect("device_edit", pk=pk)
    try:
        sample = setup.read_sample(upload)
    except Exception as exc:
        messages.error(request, f"Soubor se nepodařilo přečíst: {exc}")
        return redirect("device_edit", pk=pk)
    gone = setup.update_sample(device, sample)
    request.session[_session_key(device)] = sample.rows
    if gone:
        messages.warning(request, "V novém souboru už nejsou sloupce: "
                         + ", ".join(f"„{c}“" for c in gone)
                         + ". Pokud je výrobce přejmenoval, přiřaďte nové názvy níže a uložte.")
    else:
        messages.info(request, "Ukázkový soubor načten. Zkontrolujte přiřazení a uložte.")
    return redirect("device_edit", pk=pk)


@login_required
@require_POST
def device_delete(request, pk):
    if not can_edit(request.user):
        return _denied(request)
    device = get_object_or_404(_devices(request.user), pk=pk)
    ImportProfile.objects.filter(device=device.adapter_code).delete()
    request.session.pop(_session_key(device), None)
    record(request, AuditLog.Action.DELETE, device)
    name = device.name
    device.delete()
    messages.info(request, f"Přístroj „{name}“ smazán. Data, která se z něj už importovala, zůstala.")
    return redirect("import_list")


def device_cards(user) -> list:
    """Přístroje pro stránku Import: vestavěné i přidané průvodcem."""
    return list(_devices(user).select_related("protocol"))

