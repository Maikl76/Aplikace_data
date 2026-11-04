"""
Převod genových karet z Wordu do katalogu.

Podklady („Genové karty – úplné podklady k odborné revizi“) mají pevnou
stavbu: nadpis 1 = karta „GEN / rsID“, nadpisy 2 = části karty, texty
v uvozovkách, „Genotyp XX“: text. Převod zakládá variantu, verzi 1 karty
jako původní znění (jen ke čtení) a verzi 2 jako návrh k revizi. Pozdější
revizní texty z podkladů (ACTN3 v0.2, LCT) jdou rovnou do návrhu a rozdíl
proti původnímu znění se zapíše do revizních záznamů. Co převod nezařadí,
uloží do poznámky z podkladů – nic se neztratí bez záznamu.
"""

import re
from dataclasses import dataclass, field

from django.db import transaction

from . import seed
from .docx import Paragraph, Table, read_blocks
from .models import (
    CardEvidence,
    CardRevision,
    CardSource,
    ContextScenario,
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
from .services import copy_children

CARD_HEADING = re.compile(r"^(?P<gene>[A-Za-z0-9][A-Za-z0-9/\-]*)\s*/\s*(?P<rsid>rs\d+)\s*$")
GENOTYPE_LINE = re.compile(
    r'^"?Genotyp\s+(?P<g>[A-Z]{2})(?:\s*\((?P<alias>[A-Z]{2})\))?"?\s*:\s*(?P<text>.*)$', re.S)
RECO_LINE = re.compile(r'^"(?P<kind>[^"]+)"\s*:\s*(?P<text>.+)$', re.S)
STATEMENT = re.compile(r"^Výstup odpovědi:\s*[„\"](?P<text>.*?)[“\"]\s*$", re.S)
G_LINE = re.compile(r"^G_(?P<g>[A-Z]{2}):\s*(?P<text>.+)$", re.S)
SHORT_G_LINE = re.compile(r"^(?P<g>[A-Z]{2}):\s*(?P<text>.+)$", re.S)
SOURCE_HEADING = re.compile(r"^S(?P<n>\d+)\s+(?P<title>.+)$")
RSID = re.compile(r"rs\d+")
SOURCE_LABELS = re.compile(r"\[(S\d+(?:\s*,\s*S\d+)*)\]")
WORKING_GENOTYPES = re.compile(r"Pracovní zápisy genotypů:\s*(?P<list>[A-Z]{2}(?:\s*,\s*[A-Z]{2})*)")

RECO_KINDS = {
    "sportovní doporučení": Recommendation.Kind.SPORT,
    "tréninková doporučení": Recommendation.Kind.TRAINING,
    "rizika": Recommendation.Kind.RISK,
    "výživa": Recommendation.Kind.NUTRITION,
    "regenerace": Recommendation.Kind.REGENERATION,
}
OUTLINE_SECTIONS = ("identifikace", "biologická funkce a účinek varianty", "frekvence a důkazy",
                    "interpretace a doporučení", "dotazník a fenotyp", "interakce a zdroje",
                    "omezení a revize")


def _key(title: str) -> str:
    return " ".join(title.replace("–", "-").replace("—", "-").lower().split())


def _unquote(text: str) -> str:
    text = text.strip()
    while text.endswith(";"):
        text = text[:-1].strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1]
    return text.strip()


def _quoted_list(text: str) -> list[str]:
    found = [t.strip() for t in re.findall(r'"([^"]+)"', text)]
    return found or [t.strip() for t in re.split(r"[;,]", text) if t.strip()]


# --- rozklad dokumentu na karty a části -------------------------------------

@dataclass
class Section:
    level: int
    title: str
    items: list = field(default_factory=list)

    @property
    def key(self) -> str:
        return _key(self.title)

    @property
    def paragraphs(self) -> list[str]:
        return [b.text for b in self.items if isinstance(b, Paragraph) and b.text]

    @property
    def tables(self) -> list[Table]:
        return [b for b in self.items if isinstance(b, Table)]


@dataclass
class ParsedCard:
    gene: str
    rsid: str
    subtitle: str = ""
    area: str = ""
    header_notes: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)


