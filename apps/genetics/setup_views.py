"""
Průvodce genetikou: nastavení ve čtyřech krocích a úprava karty přímo
v aplikaci. Administrace Djanga zůstává jen „pro pokročilé“ – běžná práce
(garanti, načtení karet, panel laboratoře, revize karty) se dělá tady,
jedním tlačítkem a s vysvětlením, co se po člověku chce.
"""

import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Protocol, Question
from apps.core.audit import record
from apps.core.models import AuditLog, Role, User

from . import seed, services
from .cards_import import import_cards
from .models import (
    CardRevision,
    ContextScenario,
    Domain,
    ForbiddenStatement,
    GeneCard,
    GenePanel,
    GeneVariant,
    GenotypeText,
    PanelItem,
    Recommendation,
)
from .views import _catalog, _denied, _is_admin

PANEL_CODE = "panel-laboratore"


def _may_setup(user) -> bool:
    return user.is_superuser or user.role in (Role.ADMIN, Role.LAB)


# --- kroky nastavení ---------------------------------------------------------------

def setup_steps(user) -> list[dict]:
    """Stav čtyř kroků nastavení pro stránku Genetika."""
    domains = list(_catalog(Domain, user).filter(is_active=True).prefetch_related("guarantors"))
    with_guarantor = sum(1 for d in domains if d.guarantors.exists())
    variants = list(_catalog(GeneVariant, user).prefetch_related("cards"))
    approved = sum(1 for v in variants
                   if any(c.status == GeneCard.Status.APPROVED for c in v.cards.all()))
    panel = _catalog(GenePanel, user).filter(is_active=True).order_by("pk").first()
    return [
        {"n": 1, "title": "Garanti oblastí", "done": bool(domains) and with_guarantor == len(domains),
         "text": f"{with_guarantor} z {len(domains)} oblastí má garanta – bez garanta nejde "
                 "kartu oblasti schválit.",
         "url": reverse("genetics_setup_guarantors"), "button": "Nastavit garanty",
         "admin_only": True},
        {"n": 2, "title": "Karty z podkladů", "done": bool(variants),
         "text": (f"{len(variants)} variant v katalogu." if variants
                  else "Nahrajte Word s genovými kartami; vzniknou jako návrhy k revizi."),
         "url": reverse("genetics_setup_cards"), "button": "Načíst z Wordu"},
        {"n": 3, "title": "Panel a laboratoř", "done": panel is not None and bool(panel.provider),
         "text": (f"{panel.name}: {panel.items.count()} variant, laboratoř "
                  f"{panel.provider or 'nevyplněna'}." if panel
                  else "Která laboratoř genotypizuje a jak píše genotypy."),
         "url": reverse("genetics_setup_panel"), "button": "Upravit panel"},
        {"n": 4, "title": "Revize a schválení karet",
         "done": bool(variants) and approved == len(variants),
         "text": f"{approved} z {len(variants)} karet schváleno. Do zprávy jde jen schválená karta.",
         "url": "#karty", "button": "Ke kartám"},
    ]


# --- 1. garanti ---------------------------------------------------------------------

@login_required
def setup_guarantors(request):
    if not _is_admin(request.user):
        return _denied(request, "Garanty oblastí nastavuje správce.")
    domains = list(_catalog(Domain, request.user).filter(is_active=True)
                   .prefetch_related("guarantors").order_by("order"))
    people = list(User.objects.filter(organization=request.user.organization, is_active=True,
                                      role__in=(Role.ADMIN, Role.LAB)).order_by("last_name", "username"))
    if request.method == "POST":
        for domain in domains:
            chosen = request.POST.getlist(f"garant_{domain.pk}")
            domain.guarantors.set([p for p in people if str(p.pk) in chosen])
        record(request, AuditLog.Action.UPDATE, request.user.organization, genetika="garanti")
        messages.success(request, "Garanti oblastí jsou uložení.")
        return redirect("genetics_home")
    rows = [{"domain": d, "chosen": {u.pk for u in d.guarantors.all()}} for d in domains]
    return render(request, "genetics/setup_guarantors.html", {"rows": rows, "people": people})


# --- 2. karty z Wordu ---------------------------------------------------------------

