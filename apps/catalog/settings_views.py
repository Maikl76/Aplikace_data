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
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.core import access
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
    # metodik měření upravuje jen ukazatele své rodiny testů
    editable = setup.can_edit(user)
    for row in in_batteries + others:
        row["editable"] = editable and access.family_allowed(user, row["metric"].family)
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
                if not row["editable"]:
                    continue
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


# --- MDC z vlastních dat ---------------------------------------------------------------

def _estimate_params(request, user):
    """Skupina (tým, sport, všichni v rozsahu účtu), období a největší odstup měření."""
    from datetime import date, timedelta

    from django.utils import timezone

    from apps.subjects.models import Sport, Subject, Team

    params = request.POST if request.method == "POST" else request.GET
    teams = list(Team.objects.for_user(user).select_related("sport").order_by("name"))
    sports = list(Sport.objects.for_user(user).order_by("name"))
    group = params.get("skupina", "")
    subjects = Subject.objects.for_user(user)
    label = "všichni sportovci"
    if group.startswith("tym-"):
        team = next((t for t in teams if f"tym-{t.pk}" == group), None)
        if team is not None:
            subjects, label = subjects.filter(team=team), f"tým {team.name}"
    elif group.startswith("sport-"):
        sport = next((sp for sp in sports if f"sport-{sp.pk}" == group), None)
        if sport is not None:
            subjects, label = subjects.filter(sport=sport), f"sport {sport.name}"
    today = timezone.localdate()
    try:
        date_to = date.fromisoformat(params.get("do", "")) if params.get("do") else today
        date_from = (date.fromisoformat(params.get("od", "")) if params.get("od")
                     else date_to - timedelta(days=365))
    except ValueError:
        date_from, date_to = today - timedelta(days=365), today
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    try:
        max_gap = min(max(int(params.get("odstup", "") or 14), 1), 365)
    except ValueError:
        max_gap = 14
    return {"team_choices": [(f"tym-{t.pk}", t.name + (f" ({t.sport.name})" if t.sport else ""))
                             for t in teams],
            "sport_choices": [(f"sport-{sp.pk}", sp.name) for sp in sports],
            "group": group, "group_label": label,
            "subjects": subjects, "date_from": date_from, "date_to": date_to,
            "max_gap": max_gap}


@login_required
def mdc_estimate(request, pk):
    """
    MDC z vlastních opakovaných měření: TE ze sousedních měřených dnů skupiny
    v období, MDC90 / MDC95 a SWC; uloží se k ukazateli i se zdrojem.
    """
    from apps.analytics import reliability

    metric = get_object_or_404(MetricDef.objects.filter(_shared(request.user)), pk=pk)
    params = _estimate_params(request, request.user)
    editable = setup.can_edit(request.user) and access.family_allowed(request.user, metric.family)
    results = reliability.estimate(metric, params["subjects"], params["date_from"],
                                   params["date_to"], max_gap=params["max_gap"])
    if request.method == "POST":
        if not editable:
            return _denied(request, "MDC u ukazatelů ukládá správce nebo metodik měření.")
        chosen = next((r for r in results if r["ok"] and r["label"] == request.POST.get("kombinace", "")
                       ), None)
        level = 95 if request.POST.get("uroven") == "95" else 90
        if chosen is None:
            messages.error(request, "Z vybraných dat se MDC spočítat nedá – zkontrolujte "
                                    "skupinu, období a odstup měření.")
            return redirect(request.get_full_path())
        old = (metric.typical_error, metric.mdc, metric.swc, metric.mdc_source)
        d = metric.decimals + 1
        metric.typical_error = round(chosen["te"], d)
        metric.mdc = round(chosen["mdc95" if level == 95 else "mdc90"], d)
        if request.POST.get("swc") and chosen["swc"] is not None:
            metric.swc = round(chosen["swc"], d)
        metric.mdc_source = reliability.source_text(
            chosen, level=level, group=params["group_label"], date_from=params["date_from"],
            date_to=params["date_to"], metric=metric)
        metric.save(update_fields=["typical_error", "mdc", "swc", "mdc_source", "updated_at"])
        record(request, AuditLog.Action.UPDATE, metric, nastaveni="mdc_z_dat",
               ukazatel=metric.code, puvodne={"te": old[0], "mdc": old[1], "swc": old[2]},
               nove={"te": metric.typical_error, "mdc": metric.mdc, "swc": metric.swc},
               zdroj=metric.mdc_source)
        messages.success(request, f"{metric.name}: uložena MDC{level} "
                                  f"{str(metric.mdc).replace('.', ',')} {metric.unit} "
                                  "z vlastních dat. Další srovnání ji použijí hned.")
        return redirect(reverse("mdc_settings") + f"#mdc-{metric.pk}")
    return render(request, "catalog/mdc_estimate.html", {
        "metric": metric, "results": results, "editable": editable, **params,
        "query": request.GET.urlencode(),
    })