def split_cards(blocks) -> list[ParsedCard]:
    cards: list[ParsedCard] = []
    card = None
    section = None
    for block in blocks:
        if isinstance(block, Paragraph) and block.level == 1 and CARD_HEADING.match(block.text):
            match = CARD_HEADING.match(block.text)
            card = ParsedCard(gene=match["gene"], rsid=match["rsid"])
            cards.append(card)
            section = None
            continue
        if card is None:
            continue  # úvod dokumentu (titul, přehled karet) se nepřevádí
        if isinstance(block, Paragraph) and block.level:
            section = Section(level=min(block.level, 3) if block.level > 1 else 2,
                              title=block.text)
            card.sections.append(section)
            continue
        if section is None:
            if isinstance(block, Paragraph) and block.text:
                if not card.subtitle and "•" in block.text:
                    card.subtitle, _, card.area = (s.strip() for s in block.text.partition("•"))
                else:
                    card.header_notes.append(block.text)
            continue
        if isinstance(block, Table) or block.text:
            section.items.append(block)
    return cards


# --- výklad částí karty -------------------------------------------------------

@dataclass
class Scenario:
    kind: str
    title: str
    statement: str
    texts: dict = field(default_factory=dict)


@dataclass
class Interaction:
    areas: list
    title: str
    assumption: str
    text: str = ""


@dataclass
class CardData:
    gene: str
    rsid: str
    subtitle: str = ""
    area: str = ""
    is_outline: bool = False
    full_name: str = ""
    notation: str = ""
    review_priorities: str = ""
    biology_expert: str = ""
    biology_client: str = ""
    related_areas: list = field(default_factory=list)
    frequency_note: str = ""
    frequencies: dict = field(default_factory=dict)
    frequency_source: str = ""
    effect: str = ""
    genotypes: list = field(default_factory=list)
    aliases: dict = field(default_factory=dict)
    interpretations: dict = field(default_factory=dict)
    recommendations: list = field(default_factory=list)      # (genotype, kind, text)
    scenarios: list = field(default_factory=list)
    interactions: list = field(default_factory=list)
    sources: list = field(default_factory=list)              # (label, title, citation, url)
    notes: list = field(default_factory=list)                # co se nezařadilo
    outline: list = field(default_factory=list)              # (část, co doplnit)
    limitations: str = ""
    # pozdější revize (jde do návrhu, ne do původního znění)
    revision_reason: str = ""
    revised_biology_expert: str = ""
    revised_biology_client: str = ""
    revised_frequency_note: str = ""
    revised_texts: dict = field(default_factory=dict)
    evidence: list = field(default_factory=list)             # (code, trait, basis, usage, labels)
    revised_sources: list = field(default_factory=list)
    forbidden: list = field(default_factory=list)
    change_summary: str = ""

    @property
    def label(self) -> str:
        return f"{self.gene} / {self.rsid}"


def _genotype(data: CardData, g: str, alias: str | None):
    if g not in data.genotypes:
        data.genotypes.append(g)
    if alias:
        data.aliases[g] = alias


