"""
Genetika, fáze 1: karty z Wordu, schvalování garantem, souhlas 18+,
šifrované genotypy, kdo co vidí, přenos katalogu.
"""

import json
import zipfile
from datetime import date
from xml.sax.saxutils import escape

import pytest
from cryptography.fernet import Fernet
from django.core.management import CommandError, call_command
from django.test import Client
from django.utils import timezone

from apps.catalog.transfer import export_catalog, import_catalog
from apps.core.models import Organization, Role, User
from apps.genetics import services
from apps.genetics.cards_import import import_cards
from apps.genetics.models import (
    CardEvidence,
    CardRevision,
    CardSource,
    ContextScenario,
    Domain,
    ForbiddenStatement,
    GeneCard,
    GeneInteraction,
    GenePanel,
    GeneticSample,
    GeneVariant,
    Genotype,
    GenotypeText,
    PanelItem,
    Recommendation,
)
from apps.genetics.seed import seed_domains
from apps.subjects.models import Consent, Subject, SubjectIdentity


@pytest.fixture
def org(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.GENETICS_ENCRYPTION_KEY = Fernet.generate_key().decode()
    seed_domains()
    return Organization.objects.create(name="FTVS", short_name="ftvs")


def _user(org, role, username):
    user = User.objects.create(username=username, organization=org, role=role)
    client = Client()
    client.force_login(user)
    return user, client


def _subject(org, code, birth=None, birth_year=None):
    subject = Subject.objects.create(organization=org, code=code, birth_year=birth_year)
    identity = SubjectIdentity(subject=subject)
    identity.set_names("Jana", code)
    if birth:
        identity.set_birth_date(birth)
    identity.save()
    return subject


def _variant(org, gene="ACTN3", rsid="rs1815739", domain="vykon", **extra):
    fields = {"genotypes": ["CC", "CT", "TT"],
              "genotype_aliases": {"CC": "RR", "CT": "RX", "TT": "XX"}}
    fields.update(extra)
    return GeneVariant.objects.create(organization=org, gene=gene, rsid=rsid,
                                      domain=Domain.objects.get(code=domain), **fields)


def _card(variant, version=1, status=GeneCard.Status.DRAFT, texts=True, **extra):
    card = GeneCard.objects.create(organization=variant.organization, variant=variant,
                                   version=version, status=status,
                                   biology_client="Gen souvisí s bílkovinou svalu.", **extra)
    if texts:
        for g in variant.genotypes:
            GenotypeText.objects.create(card=card, genotype=g, client_text=f"Zjištěn genotyp {g}.")
    return card


# --- zápis genotypů ----------------------------------------------------------

def test_kanonicky_zapis_genotypu(org):
    variant = _variant(org)
    assert variant.canonical("TC") == "CT"
    assert variant.canonical("c/t") == "CT"
    assert variant.canonical("RX") == "CT"
    assert variant.canonical("xx") == "TT"
    assert variant.canonical("GG") is None and variant.canonical("") is None
    ace = _variant(org, gene="ACE", rsid="rs1799752", genotypes=["II", "ID", "DD"],
                   genotype_aliases={})
    panel = GenePanel.objects.create(organization=org, code="p", name="Panel")
    item = PanelItem.objects.create(panel=panel, variant=ace,
                                    genotype_map={"ins/ins": "II", "del/ins": "ID"})
    assert item.normalize("Ins/Ins") == "II" and item.normalize("DEL/INS") == "ID"
    assert item.normalize("DI") == "ID" and item.normalize("xx") is None
    assert services.normalize(item, "") == (None, Genotype.Quality.MISSING)
    assert services.normalize(item, "selhalo") == (None, Genotype.Quality.FAILED)
    assert services.normalize(item, "??") == (None, Genotype.Quality.UNCLEAR)


# --- převod karet z Wordu ----------------------------------------------------

def _docx(path, blocks):
    parts = []
    for kind, payload in blocks:
        if kind == "table":
            rows = "".join(
                "<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t xml:space='preserve'>{escape(c)}</w:t>"
                                   f"</w:r></w:p></w:tc>" for c in row) + "</w:tr>"
                for row in payload)
            parts.append(f"<w:tbl>{rows}</w:tbl>")
            continue
        style = {"H1": "Heading1", "H2": "Heading2", "H3": "Heading3"}.get(kind, "")
        ppr = f"<w:pPr><w:pStyle w:val='{style}'/></w:pPr>" if style else ""
        rpr = "<w:rPr><w:b/></w:rPr>" if kind == "b" else ""
        parts.append(f"<w:p>{ppr}<w:r>{rpr}<w:t xml:space='preserve'>{escape(payload)}</w:t>"
                     f"</w:r></w:p>")
    xml = ("<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
           "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>"
           f"<w:body>{''.join(parts)}</w:body></w:document>")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return path


