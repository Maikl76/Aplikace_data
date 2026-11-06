"""
Přenos katalogu genetiky (oblasti, varianty, panely, karty, interakce)
spolu s ostatním katalogem (ulozit-katalog / nacist-katalog).

Karty se párují podle varianty (rsID) a verze; děti karty se při načtení
nahradí obsahem ze souboru. Garanti oblastí jsou účty – ty se nepřenáší.
Vzorky a genotypy sportovců do katalogu nepatří nikdy.
"""

from django.core.exceptions import ObjectDoesNotExist

from .models import (
    CardEvidence,
    CardRevision,
    CardSource,
    ContextScenario,
    Domain,
    ForbiddenStatement,
    GeneCard,
    GeneInteraction,
    GenePanel,
    GeneVariant,
    GenotypeText,
    PanelItem,
    Recommendation,
    ScenarioText,
)

SKIP = {"id", "created_at", "updated_at", "organization"}


def _plain(obj, *, skip=()) -> dict:
    return {f.name: getattr(obj, f.name) for f in obj._meta.concrete_fields
            if f.name not in SKIP and f.name not in skip and not f.is_relation}


def _org(obj):
    return obj.organization.short_name if obj.organization_id else None


def _card_ref(card):
    return None if card is None else {"varianta": card.variant.rsid, "verze": card.version}


def export_genetics() -> dict:
    return {
        "oblasti": [{"organizace": _org(d), **_plain(d)} for d in Domain.objects.order_by("order", "code")],
        "varianty": [
            {"organizace": _org(v), "oblast": v.domain.code, **_plain(v)}
            for v in GeneVariant.objects.select_related("domain").order_by("order", "rsid")
        ],
        "panely": [
            {"organizace": _org(p), **_plain(p),
             "polozky": [{"varianta": i.variant.rsid, **_plain(i)}
                         for i in p.items.select_related("variant").order_by("order", "pk")]}
            for p in GenePanel.objects.order_by("code", "version")
        ],
        "karty": [_card(c) for c in GeneCard.objects.select_related("variant", "supersedes")
                  .order_by("variant__rsid", "version")],
        "interakce": [
            {"organizace": _org(i), "karta": _card_ref(i.source_card), **_plain(i)}
            for i in GeneInteraction.objects.select_related("source_card__variant")
            .order_by("order", "pk")
        ],
        "nepripustne_vyroky": [_plain(f, skip={"card"})
                               for f in ForbiddenStatement.objects.filter(card__isnull=True)],
    }


def _card(card) -> dict:
    return {
        "organizace": _org(card), "varianta": card.variant.rsid,
        "nahrazuje": _card_ref(card.supersedes),
        **_plain(card),
        "texty": [_plain(t) for t in card.genotype_texts.all()],
        "doporuceni": [{**_plain(r), "protokol": r.protocol.code if r.protocol_id else None}
                       for r in card.recommendations.select_related("protocol")],
        "dukazy": [_plain(e) for e in card.evidence.all()],
        "zdroje": [_plain(s) for s in card.sources.all()],
        "nepripustne": [_plain(f) for f in card.forbidden_statements.all()],
        "scenare": [{**_plain(s), "otazka": s.question.code if s.question_id else None,
                     "texty": [_plain(t) for t in s.texts.all()]}
                    for s in card.scenarios.select_related("question").prefetch_related("texts")],
        "revize": [_plain(r) for r in card.revisions.all()],
    }


def _fields(item: dict, *remove) -> dict:
    return {k: v for k, v in item.items() if k not in remove and k != "organizace"}


