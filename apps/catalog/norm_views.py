"""
Normy v aplikaci: referenční hodnoty, proti kterým zpráva staví výsledek
(průměr ± SD → z-skóre, nebo percentily), vždy se zdrojem. Přehled podle
ukazatele s kroky (co chybí), formulář normy v pěti částech (ukazatel,
pro koho platí, hodnoty, zdroj, poznámka) a náhled, kolika sportovcům
pracoviště norma dnes sedí – aby kritéria nebyla zbytečně úzká. Norma
s vyplněným kritériem platí jen tam, kde kritérium sedí; nejspecifičtější
vyhrává (apps/analytics/services.find_norm).
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core.audit import record
from apps.core.models import AuditLog
from apps.evidence.models import Article
from apps.measurements.models import Mode, Side
from apps.subjects.models import Sport, Subject

from . import protocol_setup as setup
from .models import Norm
from .steps import catalog_status, norm_steps

PERCENTILES = ("5", "10", "25", "50", "75", "90", "95")
SEX = [("", "obě pohlaví"), ("F", "ženy"), ("M", "muži")]
MODES = [c for c in Mode.choices if c[0]]


def _shared(user):
    return Q(organization__isnull=True) | Q(organization=user.organization)


def _denied(request, reason):
    return render(request, "core/odepreno.html", {"duvod": reason}, status=403)


def _num(text, *, integer=False):
    """„1,5“ i „1.5“ → číslo; prázdné → None; nesmysl → ValueError."""
    text = (text or "").strip().replace(",", ".").replace(" ", "")
    if not text:
        return None
    return int(float(text)) if integer else float(text)


def applies_to(norm) -> str:
    """„florbal, ženy, 15–18 let, národní úroveň, levá“ – nebo „všichni sportovci“."""
    parts = []
    if norm.sport_id:
        parts.append(norm.sport.name)
    if norm.sex:
        parts.append(dict(SEX)[norm.sex])
    if norm.age_min or norm.age_max:
        parts.append(f"{norm.age_min or '…'}–{norm.age_max or '…'} let")
    if norm.level:
        parts.append(norm.get_level_display().lower())
    if norm.side:
        parts.append(norm.get_side_display().lower())
    if norm.mode:
        parts.append(norm.get_mode_display().lower())
    if norm.speed is not None:
        parts.append(f"{norm.speed:g} °/s")
    return ", ".join(parts) or "všichni sportovci"


def values_text(norm) -> str:
    out = []
    if norm.mean is not None:
        out.append(f"{norm.mean:g}" + (f" ± {norm.sd:g}" if norm.sd else " (bez SD)"))
    if norm.percentiles:
        keys = sorted(norm.percentiles, key=lambda k: float(k))
        out.append("percentily " + ", ".join(f"P{k} {norm.percentiles[k]:g}" for k in keys))
    return "; ".join(out) or "bez hodnot"


def matching_subjects(user, *, sport=None, sex="", level="", age_min=None, age_max=None) -> int:
    """Kolika aktivním sportovcům pracoviště by norma dnes sedla (sport, pohlaví, úroveň, věk)."""
    subjects = Subject.objects.for_user(user).filter(is_active=True)
    if sport is not None:
        subjects = subjects.filter(sport=sport)
    if sex:
        subjects = subjects.filter(sex=sex)
    if level:
        subjects = subjects.filter(level=level)
    if not (age_min or age_max):
        return subjects.count()
    count = 0
    for subject in subjects:
        try:
            age = subject.age_on()
        except Exception:  # bez klíče jména nejdou číst – věk pak neznáme
            age = None
        if age is None or (age_min and age < age_min) or (age_max and age > age_max):
            continue
        count += 1
    return count


# --- přehled ---------------------------------------------------------------------------------

@login_required
def norm_list(request):
    user = request.user
    status = catalog_status(user)
    key_ids = set(status["key_metrics"])
    norms = (Norm.objects.filter(_shared(user)).select_related("metric", "sport")
             .order_by("metric__name", "sport__name", "sex", "level", "side", "pk"))
    groups = []
    for norm in norms:
        norm.applies = applies_to(norm)
        norm.values_txt = values_text(norm)
        norm.incomplete = ((norm.mean is None or not norm.sd) and not norm.percentiles
                           or len(norm.source_citation.strip()) < 30)
        if not groups or groups[-1]["metric"].pk != norm.metric_id:
            groups.append({"metric": norm.metric, "key": norm.metric_id in key_ids, "norms": []})
        groups[-1]["norms"].append(norm)
    return render(request, "catalog/norms.html", {
        "groups": groups, "steps": norm_steps(user, status), "can_edit": setup.can_edit(user),
        "count": len(norms),
    })


# --- formulář ---------------------------------------------------------------------------------

FIELDS = ("metric", "sport", "sex", "age_min", "age_max", "level", "side", "mode", "speed",
          "mean", "sd", "sample_size", "source_citation", "source_doi", "note")


def _form_data(norm, post=None) -> dict:
    if post is not None:
        data = {f: post.get(f, "").strip() for f in FIELDS}
        data.update({f"p{p}": post.get(f"p{p}", "").strip() for p in PERCENTILES})
        return data
    if norm is None:
        return {**dict.fromkeys(FIELDS, ""), **{f"p{p}": "" for p in PERCENTILES}}
    data = {
        "metric": str(norm.metric_id), "sport": str(norm.sport_id or ""), "sex": norm.sex,
        "age_min": norm.age_min or "", "age_max": norm.age_max or "", "level": norm.level,
        "side": norm.side, "mode": norm.mode,
        "speed": "" if norm.speed is None else f"{norm.speed:g}",
        "mean": "" if norm.mean is None else f"{norm.mean:g}",
        "sd": "" if norm.sd is None else f"{norm.sd:g}",
        "sample_size": norm.sample_size or "", "source_citation": norm.source_citation,
        "source_doi": norm.source_doi, "note": norm.note,
    }
    for p in PERCENTILES:
        value = norm.percentiles.get(p)
        data[f"p{p}"] = "" if value is None else f"{float(value):g}"
    return data


def _parse(data: dict, metrics, sports) -> tuple[dict, list[str]]:
    errors = []
    metric = next((m for m in metrics if str(m.pk) == data["metric"]), None)
    if metric is None:
        errors.append("Vyberte ukazatel.")
    sport = next((s for s in sports if str(s.pk) == data["sport"]), None)
    sex = data["sex"] if data["sex"] in ("F", "M") else ""
    level = data["level"] if data["level"] in Subject.Level.values else ""
    side = data["side"] if data["side"] in Side.values else ""
    mode = data["mode"] if data["mode"] in {m for m, _ in MODES} else ""
    numbers = {}
    for name, integer in (("age_min", True), ("age_max", True), ("speed", False), ("mean", False),
                          ("sd", False), ("sample_size", True)):
        try:
            numbers[name] = _num(data[name], integer=integer)
        except ValueError:
            errors.append(f"Pole „{name}“ musí být číslo.")
            numbers[name] = None
    percentiles = {}
    for p in PERCENTILES:
        try:
            value = _num(data[f"p{p}"])
        except ValueError:
            errors.append(f"Percentil P{p} musí být číslo.")
            continue
        if value is not None:
            percentiles[p] = value
    ordered = [percentiles[p] for p in PERCENTILES if p in percentiles]
    if ordered != sorted(ordered):
        errors.append("Percentily musí růst od P5 k P95.")
    if numbers["age_min"] and numbers["age_max"] and numbers["age_min"] > numbers["age_max"]:
        errors.append("Věk od je větší než věk do.")
    if numbers["sd"] is not None and numbers["sd"] <= 0:
        errors.append("SD musí být kladné číslo.")
    if (numbers["mean"] is None) != (numbers["sd"] is None):
        errors.append("Průměr a SD patří k sobě – vyplňte obě, nebo nechte obě prázdné.")
    if numbers["mean"] is None and not percentiles:
        errors.append("Doplňte průměr a SD, nebo aspoň jeden percentil.")
    citation = data["source_citation"][:500]
    if len(citation) < 10:
        errors.append("Doplňte zdroj: citaci s autory, názvem, časopisem a rokem.")
    doi = data["source_doi"][:120].removeprefix("https://doi.org/").removeprefix("doi:").strip()
    values = {"metric": metric, "sport": sport, "sex": sex, "level": level, "side": side,
              "mode": mode, **numbers, "percentiles": percentiles,
              "source_citation": citation, "source_doi": doi, "note": data["note"]}
    return values, errors


def _article_choices():
    out = []
    for a in Article.objects.filter(status=Article.Status.APPROVED).order_by("-year", "title")[:300]:
        citation = " ".join(filter(None, [
            f"{a.authors.strip().rstrip('.')}." if a.authors else "",
            f"({a.year})." if a.year else "", f"{a.title.strip().rstrip('.')}.",
            f"{a.journal.strip().rstrip('.')}." if a.journal else ""]))
        label = f"{a.authors.split(',')[0] if a.authors else a.title[:40]} {a.year or ''}: {a.title[:70]}"
        out.append({"pk": a.pk, "label": label.strip(), "citation": citation, "doi": a.doi})
    return out


@login_required
def norm_edit(request, pk=None):
    user = request.user
    if not setup.can_edit(user):
        return _denied(request, "Normy zapisuje správce.")
    norm = get_object_or_404(Norm.objects.filter(_shared(user)), pk=pk) if pk else None
    status = catalog_status(user)
    key_ids = set(status["key_metrics"])
    metrics = list(setup.available_metrics(user.organization))
    sports = list(Sport.objects.for_user(user).order_by("name"))
    if request.method == "POST":
        data = _form_data(None, request.POST)
        if norm is not None:
            data["metric"] = str(norm.metric_id)  # ukazatel se u uložené normy nemění
        values, errors = _parse(data, metrics, sports)
        if not errors:
            if norm is None:
                norm = Norm(organization=user.organization)
            for name, value in values.items():
                setattr(norm, name, value)
            norm.save()
            record(request, AuditLog.Action.CREATE if pk is None else AuditLog.Action.UPDATE,
                   norm, norma=str(norm))
            fits = matching_subjects(user, sport=norm.sport, sex=norm.sex, level=norm.level,
                                     age_min=norm.age_min, age_max=norm.age_max)
            messages.success(request, f"Norma {norm.metric.name} ({applies_to(norm)}) je uložená; "
                                      f"z aktivních sportovců pracoviště dnes sedí na {fits}.")
            return redirect(reverse("norms_settings") + f"#ukazatel-{norm.metric_id}")
        for error in errors:
            messages.error(request, error)
    else:
        data = _form_data(norm)
        if norm is None and (metric := request.GET.get("ukazatel")):
            data["metric"] = metric
    fits = None
    if norm is not None:
        fits = matching_subjects(user, sport=norm.sport, sex=norm.sex, level=norm.level,
                                 age_min=norm.age_min, age_max=norm.age_max)
    return render(request, "catalog/norm_form.html", {
        "norm": norm, "data": data, "fits": fits,
        "key_metrics": [m for m in metrics if m.pk in key_ids],
        "other_metrics": [m for m in metrics if m.pk not in key_ids],
        "sports": sports, "sexes": SEX, "levels": Subject.Level.choices, "sides": Side.choices,
        "modes": MODES, "percentile_rows": [(p, data[f"p{p}"]) for p in PERCENTILES],
        "has_percentiles": any(data[f"p{p}"] for p in PERCENTILES),
        "articles": _article_choices(),
    })


@login_required
@require_POST
def norm_delete(request, pk):
    if not setup.can_edit(request.user):
        return _denied(request, "Normy maže správce.")
    norm = get_object_or_404(Norm.objects.filter(_shared(request.user)), pk=pk)
    label = f"{norm.metric.name} ({applies_to(norm)})"
    record(request, AuditLog.Action.DELETE, norm, norma=label)
    norm.delete()
    messages.info(request, f"Norma {label} je smazaná; zprávy u tohoto ukazatele už postavení "
                           "vůči ní neukážou.")
    return redirect("norms_settings")
