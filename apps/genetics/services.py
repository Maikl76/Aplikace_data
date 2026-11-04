"""
Provozní logika genetiky: souhlas, vzorky a genotypy, životní cyklus karty.

Zásady, které tu platí bez výjimky:

* bez platného souhlasu „Genetická data“ se genotyp neuloží ani nezobrazí
  a odvolání souhlasu genotypy smaže (vydané zprávy zůstávají jako dokument);
* genetika je jen pro dospělé – věk se ověřuje z data narození;
* do zprávy smí jen schválená verze karty; schválit ji smí jen garant
  oblasti a jen bez blokujících nedostatků.
"""

from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from apps.subjects.models import Consent

from . import crypto
from .models import (
    CardEvidence,
    CardRevision,
    CardSource,
    ContextScenario,
    ForbiddenStatement,
    GeneCard,
    GeneticSample,
    Genotype,
    GenotypeText,
    Recommendation,
    ScenarioText,
)

ADULT_AGE = 18
SCOPE = Consent.Scope.GENETICS


# --- souhlas ------------------------------------------------------------------

@dataclass
class ConsentState:
    consent: Consent | None
    age: int | None
    adult: bool | None          # None = věk není znám
    samples: int = 0

    @property
    def valid(self) -> bool:
        return self.consent is not None

    @property
    def blocked_reason(self) -> str:
        """Proč souhlas nejde udělit (prázdné = jde)."""
        if self.adult is None:
            return "Bez data narození nelze ověřit věk – genetika je jen pro dospělé."
        if not self.adult:
            return f"Genetické testování je v aplikaci jen pro dospělé (od {ADULT_AGE} let)."
        return ""


def consent_state(subject) -> ConsentState:
    valid = next((c for c in subject.consents.filter(scope=SCOPE).order_by("-granted_on", "-pk")
                  if c.is_valid), None)
    age = subject.age
    adult = None if age is None else age >= ADULT_AGE
    return ConsentState(consent=valid, age=age, adult=adult,
                        samples=subject.genetic_samples.count())


def grant_consent(subject, *, by=None, note="") -> Consent:
    state = consent_state(subject)
    if state.blocked_reason:
        raise ValueError(state.blocked_reason)
    if state.consent:
        return state.consent
    who = by.get_username() if by is not None else "aplikace"
    return Consent.objects.create(subject=subject, scope=SCOPE, granted_on=timezone.localdate(),
                                  note=(note or f"uděleno v aplikaci ({who})")[:255])


def revoke_consent(subject, *, by=None) -> int:
    """Odvolá platné souhlasy s genetikou; genotypy smaže signál po uložení."""
    today = timezone.localdate()
    count = 0
    for consent in subject.consents.filter(scope=SCOPE):
        if consent.is_valid:
            consent.revoked_on = today
            consent.save(update_fields=["revoked_on", "updated_at"])
            count += 1
    return count


def purge_genotypes(subject) -> int:
    """Smaže genotypy sportovce; vzorky zůstanou jako záznam bez dat."""
    deleted, _ = Genotype.objects.filter(sample__subject=subject).delete()
    GeneticSample.objects.filter(subject=subject).exclude(
        status=GeneticSample.Status.WITHDRAWN).update(
        status=GeneticSample.Status.WITHDRAWN, invalid_reason="souhlas odvolán")
    return deleted


def on_consent_saved(sender, instance, **kwargs):
    if instance.scope == SCOPE and not instance.is_valid and not consent_state(instance.subject).valid:
        purge_genotypes(instance.subject)


def on_consent_deleted(sender, instance, **kwargs):
    if instance.scope == SCOPE:
        try:
            subject = instance.subject
        except Exception:  # sportovec se maže celý – genotypy jdou s ním
            return
        if not consent_state(subject).valid:
            purge_genotypes(subject)


# --- vzorky a genotypy --------------------------------------------------------

def may_view_genotypes(user) -> bool:
    """Genotypy vidí jen správce a laborant; výzkumník, trenér a sportovec ne."""
    return bool(user and user.is_authenticated
                and (user.is_superuser or getattr(user, "sees_identity", False)))


def normalize(item, raw: str) -> tuple[str | None, str]:
    """Kanonický genotyp a kvalita pro zápis z laboratoře (podle položky panelu)."""
    text = (raw or "").strip()
    if not text:
        return None, Genotype.Quality.MISSING
    if text.lower() in {"selhalo", "failed", "fail", "n/a", "na", "-", "—"}:
        return None, Genotype.Quality.FAILED
    value = item.normalize(text)
    return (value, Genotype.Quality.OK) if value else (None, Genotype.Quality.UNCLEAR)