@login_required
def setup_cards(request):
    if not _may_setup(request.user):
        return _denied(request, "Karty načítá správce nebo laborant.")
    variants = _catalog(GeneVariant, request.user).count()
    if request.method == "POST":
        upload = request.FILES.get("soubor")
        if settings.DEMO_MODE:
            messages.error(request, "Toto je veřejná ukázka, nahrávání souborů je v ní vypnuté.")
            return redirect("genetics_setup_cards")
        if upload is None or not upload.name.lower().endswith(".docx"):
            messages.error(request, "Vyberte soubor Word (.docx) s genovými kartami.")
            return redirect("genetics_setup_cards")
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as handle:
            for chunk in upload.chunks():
                handle.write(chunk)
            path = Path(handle.name)
        try:
            seed.seed_domains()
            result = import_cards(path, organization=None, user=request.user)
        except Exception as exc:  # poškozený nebo cizí soubor – uživatel se musí dozvědět co
            messages.error(request, f"Soubor nejde načíst: {exc}")
            return redirect("genetics_setup_cards")
        finally:
            path.unlink(missing_ok=True)
        record(request, AuditLog.Action.CREATE, request.user.organization, genetika="karty",
               zalozeno=len(result.created), preskoceno=len(result.skipped))
        if result.created:
            messages.success(request, "Načteno: " + ", ".join(result.created)
                             + ". Karty jsou návrhy k revizi – každou otevřete a upravte.")
        if result.skipped:
            messages.info(request, "Už v katalogu (nepřepsáno): " + ", ".join(result.skipped))
        if not result.created and not result.skipped:
            messages.warning(request, "V souboru nebyla žádná karta (nadpis 1 ve tvaru „GEN / rsID“).")
        return redirect("genetics_home")
    return render(request, "genetics/setup_cards.html", {"variants": variants,
                                                          "demo": settings.DEMO_MODE})


# --- 3. panel a laboratoř -------------------------------------------------------------

def _parse_map(text: str, variant) -> tuple[dict, list[str]]:
    """„RR=CC, RX=CT“ → {"RR": "CC", "RX": "CT"}; neznámý genotyp je chyba."""
    mapping, errors = {}, []
    for part in [p for p in text.replace("\n", ",").replace(";", ",").split(",") if p.strip()]:
        for sep in ("=", "→", "->", ":"):
            if sep in part:
                lab, canonical = (s.strip().upper() for s in part.split(sep, 1))
                break
        else:
            errors.append(f"{variant.gene}: zápis „{part.strip()}“ nemá tvar zápis=genotyp.")
            continue
        if canonical not in [g.upper() for g in variant.genotypes]:
            errors.append(f"{variant.gene}: genotyp „{canonical}“ varianta nemá "
                          f"({', '.join(variant.genotypes)}).")
            continue
        mapping[lab] = canonical
    return mapping, errors


def _panel_for(user):
    panel = _catalog(GenePanel, user).filter(is_active=True).order_by("pk").first()
    if panel is None:
        panel = GenePanel.objects.create(organization=None, code=PANEL_CODE,
                                         name="Panel laboratoře")
    known = set(panel.items.values_list("variant_id", flat=True))
    for order, variant in enumerate(_catalog(GeneVariant, user).order_by("order", "gene"), start=1):
        if variant.pk not in known:
            PanelItem.objects.create(panel=panel, variant=variant, order=order,
                                     genotype_map={a: g for g, a in variant.genotype_aliases.items()})
    return panel


@login_required
def setup_panel(request):
    if not _may_setup(request.user):
        return _denied(request, "Panel upravuje správce nebo laborant.")
    panel = _panel_for(request.user)
    items = list(panel.items.select_related("variant", "variant__domain").order_by("order", "pk"))
    if request.method == "POST":
        errors = []
        with transaction.atomic():
            panel.provider = request.POST.get("laborator", "").strip()[:200]
            panel.save(update_fields=["provider", "updated_at"])
            for item in items:
                variant = item.variant
                variant.is_active = f"aktivni_{variant.pk}" in request.POST
                variant.save(update_fields=["is_active"])
                mapping, item_errors = _parse_map(request.POST.get(f"zapis_{variant.pk}", ""), variant)
                errors += item_errors
                if not item_errors:
                    item.genotype_map = mapping
                    item.lab_label = request.POST.get(f"oznaceni_{variant.pk}", "").strip()[:120]
                    item.save(update_fields=["genotype_map", "lab_label"])
        record(request, AuditLog.Action.UPDATE, panel, genetika="panel")
        if errors:
            messages.warning(request, "Uloženo, ale některé zápisy neprošly: " + " ".join(errors))
        else:
            messages.success(request, "Panel a laboratoř jsou uložené.")
        return redirect("genetics_home")
    rows = [{"item": i, "variant": i.variant,
             "zapis": ", ".join(f"{k}={v}" for k, v in (i.genotype_map or {}).items())}
            for i in items]
    return render(request, "genetics/setup_panel.html", {"panel": panel, "rows": rows})


# --- 4. úprava karty ------------------------------------------------------------------

BLANK_ROWS = 2


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


def _editor_context(card, request):
    variant = card.variant
    texts = {t.genotype: t for t in card.genotype_texts.all()}
    recommendations = list(card.recommendations.select_related("protocol").order_by("order", "pk"))
    scenarios = list(card.scenarios.select_related("question").order_by("order", "pk"))
    for scenario in scenarios:
        scenario.trigger = _trigger_value(scenario)
    return {
        "card": card, "variant": variant,
        "genotypes": [{"code": g, "label": variant.genotype_label(g), "text": texts.get(g)}
                      for g in variant.genotypes],
        "recommendations": recommendations,
        "blank_rows": range(len(recommendations), len(recommendations) + BLANK_ROWS),
        "rec_count": len(recommendations) + BLANK_ROWS,
        "kinds": Recommendation.Kind.choices, "bases": Recommendation.Basis.choices,
        "protocols": _catalog(Protocol, request.user).filter(is_active=True).order_by("name"),
        "scenarios": scenarios, "triggers": _trigger_options(),
        "forbidden": "\n".join(card.forbidden_statements.values_list("text", flat=True)),
        "revisions": card.revisions.all(), "decisions": CardRevision.Decision.choices,
        "checklist": services.checklist(card),
        "may_approve": services.may_approve(request.user, card),
    }


