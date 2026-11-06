"""
Průvodce genetikou: nastavení ve čtyřech krocích. Administrace Djanga
zůstává jen „pro pokročilé“ – běžná práce (garanti, karty, panel laboratoře)
se dělá tady, jedním tlačítkem a s vysvětlením, co se po člověku chce.
Kartu samotnou vede průvodce kartou (apps/genetics/card_wizard.py).
"""

import tempfile
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.core.audit import record
from apps.core.models import AuditLog, Role, User

from . import seed
from .cards_import import import_cards
from .models import (
    Domain,
    GeneCard,
    GenePanel,
    GeneVariant,
    PanelItem,
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
        {"n": 2, "title": "Genové karty", "done": bool(variants),
         "text": (f"{len(variants)} variant v katalogu; další kartu založí Nová karta."
                  if variants
                  else "Založte první kartu – průvodce vede krok za krokem. Word s podklady "
                       "je zkratka, která založí všechny karty najednou."),
         "url": reverse("genetics_card_new"), "button": "Nová karta"},
        {"n": 3, "title": "Panel a laboratoř", "done": panel is not None and bool(panel.provider),
         "text": (f"{panel.name}: {panel.items.count()} variant, laboratoř "
                  f"{panel.provider or 'nevyplněna'}." if panel
                  else "Která laboratoř genotypizuje a jak píše genotypy."),
         "url": reverse("genetics_setup_panel"), "button": "Upravit panel"},
        {"n": 4, "title": "Revize a schválení karet",
         "done": bool(variants) and approved == len(variants),
         "text": f"{approved} z {len(variants)} karet schváleno. Do zprávy jde jen schválená "
                 "karta; každou vede průvodce kartou v osmi krocích.",
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
    return render(request, "genetics/setup_cards.html", {"variants": variants})


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


# --- jak to funguje ---------------------------------------------------------------------

@login_required
def guide(request):
    return render(request, "genetics/guide.html", {"steps": setup_steps(request.user)})