def interpret(parsed: ParsedCard) -> CardData:
    data = CardData(gene=parsed.gene, rsid=parsed.rsid, subtitle=parsed.subtitle,
                    area=parsed.area)
    data.notes.extend(parsed.header_notes)
    sections = parsed.sections
    data.is_outline = any(s.key in OUTLINE_SECTIONS for s in sections)
    after_interactions = False
    revised = False
    i = 0
    while i < len(sections):
        section = sections[i]
        key = section.key
        paragraphs = section.paragraphs
        joined = "\n\n".join(paragraphs)
        i += 1
        if key == "revizní priority této karty":
            data.review_priorities = joined
        elif key == "původní obsah karty":
            pass
        elif key == "gen":
            # Nadpis karty má přednost (panel píše „MCM6/LCT“, původní karta „LCT“).
            symbol = _unquote(joined)
            if symbol and symbol != data.gene:
                data.notes.append(f"Gen v původní kartě: {symbol}")
        elif key == "plný název genu":
            data.full_name = joined.replace('"', "").strip()
        elif key == "biologická funkce - odborný popis":
            data.biology_expert = _unquote(joined)
        elif key == "biologická funkce - vysvětlení pro klienta":
            data.biology_client = _unquote(joined)
        elif key == "související oblasti" and not after_interactions:
            data.related_areas = _quoted_list(joined)
        elif key == "související oblasti":
            _interactions(data, section)
        elif key == "varianta":
            data.notation = _unquote(joined)
        elif key == "frekvence genotypů":
            for text in paragraphs:
                match = GENOTYPE_LINE.match(text)
                if match:
                    _genotype(data, match["g"], match["alias"])
                    data.frequencies[match["g"]] = _unquote(match["text"])
                else:
                    data.frequency_note = (data.frequency_note + "\n\n" + text).strip()
        elif key == "účinek varianty":
            data.effect = _unquote(joined)
        elif key == "interpretace jednotlivých genotypů":
            for text in paragraphs:
                match = GENOTYPE_LINE.match(text)
                if match:
                    _genotype(data, match["g"], match["alias"])
                    data.interpretations[match["g"]] = _unquote(match["text"])
                else:
                    data.notes.append(text)
        elif key == "doporučení podle genotypu":
            _recommendations(data, paragraphs)
        elif key == "kontext dotazníku a fenotypu":
            data.notes.extend(paragraphs)
            while i < len(sections) and sections[i].level == 3:
                _scenario(data, sections[i])
                i += 1
        elif key == "navržené interakce a kombinace":
            after_interactions = True
            data.notes.extend(paragraphs)
        elif key == "zdroj frekvencí":
            data.frequency_source = joined.strip()
        elif key == "literatura ke kartě":
            for text in paragraphs:
                data.sources.append(("", "", text, _url_in(text)))
        elif key.startswith("pozdější revize") or key == "pozdější návrhy klientských formulací":
            revised = True
            data.revision_reason = joined
        elif key == "biologická funkce" and revised:
            for text in paragraphs:
                low = text.lower()
                if low.startswith("odborně:"):
                    data.revised_biology_expert = text.split(":", 1)[1].strip()
                elif low.startswith("pro klienta:"):
                    data.revised_biology_client = text.split(":", 1)[1].strip()
                elif low.startswith("frekvence genotypů:"):
                    data.revised_frequency_note = text.split(":", 1)[1].strip()
                else:
                    data.notes.append(text)
        elif key == "důkazy a přípustné závěry":
            data.notes.extend(paragraphs)
            for table in section.tables:
                _evidence(data, table)
        elif key == "návrhy klientských textů pro jednotlivé genotypy":
            for text in paragraphs:
                match = G_LINE.match(text)
                if match:
                    _genotype(data, match["g"], None)
                    data.revised_texts[match["g"]] = match["text"].strip()
                else:
                    data.notes.append(text)
        elif key == "výroky nepřípustné v této verzi":
            for text in paragraphs:
                data.forbidden.extend(
                    s.strip(" .„“\"") for s in re.split(r";", text) if s.strip(" .„“\""))
        elif key == "zdroje a změny proti původní kartě":
            data.notes.extend(paragraphs)
        elif SOURCE_HEADING.match(section.title) and revised:
            match = SOURCE_HEADING.match(section.title)
            data.revised_sources.append((f"S{match['n']}", match["title"].strip(), joined,
                                         _url_in(joined)))
        elif key == "přehled provedených změn":
            data.change_summary = joined
        elif key in OUTLINE_SECTIONS:
            _outline(data, section)
        elif revised and paragraphs and all(SHORT_G_LINE.match(p) for p in paragraphs):
            for text in paragraphs:
                match = SHORT_G_LINE.match(text)
                _genotype(data, match["g"], None)
                data.revised_texts[match["g"]] = match["text"].strip()
        else:
            if paragraphs:
                data.notes.append(f"{section.title}: " + " ".join(paragraphs))
            for table in section.tables:
                data.notes.append(f"{section.title}: " + " | ".join(
                    " / ".join(row) for row in table.rows))
    if revised and data.revision_reason:
        # Pozdější texty pro genotypy (LCT) stojí ve stejné části jako důvod.
        for text in data.revision_reason.split("\n\n"):
            match = SHORT_G_LINE.match(text)
            if match:
                _genotype(data, match["g"], None)
                data.revised_texts[match["g"]] = match["text"].strip()
        data.revision_reason = "\n\n".join(t for t in data.revision_reason.split("\n\n")
                                           if not SHORT_G_LINE.match(t))
    return data


def _url_in(text: str) -> str:
    match = re.search(r"https?://\S+", text)
    return match.group(0).rstrip(".,)") if match else ""


def _recommendations(data: CardData, paragraphs: list[str]) -> None:
    genotype = ""
    for text in paragraphs:
        match = GENOTYPE_LINE.match(text)
        if match and not match["text"].strip():
            genotype = match["g"]
            _genotype(data, genotype, match["alias"])
            continue
        reco = RECO_LINE.match(text)
        if reco and _key(reco["kind"]) in RECO_KINDS:
            data.recommendations.append((genotype, RECO_KINDS[_key(reco["kind"])],
                                         _unquote(reco["text"])))
        else:
            data.notes.append(text)


