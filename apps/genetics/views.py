"""
Obrazovky genetiky v aplikaci laboratoře.

* Genetika – přehled panelu, karet a fronty revize; garant tu vidí, co čeká na něj.
* Karta – čitelná podoba verze karty s kontrolou před schválením a tlačítky
  stavu (k revizi, schválit, vrátit, nová verze, vyřadit).
* Sportovec – souhlas, vzorky a genotypy; genotypy vidí jen správce a laborant.
"""

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.audit import record
from apps.core.models import AuditLog, Role
from apps.subjects.models import Subject

from . import crypto, services
from .models import Domain, GeneCard, GenePanel, GeneticSample, GeneVariant


def _catalog(model, user):
    """Sdílené záznamy a záznamy pracoviště uživatele."""
    return model.objects.filter(Q(organization__isnull=True) | Q(organization=user.organization))


def _is_admin(user) -> bool:
    return user.is_superuser or user.role == Role.ADMIN


def _denied(request, reason):
    return render(request, "core/odepreno.html", {"duvod": reason}, status=403)


# --- přehled -------------------------------------------------------------------

@login_required
def home(request):
    user = request.user
    variants = list(_catalog(GeneVariant, user).select_related("domain")
                    .prefetch_related("cards").order_by("order", "gene"))
    for v in variants:
        cards = sorted(v.cards.all(), key=lambda c: c.version)
        v.approved = next((c for c in cards if c.status == GeneCard.Status.APPROVED), None)
        v.working = next((c for c in cards if c.status in GeneCard.EDITABLE), None)
        v.latest = cards[-1] if cards else None
        v.garant = v.domain.is_guarantor(user)
    review = [v for v in variants if v.working and v.working.status == GeneCard.Status.REVIEW]
    domains = list(_catalog(Domain, user).filter(is_active=True).prefetch_related("guarantors"))
    panels = list(_catalog(GenePanel, user).filter(is_active=True).prefetch_related("items"))
    samples = None
    if services.may_view_genotypes(user):
        rows = GeneticSample.objects.filter(subject__organization=user.organization)
        samples = {"celkem": rows.count(),
                   "neovereno": rows.filter(status=GeneticSample.Status.RECEIVED).count()}
    return render(request, "genetics/home.html", {
        "variants": variants, "review": review, "domains": domains, "panels": panels,
        "samples": samples, "key_missing": not crypto.configured(),
        "approved_count": sum(1 for v in variants if v.approved),
    })


# --- karta -----------------------------------------------------------------------

def _card(request, pk):
    return get_object_or_404(
        _catalog(GeneCard, request.user).select_related("variant", "variant__domain"), pk=pk)


@login_required
def card(request, pk):
    card = _card(request, pk)
    variant = card.variant
    texts = {t.genotype: t for t in card.genotype_texts.all()}
    recommendations = list(card.recommendations.all())
    genotypes = [{
        "code": g, "label": variant.genotype_label(g), "text": texts.get(g),
        "recommendations": [r for r in recommendations if r.genotype == g],
    } for g in variant.genotypes]
    versions = list(variant.cards.order_by("version"))
    return render(request, "genetics/card.html", {
        "card": card, "variant": variant, "genotypes": genotypes,
        "general": [r for r in recommendations if not r.genotype],
        "evidence": card.evidence.select_related("article"),
        "sources": card.sources.select_related("article"),
        "forbidden": card.forbidden_statements.all(),
        "scenarios": card.scenarios.prefetch_related("texts"),
        "interactions": card.interactions.all(),
        "revisions": card.revisions.all(),
        "checklist": services.checklist(card) if card.is_editable else None,
        "versions": versions,
        "may_approve": services.may_approve(request.user, card),
        "may_edit": request.user.role != Role.RESEARCHER,
        "may_retire": _is_admin(request.user),
        "has_working": variant.cards.filter(status__in=GeneCard.EDITABLE).exists(),
    })


@login_required
@require_POST
def card_action(request, pk):
    card = _card(request, pk)
    action = request.POST.get("akce")
    user = request.user
    try:
        if action == "k_revizi":
            services.submit_for_review(card)
            messages.success(request, f"Karta {card} čeká na garanta oblasti "
                                      f"„{card.variant.domain}“.")
        elif action == "vratit":
            services.return_to_draft(card)
            messages.info(request, f"Karta {card} je zase návrh k úpravě.")
        elif action == "schvalit":
            services.approve(card, by=user)
            messages.success(request, f"Karta {card} je schválená – od teď je to jediné znění, "
                                      "které smí do zpráv.")
        elif action == "nova_verze":
            new = services.new_version(card, by=user)
            messages.success(request, f"Vznikla verze {new.version} jako návrh; upravte ji "
                                      "v administraci.")
            return redirect("genetics_card", pk=new.pk)
        elif action == "vyradit":
            if not _is_admin(user):
                return _denied(request, "Vyřadit kartu smí jen správce.")
            services.retire(card)
            messages.info(request, f"Karta {card} je vyřazená.")
        else:
            messages.error(request, "Neznámá akce.")
    except PermissionError as exc:
        return _denied(request, str(exc))
    except ValueError as exc:
        messages.error(request, str(exc))
    record(request, AuditLog.Action.UPDATE, card, karta=str(card), akce=action)
    return redirect("genetics_card", pk=card.pk)


# --- sportovec -------------------------------------------------------------------