@transaction.atomic
def record_sample(subject, panel, *, by, data: dict, genotypes: dict) -> GeneticSample:
    """
    Založí vzorek a genotypy (``genotypes`` = {variant_id: zápis laboratoře}).
    Vyžaduje platný souhlas, dospělost a nastavený klíč.
    """
    state = consent_state(subject)
    if state.blocked_reason:
        raise ValueError(state.blocked_reason)
    if not state.valid:
        raise ValueError("Sportovec nemá platný souhlas s genetickými daty.")
    if not crypto.configured():
        raise ValueError(crypto.CHYBI)
    sample = GeneticSample.objects.create(
        subject=subject, panel=panel, consent=state.consent, entered_by=by,
        provider=data.get("provider") or panel.provider,
        sampled_on=data.get("sampled_on"), reported_on=data.get("reported_on"),
        external_reference=data.get("external_reference", ""), note=data.get("note", ""))
    for item in panel.active_items():
        raw = str(genotypes.get(item.variant_id) or genotypes.get(str(item.variant_id)) or "")
        value, quality = normalize(item, raw)
        genotype = Genotype(sample=sample, variant=item.variant, quality=quality)
        genotype.set_values(raw, value)
        genotype.save()
    return sample


def verify_sample(sample, *, by) -> GeneticSample:
    sample.status = GeneticSample.Status.VERIFIED
    sample.verified_by = by
    sample.verified_at = timezone.now()
    sample.invalid_reason = ""
    sample.save(update_fields=["status", "verified_by", "verified_at", "invalid_reason",
                               "updated_at"])
    return sample


def invalidate_sample(sample, *, reason: str) -> GeneticSample:
    sample.status = GeneticSample.Status.INVALID
    sample.invalid_reason = reason[:255]
    sample.save(update_fields=["status", "invalid_reason", "updated_at"])
    return sample


def summary_for(subject, user) -> dict:
    """Pro kartu sportovce: stav souhlasu a vzorků, bez samotných genotypů."""
    state = consent_state(subject)
    samples = list(subject.genetic_samples.select_related("panel").order_by("-created_at")[:5])
    return {"state": state, "samples": samples,
            "may_view": may_view_genotypes(user), "key_missing": not crypto.configured()}


# --- životní cyklus karty -----------------------------------------------------

@dataclass
class Issue:
    text: str
    blocking: bool = True


@dataclass
class Checklist:
    issues: list[Issue] = field(default_factory=list)

    @property
    def blocking(self) -> list[Issue]:
        return [i for i in self.issues if i.blocking]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if not i.blocking]

    @property
    def ok(self) -> bool:
        return not self.blocking


def _normalized(text: str) -> str:
    return " ".join((text or "").replace("„", "").replace("“", "").replace('"', "")
                    .lower().split())


def forbidden_in(card, text: str) -> list[str]:
    """Nepřípustné výroky (karty i globální), které se v textu vyskytují."""
    haystack = _normalized(text)
    if not haystack:
        return []
    statements = ForbiddenStatement.objects.filter(card=card) | ForbiddenStatement.objects.filter(
        card__isnull=True)
    return [s.text for s in statements if _normalized(s.text) and _normalized(s.text) in haystack]


def checklist(card) -> Checklist:
    """Co kartě chybí ke schválení. Blokující nedostatky schválení zastaví."""
    out = Checklist()
    variant = card.variant
    if not variant.genotypes:
        out.issues.append(Issue("Varianta nemá definované genotypy."))
    if not card.biology_client.strip():
        out.issues.append(Issue("Chybí vysvětlení biologické funkce pro klienta."))
    texts = {t.genotype: t for t in card.genotype_texts.all()}
    for genotype in variant.genotypes:
        text = texts.get(genotype)
        if text is None or not text.client_text.strip():
            out.issues.append(Issue(f"Genotyp {genotype} nemá interpretaci pro klienta."))
        elif hits := forbidden_in(card, text.client_text):
            out.issues.append(Issue(f"Interpretace genotypu {genotype} obsahuje nepřípustný "
                                    f"výrok: „{hits[0]}“."))
    for rec in card.recommendations.all():
        if not rec.basis:
            out.issues.append(Issue(f"Doporučení „{rec.text[:50]}…“ nemá uvedený důvod."))
        elif hits := forbidden_in(card, rec.text):
            out.issues.append(Issue(f"Doporučení obsahuje nepřípustný výrok: „{hits[0]}“."))
    if not card.evidence.exists():
        out.issues.append(Issue("Karta nemá žádný řádek důkazů (E01…).", blocking=False))
    if not card.sources.exists():
        out.issues.append(Issue("Karta nemá žádný zdroj.", blocking=False))
    for source in card.sources.all():
        if len(source.citation.strip()) < 30:
            out.issues.append(Issue(f"Neúplná citace: „{source.citation.strip()}“.",
                                    blocking=False))
    if any(t.frequency.strip() for t in texts.values()) and not variant.frequency_source.strip():
        out.issues.append(Issue("Frekvence genotypů jsou uvedené bez zdroje frekvencí.",
                                blocking=False))
    if card.revisions.filter(decision=CardRevision.Decision.OPEN).exists():
        out.issues.append(Issue("Karta má nerozhodnuté revizní záznamy.", blocking=False))
    return out