@login_required
def card_edit(request, pk):
    """Úprava rozpracované karty v aplikaci – jen to, co zpráva skutečně používá."""
    if not _may_setup(request.user):
        return _denied(request, "Kartu upravuje správce nebo laborant (garant).")
    card = get_object_or_404(_catalog(GeneCard, request.user).select_related("variant", "variant__domain"),
                             pk=pk)
    if not card.is_editable:
        messages.info(request, "Tahle verze karty je jen ke čtení – upravit jde jen návrh "
                               "nebo kartu v revizi (tlačítko Nová verze).")
        return redirect("genetics_card", pk=pk)
    if request.method == "POST":
        problems = _save_card(card, request)
        for problem in problems:
            messages.warning(request, problem)
        record(request, AuditLog.Action.UPDATE, card, karta=str(card), akce="uprava")
        if request.POST.get("akce") == "k_revizi" and card.status == GeneCard.Status.DRAFT:
            services.submit_for_review(card)
            messages.success(request, f"Karta {card} je uložená a čeká na garanta oblasti "
                                      f"„{card.variant.domain}“.")
            return redirect("genetics_card", pk=pk)
        messages.success(request, "Karta je uložená.")
        if request.POST.get("akce") == "ulozit_zpet":
            return redirect("genetics_card", pk=pk)
        return redirect("genetics_card_edit", pk=pk)
    return render(request, "genetics/card_edit.html", _editor_context(card, request))


@transaction.atomic
def _save_card(card, request) -> list[str]:
    post = request.POST
    problems = []
    card.biology_client = post.get("biology_client", "").strip()
    card.biology_expert = post.get("biology_expert", "").strip()
    card.limitations = post.get("limitations", "").strip()
    card.save(update_fields=["biology_client", "biology_expert", "limitations", "updated_at"])
    for order, genotype in enumerate(card.variant.genotypes):
        GenotypeText.objects.update_or_create(
            card=card, genotype=genotype,
            defaults={"client_text": post.get(f"text_{genotype}", "").strip(),
                      "expert_text": post.get(f"expert_{genotype}", "").strip(),
                      "frequency": post.get(f"freq_{genotype}", "").strip()[:200], "order": order})
    # doporučení: existující podle id, nové z prázdných řádků, smazání zaškrtnutím
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
    # scénáře: aktivní jen s otázkou a odpovědí (dotazník) nebo podmínkou (měření)
    for scenario in card.scenarios.select_related("question"):
        wanted = f"sc_active_{scenario.pk}" in post
        if not _apply_trigger(scenario, post.get(f"sc_trigger_{scenario.pk}", "")):
            problems.append(f"Scénář „{scenario.statement[:40]}…“: neznámá otázka.")
        if wanted and scenario.kind == ContextScenario.Kind.QUESTIONNAIRE and not (
                scenario.question_id and scenario.answer_match):
            problems.append(f"Scénář „{scenario.statement[:40]}…“ nejde zapnout bez odpovědi, "
                            "která ho spouští.")
            wanted = False
        if wanted and scenario.kind == ContextScenario.Kind.MEASUREMENT and not scenario.condition:
            problems.append(f"Scénář „{scenario.statement[:40]}…“ nejde zapnout bez podmínky "
                            "nad měřením (zapisuje se v administraci).")
            wanted = False
        scenario.is_active = wanted
        scenario.save()
    # nepřípustné výroky: jeden na řádek
    lines = [line.strip(" .„“\"") for line in post.get("forbidden", "").splitlines()]
    lines = [line for line in lines if line]
    card.forbidden_statements.all().delete()
    for line in lines:
        ForbiddenStatement.objects.create(card=card, text=line[:300])
    # revizní záznamy: rozhodnutí
    for revision in card.revisions.all():
        decision = post.get(f"rev_decision_{revision.pk}")
        if decision in CardRevision.Decision.values and decision != revision.decision:
            revision.decision = decision
            revision.decided_by = request.user if decision != CardRevision.Decision.OPEN else None
            revision.decided_at = timezone.now() if decision != CardRevision.Decision.OPEN else None
            revision.save(update_fields=["decision", "decided_by", "decided_at", "updated_at"])
    return problems


# --- jak to funguje ---------------------------------------------------------------------

@login_required
def guide(request):
    return render(request, "genetics/guide.html", {"steps": setup_steps(request.user)})
