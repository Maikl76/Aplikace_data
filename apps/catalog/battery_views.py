"""
Sporty a baterie testů – správa přímo v aplikaci, bez administrace.

Úpravy baterie jdou přes HTMX: server vrátí překreslenou kartu baterie
a ta se v stránce vymění. Žádný JavaScript navíc.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from apps.core.audit import record
from apps.core.models import AuditLog
from apps.subjects.models import Sport

from .models import BatteryItem, Protocol, TestBattery


def _batteries(user):
    return TestBattery.objects.filter(sport__in=Sport.objects.for_user(user))


def _card(request, battery):
    battery.available = list(Protocol.objects.filter(is_active=True).exclude(
        pk__in=battery.items.values("protocol")).order_by("name"))
    return render(request, "catalog/_battery.html", {"battery": battery})


@login_required
def sport_list(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if name:
            org = request.user.organization
            code = slugify(name)[:32] or "sport"
            sport, created = Sport.objects.get_or_create(
                organization=org, code=code, defaults={"name": name})
            if created:
                TestBattery.objects.create(organization=org, sport=sport)
                record(request, AuditLog.Action.CREATE, sport)
                messages.success(request, f"Sport „{name}“ založen i s prázdnou baterií testů.")
            else:
                messages.info(request, f"Sport „{sport.name}“ už existuje.")
        return redirect("sport_list")

    sports = (Sport.objects.for_user(request.user)
              .annotate(pocet_sportovcu=Count("subjects", distinct=True)).order_by("name"))
    batteries = (_batteries(request.user).select_related("sport")
                 .prefetch_related("items__protocol"))
    protocols = list(Protocol.objects.filter(is_active=True).order_by("name"))
    by_sport = {}
    for battery in batteries:
        used = {item.protocol_id for item in battery.items.all()}
        battery.available = [p for p in protocols if p.pk not in used]
        by_sport.setdefault(battery.sport_id, []).append(battery)
    for sport in sports:
        sport.baterie = by_sport.get(sport.pk, [])
        sport.ma_obecnou = any(not b.category for b in sport.baterie)
    return render(request, "catalog/sports.html", {"sports": sports})


@login_required
@require_POST
def battery_add(request, sport_pk):
    sport = get_object_or_404(Sport.objects.for_user(request.user), pk=sport_pk)
    category = request.POST.get("category", "").strip()
    if TestBattery.objects.filter(sport=sport, category__iexact=category).exists():
        messages.info(request, "Taková baterie už existuje.")
    else:
        TestBattery.objects.create(organization=sport.organization, sport=sport,
                                   category=category, name=request.POST.get("name", "").strip())
        messages.success(request, "Baterie založena – přidejte do ní testy.")
    return redirect("sport_list")


@login_required
@require_POST
def battery_delete(request, pk):
    battery = get_object_or_404(_batteries(request.user), pk=pk)
    label = battery.label
    battery.delete()
    messages.info(request, f"Baterie „{label}“ smazána. Naměřená data zůstala beze změny.")
    return redirect("sport_list")


@login_required
@require_POST
def battery_item_add(request, pk):
    battery = get_object_or_404(_batteries(request.user), pk=pk)
    protocol = get_object_or_404(Protocol, pk=request.POST.get("protocol"))
    last = battery.items.aggregate(m=Max("order"))["m"]
    BatteryItem.objects.get_or_create(battery=battery, protocol=protocol,
                                      defaults={"order": (last or 0) + 1})
    return _card(request, battery)


@login_required
@require_POST
def battery_item_remove(request, pk):
    item = get_object_or_404(BatteryItem.objects.filter(battery__in=_batteries(request.user)),
                             pk=pk)
    battery = item.battery
    item.delete()
    return _card(request, battery)


@login_required
@require_POST
def battery_item_move(request, pk, direction):
    item = get_object_or_404(BatteryItem.objects.filter(battery__in=_batteries(request.user)),
                             pk=pk)
    items = list(item.battery.items.all())
    index = items.index(item)
    target = index - 1 if direction == "nahoru" else index + 1
    if 0 <= target < len(items):
        items[index], items[target] = items[target], items[index]
        for order, it in enumerate(items, start=1):
            if it.order != order:
                it.order = order
                it.save(update_fields=["order"])
    return _card(request, item.battery)
