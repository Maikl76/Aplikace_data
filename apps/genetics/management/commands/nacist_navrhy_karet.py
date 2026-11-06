"""
Návrhy genových karet ze souborů katalog/karty/*.json.

Karta připravená mimo aplikaci (návrh znění k revizi) se dostane ke garantovi
bez opisování: soubor nese variantu a její verze (původní znění z podkladů
a návrh). Příkaz běží při každé aktualizaci (spustit.bat, deploy/pa-update.sh)
a založí jen varianty, které v katalogu ještě nejsou – nic nepřepisuje.
Dál kartu vede průvodce kartou; schválení je na garantovi.
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max

from apps.genetics.models import Domain, GeneCard, GenePanel, GeneVariant, PanelItem
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
    return out


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