def _scenario_kind(title: str) -> str:
    low = title.lower()
    if "dotazník" in low:
        return ContextScenario.Kind.QUESTIONNAIRE
    if any(w in low for w in ("test", "měření", "monitorace", "vyšetření", "pokus")):
        return ContextScenario.Kind.MEASUREMENT
    return ContextScenario.Kind.OTHER


def _scenario(data: CardData, section: Section) -> None:
    kind = _scenario_kind(section.title)
    current = None
    for text in section.paragraphs:
        statement = STATEMENT.match(text)
        if statement:
            current = Scenario(kind=kind, title=section.title, statement=statement["text"].strip())
            data.scenarios.append(current)
            continue
        match = GENOTYPE_LINE.match(text)
        if match and current is not None:
            _genotype(data, match["g"], match["alias"])
            current.texts[match["g"]] = _unquote(match["text"])
        else:
            data.notes.append(f"{section.title}: {text}")


def _interactions(data: CardData, section: Section) -> None:
    paragraphs = section.paragraphs
    areas = _quoted_list(paragraphs[0]) if paragraphs and paragraphs[0].startswith('"') else []
    title = ""
    current = None
    for text in paragraphs[1 if areas else 0:]:
        if text.startswith("Interakce"):
            title = text.rstrip(":").strip()
            current = None
        elif text.startswith("Za předpokladu"):
            current = Interaction(areas=areas, title=title or f"Interakce {data.label}",
                                  assumption=text.rstrip(":").strip())
            data.interactions.append(current)
        elif current is not None and not current.text:
            current.text = _unquote(text)
        else:
            data.notes.append(f"{section.title}: {text}")


def _evidence(data: CardData, table: Table) -> None:
    for row in table.rows:
        if len(row) < 2 or not row[0].strip() or row[0].strip().lower().startswith("id"):
            continue
        head = row[0].strip()
        code, _, trait = head.partition(" ")
        if not re.fullmatch(r"E\d+", code):
            code, trait = "", head
        basis = row[1].strip()
        usage = row[2].strip() if len(row) > 2 else ""
        labels = ", ".join(sorted({label.strip() for m in SOURCE_LABELS.findall(basis + usage)
                                   for label in m.split(",")},
                                  key=lambda s: int(s[1:])))
        data.evidence.append((code, trait.strip(), basis, usage, labels))


def _outline(data: CardData, section: Section) -> None:
    text = "\n\n".join(section.paragraphs)
    if section.key == "identifikace":
        match = WORKING_GENOTYPES.search(text)
        if match:
            for g in re.split(r"\s*,\s*", match["list"]):
                _genotype(data, g, None)
    if section.key == "omezení a revize":
        data.limitations = text
    data.outline.append((section.title, text))


# --- zápis do katalogu --------------------------------------------------------

PANEL_CODE = "panel-podklady"


@dataclass
class ImportResult:
    created: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    panel: GenePanel | None = None

    def lines(self) -> list[str]:
        out = [f"Založeno: {label}" for label in self.created]
        out += [f"Přeskočeno (už existuje): {label}" for label in self.skipped]
        if self.panel is not None:
            out.append(f"Panel: {self.panel} – {self.panel.items.count()} variant")
        return out


def parse_file(path) -> list[CardData]:
    return [interpret(card) for card in split_cards(read_blocks(path))]


@transaction.atomic
def import_cards(path, *, organization=None, user=None) -> ImportResult:
    """Načte karty z .docx. Existující varianty (podle rsID) nechá být."""
    result = ImportResult()
    panel, _ = GenePanel.objects.get_or_create(
        organization=organization, code=PANEL_CODE, version=1,
        defaults={"name": "Panel variant z podkladů", "provider": "",
                  "note": "Založeno převodem genových karet z Wordu. Doplňte laboratoř "
                          "a její zápis genotypů u jednotlivých variant."})
    result.panel = panel
    for order, data in enumerate(parse_file(path), start=1):
        variant = GeneVariant.objects.filter(organization=organization, rsid=data.rsid).first()
        if variant is not None and variant.cards.exists():
            result.skipped.append(data.label)
            continue
        variant = _variant(data, variant, organization, order)
        _cards(data, variant, user)
        PanelItem.objects.get_or_create(
            panel=panel, variant=variant,
            defaults={"order": order, "lab_label": data.notation[:120],
                      "genotype_map": {alias: g for g, alias in data.aliases.items()}})
        result.created.append(data.label)
    seed.link_scenarios()
    return result


