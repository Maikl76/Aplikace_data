"""
Průvodce kartou: nová karta a osm kroků místo jednoho dlouhého formuláře.

Karta vzniká a reviduje se v aplikaci: „Nová karta“ založí variantu a první
návrh, každý krok má jediný formulář, vedle polí je vidět původní znění
z podkladů (nebo předchozí verze) a připomínka, co se v tom kroku nesmí.
Stav kroků plyne z dat (apps/genetics/card_steps.py). Načtení z Wordu je
jen zkratka, která stejné karty založí najednou.
"""

import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.catalog.models import Protocol, Question
from apps.core.audit import record
from apps.core.models import AuditLog

from . import seed, services
from .card_steps import HINTS, STEPS, TITLES, card_steps, next_slug
from .models import (
    CardEvidence,
    CardRevision,
    CardSource,
    ContextScenario,
    Domain,
    ForbiddenStatement,
    GeneCard,
    GeneVariant,
    GenotypeText,
    Recommendation,
    ScenarioText,
)
from .setup_views import _may_setup, _panel_for
from .views import _catalog, _denied, _is_admin

BLANK_ROWS = 2
VARIANT_FIELDS = ("gene", "rsid", "full_name", "domain", "genotypes", "aliases", "notation",
                  "subtitle", "strand_note", "frequency_source")
READONLY = ("Tahle verze karty je jen ke čtení – upravit jde jen návrh nebo kartu v revizi "
            "(tlačítko Nová verze).")


# --- varianta: společné pro novou kartu i krok 1 -------------------------------------

def _tokens(text: str) -> list[str]:
    seen, out = set(), []
    for token in re.split(r"[,\s;]+", (text or "").upper()):
        token = token.strip()[:16]
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _parse_aliases(text: str, genotypes: list[str]) -> tuple[dict, list[str]]:
    """„CC=RR, CT=RX“ (nebo „RR=CC“) → {"CC": "RR", "CT": "RX"}; cizí genotyp je chyba."""
    mapping, errors = {}, []
    for part in [p for p in re.split(r"[,;\n]", text or "") if p.strip()]:
        for sep in ("=", "→", "->", ":"):
            if sep in part:
                left, right = (s.strip().upper() for s in part.split(sep, 1))
                break
        else:
            errors.append(f"Jiný zápis „{part.strip()}“ nemá tvar genotyp=zápis.")
            continue
        if left in genotypes:
            mapping[left] = right
        elif right in genotypes:
            mapping[right] = left
        else:
            errors.append(f"Jiný zápis „{part.strip()}“: ani {left} ani {right} není genotyp "
                          f"varianty ({', '.join(genotypes)}).")
    return mapping, errors


def _variant_form(variant=None) -> dict:
    if variant is None:
        return dict.fromkeys(VARIANT_FIELDS, "")
    return {
        "gene": variant.gene, "rsid": variant.rsid, "full_name": variant.full_name,
        "domain": str(variant.domain_id), "genotypes": ", ".join(variant.genotypes),
        "aliases": ", ".join(f"{g}={a}" for g, a in variant.genotype_aliases.items() if a),
        "notation": variant.notation, "subtitle": variant.subtitle,
        "strand_note": variant.strand_note, "frequency_source": variant.frequency_source,
    }


def _variant_values(form: dict, domains, user, variant=None) -> tuple[dict, list[str]]:
    errors = []
    gene, rsid = form["gene"][:32].upper(), form["rsid"][:32]
    if rsid[:2].lower() == "rs":
        rsid = "rs" + rsid[2:]  # gen velkými, rsID malým „rs“ – jak to píše literatura
    if not gene:
        errors.append("Doplňte gen (např. ACTN3).")
    if not rsid:
        errors.append("Doplňte rsID varianty (např. rs1815739).")
    else:
        others = _catalog(GeneVariant, user).filter(rsid__iexact=rsid)
        if variant is not None:
            others = others.exclude(pk=variant.pk)
        if others.exists():
            errors.append(f"Varianta s rsID {rsid} v katalogu už je – každá varianta má jednu kartu.")
    domain = next((d for d in domains if str(d.pk) == form["domain"]), None)
    if domain is None:
        errors.append("Vyberte oblast – podle ní se najde garant, který kartu schvaluje.")
    genotypes = _tokens(form["genotypes"])
    if len(genotypes) < 2:
        errors.append("Zadejte aspoň dva genotypy oddělené čárkou, např. CC, CT, TT.")
    aliases, alias_errors = _parse_aliases(form["aliases"], genotypes)
    errors += alias_errors
    values = {
        "gene": gene, "rsid": rsid, "full_name": form["full_name"][:200], "domain": domain,
        "genotypes": genotypes, "genotype_aliases": aliases, "notation": form["notation"][:200],
        "subtitle": form["subtitle"][:200], "strand_note": form["strand_note"],
        "frequency_source": form["frequency_source"][:500],
    }
    return values, errors


