"""
Návrhy genových karet ze souborů katalog/karty/*.json.

Karta připravená mimo aplikaci (návrh znění k revizi) se dostane ke garantovi
bez opisování: soubor nese variantu a její verze (původní znění z podkladů
a návrh). Příkaz běží při každé aktualizaci (spustit.bat, deploy/pa-update.sh)
a založí jen varianty, které v katalogu ještě nejsou – nic nepřepisuje.
Dál kartu vede průvodce kartou; schválení je na garantovi.

Dvě výjimky pro karty, které už v katalogu jsou: kombinace variant
(„interakce“) ze souboru se ke kartě založí jednou – smazaná se znovu
nevrátí; a přehled změn neschváleného návrhu se doplní, jen když ho nikdo
neupravil (text v katalogu je začátkem textu v souboru).
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max

from apps.genetics.cards_import import RSID_FIXES
from apps.genetics.models import (
    Domain,
    GeneCard,
    GeneInteraction,
    GenePanel,
    GeneVariant,
    PanelItem,
)
from apps.genetics.seed import seed_genetics
from apps.genetics.transfer import _children, _fields

FOLDER = Path(settings.BASE_DIR) / "katalog" / "karty"
FORMAT = "navrh-karty/1"
PANEL_CODE = "panel-laboratore"


def _panel():
    panel = GenePanel.objects.filter(is_active=True).order_by("organization_id", "pk").first()
    return panel or GenePanel.objects.create(organization=None, code=PANEL_CODE,
                                             name="Panel laboratoře")


@transaction.atomic
def load_draft(data: dict) -> list[str]:
    """Založí varianty a karty ze souboru; vrací popis toho, co vzniklo."""
    if data.get("format") != FORMAT:
        raise ValueError(f"Neznámý formát souboru ({data.get('format')!r}).")
    seed_genetics()  # oblasti a dotazník, na který se scénáře napojují
    out, cards = [], {}
    for item in data.get("varianty", []):
        if GeneVariant.objects.filter(rsid=item["rsid"]).exists():
            out.append(f"{item['gene']} / {item['rsid']}: už v katalogu, nechávám být")
            continue
        domain = Domain.objects.filter(code=item["oblast"]).order_by("organization_id").first()
        if domain is None:
            raise ValueError(f"Oblast „{item['oblast']}“ pro variantu {item['rsid']} neexistuje.")
        order = (GeneVariant.objects.aggregate(m=Max("order"))["m"] or 0) + 1
        variant = GeneVariant.objects.create(
            organization=None, domain=domain,
            **{**_fields(item, "oblast", "order"), "order": order})
        for card_item in [c for c in data.get("karty", []) if c["varianta"] == variant.rsid]:
            card = GeneCard.objects.create(
                organization=None, variant=variant,
                **_fields(card_item, "varianta", "nahrazuje", "texty", "doporuceni", "dukazy",
                          "zdroje", "nepripustne", "scenare", "revize"))
            _children(card, card_item)
            cards[(variant.rsid, card.version)] = (card, card_item.get("nahrazuje"))
        panel = _panel()
        PanelItem.objects.get_or_create(
            panel=panel, variant=variant,
            defaults={"order": panel.items.count() + 1, "lab_label": variant.notation[:120],
                      "genotype_map": {a: g for g, a in variant.genotype_aliases.items() if a}})
        versions = ", ".join(f"v{c.version} {c.get_status_display().lower()}"
                             for c, _ in cards.values() if c.variant_id == variant.pk)
        out.append(f"{variant.label}: založeno ({versions}); panel {panel.name}")
    for card, ref in cards.values():
        if ref and (ref["varianta"], ref["verze"]) in cards:
            card.supersedes = cards[(ref["varianta"], ref["verze"])][0]
            card.save(update_fields=["supersedes"])
    out += _change_summaries(data, created=cards)
    out += _interactions(data)
    return out


def _card(ref: dict | None):
    if not ref:
        return None
    return (GeneCard.objects.filter(variant__rsid=ref["varianta"], version=ref["verze"])
            .select_related("variant").order_by("organization_id").first())


def _change_summaries(data: dict, *, created) -> list[str]:
    """Přehled změn neschváleného návrhu doplní, jen když v katalogu nikdo text neupravil."""
    out = []
    for item in data.get("karty", []):
        if (item["varianta"], item["version"]) in created:
            continue
        card = _card({"varianta": item["varianta"], "verze": item["version"]})
        wanted = (item.get("change_summary") or "").strip()
        if card is None or card.status not in (GeneCard.Status.DRAFT, GeneCard.Status.REVIEW):
            continue
        current = card.change_summary.strip()
        if wanted and current != wanted and wanted.startswith(current):
            card.change_summary = wanted
            card.save(update_fields=["change_summary", "updated_at"])
            out.append(f"{card.label}: doplněn přehled změn ze souboru")
    return out


def _interactions(data: dict) -> list[str]:
    """
    Kombinace variant ze souboru: ke kartě jednou (příznak na kartě), jako
    hypotézy k posouzení. Karta, která kombinace už má (převod z Wordu),
    se jen označí a opraví se u ní známý chybný identifikátor.
    """
    by_card: dict = {}
    for item in data.get("interakce", []):
        card = _card(item.get("karta"))
        if card is not None:
            by_card.setdefault(card.pk, (card, []))[1].append(item)
    out = []
    for card, items in by_card.values():
        if card.interactions_loaded:
            continue
        existing = list(card.interactions.all())
        if existing:
            for row in existing:
                _fix_rsids(row)
        else:
            order = GeneInteraction.objects.filter(organization=None).count()
            for item in items:
                order += 1
                GeneInteraction.objects.create(
                    organization=None, source_card=card,
                    **{**_fields(item, "karta", "order"), "order": order})
            out.append(f"{card.label}: {len(items)} kombinací variant (hypotézy k posouzení)")
        card.interactions_loaded = True
        card.save(update_fields=["interactions_loaded"])
    return out


def _fix_rsids(row) -> None:
    variants = list(row.variants or [])
    notes = []
    for wrong, (right, note) in RSID_FIXES.items():
        if wrong in variants:
            variants = sorted((set(variants) - {wrong}) | {right})
            notes.append(note)
    if notes:
        row.variants = variants
        row.evidence = "\n".join([row.evidence.strip(), *notes]).strip()
        row.save(update_fields=["variants", "evidence", "updated_at"])


class Command(BaseCommand):
    help = "Načte návrhy genových karet z katalog/karty/*.json (jen varianty, které chybí)."

    def add_arguments(self, parser):
        parser.add_argument("soubory", nargs="*", help="Konkrétní soubory; prázdné = celá složka.")

    def handle(self, *args, **options):
        paths = [Path(p) for p in options["soubory"]] or sorted(FOLDER.glob("*.json"))
        if not paths:
            self.stdout.write("Žádné návrhy karet (katalog/karty/*.json).")
            return
        for path in paths:
            if not path.is_file():
                raise CommandError(f"Soubor {path} neexistuje.")
            try:
                lines = load_draft(json.loads(path.read_text(encoding="utf-8")))
            except (ValueError, KeyError) as exc:
                raise CommandError(f"{path.name}: soubor nejde načíst: {exc}") from exc
            for line in lines:
                self.stdout.write(f"{path.name}: {line}")