def may_approve(user, card) -> bool:
    return card.variant.domain.is_guarantor(user)


def submit_for_review(card) -> GeneCard:
    if card.status != GeneCard.Status.DRAFT:
        raise ValueError("K revizi jde poslat jen návrh.")
    card.status = GeneCard.Status.REVIEW
    card.save(update_fields=["status", "updated_at"])
    return card


def return_to_draft(card) -> GeneCard:
    if card.status != GeneCard.Status.REVIEW:
        raise ValueError("Vrátit k úpravě jde jen kartu v revizi.")
    card.status = GeneCard.Status.DRAFT
    card.save(update_fields=["status", "updated_at"])
    return card


@transaction.atomic
def approve(card, *, by) -> GeneCard:
    """Schválení: jen garant, jen z revize, jen bez blokujících nedostatků."""
    if card.status != GeneCard.Status.REVIEW:
        raise ValueError("Schválit jde jen kartu v revizi.")
    if not may_approve(by, card):
        raise PermissionError("Kartu smí schválit jen garant oblasti "
                              f"„{card.variant.domain.name}“.")
    check = checklist(card)
    if not check.ok:
        raise ValueError("Kartu nejde schválit: " + " ".join(i.text for i in check.blocking))
    previous = card.variant.cards.filter(status=GeneCard.Status.APPROVED).exclude(pk=card.pk)
    for old in previous:
        old.status = GeneCard.Status.SUPERSEDED
        old.save(update_fields=["status", "updated_at"])
        if card.supersedes_id is None:
            card.supersedes = old
    card.status = GeneCard.Status.APPROVED
    card.approved_by = by
    card.approved_at = timezone.now()
    card.save()
    return card


def retire(card) -> GeneCard:
    card.status = GeneCard.Status.RETIRED
    card.save(update_fields=["status", "updated_at"])
    return card


@transaction.atomic
def new_version(card, *, by=None) -> GeneCard:
    """Kopie karty jako nový návrh (původní zůstává beze změny)."""
    if card.variant.cards.filter(status__in=GeneCard.EDITABLE).exists():
        raise ValueError("Varianta už má rozpracovanou verzi – dokončete ji.")
    version = (card.variant.cards.order_by("-version").first().version or 0) + 1
    copy = GeneCard.objects.create(
        organization=card.organization, variant=card.variant, version=version,
        status=GeneCard.Status.DRAFT, supersedes=card,
        review_priorities=card.review_priorities, biology_expert=card.biology_expert,
        biology_client=card.biology_client, effect=card.effect, limitations=card.limitations,
        frequency_note=card.frequency_note, related_areas=list(card.related_areas),
        created_by=by)
    copy_children(card, copy)
    return copy


def copy_children(source: GeneCard, target: GeneCard) -> None:
    for t in source.genotype_texts.all():
        GenotypeText.objects.create(card=target, genotype=t.genotype, client_text=t.client_text,
                                    expert_text=t.expert_text, frequency=t.frequency,
                                    order=t.order)
    for r in source.recommendations.all():
        Recommendation.objects.create(card=target, genotype=r.genotype, kind=r.kind,
                                      text=r.text, basis=r.basis, merge_key=r.merge_key,
                                      order=r.order)
    for e in source.evidence.all():
        CardEvidence.objects.create(card=target, code=e.code, trait=e.trait,
                                    basis_text=e.basis_text, usage=e.usage,
                                    source_labels=e.source_labels, article=e.article,
                                    order=e.order)
    for s in source.sources.all():
        CardSource.objects.create(card=target, label=s.label, title=s.title,
                                  citation=s.citation, url=s.url, article=s.article,
                                  order=s.order)
    for f in source.forbidden_statements.all():
        ForbiddenStatement.objects.create(card=target, text=f.text, note=f.note)
    for sc in source.scenarios.all():
        new = ContextScenario.objects.create(card=target, kind=sc.kind, title=sc.title,
                                             statement=sc.statement, condition=sc.condition,
                                             is_active=sc.is_active, order=sc.order)
        for st in sc.texts.all():
            ScenarioText.objects.create(scenario=new, genotype=st.genotype, text=st.text)