def _domains(user):
    seed.seed_domains()
    return list(_catalog(Domain, user).filter(is_active=True).order_by("order", "name"))


@login_required
def card_new(request):
    """Nová varianta a její první návrh karty; dál vede průvodce kartou."""
    if not _may_setup(request.user):
        return _denied(request, "Kartu zakládá správce nebo laborant.")
    domains = _domains(request.user)
    form, errors = _variant_form(), []
    if request.method == "POST":
        form = {k: request.POST.get(k, "").strip() for k in VARIANT_FIELDS}
        values, errors = _variant_values(form, domains, request.user)
        if not errors:
            with transaction.atomic():
                last = _catalog(GeneVariant, request.user).order_by("-order").first()
                variant = GeneVariant.objects.create(
                    organization=None, order=(last.order if last else 0) + 1, **values)
                card = GeneCard.objects.create(organization=None, variant=variant, version=1,
                                               status=GeneCard.Status.DRAFT,
                                               created_by=request.user)
                _panel_for(request.user)
            record(request, AuditLog.Action.CREATE, card, karta=str(card), akce="nova_karta")
            messages.success(request, f"Karta {variant.label} je založená jako návrh. Projděte "
                                      "kroky průvodce – začněte tím, co gen dělá.")
            return redirect("genetics_card_step", pk=card.pk, krok="gen")
        for error in errors:
            messages.error(request, error)
    return render(request, "genetics/card_new.html", {"form": form, "domains": domains})


# --- načtení karty k úpravě ------------------------------------------------------------

def _load(request, pk):
    """Karta k úpravě, nebo odpověď (403 / přesměrování), když upravit nejde."""
    if not _may_setup(request.user):
        return None, _denied(request, "Kartu upravuje správce nebo laborant (garant).")
    card = get_object_or_404(
        _catalog(GeneCard, request.user).select_related("variant", "variant__domain"), pk=pk)
    if not card.is_editable:
        messages.info(request, READONLY)
        return None, redirect("genetics_card", pk=pk)
    return card, None


def _original(card):
    """Znění, se kterým se při revizi srovnává: z podkladů (v1), jinak předchozí verze."""
    original = (card.variant.cards.filter(status=GeneCard.Status.ORIGINAL)
                .exclude(pk=card.pk).order_by("version").first())
    if original is None and card.supersedes_id and card.supersedes_id != card.pk:
        original = card.supersedes
    if original is None:
        return None, ""
    label = ("Původní znění z podkladů" if original.status == GeneCard.Status.ORIGINAL
             else f"Předchozí verze (v{original.version})")
    return original, label


@login_required
def card_wizard(request, pk):
    """Přehled kroků karty: co je hotové, co chybí, kam dál."""
    card, response = _load(request, pk)
    if response is not None:
        return response
    original, original_label = _original(card)
    return render(request, "genetics/card_wizard.html", {
        "card": card, "variant": card.variant, "steps": card_steps(card),
        "original": original, "original_label": original_label,
        "open_revisions": card.revisions.filter(decision=CardRevision.Decision.OPEN).count(),
    })


# --- kroky ----------------------------------------------------------------------------

def _trigger_options():
    """Odpovědi dotazníku, které mohou spouštět scénář: „otázka → možnost“."""
    questionnaire = seed.seed_questionnaire()
    out = []
    for q in Question.objects.filter(questionnaire=questionnaire).order_by("order"):
        if q.kind in (Question.Kind.CHOICE, Question.Kind.MULTI):
            out += [(f"{q.code}|{o['code']}", f"{q.text} → {o['label']}") for o in q.options]
        elif q.kind == Question.Kind.YESNO:
            out += [(f"{q.code}|1", f"{q.text} → ano"), (f"{q.code}|0", f"{q.text} → ne")]
    return out