def _variant(data: CardData, variant, organization, order) -> GeneVariant:
    fields = {
        "gene": data.gene, "full_name": data.full_name[:200], "notation": data.notation[:200],
        "domain": seed.domain_for(data.area), "subtitle": data.subtitle[:200],
        "genotypes": list(data.genotypes), "genotype_aliases": dict(data.aliases),
        "strand_note": data.limitations if data.is_outline else "",
        "frequency_source": data.frequency_source[:500], "order": order,
    }
    if variant is None:
        return GeneVariant.objects.create(organization=organization, rsid=data.rsid, **fields)
    for name, value in fields.items():
        setattr(variant, name, value)
    variant.save()
    return variant


def _cards(data: CardData, variant: GeneVariant, user) -> None:
    note = "\n\n".join(n for n in data.notes if n.strip())
    common = {
        "organization": variant.organization, "variant": variant,
        "review_priorities": data.review_priorities, "biology_expert": data.biology_expert,
        "biology_client": data.biology_client, "effect": data.effect,
        "frequency_note": data.frequency_note, "related_areas": list(data.related_areas),
        "limitations": data.limitations, "import_note": note, "created_by": user,
    }
    if data.is_outline:
        draft = GeneCard.objects.create(version=1, status=GeneCard.Status.DRAFT, **common)
        for part, text in data.outline:
            CardRevision.objects.create(card=draft, part=part, reason=text,
                                        source="podklady – osnova k doplnění",
                                        created_by=user)
        return
    original = GeneCard.objects.create(version=1, status=GeneCard.Status.ORIGINAL, **common)
    for order, g in enumerate(data.genotypes):
        GenotypeText.objects.create(card=original, genotype=g, order=order,
                                    client_text=data.interpretations.get(g, ""),
                                    frequency=data.frequencies.get(g, "")[:200])
    for order, (g, kind, text) in enumerate(data.recommendations):
        Recommendation.objects.create(card=original, genotype=g, kind=kind, text=text,
                                      order=order)
    for order, scenario in enumerate(data.scenarios):
        row = ContextScenario.objects.create(card=original, kind=scenario.kind,
                                             title=scenario.title[:200],
                                             statement=scenario.statement, order=order)
        for g, text in scenario.texts.items():
            ScenarioText.objects.create(scenario=row, genotype=g, text=text)
    for order, (label, title, citation, url) in enumerate(data.sources):
        CardSource.objects.create(card=original, label=label, title=title, citation=citation,
                                  url=url[:500], order=order)
    for order, item in enumerate(data.interactions):
        rsids = sorted(set(RSID.findall(item.assumption + " " + item.title)) | {data.rsid})
        GeneInteraction.objects.create(
            organization=variant.organization, title=item.title[:300], areas=item.areas,
            assumption=item.assumption, text=item.text, variants=rsids,
            source_card=original, order=order)

    draft = GeneCard.objects.create(
        version=2, status=GeneCard.Status.DRAFT, supersedes=original,
        **{**common,
           "biology_expert": data.revised_biology_expert or data.biology_expert,
           "biology_client": data.revised_biology_client or data.biology_client,
           "frequency_note": data.revised_frequency_note or data.frequency_note,
           "change_summary": data.change_summary})
    copy_children(original, draft)
    reason = data.revision_reason or "Pozdější revize z podkladů; má přednost před původní formulací."
    for g, text in data.revised_texts.items():
        row, _ = GenotypeText.objects.get_or_create(card=draft, genotype=g)
        if row.client_text != text:
            CardRevision.objects.create(card=draft, part=f"Interpretace genotypu {g}",
                                        original=row.client_text, proposal=text,
                                        reason=reason, source="podklady v02", created_by=user)
            row.client_text = text
            row.save(update_fields=["client_text"])
    if data.revised_biology_client and data.revised_biology_client != data.biology_client:
        CardRevision.objects.create(card=draft, part="Biologická funkce – pro klienta",
                                    original=data.biology_client,
                                    proposal=data.revised_biology_client, reason=reason,
                                    source="podklady v02", created_by=user)
    for order, (code, trait, basis, usage, labels) in enumerate(data.evidence):
        CardEvidence.objects.create(card=draft, code=code, trait=trait[:200], basis_text=basis,
                                    usage=usage, source_labels=labels[:120], order=order)
    start = draft.sources.count()
    for order, (label, title, citation, url) in enumerate(data.revised_sources, start=start):
        CardSource.objects.create(card=draft, label=label, title=title[:200],
                                  citation=citation, url=url[:500], order=order)
    for text in data.forbidden:
        ForbiddenStatement.objects.create(card=draft, text=text[:300],
                                          note="z revize v podkladech")
