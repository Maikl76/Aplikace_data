"""
Průvodce kartou: osm kroků, stav z dat. Krok říká, co chybí, a vede na
stránku s jediným formulářem. Pořadí kopíruje odbornou revizi karty:
varianta → co gen dělá → texty pro genotypy → doporučení s důvody →
kontext z dotazníku → co se nesmí → zdroje a důkazy → kontrola a schválení.
"""

from django.urls import reverse

from apps.core.steps import step

from . import services
from .models import ContextScenario, ForbiddenStatement, GeneCard

STEPS = ("varianta", "gen", "genotypy", "doporuceni", "kontext", "vyroky", "zdroje",
         "kontrola")
TITLES = {
    "varianta": "Varianta", "gen": "Co gen dělá", "genotypy": "Texty pro genotypy",
    "doporuceni": "Doporučení s důvody", "kontext": "Kontext z dotazníku",
    "vyroky": "Co zpráva říkat nesmí", "zdroje": "Zdroje a důkazy",
    "kontrola": "Kontrola a schválení",
}
# Připomínka ke každému kroku: co se v něm nesmí, aby to garant nemusel hledat v podkladech.
HINTS = {
    "varianta": "Gen, rsID a genotypy přesně tak, jak je bude psát laboratoř. Jiný zápis "
                "(RR = CC) patří sem, ne do textů.",
    "gen": "Pište, co gen dělá, ne co to znamená pro výkon. Omezení interpretace jde do "
           "zprávy doslova: co z výsledku určit nejde.",
    "genotypy": "Text jde do zprávy doslova. Pište, co studie u genotypu popisují, a co z "
                "výsledku pro konkrétního člověka určit nejde. Žádné „máte více rychlých "
                "vláken“, „jste univerzální typ“, „potenciál se projevil“.",
    "doporuceni": "Bez důvodu kartu nejde schválit. Dávky, výběr sportu ani riziko zranění "
                  "podle genotypu nejsou doloženy – pište obecný postup pro všechny, nebo "
                  "budoucí měření s testem z katalogu.",
    "kontext": "Odpověď v dotazníku genotyp nepotvrzuje ani nevyvrací. Text scénáře má "
               "mluvit o zkušenosti sportovce vedle genotypu, ne „odpověď potvrzuje profil“.",
    "vyroky": "Jeden výrok na řádek. Aplikace ho nepustí do textu karty, do souhrnu od "
              "modelu ani do komentáře diagnostika.",
    "zdroje": "Každé tvrzení v kartě má mít zdroj. Řádek důkazů říká, co zdroj dokládá, "
              "jaká má omezení a co z něj smí do zprávy.",
    "kontrola": "Schvaluje jen garant oblasti a jen kartu bez blokujících nedostatků. "
                "Schválené znění je neměnné – další změna je nová verze.",
}


def card_steps(card) -> list[dict]:
    variant = card.variant
    editable = card.is_editable
    checklist = services.checklist(card)

    def url(slug):
        return reverse("genetics_card_step", args=[card.pk, slug])

    def button(label="Upravit"):
        return label if editable else ""

    genotypes = list(variant.genotypes or [])
    texts = {t.genotype: t for t in card.genotype_texts.all()}
    missing = [g for g in genotypes if not (texts.get(g) and texts[g].client_text.strip())]
    recs = list(card.recommendations.all())
    no_basis = [r for r in recs if not r.basis]
    scenarios = list(card.scenarios.all())
    active = [s for s in scenarios if s.is_active]
    broken = [s for s in active if s.kind == ContextScenario.Kind.QUESTIONNAIRE
              and not (s.question_id and s.answer_match)]
    forbidden = card.forbidden_statements.count()
    shared = ForbiddenStatement.objects.filter(card__isnull=True).count()
    sources, evidence = card.sources.count(), card.evidence.count()
    approved = card.status == GeneCard.Status.APPROVED

    variant_ok = bool(variant.gene and variant.rsid and variant.domain_id and len(genotypes) >= 2)
    if approved:
        control = f"Schváleno {card.approved_at:%d.%m.%Y}." if card.approved_at else "Schváleno."
    elif checklist.blocking:
        control = (f"{len(checklist.blocking)} blokujících nedostatků: "
                   + checklist.blocking[0].text)
    elif card.status == GeneCard.Status.DRAFT:
        control = "Nic neblokuje – pošlete kartu k revizi garantovi oblasti."
    elif card.status == GeneCard.Status.REVIEW:
        control = "V revizi: schvaluje garant oblasti."
    else:
        control = card.get_status_display()
    return [
        step(1, TITLES["varianta"], variant_ok,
             (f"{variant.label}, genotypy {', '.join(genotypes)}, oblast {variant.domain}."
              if variant_ok else "Doplňte gen, rsID, oblast a aspoň dva genotypy."),
             url=url("varianta"), button=button()),
        step(2, TITLES["gen"], bool(card.biology_client.strip()),
             ("Vysvětlení pro klienta je vyplněné."
              + ("" if card.limitations.strip() else " Doplňte omezení interpretace.")
              if card.biology_client.strip()
              else "Napište, co gen dělá, srozumitelně a bez slibů."),
             url=url("gen"), button=button()),
        step(3, TITLES["genotypy"], bool(genotypes) and not missing,
             (f"Chybí text pro {', '.join(missing)}." if missing
              else "Každý genotyp má text pro klienta." if genotypes else "Nejdřív genotypy."),
             url=url("genotypy"), button=button(), count=len(missing) or None),
        step(4, TITLES["doporuceni"], not no_basis,
             (f"{len(no_basis)} doporučení bez důvodu – bez něj kartu nejde schválit."
              if no_basis else f"{len(recs)} doporučení, každé má důvod." if recs
              else "Žádné doporučení; zpráva uvede jen interpretaci. Zvažte obecný postup "
                   "nebo budoucí měření."),
             url=url("doporuceni"), button=button(), count=len(no_basis) or None),
        step(5, TITLES["kontext"], not broken,
             (f"{len(broken)} zapnutých scénářů bez odpovědi, která je spouští." if broken
              else f"{len(scenarios)} scénářů, {len(active)} zapnutých." if scenarios
              else "Bez scénářů; zpráva kontext z dotazníku neuvede."),
             url=url("kontext"), button=button(), optional=True, count=len(broken) or None),
        step(6, TITLES["vyroky"], forbidden > 0,
             (f"{forbidden} výroků u karty, {shared} společných pro všechny karty." if forbidden
              else "Doplňte výroky, které se u této varianty nesmí objevit; aplikace je hlídá "
                   "i v textu od modelu."),
             url=url("vyroky"), button=button(), optional=True),
        step(7, TITLES["zdroje"], sources > 0,
             (f"{sources} zdrojů, {evidence} řádků důkazů."
              + ("" if evidence else " Doplňte, co který zdroj dokládá.")
              if sources else "Bez zdroje nejde doložit žádné tvrzení v kartě."),
             url=url("zdroje"), button=button()),
        step(8, TITLES["kontrola"], approved, control, url=url("kontrola"),
             button="" if approved else "Zkontrolovat", count=len(checklist.blocking) or None),
    ]


def next_slug(slug: str) -> str | None:
    index = STEPS.index(slug)
    return STEPS[index + 1] if index + 1 < len(STEPS) else None