def _trigger_value(scenario) -> str:
    if scenario.question_id is None or not scenario.answer_match:
        return ""
    match = scenario.answer_match
    if match.get("choices"):
        return f"{scenario.question.code}|{match['choices'][0]}"
    if "value" in match:
        return f"{scenario.question.code}|{int(match['value'])}"
    return ""


def _apply_trigger(scenario, value: str) -> bool:
    """Nastaví otázku a shodu odpovědi podle „kód|možnost“. Prázdné nic nemění."""
    if not value:
        return True
    code, _, option = value.partition("|")
    question = Question.objects.filter(questionnaire__code=seed.QUESTIONNAIRE_CODE, code=code).first()
    if question is None:
        return False
    scenario.question = question
    if question.kind == Question.Kind.YESNO:
        scenario.answer_match = {"value": 1 if option == "1" else 0}
    else:
        scenario.answer_match = {"choices": [option]}
    return True


def _genotype_rows(card, original):
    variant = card.variant
    texts = {t.genotype: t for t in card.genotype_texts.all()}
    before = {t.genotype: t for t in original.genotype_texts.all()} if original else {}
    return [{"code": g, "label": variant.genotype_label(g), "text": texts.get(g),
             "original": before.get(g)} for g in variant.genotypes]


def _scenario_rows(card, original):
    variant = card.variant
    rows = list(card.scenarios.select_related("question").prefetch_related("texts")
                .order_by("order", "pk"))
    before = {}
    if original:
        for s in original.scenarios.prefetch_related("texts"):
            before[s.statement.strip().lower()] = {t.genotype: t.text for t in s.texts.all()}
    for s in rows:
        s.trigger = _trigger_value(s)
        texts = {t.genotype: t.text for t in s.texts.all()}
        was = before.get(s.statement.strip().lower(), {})
        s.rows = [{"code": g, "label": variant.genotype_label(g), "text": texts.get(g, ""),
                   "original": was.get(g, "")} for g in variant.genotypes]
    return rows


def _context_varianta(card, request, original):
    variant = card.variant
    locked = (variant.cards.filter(status=GeneCard.Status.APPROVED).exists()
              or variant.subject_genotypes.exists())
    return {"form": _variant_form(variant), "domains": _domains(request.user), "locked": locked}


def _context_gen(card, request, original):
    return {}


def _context_genotypy(card, request, original):
    return {"genotypes": _genotype_rows(card, original)}


def _context_doporuceni(card, request, original):
    recommendations = list(card.recommendations.select_related("protocol").order_by("order", "pk"))
    return {
        "genotypes": _genotype_rows(card, None), "recommendations": recommendations,
        "blank_rows": range(len(recommendations), len(recommendations) + BLANK_ROWS),
        "rec_count": len(recommendations) + BLANK_ROWS,
        "kinds": Recommendation.Kind.choices, "bases": Recommendation.Basis.choices,
        "protocols": _catalog(Protocol, request.user).filter(is_active=True).order_by("name"),
        "original_recs": list(original.recommendations.order_by("order", "pk")) if original else [],
    }


def _context_kontext(card, request, original):
    return {"scenarios": _scenario_rows(card, original), "triggers": _trigger_options(),
            "genotypes": _genotype_rows(card, None), "new_rows": range(1), "nsc_count": 1}


def _context_vyroky(card, request, original):
    shared = list(ForbiddenStatement.objects.filter(card__isnull=True).order_by("pk"))
    return {"forbidden": "\n".join(card.forbidden_statements.values_list("text", flat=True)),
            "shared": shared, "shared_text": "\n".join(s.text for s in shared),
            "is_admin": _is_admin(request.user),
            "original_forbidden": list(original.forbidden_statements.all()) if original else []}