KARTY = [
    ("p", "Genové karty"), ("b", "Úvod dokumentu, který se nepřevádí."),
    ("H1", "ACE / rs1799752"),
    ("b", "Vytrvalost a výkonový kontext • Výkon a trénink"),
    ("b", "Původní návrh k revizi. Zachováno 61 odstavců."),
    ("H2", "Revizní priority této karty"), ("b", "Ověřit mapování ACE I/D."),
    ("H2", "Původní obsah karty"),
    ("H2", "Gen"), ("b", '"ACE"'),
    ("H2", "Plný název genu"),
    ("b", '"Angiotensin-converting enzyme" ("Angiotenzin-konvertující enzym")'),
    ("H2", "Biologická funkce – odborný popis"), ("b", '"ACE kóduje enzym."'),
    ("H2", "Biologická funkce – vysvětlení pro klienta"), ("b", '"Gen ACE ovlivňuje cévy."'),
    ("H2", "Související oblasti"), ("b", '"Aerobní kapacita"; "Vytrvalostní výkon"'),
    ("H2", "Varianta"), ("b", '"rs1799752 (I/D)"'),
    ("H2", "Frekvence genotypů"), ("b", "Převzaté frekvence: doložit zdroj."),
    ("b", '"Genotyp II": "20 % (Evropská populace)";'), ("b", '"Genotyp ID": "50 %";'),
    ("b", '"Genotyp DD": "30 %"'),
    ("H2", "Účinek varianty"), ("b", '"Alela D je spojena s vyšší aktivitou ACE."'),
    ("H2", "Interpretace jednotlivých genotypů"),
    ("b", '"Genotyp II": "Váš profil odpovídá vytrvalosti."'),
    ("b", '"Genotyp ID": "Smíšený profil."'), ("b", '"Genotyp DD": "Silově-rychlostní profil."'),
    ("H2", "Doporučení podle genotypu"), ("b", "Následují původní návrhy doporučení."),
    ("b", '"Genotyp II":'), ("b", '"Sportovní doporučení": "Vytrvalostní disciplíny."'),
    ("b", '"Tréninková doporučení": "Aerobní zóny."'),
    ("b", '"Rizika": "Méně spontánní explozivita."'),
    ("H2", "Kontext dotazníku a fenotypu"), ("b", "Původní scénáře k posouzení."),
    ("H3", "Kontext 1: zdroj dotazník"),
    ("b", "Výstup odpovědi: „Lépe zvládám delší zátěž.“"),
    ("b", '"Genotyp II": "Odpovídá profilu."'), ("b", '"Genotyp ID": "Smíšený."'),
    ("b", '"Genotyp DD": "Nesoulad."'),
    ("H3", "Kontext 2: zdroj zátěžový test – VO2max"),
    ("b", "Výstup odpovědi: „Nadprůměrné VO2max.“"), ("b", '"Genotyp II": "Potvrzuje."'),
    ("H2", "Navržené interakce a kombinace"), ("b", "Původní hypotézy k posouzení."),
    ("H2", "Související oblasti"), ("b", '"Svalová hypertrofie a síla", "Vytrvalostní výkon"'),
    ("b", "Interakce variant ACE rs1799752 (I/D) a ACTN3 rs1815739 (R577X):"),
    ("b", "Za předpokladu kombinace ACE rs1799752 DD nebo ID + ACTN3 rs1815739 CC nebo CT:"),
    ("b", '"Kombinace může podporovat silově-rychlostní profil."'),
    ("H2", "Zdroj frekvencí"), ("b", "https://www.ncbi.nlm.nih.gov/snp/rs1799752#frequency_tab"),
    ("H2", "Literatura ke kartě"),
    ("b", "Montgomery, H. E., et al. (1998). Human gene for physical performance. Nature, 393."),
    ("b", "elders in Taiwan. Exp Ger."),

    ("H1", "MCM6/LCT / rs4988235"),
    ("b", "Trávení laktózy • Laktóza"), ("b", "Původní návrh k revizi."),
    ("H2", "Gen"), ("b", '"LCT"'),
    ("H2", "Biologická funkce – vysvětlení pro klienta"), ("b", '"Gen LCT souvisí s laktázou."'),
    ("H2", "Interpretace jednotlivých genotypů"),
    ("b", '"Genotyp CC": "Poroste riziko intolerance."'), ("b", '"Genotyp CT": "Tolerance."'),
    ("b", '"Genotyp TT": "Dobrá tolerance."'),
    ("H2", "Pozdější návrhy klientských formulací"),
    ("b", "Převzato z předchozího balíčku. Čekají na schválení."),
    ("b", "CC: Genotyp CC je spojen s nepersistencí laktázy. Sám neprokazuje obtíže."),
    ("b", "CT: Genotyp CT je spojen s persistencí."), ("b", "TT: Genotyp TT je spojen s persistencí."),

    ("H1", "ACTN3 / rs1815739"),
    ("b", "Síla a výbušnost • Výkon a trénink"), ("b", "Původní návrh k revizi."),
    ("H2", "Gen"), ("b", '"ACTN3"'),
    ("H2", "Biologická funkce – vysvětlení pro klienta"),
    ("b", '"Gen ACTN3 kóduje protein rychlých vláken."'),
    ("H2", "Interpretace jednotlivých genotypů"),
    ("b", '"Genotyp CC (RR)": "Máte vyšší podíl rychlých vláken."'),
    ("b", '"Genotyp CT (RX)": "Vyvážený profil."'), ("b", '"Genotyp TT (XX)": "Vytrvalostní."'),
    ("H2", "Literatura ke kartě"),
    ("H2", "Pozdější revize ACTN3 – obsah k zachování"),
    ("b", "Převzato z genové karty ACTN3 v0.2. Má přednost před rozpornou původní formulací."),
    ("H2", "Biologická funkce"), ("b", "Odborně: ACTN3 kóduje protein Z-linie."),
    ("b", "Pro klienta: Gen ACTN3 souvisí s bílkovinou rychlých vláken."),
    ("b", "Frekvence genotypů: původní hodnoty se nepřebírají bez zdroje."),
    ("H1", "Důkazy a přípustné závěry"), ("b", "Interní pracovní posouzení."),
    ("table", [["ID a znak", "Podklad a omezení", "Použití v reportu"],
               ["E01 Molekulární důsledek", "Záznam ClinVar. [S1, S2]", "Nevyvozovat výkon."],
               ["E02 Silově-rychlostní disciplíny", "Metaanalýza OR 1,21. [S3]", "Populační asociace."]]),
    ("H2", "Návrhy klientských textů pro jednotlivé genotypy"),
    ("b", "G_CC: Byl zjištěn genotyp CC (RR). Z výsledku nelze určit sílu. [S3, S4]"),
    ("b", "G_CT: Byl zjištěn genotyp CT (RX)."), ("b", "G_TT: Byl zjištěn genotyp TT (XX)."),
    ("H2", "Výroky nepřípustné v této verzi"),
    ("b", "„Máte více rychlých vláken“; „jste univerzální typ“; „nevyužíváte svůj genetický potenciál“."),
    ("H1", "Zdroje a změny proti původní kartě"), ("b", "Zdroje byly ověřeny."),
    ("H2", "S1 Identita varianty"),
    ("b", "NCBI ClinVar. ACTN3 NM_001104.4:c.1729C>T. Variation ID 18312. Přístup 3. 11. 2026.\n"
          "https://www.ncbi.nlm.nih.gov/clinvar/variation/18312/"),
    ("H2", "S3 Populační asociace"),
    ("b", "Ma F et al. PLOS ONE. 2013;8(1):e54685. https://doi.org/10.1371/journal.pone.0054685"),
    ("H2", "Přehled provedených změn"), ("b", "Odstraněny deterministické výroky."),

    ("H1", "FTO / rs9939609"),
    ("b", "Hmotnost a stravovací kontext • Hmotnost a metabolický kontext"),
    ("b", "K odbornému dopracování."),
    ("H2", "Identifikace"),
    ("b", "Pracovní zápisy genotypů: TT, AT, AA. Laboratorní konvenci je třeba potvrdit."),
    ("H2", "Frekvence a důkazy"), ("b", "Doplnit konkrétní populaci."),
    ("H2", "Omezení a revize"), ("b", "Neurčovat kalorický příjem z genotypu."),
]


