"""
Sporty a baterie testů – správa přímo v aplikaci, bez administrace.

Úpravy baterie jdou přes HTMX: server vrátí překreslenou kartu baterie
a ta se v stránce vymění. Žádný JavaScript navíc.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Max
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from apps.core import access
from apps.core.audit import record
from apps.core.models import AuditLog, default_organization
from apps.subjects.models import Sport

from .models import BatteryItem, Protocol, TestBattery


def _batteries(user):
    return TestBattery.objects.filter(sport__in=Sport.objects.for_user(user))


def _catalog_protocols(user):
    """Testy, které jde dát do baterie: sdílené z katalogu a vlastní pracoviště, ne cizí."""
    from django.db.models import Q

    scope = Q(organization__isnull=True)
    if user.organization_id:
        scope |= Q(organization_id=user.organization_id)
    return Protocol.objects.filter(scope)


def _card(request, battery):
    battery.available = list(_catalog_protocols(request.user).filter(is_active=True).exclude(
        pk__in=battery.items.values("protocol")).order_by("name"))
    return render(request, "catalog/_battery.html", {"battery": battery})


@login_required
def sport_list(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        org = request.user.organization or default_organization()
        if name and not access.may_add_sport(request.user):
            messages.error(request, "Nový sport zakládá správce nebo účet se všemi sporty – "
                                    "sám byste ho ve svém rozsahu neviděl.")
            return redirect("sport_list")
        if name and org is None:
            messages.error(request, "Účet nemá přiřazené pracoviště – v administraci "
                                    "u uživatele vyberte organizaci.")
        elif name:
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
    protocols = list(_catalog_protocols(request.user).filter(is_active=True).order_by("name"))
    by_sport = {}
    for battery in batteries:
        used = {item.protocol_id for item in battery.items.all()}
        battery.available = [p for p in protocols if p.pk not in used]
        by_sport.setdefault(battery.sport_id, []).append(battery)
    responsible = access.Responsibility(request.user.organization)
    for sport in sports:
        sport.baterie = by_sport.get(sport.pk, [])
        sport.ma_obecnou = any(not b.category for b in sport.baterie)
        sport.metodici = ", ".join(responsible.for_sport(sport.pk))
    from apps.analytics.compare import MONTHS_LOCATIVE

    from .steps import catalog_steps

    return render(request, "catalog/sports.html", {
        "sports": sports, "steps": catalog_steps(request.user),
        "months": list(enumerate(MONTHS_LOCATIVE, start=1)),
        "may_add_sport": access.may_add_sport(request.user)})


@login_required
@require_POST
def sport_season(request, sport_pk):
    """Měsíc začátku sezóny – od něj se srovnává „od začátku sezóny“."""
    from apps.analytics.compare import season_phrase

    sport = get_object_or_404(Sport.objects.for_user(request.user), pk=sport_pk)
    raw = request.POST.get("mesic", "").strip()
    try:
        month = int(raw) if raw else None
        if month is not None and not 1 <= month <= 12:
            raise ValueError
    except ValueError:
        messages.error(request, "Měsíc začátku sezóny vyberte ze seznamu.")
        return redirect("sport_list")
    sport.season_start_month = month
    sport.save(update_fields=["season_start_month", "updated_at"])
    record(request, AuditLog.Action.UPDATE, sport, sezona_od=month)
    messages.success(request, f"{sport.name}: sezóna začíná {season_phrase(sport, case='v')}.")
    return redirect("sport_list")


def _count(n: int, one: str, few: str, many: str) -> str:
    from apps.reports.narrative import plural

    return f"{n} {plural(n, one, few, many)}"


def sport_delete_plan(sport) -> dict:
    """
    Co smazání sportu znamená. ``blockers`` – proč teď nejde (sportovci, nálezy
    ve zprávách z jeho pravidel); ``removed`` – co zmizí s ním; ``warnings`` –
    účty, které by pak neviděly nikoho.
    """
    from apps.core.models import Access
    from apps.evidence.models import Article
    from apps.measurements.models import TestSession
    from apps.rules.models import Finding, Rule
    from apps.subjects.models import Subject

    from .models import Norm

    blockers, removed, warnings = [], [], []
    subjects = Subject.objects.filter(sport=sport)
    if total := subjects.count():
        inactive = subjects.filter(is_active=False).count()
        blockers.append({
            "text": (f"Sport má {_count(total, 'sportovce', 'sportovce', 'sportovců')}"
                     + (f" (z toho {_count(inactive, 'neaktivní', 'neaktivní', 'neaktivních')})"
                        if inactive else "")
                     + ". Převeďte je do jiného sportu v údajích sportovce, nebo sport "
                       "nechte – sportovce ani jejich měření smazání sportu nesmaže."),
            "url": reverse("subject_list") + f"?sport={sport.pk}", "link": "Sportovci sportu"})
    if foreign := Subject.objects.filter(team__sport=sport).exclude(sport=sport).count():
        blockers.append({"text": f"V týmech tohoto sportu je {foreign} sportovců jiného sportu "
                                 "– nejdřív jim tým změňte.", "url": "", "link": ""})
    if Finding.objects.filter(rule__applies_to_sport=sport).exists():
        blockers.append({"text": "Pravidla tohoto sportu už vytvořila nálezy ve zprávách a ty "
                                 "musí zůstat dohledatelné. Pravidla můžete místo toho vypnout.",
                         "url": reverse("rules_settings"), "link": "Pravidla"})

    batteries = list(sport.batteries.all())
    if batteries:
        removed.append(f"baterie testů: {', '.join(b.label for b in batteries)} – testy "
                       "samotné v katalogu zůstanou")
    teams = list(sport.teams.all())
    if teams:
        removed.append(f"týmy: {', '.join(t.name for t in teams)}")
    if norms := Norm.objects.filter(sport=sport).count():
        removed.append(f"normy jen pro tento sport: {norms}")
    if rules := Rule.objects.filter(applies_to_sport=sport).count():
        removed.append(f"pravidla jen pro tento sport: {rules}")
    if articles := Article.objects.filter(sports=sport).count():
        removed.append(f"sport z populace studie u článků: {articles} (články zůstanou)")
    accesses = list(Access.objects.filter(sports=sport).select_related("user")
                    .prefetch_related("sports"))
    if accesses:
        removed.append("sport z rozsahu dat účtů: "
                       + ", ".join(_user_name(a.user) for a in accesses))
        alone = [a for a in accesses if not a.all_sports and len(a.sports.all()) == 1]
        if alone:
            warnings.append({
                "text": (f"{', '.join(_user_name(a.user) for a in alone)} "
                         + ("má" if len(alone) == 1 else "mají")
                         + " v rozsahu dat jen tento sport – po smazání neuvidí žádného "
                           "sportovce. Přístup upravte v Kolegové."),
                "url": reverse("colleagues"), "link": "Kolegové"})
    if sessions := TestSession.objects.filter(battery__sport=sport).count():
        removed.append(f"odkaz na baterii u testovacích dnů jiných sportovců, které podle ní "
                       f"vznikly: {sessions} (dny i hodnoty zůstanou)")
    return {"blockers": blockers, "removed": removed, "warnings": warnings, "teams": teams,
            "counts": {"baterie": len(batteries), "tymy": len(teams), "normy": norms,
                       "pravidla": rules, "clanky": articles, "ucty": len(accesses)}}


def _user_name(user) -> str:
    return user.get_full_name() or user.get_username()


@login_required
def sport_delete(request, pk):
    """Smazání sportu: nejdřív přehled, co se smaže a co tomu brání; pak POST."""
    sport = get_object_or_404(Sport.objects.for_user(request.user), pk=pk)
    if not access.may_add_sport(request.user):
        messages.error(request, "Sport maže správce nebo účet se všemi sporty.")
        return redirect("sport_list")
    plan = sport_delete_plan(sport)
    if request.method == "POST" and not plan["blockers"]:
        name = sport.name
        with transaction.atomic():
            record(request, AuditLog.Action.DELETE, sport, sport=name, kod=sport.code,
                   **plan["counts"])
            for team in plan["teams"]:
                team.delete()     # tým je na sportu chráněný (PROTECT), jde první
            sport.delete()        # baterie, normy a pravidla sportu se smažou s ním
        messages.success(request, f"Sport „{name}“ smazán.")
        return redirect("sport_list")
    return render(request, "catalog/sport_delete.html", {"sport": sport, "plan": plan})


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
def battery_interval(request, pk):
    """Doporučený odstup dalšího měření u baterie; z něj plyne, kdo je na řadě."""
    battery = get_object_or_404(_batteries(request.user), pk=pk)
    raw = request.POST.get("tydny", "").strip()
    try:
        weeks = int(raw) if raw else None
        if weeks is not None and not 1 <= weeks <= 104:
            raise ValueError
    except ValueError:
        messages.error(request, "Opakování zadejte v týdnech (1 až 104), nebo nechte prázdné.")
        return _card(request, battery) if request.headers.get("HX-Request") else redirect("sport_list")
    battery.retest_weeks = weeks
    battery.save(update_fields=["retest_weeks", "updated_at"])
    record(request, AuditLog.Action.UPDATE, battery, opakovani_tydnu=weeks)
    if request.headers.get("HX-Request"):
        return _card(request, battery)
    messages.success(request, f"Baterie {battery.label}: opakování "
                              + (f"po {weeks} týdnech." if weeks else "bez plánu."))
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
    protocol = get_object_or_404(_catalog_protocols(request.user), pk=request.POST.get("protocol"))
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