def _context_zdroje(card, request, original):
    sources = list(card.sources.select_related("article").order_by("order", "pk"))
    evidence = list(card.evidence.select_related("article").order_by("order", "pk"))
    return {
        "sources": sources, "src_blank": range(len(sources), len(sources) + BLANK_ROWS),
        "src_count": len(sources) + BLANK_ROWS,
        "evidence": evidence, "ev_blank": range(len(evidence), len(evidence) + BLANK_ROWS),
        "ev_count": len(evidence) + BLANK_ROWS,
        "original_sources": list(original.sources.all()) if original else [],
    }


def _context_kontrola(card, request, original):
    return {"checklist": services.checklist(card), "revisions": card.revisions.all(),
            "decisions": CardRevision.Decision.choices,
            "may_approve": services.may_approve(request.user, card),
            "guarantors": list(card.variant.domain.guarantors.all())}


CONTEXTS = {
    "varianta": _context_varianta, "gen": _context_gen, "genotypy": _context_genotypy,
    "doporuceni": _context_doporuceni, "kontext": _context_kontext, "vyroky": _context_vyroky,
    "zdroje": _context_zdroje, "kontrola": _context_kontrola,
}


@login_required
def card_step(request, pk, krok):
    if krok not in STEPS:
        raise Http404
    card, response = _load(request, pk)
    if response is not None:
        return response
    if request.method == "POST":
        action = request.POST.get("akce", "ulozit")
        with transaction.atomic():
            problems = SAVERS[krok](card, request)
        for problem in problems:
            messages.warning(request, problem)
        record(request, AuditLog.Action.UPDATE, card, karta=str(card), krok=krok, akce=action)
        if krok == "kontrola" and action in ("k_revizi", "vratit", "schvalit"):
            return _control_action(request, card, action)
        if krok == "varianta" and problems:
            return redirect("genetics_card_step", pk=pk, krok=krok)  # neuloženo – opravit
        messages.success(request, f"{TITLES[krok]}: uloženo.")
        if action == "dalsi" and next_slug(krok):
            return redirect("genetics_card_step", pk=pk, krok=next_slug(krok))
        if action == "prehled":
            return redirect("genetics_card_edit", pk=pk)
        return redirect("genetics_card_step", pk=pk, krok=krok)
    original, original_label = _original(card)
    context = CONTEXTS[krok](card, request, original)
    following = next_slug(krok)
    context.update({
        "card": card, "variant": card.variant, "slug": krok, "n": STEPS.index(krok) + 1,
        "title": TITLES[krok], "hint": HINTS[krok], "steps": card_steps(card),
        "next": following, "next_title": TITLES.get(following, ""),
        "original": original, "original_label": original_label,
        "forbidden_all": (list(card.forbidden_statements.values_list("text", flat=True))
                          + list(ForbiddenStatement.objects.filter(card__isnull=True)
                                 .values_list("text", flat=True)))
        if krok in ("gen", "genotypy", "doporuceni", "kontext") else [],
        "step_template": f"genetics/steps/_{krok}.html",
    })
    return render(request, "genetics/card_step.html", context)


def _control_action(request, card, action):
    try:
        if action == "k_revizi":
            services.submit_for_review(card)
            messages.success(request, f"Karta {card} čeká na garanta oblasti "
                                      f"„{card.variant.domain}“.")
            return redirect("genetics_card", pk=card.pk)
        if action == "vratit":
            services.return_to_draft(card)
            messages.info(request, f"Karta {card} je zase návrh k úpravě.")
        if action == "schvalit":
            services.approve(card, by=request.user)
            messages.success(request, f"Karta {card} je schválená – od teď je to jediné znění, "
                                      "které smí do zpráv.")
            return redirect("genetics_card", pk=card.pk)
    except PermissionError as exc:
        return _denied(request, str(exc))
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("genetics_card_step", pk=card.pk, krok="kontrola")


# --- ukládání jednotlivých kroků ----------------------------------------------------------

def _save_varianta(card, request) -> list[str]:
    variant = card.variant
    form = {k: request.POST.get(k, "").strip() for k in VARIANT_FIELDS}
    if (variant.cards.filter(status=GeneCard.Status.APPROVED).exists()
            or variant.subject_genotypes.exists()):
        form["genotypes"] = ", ".join(variant.genotypes)  # genotypy se u používané varianty nemění
    values, errors = _variant_values(form, _domains(request.user), request.user, variant)
    if errors:
        return errors
    for name, value in values.items():
        setattr(variant, name, value)
    variant.save()
    return []


