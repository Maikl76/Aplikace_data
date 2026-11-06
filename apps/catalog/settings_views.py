"""
Nastavení testování mimo testy samotné: MDC u ukazatelů (se zdrojem hodnoty)
a profily importu vestavěných přístrojů (které sloupce exportu jsou které
ukazatele). Obojí bývalo jen v administraci; tady má jeden formulář
a nápovědu, co a proč.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect, render

from apps.core.audit import record
from apps.core.models import AuditLog

from . import protocol_setup as setup
from .models import DeviceFormat, ImportColumn, ImportProfile, MetricDef, Protocol
from .steps import catalog_status, catalog_steps

BLANK_ROWS = 2


def _number(text):
    """„1,5“ i „1.5“ → 1.5; prázdné → None; nesmysl → ValueError."""
    text = (text or "").strip().replace(",", ".").replace(" ", "")
    return float(text) if text else None


def _denied(request, reason):
    return render(request, "core/odepreno.html", {"duvod": reason}, status=403)


def _shared(user):
    return Q(organization__isnull=True) | Q(organization=user.organization)


# --- MDC u ukazatelů ------------------------------------------------------------------

def _metric_rows(user):
    """Ukazatele testů v bateriích (klíčové první) a ostatní ukazatele katalogu."""
    status = catalog_status(user)
    rows = {}
    for protocol in sorted(status["protocols"].values(), key=lambda p: p.name):
        for pm in protocol.protocol_metrics.all():
            row = rows.setdefault(pm.metric.pk, {"metric": pm.metric, "tests": [], "key": False})
            row["tests"].append(protocol.name)
            row["key"] = row["key"] or pm.is_primary
    in_batteries = sorted(rows.values(), key=lambda r: (not r["key"], r["metric"].name))
    others = [{"metric": m, "tests": [], "key": False}
              for m in MetricDef.objects.filter(_shared(user), is_active=True).order_by("name")
              if m.pk not in rows]
    return status, in_batteries, others


@login_required
def mdc_settings(request):
    """MDC a SWC ke každému ukazateli, vždy se zdrojem hodnoty."""
    can_edit = setup.can_edit(request.user)
    status, in_batteries, others = _metric_rows(request.user)
    if request.method == "POST":
        if not can_edit:
            return _denied(request, "MDC u ukazatelů doplňuje správce.")
        problems, changed = [], 0
        with transaction.atomic():
            for row in in_batteries + others:
                m = row["metric"]
                try:
                    mdc = _number(request.POST.get(f"mdc_{m.pk}"))
                    swc = _number(request.POST.get(f"swc_{m.pk}"))
                except ValueError:
                    problems.append(f"{m.name}: MDC a SWC musí být číslo – neuloženo.")
                    continue
                source = request.POST.get(f"zdroj_{m.pk}", "").strip()[:300]
                if mdc is not None and not source:
                    problems.append(f"{m.name}: k hodnotě MDC doplňte zdroj – neuloženo.")
                    continue
                if (m.mdc, m.swc, m.mdc_source) != (mdc, swc, source):
                    m.mdc, m.swc, m.mdc_source = mdc, swc, source
                    m.save(update_fields=["mdc", "swc", "mdc_source", "updated_at"])
                    changed += 1
        record(request, AuditLog.Action.UPDATE, request.user.organization or request.user,
               nastaveni="mdc", zmeneno=changed)
        for problem in problems:
            messages.warning(request, problem)
        messages.success(request, f"Uloženo: {changed} ukazatelů změněno." if changed
                         else "Uloženo, beze změn.")
        return redirect("mdc_settings")
    return render(request, "catalog/mdc.html", {
        "rows": in_batteries, "others": others, "can_edit": can_edit,
        "steps": catalog_steps(request.user, status),
        "key_total": len(status["key_metrics"]), "key_missing": len(status["no_mdc"]),
    })


# --- profily importu vestavěných přístrojů ---------------------------------------------

def _builtin_profiles(user):
    return (ImportProfile.objects.filter(_shared(user))
            .exclude(device__startswith=DeviceFormat.PREFIX)
            .select_related("protocol").prefetch_related("columns__metric", "protocol__protocol_metrics")
            .order_by("device", "test_type"))


def _factor(text) -> float:
    value = _number(text)
    if value is None:
        return 1.0
    if value == 0:
        raise ValueError("násobek nesmí být nula")
    return value


def _save_profiles(post, profiles, protocols, metrics, user) -> list[str]:
    problems = []
    protocol_by_pk = {str(p.pk): p for p in protocols}
    metric_by_pk = {str(m.pk): m for m in metrics}
    with transaction.atomic():
        for profile in profiles:
            protocol = protocol_by_pk.get(post.get(f"p{profile.pk}_protocol", ""))
            if protocol is not None:
                profile.protocol = protocol
            profile.is_active = f"p{profile.pk}_active" in post
            profile.save()
            seen = set()
            for column in list(profile.columns.all()):
                name = post.get(f"c{column.pk}_column", column.column).strip()[:200]
                if f"c{column.pk}_delete" in post or not name:
                    column.delete()
                    continue
                metric = metric_by_pk.get(post.get(f"c{column.pk}_metric", ""))
                if metric is None:
                    problems.append(f"{profile}: sloupec „{name}“ nemá ukazatel – neuloženo.")
                    continue
                if name in seen:
                    problems.append(f"{profile}: sloupec „{name}“ je uvedený dvakrát – neuloženo.")
                    continue
                try:
                    factor = _factor(post.get(f"c{column.pk}_factor"))
                except ValueError:
                    problems.append(f"{profile}: sloupec „{name}“ má špatný násobek – neuloženo.")
                    continue
                seen.add(name)
                column.column, column.metric, column.factor = name, metric, factor
                column.with_sides = f"c{column.pk}_sides" in post
                column.save()
            for i in range(BLANK_ROWS):
                name = post.get(f"n{profile.pk}_{i}_column", "").strip()[:200]
                if not name:
                    continue
                metric = metric_by_pk.get(post.get(f"n{profile.pk}_{i}_metric", ""))
                if metric is None:
                    problems.append(f"{profile}: nový sloupec „{name}“ nemá ukazatel – neuloženo.")
                    continue
                if name in seen or profile.columns.filter(column=name).exists():
                    problems.append(f"{profile}: sloupec „{name}“ už v profilu je – neuloženo.")
                    continue
                try:
                    factor = _factor(post.get(f"n{profile.pk}_{i}_factor"))
                except ValueError:
                    problems.append(f"{profile}: nový sloupec „{name}“ má špatný násobek – neuloženo.")
                    continue
                seen.add(name)
                ImportColumn.objects.create(profile=profile, column=name, metric=metric,
                                            factor=factor,
                                            with_sides=f"n{profile.pk}_{i}_sides" in post)
        device = post.get("np_device", "")
        test_type = post.get("np_test_type", "").strip()[:120]
        protocol = protocol_by_pk.get(post.get("np_protocol", ""))
        if test_type or protocol is not None:
            if device not in ImportProfile.Device.values:
                problems.append("Nový profil: vyberte přístroj.")
            elif not test_type:
                problems.append("Nový profil: napište typ testu přesně tak, jak ho píše export.")
            elif protocol is None:
                problems.append("Nový profil: vyberte test z katalogu.")
            elif ImportProfile.objects.filter(device=device, test_type=test_type).exists():
                problems.append(f"Nový profil: typ testu „{test_type}“ už profil má.")
            else:
                ImportProfile.objects.create(organization=user.organization, device=device,
                                             test_type=test_type, protocol=protocol)
    return problems


@login_required
def import_profiles(request):
    """Které sloupce exportu VALD jsou které ukazatele – a který typ testu je který test."""
    from apps.ingest.device_views import can_edit

    allowed = can_edit(request.user)
    profiles = list(_builtin_profiles(request.user))
    protocols = list(Protocol.objects.filter(_shared(request.user), is_active=True).order_by("name"))
    metrics = list(MetricDef.objects.filter(_shared(request.user), is_active=True)
                   .order_by("family", "name"))
    if request.method == "POST":
        if not allowed:
            return _denied(request, "Profily importu nastavuje správce.")
        problems = _save_profiles(request.POST, profiles, protocols, metrics, request.user)
        record(request, AuditLog.Action.UPDATE, request.user.organization or request.user,
               nastaveni="profily_importu")
        for problem in problems:
            messages.warning(request, problem)
        messages.success(request, "Profily importu jsou uložené.")
        return redirect("import_profiles")
    labels = dict(ImportProfile.Device.choices)
    groups = []
    for profile in profiles:
        own = {pm.metric_id for pm in profile.protocol.protocol_metrics.all()}
        profile.rows = list(profile.columns.all())
        profile.blank = range(BLANK_ROWS)
        profile.metric_groups = [
            (f"Ukazatele testu {profile.protocol.name}", [m for m in metrics if m.pk in own]),
            ("Další ukazatele z katalogu", [m for m in metrics if m.pk not in own]),
        ]
        if not groups or groups[-1]["code"] != profile.device:
            groups.append({"code": profile.device, "label": labels.get(profile.device, profile.device),
                           "profiles": []})
        groups[-1]["profiles"].append(profile)
    return render(request, "catalog/import_profiles.html", {
        "groups": groups, "protocols": protocols, "metrics": metrics, "can_edit": allowed,
        "devices": ImportProfile.Device.choices,
    })