def test_prevod_karet_z_wordu(org, tmp_path):
    path = _docx(tmp_path / "karty.docx", KARTY)
    result = import_cards(path, organization=org)
    assert result.created == ["ACE / rs1799752", "MCM6/LCT / rs4988235", "ACTN3 / rs1815739",
                              "FTO / rs9939609"]

    ace = GeneVariant.objects.get(rsid="rs1799752")
    assert ace.gene == "ACE" and ace.domain.code == "vykon"
    assert ace.full_name == "Angiotensin-converting enzyme (Angiotenzin-konvertující enzym)"
    assert ace.genotypes == ["II", "ID", "DD"] and ace.notation == "rs1799752 (I/D)"
    assert ace.frequency_source.startswith("https://www.ncbi")
    original, draft = ace.cards.order_by("version")
    assert original.status == GeneCard.Status.ORIGINAL and draft.status == GeneCard.Status.DRAFT
    assert draft.supersedes == original
    assert original.review_priorities == "Ověřit mapování ACE I/D."
    assert original.biology_client == "Gen ACE ovlivňuje cévy." and original.effect.startswith("Alela D")
    assert original.related_areas == ["Aerobní kapacita", "Vytrvalostní výkon"]
    assert original.frequency_note == "Převzaté frekvence: doložit zdroj."
    ii = original.genotype_texts.get(genotype="II")
    assert ii.client_text == "Váš profil odpovídá vytrvalosti." and ii.frequency == "20 % (Evropská populace)"
    kinds = list(original.recommendations.values_list("genotype", "kind", "basis"))
    assert kinds == [("II", "sport", ""), ("II", "training", ""), ("II", "risk", "")]
    first, second = original.scenarios.order_by("order")
    assert first.kind == ContextScenario.Kind.QUESTIONNAIRE and not first.is_active
    assert first.statement == "Lépe zvládám delší zátěž." and first.texts.count() == 3
    assert second.kind == ContextScenario.Kind.MEASUREMENT and second.texts.count() == 1
    interaction = GeneInteraction.objects.get(source_card=original)
    assert interaction.variants == ["rs1799752", "rs1815739"]
    assert interaction.areas == ["Svalová hypertrofie a síla", "Vytrvalostní výkon"]
    assert interaction.text == "Kombinace může podporovat silově-rychlostní profil."
    assert interaction.status == GeneInteraction.Status.HYPOTHESIS
    assert original.sources.count() == 2 and draft.sources.count() == 2
    assert "Následují původní návrhy doporučení." in original.import_note
    # Návrh je kopie původního znění; kontrola řekne, co chybí ke schválení.
    assert draft.genotype_texts.count() == 3 and draft.recommendations.count() == 3
    check = services.checklist(draft)
    assert any("nemá uvedený důvod" in i.text for i in check.blocking)
    assert any("Neúplná citace" in i.text for i in check.warnings)
    assert any("řádek důkazů" in i.text for i in check.warnings)

    # Název z nadpisu karty má přednost před „Gen“ v původní kartě.
    lct = GeneVariant.objects.get(rsid="rs4988235")
    assert lct.gene == "MCM6/LCT" and lct.domain.code == "laktoza"
    lct_draft = lct.cards.get(version=2)
    assert lct_draft.genotype_texts.get(genotype="CC").client_text.startswith("Genotyp CC je spojen")
    assert lct.cards.get(version=1).genotype_texts.get(genotype="CC").client_text == "Poroste riziko intolerance."
    assert "Gen v původní kartě: LCT" in lct_draft.import_note
    assert lct_draft.revisions.count() == 3

    # Pozdější revize ACTN3: nové texty v návrhu, původní znění zachováno a zapsáno v revizích.
    actn3 = GeneVariant.objects.get(rsid="rs1815739")
    assert actn3.genotype_aliases == {"CC": "RR", "CT": "RX", "TT": "XX"}
    v1, v2 = actn3.cards.order_by("version")
    assert v1.genotype_texts.get(genotype="CC").client_text == "Máte vyšší podíl rychlých vláken."
    assert v2.genotype_texts.get(genotype="CC").client_text.startswith("Byl zjištěn genotyp CC (RR)")
    assert v2.biology_client == "Gen ACTN3 souvisí s bílkovinou rychlých vláken."
    assert v2.biology_expert == "ACTN3 kóduje protein Z-linie."
    assert v2.frequency_note == "původní hodnoty se nepřebírají bez zdroje."
    assert v2.change_summary == "Odstraněny deterministické výroky."
    revision = v2.revisions.get(part="Interpretace genotypu CC")
    assert revision.original == "Máte vyšší podíl rychlých vláken."
    assert revision.decision == CardRevision.Decision.OPEN and "v0.2" in revision.reason
    assert v2.revisions.count() == 4
    e01 = v2.evidence.get(code="E01")
    assert e01.trait == "Molekulární důsledek" and e01.source_labels == "S1, S2"
    assert e01.usage == "Nevyvozovat výkon."
    s1 = v2.sources.get(label="S1")
    assert s1.title == "Identita varianty" and s1.url == "https://www.ncbi.nlm.nih.gov/clinvar/variation/18312/"
    assert v2.sources.get(label="S3").url == "https://doi.org/10.1371/journal.pone.0054685"
    assert list(v2.forbidden_statements.values_list("text", flat=True)) == [
        "Máte více rychlých vláken", "jste univerzální typ", "nevyužíváte svůj genetický potenciál"]
    assert v1.evidence.count() == 0 and v1.forbidden_statements.count() == 0
    assert services.forbidden_in(v2, "Podle testu máte více rychlých vláken.") == ["Máte více rychlých vláken"]
    assert not any("nepřípustný" in i.text for i in services.checklist(v2).blocking)

    # Osnova bez původního obsahu: jen návrh s úkoly k doplnění.
    fto = GeneVariant.objects.get(rsid="rs9939609")
    assert fto.genotypes == ["TT", "AT", "AA"] and fto.domain.code == "hmotnost"
    (fto_card,) = fto.cards.all()
    assert fto_card.status == GeneCard.Status.DRAFT and fto_card.version == 1
    assert fto_card.limitations == "Neurčovat kalorický příjem z genotypu."
    assert list(fto_card.revisions.values_list("part", flat=True)) == [
        "Identifikace", "Frekvence a důkazy", "Omezení a revize"]

    panel = GenePanel.objects.get(code="panel-podklady")
    assert panel.items.count() == 4
    item = panel.items.get(variant=actn3)
    assert item.genotype_map == {"RR": "CC", "RX": "CT", "XX": "TT"}
    assert item.normalize("RX") == "CT" and item.lab_label == ""

    # Opakovaný převod nic nepřepíše.
    again = import_cards(path, organization=org)
    assert again.created == [] and len(again.skipped) == 4
    assert GeneCard.objects.count() == 7