# --- popisy pro klienta ----------------------------------------------------------------

def _text(post, name: str) -> str:
    return " ".join(post.get(name, "").split())[:300]


@login_required
def client_texts(request):
    """Co ukazatel znamená (pro sportovce, pro trenéra) a jak test probíhá; návrh modelem."""
    from apps.reports import llm

    from . import client_texts as texts

    can_edit = setup.can_edit(request.user)
    status, in_batteries, others = _metric_rows(request.user)
    protocols = sorted(status["protocols"].values(), key=lambda p: p.name)
    for p in protocols:
        p.text_p, p.draft = p.athlete_text, False
        p.editable = can_edit and access.family_allowed(request.user, p.family)
    for row in in_batteries + others:
        row["text_s"], row["text_t"], row["draft"] = row["metric"].athlete_text, row["metric"].coach_text, False
    drafts = None

    if request.method == "POST":
        if not can_edit:
            return _denied(request, "Popisy pro klienta doplňuje správce.")
        if request.POST.get("akce") == "navrhnout":
            wanted = [(r["metric"], r["tests"]) for r in in_batteries + others
                      if not (r["metric"].athlete_text and r["metric"].coach_text)]
            wanted_tests = [p for p in protocols if not p.athlete_text]
            if not wanted and not wanted_tests:
                messages.info(request, "Všechny ukazatele i testy už popis mají.")
                return redirect("client_texts")
            try:
                drafts = texts.suggest(wanted, wanted_tests)
            except texts.SuggestError as exc:
                messages.error(request, f"Model popisy nenavrhl: {exc}")
                return redirect("client_texts")
            for row in in_batteries + others:
                if d := drafts["ukazatele"].get(row["metric"].code):
                    row["text_s"] = row["text_s"] or d["sportovec"]
                    row["text_t"] = row["text_t"] or d["trener"]
                    row["draft"] = True
            for p in protocols:
                if d := drafts["testy"].get(p.code):
                    p.text_p, p.draft = d["sportovec"], True
            record(request, AuditLog.Action.UPDATE, request.user.organization or request.user,
                   nastaveni="popisy", navrh=len(drafts["ukazatele"]) + len(drafts["testy"]))
        else:
            changed = 0
            with transaction.atomic():
                for row in in_batteries + others:
                    if not row["editable"]:
                        continue
                    m = row["metric"]
                    athlete, coach = _text(request.POST, f"s_{m.pk}"), _text(request.POST, f"t_{m.pk}")
                    if (m.athlete_text, m.coach_text) != (athlete, coach):
                        changed += (m.athlete_text != athlete) + (m.coach_text != coach)
                        m.athlete_text, m.coach_text = athlete, coach
                        m.save(update_fields=["athlete_text", "coach_text", "updated_at"])
                for p in protocols:
                    if not p.editable:
                        continue
                    text = _text(request.POST, f"p_{p.pk}")
                    if p.athlete_text != text:
                        p.athlete_text = text
                        p.save(update_fields=["athlete_text", "updated_at"])
                        changed += 1
            record(request, AuditLog.Action.UPDATE, request.user.organization or request.user,
                   nastaveni="popisy", zmeneno=changed)
            messages.success(request, f"Uloženo: {changed} popisů změněno." if changed
                             else "Uloženo, beze změn.")
            return redirect("client_texts")

    key = list(status["key_metrics"].values())
    return render(request, "catalog/client_texts.html", {
        "rows": in_batteries, "others": others, "protocols": protocols, "can_edit": can_edit,
        "drafts": drafts, "llm_on": llm.is_enabled(),
        "steps": catalog_steps(request.user, status),
        "key_total": len(key), "key_missing": sum(1 for m in key if not m.athlete_text),
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
            if not getattr(profile, "editable", True):
                continue
            protocol = protocol_by_pk.get(post.get(f"p{profile.pk}_protocol", ""))
            if protocol is not None and not access.family_allowed(user, protocol.family):
                problems.append(f"{profile}: test {protocol.name} patří do jiné metodiky – neuloženo.")
                continue
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
            elif not access.family_allowed(user, protocol.family):
                problems.append(f"Nový profil: test {protocol.name} patří do jiné metodiky než vaší.")
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
    for profile in profiles:
        profile.editable = allowed and access.family_allowed(request.user, profile.protocol.family)
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