def import_genetics(data: dict, imp) -> None:
    """``imp`` je _Importer z katalogu (org(), upsert())."""
    for item in data.get("oblasti", []):
        imp.upsert("oblasti", Domain, {"organization": imp.org(item["organizace"]),
                                      "code": item["code"]}, _fields(item, "code"))
    for item in data.get("varianty", []):
        org = imp.org(item["organizace"])
        domain = Domain.objects.filter(code=item["oblast"]).order_by("organization_id").first()
        if domain is None:
            raise ValueError(f"Oblast „{item['oblast']}“ pro variantu {item['rsid']} v souboru chybí.")
        imp.upsert("genové varianty", GeneVariant, {"organization": org, "rsid": item["rsid"]},
                   {**_fields(item, "rsid", "oblast"), "domain": domain})
    for item in data.get("panely", []):
        org = imp.org(item["organizace"])
        panel = imp.upsert("panely variant", GenePanel,
                           {"organization": org, "code": item["code"], "version": item["version"]},
                           _fields(item, "code", "version", "polozky"))
        for row in item.get("polozky", []):
            imp.upsert("varianty v panelu", PanelItem,
                       {"panel": panel, "variant": _variant(row["varianta"])},
                       _fields(row, "varianta"))
    cards = {}
    for item in data.get("karty", []):
        org = imp.org(item["organizace"])
        variant = _variant(item["varianta"])
        card = imp.upsert("genové karty", GeneCard, {"variant": variant, "version": item["version"]},
                          {**_fields(item, "varianta", "version", "nahrazuje", "texty", "doporuceni",
                                     "dukazy", "zdroje", "nepripustne", "scenare", "revize"),
                           "organization": org})
        cards[(variant.rsid, card.version)] = (card, item.get("nahrazuje"))
        _children(card, item)
    for card, ref in cards.values():
        if ref:
            previous = cards.get((ref["varianta"], ref["verze"]))
            card.supersedes = previous[0] if previous else GeneCard.objects.filter(
                variant__rsid=ref["varianta"], version=ref["verze"]).first()
            card.save(update_fields=["supersedes"])
    for item in data.get("interakce", []):
        org = imp.org(item["organizace"])
        source = None
        if item.get("karta"):
            source = GeneCard.objects.filter(variant__rsid=item["karta"]["varianta"],
                                             version=item["karta"]["verze"]).first()
        imp.upsert("interakce variant", GeneInteraction,
                   {"organization": org, "title": item["title"], "assumption": item["assumption"]},
                   {**_fields(item, "title", "assumption", "karta"), "source_card": source})
    for item in data.get("nepripustne_vyroky", []):
        imp.upsert("nepřípustné výroky", ForbiddenStatement, {"card": None, "text": item["text"]},
                   _fields(item, "text"))


def _variant(rsid: str) -> GeneVariant:
    try:
        return GeneVariant.objects.filter(rsid=rsid).order_by("organization_id").first() or \
            GeneVariant.objects.get(rsid=rsid)
    except ObjectDoesNotExist as exc:
        raise ValueError(f"Varianta {rsid} v souboru chybí.") from exc


def _protocol(code):
    """Test z katalogu podle kódu; neznámý kód doporučení nezastaví, jen bez testu."""
    if not code:
        return None
    from apps.catalog.models import Protocol

    return Protocol.objects.filter(code=code).order_by("-version", "organization_id").first()


def _question(code):
    """Otázka dotazníku genetiky podle kódu; bez ní scénář zůstane nenapojený (a vypnutý)."""
    if not code:
        return None
    from apps.catalog.models import Question

    from .seed import QUESTIONNAIRE_CODE

    return Question.objects.filter(questionnaire__code=QUESTIONNAIRE_CODE, code=code).first()


def _children(card, item: dict) -> None:
    for related in (card.genotype_texts, card.recommendations, card.evidence, card.sources,
                    card.forbidden_statements, card.scenarios, card.revisions):
        related.all().delete()
    for row in item.get("texty", []):
        GenotypeText.objects.create(card=card, **row)
    for row in item.get("doporuceni", []):
        Recommendation.objects.create(card=card, protocol=_protocol(row.get("protokol")),
                                      **_fields(row, "protokol"))
    for row in item.get("dukazy", []):
        CardEvidence.objects.create(card=card, **row)
    for row in item.get("zdroje", []):
        CardSource.objects.create(card=card, **row)
    for row in item.get("nepripustne", []):
        ForbiddenStatement.objects.create(card=card, **row)
    for row in item.get("scenare", []):
        scenario = ContextScenario.objects.create(card=card, question=_question(row.get("otazka")),
                                                  **_fields(row, "texty", "otazka"))
        for text in row.get("texty", []):
            ScenarioText.objects.create(scenario=scenario, **text)
    for row in item.get("revize", []):
        CardRevision.objects.create(card=card, **row)