class SampleForm(forms.Form):
    provider = forms.CharField(label="Laboratoř", max_length=200, required=False)
    sampled_on = forms.DateField(label="Datum odběru", required=False,
                                 widget=forms.DateInput(attrs={"type": "date"}))
    reported_on = forms.DateField(label="Datum výsledku", required=False,
                                  widget=forms.DateInput(attrs={"type": "date"}))
    external_reference = forms.CharField(label="Reference laboratoře", max_length=120,
                                         required=False)
    note = forms.CharField(label="Poznámka", max_length=255, required=False)

    def __init__(self, panel, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.panel = panel
        self.items = list(panel.active_items())
        if not self.fields["provider"].initial:
            self.fields["provider"].initial = panel.provider
        for item in self.items:
            self.fields[f"g_{item.variant_id}"] = forms.CharField(
                label=item.variant.label, max_length=16, required=False,
                help_text=", ".join(item.variant.genotype_label(g) for g in item.variant.genotypes))

    def genotype_fields(self):
        return [(item, self[f"g_{item.variant_id}"]) for item in self.items]

    def genotypes(self) -> dict:
        return {item.variant_id: self.cleaned_data.get(f"g_{item.variant_id}", "")
                for item in self.items}


def _subject(request, pk):
    return get_object_or_404(Subject.objects.for_user(request.user).select_related("sport"), pk=pk)


@login_required
def subject(request, pk):
    if not services.may_view_genotypes(request.user):
        return _denied(request, "Genetická data smí otevřít jen správce nebo laborant.")
    subject = _subject(request, pk)
    record(request, AuditLog.Action.VIEW, subject, subject_code=subject.code, genetika=True)
    state = services.consent_state(subject)
    panels = list(_catalog(GenePanel, request.user).filter(is_active=True))
    panel = None
    if panels:
        wanted = request.GET.get("panel") or request.POST.get("panel")
        panel = next((p for p in panels if str(p.pk) == str(wanted)), panels[0])
    entry_blocked = ("V ukázce se genotypy nezadávají." if settings.DEMO_MODE
                     else crypto.CHYBI if not crypto.configured()
                     else state.blocked_reason or ("Sportovec nemá platný souhlas s genetickými daty."
                                                   if not state.valid else "")
                     if panels else "Není žádný aktivní panel variant (administrace → Genetika).")
    form = SampleForm(panel) if panel else None
    if request.method == "POST" and request.POST.get("akce") == "vzorek":
        if entry_blocked:
            messages.error(request, entry_blocked)
            return redirect("genetics_subject", pk=pk)
        form = SampleForm(panel, request.POST)
        if form.is_valid():
            sample = services.record_sample(subject, panel, by=request.user,
                                            data=form.cleaned_data, genotypes=form.genotypes())
            record(request, AuditLog.Action.CREATE, sample, subject_code=subject.code,
                   panel=str(panel))
            unclear = sample.genotypes.exclude(quality="ok").count()
            messages.success(request, "Vzorek je uložený (neověřený)."
                             + (f" {unclear}× nejasný nebo chybějící zápis – zkontrolujte."
                                if unclear else ""))
            return redirect("genetics_subject", pk=pk)
    samples = list(subject.genetic_samples.select_related("panel", "verified_by", "entered_by")
                   .prefetch_related("genotypes__variant").order_by("-created_at"))
    for s in samples:
        s.rows = [_genotype_row(g) for g in s.genotypes.all() if g.variant.is_active]
    return render(request, "genetics/subject.html", {
        "subject": subject, "display_name": subject.display_for(request.user),
        "state": state, "samples": samples, "panels": panels, "panel": panel, "form": form,
        "entry_blocked": entry_blocked, "demo": settings.DEMO_MODE,
    })


def _genotype_row(genotype) -> dict:
    try:
        value, raw = genotype.value, genotype.raw
    except Exception:
        value, raw = "", "(nejde přečíst – jiný nebo chybějící klíč)"
    return {"variant": genotype.variant, "value": value, "raw": raw,
            "label": genotype.variant.genotype_label(value) if value else "",
            "quality": genotype.get_quality_display(), "ok": genotype.quality == "ok"}


@login_required
@require_POST
def subject_action(request, pk):
    if not services.may_view_genotypes(request.user):
        return _denied(request, "Genetická data smí měnit jen správce nebo laborant.")
    subject = _subject(request, pk)
    action = request.POST.get("akce")
    try:
        if action == "souhlas_udelit":
            services.grant_consent(subject, by=request.user,
                                   note="podepsaný souhlas převzala laboratoř")
            messages.success(request, "Souhlas s genetickými daty je zapsaný.")
        elif action == "souhlas_odvolat":
            services.revoke_consent(subject, by=request.user)
            messages.info(request, "Souhlas je odvolaný; genotypy sportovce jsou smazané.")
        elif action in ("overit", "nevalidni"):
            sample = get_object_or_404(subject.genetic_samples, pk=request.POST.get("vzorek"))
            if action == "overit":
                services.verify_sample(sample, by=request.user)
                messages.success(request, "Vzorek je ověřený – výsledek patří sportovci.")
            else:
                services.invalidate_sample(sample, reason=request.POST.get("duvod", "")
                                           or "neuvedeno")
                messages.info(request, "Vzorek je označený jako nevalidní.")
        else:
            messages.error(request, "Neznámá akce.")
    except ValueError as exc:
        messages.error(request, str(exc))
    record(request, AuditLog.Action.UPDATE, subject, subject_code=subject.code,
           genetika=action)
    return redirect("genetics_subject", pk=pk)
