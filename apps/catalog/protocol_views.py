"""Testy (protokoly) – přehled, založení a úprava přímo v aplikaci."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.audit import record
from apps.core.models import AuditLog

from . import protocol_setup as setup
from .battery_views import _batteries
from .models import Direction, MetricDef, Protocol, TestFamily


@login_required
def test_list(request):
    protocols = (Protocol.objects.annotate(pocet_metrik=Count("protocol_metrics", distinct=True))
                 .prefetch_related("battery_items__battery__sport").order_by("-is_active", "name"))
    for p in protocols:
        p.baterie = sorted({item.battery.label for item in p.battery_items.all()})
    return render(request, "catalog/tests.html", {
        "protocols": protocols, "can_edit": setup.can_edit(request.user)})


def _form(request, protocol, *, data, rows, battery_ids):
    organization = request.user.organization
    metrics = [{"id": str(m.pk), "label": f"{m.name} [{m.unit}]" if m.unit else m.name,
                "family": m.get_family_display()}
               for m in setup.available_metrics(organization)]
    batteries = list(_batteries(request.user).select_related("sport").order_by("sport__name",
                                                                               "category"))
    return render(request, "catalog/test_form.html", {
        "protocol": protocol, "data": data, "rows": rows, "metrics": metrics,
        "batteries": batteries, "battery_ids": {str(b) for b in battery_ids},
        "families": TestFamily.choices, "directions": Direction.choices,
        "rules": MetricDef.TrialRule.choices, "sides": setup.SIDES, "modes": setup.MODES,
        "segments": setup.SEGMENTS,
    })


def _posted_data(post) -> dict:
    def whole(name, default, low, high):
        try:
            return max(low, min(high, int(post.get(name) or default)))
        except ValueError:
            return default

    rest = post.get("rest", "").strip()
    return {"name": post.get("name", ""), "family": post.get("family") or TestFamily.OTHER,
            "device": post.get("device", ""), "description": post.get("description", ""),
            "trials": whole("trials", 3, 1, 20),
            "rest": whole("rest", 0, 0, 3600) if rest else None,
            "rpe": bool(post.get("rpe")), "active": bool(post.get("active"))}


def _edit(request, protocol):
    if not setup.can_edit(request.user):
        messages.error(request, "Testy v katalogu nastavuje správce (role Správce).")
        return redirect("test_list")
    all_batteries = list(_batteries(request.user))
    if request.method == "POST":
        data = _posted_data(request.POST)
        if data["family"] not in TestFamily.values:
            data["family"] = TestFamily.OTHER
        chosen = set(request.POST.getlist("baterie"))
        try:
            rows = setup.read_rows(request.POST, request.user.organization)
            result = setup.save_test(
                protocol, data=data, rows=rows,
                batteries=[b for b in all_batteries if str(b.pk) in chosen],
                all_batteries=all_batteries, organization=request.user.organization)
        except setup.TestSetupError as exc:
            messages.error(request, str(exc))
            return _form(request, protocol, data=data, rows=setup.posted_rows(request.POST),
                         battery_ids=chosen)
        saved = result["protocol"]
        record(request, AuditLog.Action.CREATE if result["created"] else AuditLog.Action.UPDATE,
               saved, metrik=result["metrik"], novych_metrik=result["novych_metrik"])
        text = (f"Test „{saved.name}“ {'založen' if result['created'] else 'uložen'} "
                f"({result['metrik']} metrik")
        if result["novych_metrik"]:
            text += f", z toho {result['novych_metrik']} nových v katalogu"
        text += ")."
        if result["odebrano"]:
            text += " Odebrané metriky se už nebudou zadávat; naměřená data zůstala."
        messages.success(request, text)
        return redirect("test_list")

    if protocol is None:
        data = {"name": "", "family": TestFamily.FIELD, "device": "", "description": "",
                "trials": 3, "rest": None, "rpe": False, "active": True}
        rows = [setup._row_dict("0")]
        battery_ids = set()
        if battery := request.GET.get("baterie"):
            battery_ids = {battery}
    else:
        data = {"name": protocol.name, "family": protocol.family, "device": protocol.device,
                "description": protocol.description, "trials": protocol.default_trials,
                "rest": protocol.rest_seconds, "rpe": protocol.rpe_after,
                "active": protocol.is_active}
        rows = setup.rows_for(protocol)
        battery_ids = {b.battery_id for b in protocol.battery_items.all()}
    return _form(request, protocol, data=data, rows=rows, battery_ids=battery_ids)


@login_required
def test_new(request):
    return _edit(request, None)


@login_required
def test_edit(request, pk):
    return _edit(request, get_object_or_404(Protocol, pk=pk))