def test_prikaz_nacist_karty(org, tmp_path, capsys):
    with pytest.raises(CommandError):
        call_command("nacist_genove_karty", str(tmp_path / "neexistuje.docx"))
    path = _docx(tmp_path / "karty.docx", KARTY[:5] + KARTY[8:10])
    call_command("nacist_genove_karty", str(path), organizace="ftvs")
    out = capsys.readouterr().out
    assert "Založeno: ACE / rs1799752" in out and "Hotovo" in out
    assert GeneVariant.objects.get(rsid="rs1799752").organization == org


# --- životní cyklus karty -----------------------------------------------------

def test_schvaluje_jen_garant_a_jen_bez_blokujicich_nedostatku(org):
    guarantor, g_client = _user(org, Role.LAB, "metodik")
    lab, lab_client = _user(org, Role.LAB, "laborant")
    admin, admin_client = _user(org, Role.ADMIN, "spravce")
    Domain.objects.get(code="vykon").guarantors.add(guarantor)
    variant = _variant(org)
    original = _card(variant, status=GeneCard.Status.ORIGINAL)
    draft = services.new_version(original, by=lab)
    assert draft.version == 2 and draft.status == GeneCard.Status.DRAFT
    assert draft.genotype_texts.count() == 3 and draft.supersedes == original
    with pytest.raises(ValueError):
        services.new_version(original)  # rozpracovaná verze už existuje

    page = lab_client.get(f"/genetika/karta/{draft.pk}/").content.decode()
    assert "Kontrola před schválením" in page and "Poslat k revizi" in page
    Recommendation.objects.create(card=draft, genotype="CC", kind="training",
                                  text="Zařaďte plyometrii.")
    assert lab_client.post(f"/genetika/karta/{draft.pk}/akce/", {"akce": "k_revizi"}).status_code == 302
    draft.refresh_from_db()
    assert draft.status == GeneCard.Status.REVIEW

    # Laborant bez garance schválit nesmí; garant jen bez blokujících nedostatků.
    response = lab_client.post(f"/genetika/karta/{draft.pk}/akce/", {"akce": "schvalit"})
    assert response.status_code == 403 and "garant" in response.content.decode()
    response = g_client.post(f"/genetika/karta/{draft.pk}/akce/", {"akce": "schvalit"}, follow=True)
    assert "nemá uvedený důvod" in response.content.decode()
    draft.refresh_from_db()
    assert draft.status == GeneCard.Status.REVIEW
    draft.recommendations.update(basis=Recommendation.Basis.GENERAL)
    ForbiddenStatement.objects.create(card=None, text="jste univerzální typ")
    draft.genotype_texts.filter(genotype="CT").update(client_text="Jste univerzální typ sportovce.")
    assert any("nepřípustný výrok" in i.text for i in services.checklist(draft).blocking)
    draft.genotype_texts.filter(genotype="CT").update(client_text="Byl zjištěn genotyp CT.")
    assert services.checklist(draft).ok

    g_client.post(f"/genetika/karta/{draft.pk}/akce/", {"akce": "schvalit"})
    draft.refresh_from_db()
    assert draft.status == GeneCard.Status.APPROVED and draft.approved_by == guarantor
    assert variant.current_card() == draft

    # Nová verze ze schválené; její schválení nahradí předchozí.
    response = lab_client.post(f"/genetika/karta/{draft.pk}/akce/", {"akce": "nova_verze"})
    v3 = variant.cards.get(version=3)
    assert response.url.endswith(f"/genetika/karta/{v3.pk}/") and v3.supersedes == draft
    services.submit_for_review(v3)
    g_client.post(f"/genetika/karta/{v3.pk}/akce/", {"akce": "schvalit"})
    draft.refresh_from_db()
    v3.refresh_from_db()
    assert draft.status == GeneCard.Status.SUPERSEDED and v3.status == GeneCard.Status.APPROVED
    assert variant.current_card() == v3
    page = admin_client.get(f"/genetika/karta/{v3.pk}/").content.decode()
    assert "Nová verze k revizi" in page and "schválil metodik" in page