def _save_gen(card, request) -> list[str]:
    post = request.POST
    card.biology_client = post.get("biology_client", "").strip()
    card.biology_expert = post.get("biology_expert", "").strip()
    card.effect = post.get("effect", "").strip()
    card.limitations = post.get("limitations", "").strip()
    card.save(update_fields=["biology_client", "biology_expert", "effect", "limitations",
                             "updated_at"])
    return []


def _save_genotypy(card, request) -> list[str]:
    post = request.POST
    for order, genotype in enumerate(card.variant.genotypes):
        GenotypeText.objects.update_or_create(
            card=card, genotype=genotype,
            defaults={"client_text": post.get(f"text_{genotype}", "").strip(),
                      "expert_text": post.get(f"expert_{genotype}", "").strip(),
                      "frequency": post.get(f"freq_{genotype}", "").strip()[:200], "order": order})
    card.frequency_note = post.get("frequency_note", "").strip()
    card.save(update_fields=["frequency_note", "updated_at"])
    variant = card.variant
    variant.frequency_source = post.get("frequency_source", "").strip()[:500]
    variant.save(update_fields=["frequency_source"])
    return []


def _save_doporuceni(card, request) -> list[str]:
    """Existující řádky podle id, nové z prázdných řádků, smazání zaškrtnutím nebo prázdným textem."""
    post = request.POST
    count = int(post.get("rec_count", 0) or 0)
    kinds = {k for k, _ in Recommendation.Kind.choices}
    bases = {b for b, _ in Recommendation.Basis.choices}
    for i in range(count):
        text = post.get(f"rec_text_{i}", "").strip()
        rec_id = post.get(f"rec_id_{i}", "")
        existing = card.recommendations.filter(pk=rec_id).first() if rec_id else None
        if existing is not None and (f"rec_delete_{i}" in post or not text):
            existing.delete()
            continue
        if not text:
            continue
        kind = post.get(f"rec_kind_{i}", "other")
        basis = post.get(f"rec_basis_{i}", "")
        protocol_id = post.get(f"rec_protocol_{i}", "")
        fields = {
            "genotype": post.get(f"rec_genotype_{i}", "").strip().upper(),
            "kind": kind if kind in kinds else Recommendation.Kind.OTHER, "text": text,
            "basis": basis if basis in bases else "",
            "merge_key": post.get(f"rec_key_{i}", "").strip()[:64],
            "protocol": Protocol.objects.filter(pk=protocol_id).first() if protocol_id else None,
            "order": i,
        }
        if existing is not None:
            for name, value in fields.items():
                setattr(existing, name, value)
            existing.save()
        else:
            Recommendation.objects.create(card=card, **fields)
    return []


def _scenario_texts(scenario, genotypes, post, prefix):
    for genotype in genotypes:
        text = post.get(f"{prefix}_{genotype}", "").strip()
        if text:
            ScenarioText.objects.update_or_create(scenario=scenario, genotype=genotype,
                                                  defaults={"text": text})
        else:
            scenario.texts.filter(genotype=genotype).delete()


def _activate(scenario, wanted: bool, problems: list[str]) -> bool:
    """Zapnout jde jen scénář, který má co ho spouští; jinak zůstane vypnutý a řekne proč."""
    name = scenario.statement[:40]
    if wanted and scenario.kind == ContextScenario.Kind.QUESTIONNAIRE and not (
            scenario.question_id and scenario.answer_match):
        problems.append(f"Scénář „{name}…“ nejde zapnout bez odpovědi, která ho spouští.")
        return False
    if wanted and scenario.kind == ContextScenario.Kind.MEASUREMENT and not scenario.condition:
        problems.append(f"Scénář „{name}…“ nejde zapnout bez podmínky nad měřením "
                        "(zapisuje se v administraci).")
        return False
    return wanted


