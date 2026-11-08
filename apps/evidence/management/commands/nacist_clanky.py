"""
Články ke genovým kartám ze souborů katalog/clanky/*.json.

Studie citované v genových kartách (a několik doplňkových, které karty
výslovně postrádají) připravené mimo aplikaci: DOI, PMID, název, autoři,
abstrakt, navržené hlavní zjištění pro praxi, omezení, populace a úroveň
evidence. Příkaz běží při každé aktualizaci (spustit.bat,
deploy/pa-update.sh): založí jen články, které v knihovně ještě nejsou
(podle DOI, PMID, nebo názvu a roku), nic nepřepisuje, a připojí je ke
zdrojům a důkazům karet, které na ně odkazují a článek zatím nemají.
Články vznikají jako „navržené“ – zařazuje je správce v knihovně, až texty
zkontroluje; model dostane jen zařazené.
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.evidence.models import Article, EvidenceLevel

FOLDER = Path(settings.BASE_DIR) / "katalog" / "clanky"
FORMAT = "clanky/1"
FIELDS = ("title", "authors", "journal", "year", "doi", "pmid", "abstract", "url",
          "evidence_level", "key_finding", "limitations", "population_sport", "population_sex",
          "population_age_min", "population_age_max", "population_level", "sample_size",
          "curator_note", "tags")


def find_existing(item: dict):
    """Článek už v knihovně je: podle DOI, jinak PMID, jinak názvu a roku."""
    if item.get("doi"):
        found = Article.objects.filter(doi__iexact=item["doi"]).first()
        if found:
            return found
    if item.get("pmid"):
        found = Article.objects.filter(pmid=str(item["pmid"])).first()
        if found:
            return found
    return Article.objects.filter(title__iexact=item["title"].strip(), year=item.get("year")).first()


def link_cards(article, refs: list[dict]) -> int:
    """Připojí článek ke zdrojům (a důkazům jen z nich) karet, které článek zatím nemají."""
    from apps.genetics.models import CardEvidence, CardSource

    linked = 0
    for ref in refs:
        labels = [lab.strip() for lab in ref.get("zdroje", []) if lab.strip()]
        if not labels:
            continue
        sources = CardSource.objects.filter(card__variant__rsid=ref["varianta"], label__in=labels,
                                            article__isnull=True)
        linked += sources.update(article=article)
        for evidence in CardEvidence.objects.filter(card__variant__rsid=ref["varianta"],
                                                    article__isnull=True).exclude(source_labels=""):
            mine = {lab.strip() for lab in evidence.source_labels.split(",") if lab.strip()}
            if mine and mine <= set(labels):
                evidence.article = article
                evidence.save(update_fields=["article"])
                linked += 1
    return linked


@transaction.atomic
def load_file(data: dict) -> dict:
    if data.get("format") != FORMAT:
        raise ValueError(f"Neznámý formát souboru ({data.get('format')!r}).")
    counts = {"nove": 0, "existujici": 0, "vazby": 0}
    levels = set(EvidenceLevel.values)
    for item in data.get("clanky", []):
        if not item.get("title"):
            raise ValueError("Článek bez názvu.")
        if item.get("evidence_level") and item["evidence_level"] not in levels:
            raise ValueError(f"Neznámá úroveň evidence „{item['evidence_level']}“ u „{item['title'][:60]}“.")
        article = find_existing(item)
        if article is None:
            values = {k: item[k] for k in FIELDS if k in item and item[k] is not None}
            values["pmid"] = str(values.get("pmid") or "")
            article = Article.objects.create(status=Article.Status.SUGGESTED, **values)
            counts["nove"] += 1
        else:
            counts["existujici"] += 1
        counts["vazby"] += link_cards(article, item.get("karty", []))
    return counts


class Command(BaseCommand):
    help = ("Načte články ke genovým kartám z katalog/clanky/*.json – jen chybějící, nic "
            "nepřepisuje – a připojí je ke zdrojům karet.")

    def add_arguments(self, parser):
        parser.add_argument("--slozka", default=str(FOLDER))

    def handle(self, *args, **opts):
        folder = Path(opts["slozka"])
        files = sorted(folder.glob("*.json")) if folder.exists() else []
        if not files:
            self.stdout.write(f"Ve složce {folder} není žádný soubor článků.")
            return
        for path in files:
            try:
                counts = load_file(json.loads(path.read_text(encoding="utf-8")))
            except (ValueError, KeyError) as exc:
                raise CommandError(f"{path.name}: {exc}") from exc
            self.stdout.write(f"{path.name}: nových článků {counts['nove']}, už v knihovně "
                              f"{counts['existujici']}, nových vazeb na karty {counts['vazby']}")