def test_spravce_bez_garance_neschvaluje_a_vyrazuje_jen_spravce(org):
    guarantor, _ = _user(org, Role.LAB, "metodik")
    admin, admin_client = _user(org, Role.ADMIN, "spravce")
    lab, lab_client = _user(org, Role.LAB, "laborant")
    Domain.objects.get(code="vykon").guarantors.add(guarantor)
    variant = _variant(org)
    card = _card(variant, status=GeneCard.Status.REVIEW)
    with pytest.raises(PermissionError):
        services.approve(card, by=admin)
    services.approve(card, by=guarantor)
    v2 = services.new_version(card, by=lab)
    services.submit_for_review(v2)
    services.approve(v2, by=guarantor)
    card.refresh_from_db()
    assert card.status == GeneCard.Status.SUPERSEDED and variant.current_card() == v2
    assert lab_client.post(f"/genetika/karta/{v2.pk}/akce/", {"akce": "vyradit"}).status_code == 403
    admin_client.post(f"/genetika/karta/{v2.pk}/akce/", {"akce": "vyradit"})
    v2.refresh_from_db()
    assert v2.status == GeneCard.Status.RETIRED and variant.current_card() is None
    page = admin_client.get("/genetika/").content.decode()
    assert "Garanti oblastí" in page and "metodik" in page