def _save_kontext(card, request) -> list[str]:
    post, problems = request.POST, []
    genotypes = card.variant.genotypes
    for scenario in card.scenarios.select_related("question"):
        key = scenario.pk
        statement = post.get(f"sc_statement_{key}", scenario.statement).strip()
        if f"sc_delete_{key}" in post or not statement:
            scenario.delete()
            continue
        scenario.statement = statement
        if not _apply_trigger(scenario, post.get(f"sc_trigger_{key}", "")):
            problems.append(f"Scénář „{statement[:40]}…“: neznámá otázka.")
        scenario.is_active = _activate(scenario, f"sc_active_{key}" in post, problems)
        scenario.save()
        _scenario_texts(scenario, genotypes, post, f"sc_text_{key}")
    order = card.scenarios.count()
    for i in range(int(post.get("nsc_count", 0) or 0)):
        statement = post.get(f"nsc_statement_{i}", "").strip()
        if not statement:
            continue
        scenario = ContextScenario(card=card, kind=ContextScenario.Kind.QUESTIONNAIRE,
                                   statement=statement, order=order + i)
        if not _apply_trigger(scenario, post.get(f"nsc_trigger_{i}", "")):
            problems.append(f"Scénář „{statement[:40]}…“: neznámá otázka.")
        scenario.is_active = _activate(scenario, f"nsc_active_{i}" in post, problems)
        scenario.save()
        _scenario_texts(scenario, genotypes, post, f"nsc_text_{i}")
    return problems


def _lines(text: str) -> list[str]:
    lines = [line.strip(" .„“\"") for line in (text or "").splitlines()]
    return [line[:300] for line in lines if line]


def _save_vyroky(card, request) -> list[str]:
    notes = {s.text: s.note for s in card.forbidden_statements.all()}
    card.forbidden_statements.all().delete()
    for line in _lines(request.POST.get("forbidden", "")):
        ForbiddenStatement.objects.create(card=card, text=line, note=notes.get(line, ""))
    if _is_admin(request.user) and "shared" in request.POST:
        shared = ForbiddenStatement.objects.filter(card__isnull=True)
        notes = {s.text: s.note for s in shared}
        shared.delete()
        for line in _lines(request.POST.get("shared", "")):
            ForbiddenStatement.objects.create(card=None, text=line, note=notes.get(line, ""))
    return []


def _save_rows(card, post, prefix, manager, model, required, fields):
    """Řádky zdrojů a důkazů: podle id upravit, prázdné nové přeskočit, smazat zaškrtnutím."""
    for i in range(int(post.get(f"{prefix}_count", 0) or 0)):
        values = {name: post.get(f"{prefix}_{name}_{i}", "").strip()[:limit]
                  for name, limit in fields.items()}
        row_id = post.get(f"{prefix}_id_{i}", "")
        existing = manager.filter(pk=row_id).first() if row_id else None
        if existing is not None and (f"{prefix}_delete_{i}" in post or not values[required]):
            existing.delete()
            continue
        if not values[required]:
            continue
        values["order"] = i
        if existing is not None:
            for name, value in values.items():
                setattr(existing, name, value)
            existing.save()
        else:
            model.objects.create(card=card, **values)


def _save_zdroje(card, request) -> list[str]:
    _save_rows(card, request.POST, "src", card.sources, CardSource, "citation",
               {"label": 12, "title": 200, "citation": 10_000, "url": 500})
    _save_rows(card, request.POST, "ev", card.evidence, CardEvidence, "trait",
               {"code": 12, "trait": 200, "basis_text": 10_000, "usage": 10_000,
                "source_labels": 120})
    return []


def _save_kontrola(card, request) -> list[str]:
    post = request.POST
    for revision in card.revisions.all():
        decision = post.get(f"rev_decision_{revision.pk}")
        if decision in CardRevision.Decision.values and decision != revision.decision:
            revision.decision = decision
            open_ = decision == CardRevision.Decision.OPEN
            revision.decided_by = None if open_ else request.user
            revision.decided_at = None if open_ else timezone.now()
            revision.save(update_fields=["decision", "decided_by", "decided_at", "updated_at"])
    return []


SAVERS = {
    "varianta": _save_varianta, "gen": _save_gen, "genotypy": _save_genotypy,
    "doporuceni": _save_doporuceni, "kontext": _save_kontext, "vyroky": _save_vyroky,
    "zdroje": _save_zdroje, "kontrola": _save_kontrola,
}
