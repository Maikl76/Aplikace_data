"""
Interakce variant (kombinace genotypů víc variant) v aplikaci místo
administrace: přehled se stavem (hypotéza / schváleno / zamítnuto)
a s upozorněním, když některá varianta kombinace není v panelu laboratoře,
a formulář ve čtyřech částech (název a oblasti, předpoklad a text, varianty,
posouzení). Hypotézu posuzuje správce; schválená se ukáže na kartě.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core.audit import record
from apps.core.models import AuditLog
from apps.core.steps import step

from .models import Domain, GeneCard, GeneInteraction, GenePanel, GeneVariant
from .setup_views import _may_setup
from .views import _catalog, _denied, _is_admin


def interaction_status(user) -> dict:
    rows = list(_catalog(GeneInteraction, user).select_related("source_card__variant")
                .order_by("order", "pk"))
    panel = _catalog(GenePanel, user).filter(is_active=True).order_by("pk").first()
    for row in rows:
        row.missing = row.missing_variants(panel)
    return {
        "interactions": rows, "panel": panel,
        "hypotheses": [r for r in rows if r.status == GeneInteraction.Status.HYPOTHESIS],
        "approved": [r for r in rows if r.status == GeneInteraction.Status.APPROVED],
        "outside_panel": [r for r in rows if r.missing
                          and r.status != GeneInteraction.Status.REJECTED],
    }


def interaction_step(user, status: dict | None = None) -> dict:
    """Krok 5 nastavení genetiky (volitelný): hypotézy posouzené, varianty v panelu."""
    s = status or interaction_status(user)
    rows, hyp, outside = s["interactions"], s["hypotheses"], s["outside_panel"]
    pending = hyp or outside
    return step(5, "Interakce variant", not pending,
                (f"{len(hyp)} hypotéz čeká na posouzení správcem." if hyp else
                 f"{len(outside)} kombinací má variantu mimo panel – z výsledku je nejde "
                 "vyhodnotit." if outside else
                 f"{len(s['approved'])} schválených z {len(rows)} kombinací." if rows else
                 "Žádná kombinace variant; z Wordu přijdou jako hypotézy, další jdou zapsat "
                 "tady."),
                url=reverse("genetics_interactions"), button="Interakce", optional=True,
                count=len({r.pk for r in hyp + outside}) or None)


@login_required
def interaction_list(request):
    user = request.user
    status = interaction_status(user)
    return render(request, "genetics/interactions.html", {
        **status, "step": interaction_step(user, status), "may_edit": _may_setup(user),
        "is_admin": _is_admin(user),
    })


FIELDS = ("title", "assumption", "text", "status")


def _form_data(interaction, post=None, *, card=None, variant=None) -> dict:
    if post is not None:
        data = {f: post.get(f, "").strip() for f in FIELDS}
        data["areas"] = post.getlist("areas")
        data["variants"] = post.getlist("variants")
        return data
    if interaction is None:
        rsids = [variant.rsid] if variant is not None else []
        return {"title": "", "assumption": "", "text": "", "status": GeneInteraction.Status.HYPOTHESIS,
                "areas": [variant.domain.name] if variant is not None else [],
                "variants": rsids}
    return {"title": interaction.title, "assumption": interaction.assumption,
            "text": interaction.text, "status": interaction.status,
            "areas": list(interaction.areas or []), "variants": list(interaction.variants or [])}


def _parse(data: dict, variants, domains, interaction, user) -> tuple[dict, list[str]]:
    errors = []
    title = data["title"][:300]
    if len(title) < 3:
        errors.append("Doplňte název kombinace (např. ACE × ACTN3 – silově-vytrvalostní profil).")
    if not data["text"].strip():
        errors.append("Doplňte text – co kombinace pro sportovce znamená a s jakou jistotou.")
    known = {v.rsid: v for v in variants}
    chosen = [rs for rs in data["variants"] if rs in known]
    if len(chosen) < 2:
        errors.append("Kombinace potřebuje aspoň dvě varianty z katalogu.")
    names = {d.name for d in domains}
    areas = [a for a in data["areas"] if a in names]
    status = data["status"] if data["status"] in GeneInteraction.Status.values else (
        GeneInteraction.Status.HYPOTHESIS)
    if interaction is not None and status != interaction.status and not _is_admin(user):
        errors.append("Stav kombinace (hypotéza / schváleno / zamítnuto) mění správce.")
    if interaction is None and status != GeneInteraction.Status.HYPOTHESIS and not _is_admin(user):
        status = GeneInteraction.Status.HYPOTHESIS
    return {"title": title, "assumption": data["assumption"][:2000], "text": data["text"][:5000],
            "status": status, "areas": areas, "variants": chosen}, errors


@login_required
def interaction_edit(request, pk=None):
    user = request.user
    if not _may_setup(user):
        return _denied(request, "Interakce variant zapisuje správce nebo laborant.")
    interaction = get_object_or_404(_catalog(GeneInteraction, user), pk=pk) if pk else None
    variants = list(_catalog(GeneVariant, user).select_related("domain").order_by("order", "gene"))
    domains = list(_catalog(Domain, user).filter(is_active=True).order_by("order", "name"))
    card = None
    if interaction is not None:
        card = interaction.source_card
    elif request.GET.get("karta"):
        card = _catalog(GeneCard, user).filter(pk=request.GET["karta"]).select_related("variant").first()
    if request.method == "POST":
        data = _form_data(None, request.POST)
        values, errors = _parse(data, variants, domains, interaction, user)
        if not errors:
            created = interaction is None
            if created:
                interaction = GeneInteraction(organization=user.organization, source_card=card,
                                              order=_catalog(GeneInteraction, user).count() + 1)
            for name, value in values.items():
                setattr(interaction, name, value)
            interaction.save()
            record(request, AuditLog.Action.CREATE if created else AuditLog.Action.UPDATE,
                   interaction, interakce=interaction.title[:80], stav=interaction.status)
            messages.success(request, f"Kombinace „{interaction.title[:60]}“ je uložená"
                             + (" jako hypotéza k posouzení správcem."
                                if interaction.status == GeneInteraction.Status.HYPOTHESIS else "."))
            return redirect(reverse("genetics_interactions") + f"#interakce-{interaction.pk}")
        for error in errors:
            messages.error(request, error)
    else:
        data = _form_data(interaction, card=card, variant=card.variant if card else None)
    panel = _catalog(GenePanel, user).filter(is_active=True).order_by("pk").first()
    in_panel = set(panel.items.values_list("variant__rsid", flat=True)) if panel else set()
    return render(request, "genetics/interaction_form.html", {
        "interaction": interaction, "data": data, "variants": variants, "domains": domains,
        "statuses": GeneInteraction.Status.choices, "is_admin": _is_admin(user), "card": card,
        "in_panel": in_panel, "panel": panel,
    })


@login_required
@require_POST
def interaction_delete(request, pk):
    user = request.user
    if not _is_admin(user):
        return _denied(request, "Interakce variant maže správce.")
    interaction = get_object_or_404(_catalog(GeneInteraction, user), pk=pk)
    record(request, AuditLog.Action.DELETE, interaction, interakce=interaction.title[:80])
    label = interaction.title[:60]
    interaction.delete()
    messages.info(request, f"Kombinace „{label}“ je smazaná.")
    return redirect("genetics_interactions")