# --- souhlas, vzorek, genotypy --------------------------------------------------

def _panel(org):
    panel = GenePanel.objects.create(organization=org, code="p10", name="Panel", provider="Lab s.r.o.")
    actn3 = _variant(org)
    ace = _variant(org, gene="ACE", rsid="rs1799752", genotypes=["II", "ID", "DD"],
                   genotype_aliases={})
    PanelItem.objects.create(panel=panel, variant=actn3, order=1, lab_label="ACTN3 R577X")
    PanelItem.objects.create(panel=panel, variant=ace, order=2)
    return panel, actn3, ace


def test_souhlas_jen_dospely_a_genotypy_sifrovane(org, settings):
    lab, lab_client = _user(org, Role.LAB, "laborant")
    panel, actn3, ace = _panel(org)
    adult = _subject(org, "FTVS-0001", birth=date(1990, 5, 1))
    minor = _subject(org, "FTVS-0002", birth_year=timezone.localdate().year - 15)
    unknown = Subject.objects.create(organization=org, code="FTVS-0003")

    with pytest.raises(ValueError, match="dospělé"):
        services.grant_consent(minor, by=lab)
    with pytest.raises(ValueError, match="věk"):
        services.grant_consent(unknown, by=lab)
    page = lab_client.get(f"/genetika/sportovec/{minor.pk}/").content.decode()
    assert "jen pro dospělé" in page and "Zapsat souhlas" not in page

    # Bez souhlasu se vzorek neuloží.
    page = lab_client.get(f"/genetika/sportovec/{adult.pk}/").content.decode()
    assert "nemá platný souhlas" in page and "Zapsat souhlas" in page
    lab_client.post(f"/genetika/sportovec/{adult.pk}/akce/", {"akce": "souhlas_udelit"})
    assert Consent.has(adult, Consent.Scope.GENETICS)
    data = {"akce": "vzorek", "panel": panel.pk, "provider": "", "external_reference": "L-77",
            "sampled_on": "2026-10-01", "reported_on": "2026-10-20", "note": "",
            f"g_{actn3.pk}": "rx", f"g_{ace.pk}": "XY"}
    response = lab_client.post(f"/genetika/sportovec/{adult.pk}/", data, follow=True)
    page = response.content.decode()
    sample = GeneticSample.objects.get(subject=adult)
    assert sample.status == GeneticSample.Status.RECEIVED and sample.provider == "Lab s.r.o."
    assert sample.consent == adult.consents.get(scope=Consent.Scope.GENETICS)
    first = sample.genotypes.get(variant=actn3)
    assert first.value == "CT" and first.raw == "rx" and first.quality == Genotype.Quality.OK
    assert "CT" not in first.value_enc and "rx" not in first.raw_enc
    second = sample.genotypes.get(variant=ace)
    assert second.value == "" and second.quality == Genotype.Quality.UNCLEAR
    assert "CT (RX)" in page and "Nejasný zápis" in page and "1× nejasný" in page

    lab_client.post(f"/genetika/sportovec/{adult.pk}/akce/",
                    {"akce": "overit", "vzorek": sample.pk})
    sample.refresh_from_db()
    assert sample.status == GeneticSample.Status.VERIFIED and sample.verified_by == lab
    detail = lab_client.get(f"/sportovci/{adult.pk}/").content.decode()
    assert "Genetika" in detail and "ověřeno" in detail

    # Vypnutá varianta zmizí z výpisu, genotyp zůstane uložený.
    ace.is_active = False
    ace.save()
    page = lab_client.get(f"/genetika/sportovec/{adult.pk}/").content.decode()
    assert "ACE / rs1799752" not in page and Genotype.objects.filter(variant=ace).exists()
    assert "vypnuto" in lab_client.get("/genetika/").content.decode()

    # Odvolání souhlasu (tady laboratoří) smaže genotypy, vzorek zůstane jako záznam.
    lab_client.post(f"/genetika/sportovec/{adult.pk}/akce/", {"akce": "souhlas_odvolat"})
    assert not Genotype.objects.filter(sample__subject=adult).exists()
    sample.refresh_from_db()
    assert sample.status == GeneticSample.Status.WITHDRAWN
    assert not Consent.has(adult, Consent.Scope.GENETICS)

    # Bez klíče a v ukázce se genotypy nezadávají.
    services.grant_consent(adult, by=lab)
    settings.GENETICS_ENCRYPTION_KEY = ""
    page = lab_client.get(f"/genetika/sportovec/{adult.pk}/").content.decode()
    assert "GENETICS_ENCRYPTION_KEY není nastaven" in page
    settings.GENETICS_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.DEMO_MODE = True
    response = lab_client.post(f"/genetika/sportovec/{adult.pk}/", data, follow=True)
    assert "V ukázce se genotypy nezadávají" in response.content.decode()
    assert GeneticSample.objects.filter(subject=adult).count() == 1


def test_sportovec_dava_souhlas_v_portalu_trener_a_vyzkumnik_genetiku_nevidi(org):
    lab, lab_client = _user(org, Role.LAB, "laborant")
    panel, actn3, ace = _panel(org)
    adult = _subject(org, "FTVS-0001", birth=date(1990, 5, 1))
    athlete, athlete_client = _user(org, Role.ATHLETE, "jana@example.cz")
    identity = adult.identity
    identity.user = athlete
    identity.save()

    page = athlete_client.get(f"/muj/{adult.pk}/souhlasy/").content.decode()
    assert "Udělit souhlas s genetickými daty" in page and "trenér ho nevidí nikdy" in page
    athlete_client.post(f"/muj/{adult.pk}/souhlasy/", {"akce": "genetika_udelit"})
    consent = adult.consents.get(scope=Consent.Scope.GENETICS)
    assert consent.is_valid and "účtu sportovce" in consent.note
    sample = services.record_sample(adult, panel, by=lab, data={},
                                    genotypes={actn3.pk: "CC", ace.pk: "ID"})
    assert sample.genotypes.count() == 2
    page = athlete_client.get(f"/muj/{adult.pk}/souhlasy/").content.decode()
    assert "Odvolat souhlas" in page and "vzorky: 1" in page and "CC" not in page.split("Genetika")[1][:600]

    # Portálové role na obrazovky genetiky nemůžou; výzkumník vidí karty, ne genotypy.
    assert athlete_client.get("/genetika/").url == "/muj/"
    coach, coach_client = _user(org, Role.COACH, "trener")
    assert coach_client.get("/genetika/").url == "/trener/"
    assert coach_client.get(f"/genetika/sportovec/{adult.pk}/").url == "/trener/"
    researcher, r_client = _user(org, Role.RESEARCHER, "vyzkum")
    assert r_client.get("/genetika/").status_code == 200
    assert r_client.get(f"/genetika/sportovec/{adult.pk}/").status_code == 403
    detail = r_client.get(f"/sportovci/{adult.pk}/").content.decode()
    assert "Genetika" in detail and "Otevřít" not in detail.split('id="genetika"')[1][:400]

    # Odvolání v portálu smaže genotypy; změna je v auditu.
    athlete_client.post(f"/muj/{adult.pk}/souhlasy/", {"akce": "genetika_odvolat"})
    assert Genotype.objects.count() == 0
    sample.refresh_from_db()
    assert sample.status == GeneticSample.Status.WITHDRAWN
    from apps.core.models import AuditLog

    assert AuditLog.objects.filter(subject_code="FTVS-0001", detail__souhlas="genetika").count() == 2


def test_smazany_souhlas_v_administraci_take_maze_genotypy(org):
    lab, _ = _user(org, Role.LAB, "laborant")
    panel, actn3, ace = _panel(org)
    adult = _subject(org, "FTVS-0001", birth=date(1990, 5, 1))
    services.grant_consent(adult, by=lab)
    sample = services.record_sample(adult, panel, by=lab, data={}, genotypes={actn3.pk: "TT"})
    # Chybějící výsledek se zapíše jako „chybí“, ať je vidět, co laboratoř nedodala.
    assert sample.genotypes.get(variant=ace).quality == Genotype.Quality.MISSING
    assert Genotype.objects.count() == 2
    adult.consents.get(scope=Consent.Scope.GENETICS).delete()
    assert Genotype.objects.count() == 0


# --- přenos katalogu --------------------------------------------------------------

def test_katalog_genetiky_projde_tam_a_zpet(org):
    guarantor, _ = _user(org, Role.LAB, "metodik")
    domain = Domain.objects.get(code="vykon")
    domain.guarantors.add(guarantor)
    variant = _variant(org, order=3, strand_note="C/T vs. R/X")
    panel = GenePanel.objects.create(organization=org, code="p10", name="Panel", provider="Lab")
    PanelItem.objects.create(panel=panel, variant=variant, genotype_map={"RR": "CC"}, order=1)
    v1 = _card(variant, status=GeneCard.Status.REVIEW, review_priorities="Nevyvozovat typ sportu.")
    Recommendation.objects.create(card=v1, genotype="CC", kind="training", text="Plyometrie.",
                                  basis="general", merge_key="plyometrie")
    CardEvidence.objects.create(card=v1, code="E01", trait="Důsledek", basis_text="ClinVar [S1]",
                                usage="Nevyvozovat výkon.", source_labels="S1")
    CardSource.objects.create(card=v1, label="S1", title="Identita", citation="NCBI ClinVar 18312.",
                              url="https://www.ncbi.nlm.nih.gov/clinvar/variation/18312/")
    ForbiddenStatement.objects.create(card=v1, text="jste univerzální typ")
    scenario = ContextScenario.objects.create(card=v1, kind="questionnaire",
                                              statement="Lépe zvládám sprinty.")
    scenario.texts.create(genotype="CC", text="Odpovídá.")
    CardRevision.objects.create(card=v1, part="Interpretace CC", original="Staré.", proposal="Nové.",
                                reason="důkazy", decision="accepted")
    services.approve(v1, by=guarantor)
    v2 = services.new_version(v1)
    GeneInteraction.objects.create(organization=org, title="ACE × ACTN3", assumption="DD + CC",
                                   text="Hypotéza.", variants=["rs1799752", "rs1815739"],
                                   source_card=v1)
    ForbiddenStatement.objects.create(card=None, text="nevyužíváte potenciál")

    data = json.loads(json.dumps(export_catalog(), default=str))
    assert {c["version"] for c in data["genetika"]["karty"]} == {1, 2}
    GeneInteraction.objects.all().delete()
    GeneCard.objects.all().delete()
    PanelItem.objects.all().delete()
    GenePanel.objects.all().delete()
    GeneVariant.objects.all().delete()
    ForbiddenStatement.objects.all().delete()
    Domain.objects.all().delete()

    counts = import_catalog(data)
    assert counts["genové karty"] == [2, 0] and counts["genové varianty"] == [1, 0]
    variant = GeneVariant.objects.get(rsid="rs1815739")
    assert variant.strand_note == "C/T vs. R/X" and variant.domain.code == "vykon"
    assert Domain.objects.get(code="vykon").guarantors.count() == 0  # účty se nepřenáší
    assert GenePanel.objects.get(code="p10").items.get().genotype_map == {"RR": "CC"}
    v1, v2 = variant.cards.order_by("version")
    assert v1.status == GeneCard.Status.APPROVED and v1.review_priorities == "Nevyvozovat typ sportu."
    assert v1.approved_at is not None and v2.supersedes == v1
    assert v1.recommendations.get().merge_key == "plyometrie"
    assert v1.evidence.get().source_labels == "S1" and v1.sources.get().url.endswith("18312/")
    assert v1.forbidden_statements.get().text == "jste univerzální typ"
    assert v1.scenarios.get().texts.get().text == "Odpovídá."
    assert v1.revisions.get().decision == "accepted"
    assert v2.genotype_texts.count() == 3
    assert GeneInteraction.objects.get().source_card == v1
    assert ForbiddenStatement.objects.get(card__isnull=True).text == "nevyužíváte potenciál"
    # Druhé načtení jen aktualizuje.
    assert import_catalog(data)["genové karty"] == [0, 2]


# --- administrace: skupiny rolí ---------------------------------------------------------

def test_skupiny_roli_dosahnou_na_genetiku(org):
    """Správce a diagnostik bez superuživatele musí administraci genetiky otevřít."""
    from django.contrib.auth.models import Group
    from django.core.management import call_command

    call_command("seed_roles", verbosity=0)
    spravce = Group.objects.get(name="Správce")
    diagnostik = Group.objects.get(name="Diagnostik")
    vyzkumnik = Group.objects.get(name="Výzkumník")
    codes = lambda g: set(g.permissions.values_list("codename", flat=True))  # noqa: E731
    assert {"add_genecard", "change_genecard", "delete_genecard", "view_geneticsample",
            "change_bookingrequest"} <= codes(spravce)
    assert {"change_genecard", "view_geneticsample"} <= codes(diagnostik)
    assert "delete_genecard" not in codes(diagnostik)
    assert "view_genecard" in codes(vyzkumnik)
    assert not {"view_geneticsample", "view_genotype", "change_genecard"} & codes(vyzkumnik)

    admin, admin_client = _user(org, Role.ADMIN, "spravce-bez-super")
    admin.is_staff = True
    admin.save()
    admin.groups.add(spravce)
    assert admin_client.get("/admin/genetics/").status_code == 200
    assert admin_client.get("/admin/genetics/genecard/").status_code == 200
    page = admin_client.get("/genetika/").content.decode()
    assert "Administrace genetiky" in page
    researcher, r_client = _user(org, Role.RESEARCHER, "vyzkum-staff")
    researcher.is_staff = True
    researcher.save()
    researcher.groups.add(vyzkumnik)
    assert r_client.get("/admin/genetics/genecard/").status_code == 200
    assert r_client.get("/admin/genetics/geneticsample/").status_code == 403
    # Bez přístupu do administrace se tlačítko nenabízí.
    lab, lab_client = _user(org, Role.LAB, "laborant-bez-admin")
    page = lab_client.get("/genetika/").content.decode()
    assert "Administrace genetiky" not in page and "Stav týmu" in page
