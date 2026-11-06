"""
Průvodce kartou: nová karta v aplikaci, osm kroků s jedním formulářem,
původní znění vedle polí, texty scénářů, zdroje a důkazy v aplikaci,
kontrola a schválení. Stav kroků plyne z dat; Word je jen zkratka.
"""

from html.parser import HTMLParser

import pytest
from cryptography.fernet import Fernet
from django.urls import reverse

from apps.core.models import Organization, Role
from apps.genetics import services
from apps.genetics.card_steps import STEPS, card_steps
from apps.genetics.models import (
    CardEvidence,
    CardRevision,
    CardSource,
    ContextScenario,
    Domain,
    ForbiddenStatement,
    GeneCard,
    GenePanel,
    GeneVariant,
    GenotypeText,
    Recommendation,
    ScenarioText,
)
from apps.genetics.seed import seed_domains
from tests.test_genetika import _card, _user, _variant


@pytest.fixture
def org(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.GENETICS_ENCRYPTION_KEY = Fernet.generate_key().decode()
    seed_domains()
    return Organization.objects.create(name="FTVS", short_name="ftvs")


def _step(card, slug):
    return reverse("genetics_card_step", args=[card.pk, slug])


# --- nová karta --------------------------------------------------------------------------

def test_novou_kartu_zalozi_laborant_a_pruvodce_vede_dal(org):
    _, client = _user(org, Role.LAB, "laborant")
    _, r_client = _user(org, Role.RESEARCHER, "vyzkumnik")
    url = reverse("genetics_card_new")
    assert r_client.get(url).status_code == 403
    page = client.get(url)
    assert page.status_code == 200 and "Nová genová karta" in page.content.decode()
    home = client.get(reverse("genetics_home")).content.decode()
    assert url in home and "Nová karta" in home

    vykon = Domain.objects.get(code="vykon")
    data = {"gene": "cyp1a2", "rsid": "rs762551", "full_name": "cytochrom P450 1A2",
            "domain": str(vykon.pk), "genotypes": "AA, AC, CC", "aliases": "AA=A/A; cc = C/C",
            "notation": "rs762551 (-163C>A)", "subtitle": "Kofein", "strand_note": "",
            "frequency_source": "gnomAD v4"}
    resp = client.post(url, data)
    variant = GeneVariant.objects.get(rsid="rs762551")
    card = variant.cards.get()
    assert resp.status_code == 302 and resp.url == _step(card, "gen")
    assert (variant.gene, variant.domain, variant.genotypes) == ("CYP1A2", vykon, ["AA", "AC", "CC"])
    assert variant.genotype_aliases == {"AA": "A/A", "CC": "C/C"}
    assert variant.organization is None and variant.subtitle == "Kofein"
    assert card.status == GeneCard.Status.DRAFT and card.version == 1 and card.is_editable
    # varianta je rovnou v panelu laboratoře, s převodem zápisu
    item = GenePanel.objects.get().items.get(variant=variant)
    assert item.genotype_map == {"A/A": "AA", "C/C": "CC"}
    # krok 2 nastavení je hotový, krok 1 průvodce kartou taky
    assert client.get(reverse("genetics_home")).context["steps"][1]["done"]
    steps = card_steps(card)
    assert [s["n"] for s in steps] == list(range(1, 9)) and len(STEPS) == 8
    assert steps[0]["done"] and not steps[1]["done"] and not steps[7]["done"]

    # stejné rsID podruhé neprojde, chybějící genotypy taky
    text = client.post(url, data, follow=True).content.decode()
    assert "už je" in text and GeneVariant.objects.filter(rsid="rs762551").count() == 1
    text = client.post(url, {**data, "rsid": "rs1", "genotypes": "AA"}, follow=True).content.decode()
    assert "aspoň dva genotypy" in text and not GeneVariant.objects.filter(rsid="rs1").exists()
    text = client.post(url, {**data, "rsid": "rs2", "aliases": "GG=X"}, follow=True).content.decode()
    assert "není genotyp varianty" in text and not GeneVariant.objects.filter(rsid="rs2").exists()


# --- přehled a kroky --------------------------------------------------------------------

def test_prehled_karty_ukazuje_osm_kroku_a_co_chybi(org):
    _, client = _user(org, Role.LAB, "laborant")
    _, r_client = _user(org, Role.RESEARCHER, "vyzkumnik")
    card = _card(_variant(org), texts=False)
    url = reverse("genetics_card_edit", args=[card.pk])
    assert r_client.get(url).status_code == 403
    page = client.get(url)
    assert page.status_code == 200
    titles = [s["title"] for s in page.context["steps"]]
    assert titles == ["Varianta", "Co gen dělá", "Texty pro genotypy", "Doporučení s důvody",
                      "Kontext z dotazníku", "Co zpráva říkat nesmí", "Zdroje a důkazy",
                      "Kontrola a schválení"]
    text = page.content.decode()
    assert "Průvodce kartou" in text and "Další krok: Texty pro genotypy" in text
    assert _step(card, "genotypy") in text and _step(card, "kontrola") in text
    assert "Chybí text pro CC, CT, TT" in text
    assert url in client.get(reverse("genetics_card", args=[card.pk])).content.decode()

    # neznámý krok 404; schválená karta je jen ke čtení
    assert client.get(_step(card, "neznamy")).status_code == 404
    card.status = GeneCard.Status.APPROVED
    card.save()
    resp = client.get(url, follow=True)
    assert resp.redirect_chain[-1][0] == reverse("genetics_card", args=[card.pk])
    assert "jen ke čtení" in resp.content.decode()
    assert client.get(_step(card, "gen")).status_code == 302


def test_krok_varianta_upravi_variantu_a_genotypy_hlida(org):
    _, client = _user(org, Role.LAB, "laborant")
    variant = _variant(org)
    card = _card(variant)
    url = _step(card, "varianta")
    form = _form_values(client.get(url).content.decode())
    assert form["genotypes"] == "CC, CT, TT" and form["aliases"] == "CC=RR, CT=RX, TT=XX"
    resp = client.post(url, {**form, "full_name": "alfa-aktinin 3", "genotypes": "CC, CT, TT, XY",
                             "subtitle": "Síla", "akce": "dalsi"})
    assert resp.url == _step(card, "gen")
    variant.refresh_from_db()
    assert variant.full_name == "alfa-aktinin 3" and variant.genotypes == ["CC", "CT", "TT", "XY"]
    # chyba: nic se neuloží a zůstane se na kroku
    text = client.post(url, {**form, "rsid": "", "akce": "dalsi"}, follow=True).content.decode()
    assert "Doplňte rsID" in text
    variant.refresh_from_db()
    assert variant.rsid == "rs1815739"
    # schválená karta zamkne genotypy, ostatní jde měnit
    _card(variant, version=2, status=GeneCard.Status.APPROVED)
    page = client.get(url)
    assert page.context["locked"] and "readonly" in page.content.decode()
    client.post(url, {**form, "genotypes": "AA, BB", "subtitle": "Výbušnost"})
    variant.refresh_from_db()
    assert variant.genotypes == ["CC", "CT", "TT", "XY"] and variant.subtitle == "Výbušnost"


def test_kroky_gen_a_genotypy_ulozi_texty_a_ukazi_puvodni_zneni(org):
    _, client = _user(org, Role.LAB, "laborant")
    variant = _variant(org)
    original = _card(variant, status=GeneCard.Status.ORIGINAL,
                     limitations="Původní omezení z Wordu.")
    card = _card(variant, version=2, texts=False, supersedes=original)
    ForbiddenStatement.objects.create(card=card, text="máte více rychlých vláken")

    page = client.get(_step(card, "gen"))
    text = page.content.decode()
    assert page.status_code == 200 and "Původní znění z podkladů" in text
    assert "Původní omezení z Wordu." in text and "máte více rychlých vláken" in text
    resp = client.post(_step(card, "gen"), {
        "biology_client": "Gen ACTN3 ovlivňuje bílkovinu rychlých svalových vláken.",
        "limitations": "Jeden gen výkon neurčuje.", "effect": "Zkrácená bílkovina.",
        "akce": "dalsi"})
    assert resp.url == _step(card, "genotypy")
    card.refresh_from_db()
    assert card.biology_client.startswith("Gen ACTN3") and card.effect == "Zkrácená bílkovina."
    assert card.limitations == "Jeden gen výkon neurčuje."

    text = client.get(_step(card, "genotypy")).content.decode()
    assert "Zjištěn genotyp CC." in text  # původní text z verze 1 vedle pole
    resp = client.post(_step(card, "genotypy"), {
        "text_CC": "Genotyp CC: bílkovina se tvoří.", "text_CT": "Genotyp CT: tvoří se méně.",
        "text_TT": "Genotyp TT: bílkovina se netvoří.", "freq_CC": "30 % (Evropa)",
        "frequency_source": "gnomAD v4", "frequency_note": "Evropská populace.",
        "akce": "prehled"})
    assert resp.url == reverse("genetics_card_edit", args=[card.pk])
    card.refresh_from_db()
    variant.refresh_from_db()
    assert card.genotype_texts.get(genotype="CC").frequency == "30 % (Evropa)"
    assert card.genotype_texts.get(genotype="TT").client_text == "Genotyp TT: bílkovina se netvoří."
    assert variant.frequency_source == "gnomAD v4" and card.frequency_note == "Evropská populace."
    steps = card_steps(card)
    assert steps[1]["done"] and steps[2]["done"] and services.checklist(card).ok


def test_krok_doporuceni_upravi_prida_a_smaze(org):
    _, client = _user(org, Role.LAB, "laborant")
    card = _card(_variant(org))
    url = _step(card, "doporuceni")
    assert client.get(url).status_code == 200
    data = {"rec_count": "2", "rec_genotype_0": "TT", "rec_kind_0": "training",
            "rec_basis_0": "variant", "rec_text_0": "Zařaďte plyometrii.", "rec_key_0": "plyometrie",
            "rec_text_1": "", "akce": "ulozit"}
    resp = client.post(url, data)
    assert resp.status_code == 302 and resp.url == url
    rec = card.recommendations.get()
    assert (rec.genotype, rec.kind, rec.basis, rec.merge_key) == ("TT", "training", "variant", "plyometrie")
    assert card_steps(card)[3]["done"]

    data.update({"rec_count": "3", "rec_id_0": str(rec.pk),
                 "rec_text_0": "Zařaďte plyometrii dvakrát týdně.",
                 "rec_kind_1": "regeneration", "rec_basis_1": "", "rec_text_1": "Spánek 8 h."})
    client.post(url, data)
    rec.refresh_from_db()
    assert rec.text == "Zařaďte plyometrii dvakrát týdně." and card.recommendations.count() == 2
    other = card.recommendations.exclude(pk=rec.pk).get()
    assert other.basis == "" and other.genotype == ""
    step = card_steps(card)[3]
    assert not step["done"] and step["count"] == 1 and "bez důvodu" in step["text"]

    data.update({"rec_delete_0": "on", "rec_id_1": str(other.pk), "rec_basis_1": "general"})
    client.post(url, data)
    assert list(card.recommendations.values_list("text", "basis")) == [("Spánek 8 h.", "general")]


def test_krok_kontext_spravuje_scenare_i_jejich_texty(org):
    _, client = _user(org, Role.LAB, "laborant")
    card = _card(_variant(org))
    scenario = ContextScenario.objects.create(
        card=card, kind=ContextScenario.Kind.QUESTIONNAIRE,
        statement="Lépe zvládám delší souvislou zátěž.")
    ScenarioText.objects.create(scenario=scenario, genotype="CC", text="Starý text CC.")
    url = _step(card, "kontext")
    page = client.get(url)
    text = page.content.decode()
    assert "vykonovy_profil|vytrvalost" in text and "Starý text CC." in text
    key = scenario.pk

    # zapnout bez spouštěcí odpovědi nejde; texty se uloží
    text = client.post(url, {"nsc_count": "0", f"sc_statement_{key}": scenario.statement,
                             f"sc_active_{key}": "on", f"sc_text_{key}_CC": "Nový text CC.",
                             f"sc_text_{key}_TT": "Text TT."}, follow=True).content.decode()
    scenario.refresh_from_db()
    assert not scenario.is_active and "nejde zapnout bez odpovědi" in text
    assert dict(scenario.texts.values_list("genotype", "text")) == {"CC": "Nový text CC.", "TT": "Text TT."}
    step = card_steps(card)[4]
    assert step["done"] and "1 scénářů, 0 zapnutých" in step["text"]

    client.post(url, {"nsc_count": "0", f"sc_statement_{key}": "Lépe zvládám dlouhou zátěž.",
                      f"sc_active_{key}": "on", f"sc_trigger_{key}": "vykonovy_profil|vytrvalost",
                      f"sc_text_{key}_CC": "Nový text CC."})
    scenario.refresh_from_db()
    assert scenario.is_active and scenario.question.code == "vykonovy_profil"
    assert scenario.answer_match == {"choices": ["vytrvalost"]}
    assert scenario.statement == "Lépe zvládám dlouhou zátěž."
    assert list(scenario.texts.values_list("genotype", flat=True)) == ["CC"]  # prázdný TT smazán

    # nový scénář z prázdného řádku, ano/ne otázka; smazání zaškrtnutím
    client.post(url, {"nsc_count": "1", f"sc_statement_{key}": scenario.statement,
                      f"sc_delete_{key}": "on",
                      "nsc_statement_0": "Mám potíže nyní.", "nsc_active_0": "on",
                      "nsc_trigger_0": "obtize_nyni|1", "nsc_text_0_CT": "Text pro CT."})
    assert not ContextScenario.objects.filter(pk=key).exists()
    new = card.scenarios.get()
    assert new.is_active and new.question.code == "obtize_nyni" and new.answer_match == {"value": 1}
    assert new.kind == ContextScenario.Kind.QUESTIONNAIRE
    assert dict(new.texts.values_list("genotype", "text")) == {"CT": "Text pro CT."}


def test_krok_vyroky_karty_a_spolecne_jen_spravce(org):
    admin, a_client = _user(org, Role.ADMIN, "spravce")
    _, client = _user(org, Role.LAB, "laborant")
    card = _card(_variant(org))
    ForbiddenStatement.objects.create(card=None, text="jste univerzální typ", note="globální")
    url = _step(card, "vyroky")
    page = client.get(url)
    text = page.content.decode()
    assert "jste univerzální typ" in text and 'name="shared"' not in text
    client.post(url, {"forbidden": "máte více rychlých vláken\n\n„Jste sprinter.“",
                      "shared": "laborant to nemění", "akce": "ulozit"})
    assert list(card.forbidden_statements.values_list("text", flat=True)) == [
        "máte více rychlých vláken", "Jste sprinter"]
    assert list(ForbiddenStatement.objects.filter(card__isnull=True).values_list("text", flat=True)) == [
        "jste univerzální typ"]
    assert card_steps(card)[5]["done"] and "2 výroků u karty, 1 společných" in card_steps(card)[5]["text"]

    assert 'name="shared"' in a_client.get(url).content.decode()
    a_client.post(url, {"forbidden": "máte více rychlých vláken",
                        "shared": "jste univerzální typ\npotenciál se projevil"})
    shared = ForbiddenStatement.objects.filter(card__isnull=True).order_by("pk")
    assert [(s.text, s.note) for s in shared] == [("jste univerzální typ", "globální"),
                                                   ("potenciál se projevil", "")]
    # výrok v textu genotypu kontrola zachytí
    GenotypeText.objects.filter(card=card, genotype="CC").update(
        client_text="Máte více rychlých vláken.")
    assert not services.checklist(card).ok


def test_krok_zdroje_a_dukazy_v_aplikaci(org):
    _, client = _user(org, Role.LAB, "laborant")
    card = _card(_variant(org))
    url = _step(card, "zdroje")
    assert client.get(url).status_code == 200
    step = card_steps(card)[6]
    assert not step["done"] and "Bez zdroje" in step["text"]
    client.post(url, {
        "src_count": "2", "src_label_0": "S1", "src_title_0": "Frekvence",
        "src_citation_0": "Yang N. et al. ACTN3 genotype is associated with human elite athletic "
                          "performance. Am J Hum Genet. 2003.",
        "src_url_0": "https://doi.org/10.1086/377590",
        "src_citation_1": "",
        "ev_count": "1", "ev_code_0": "E01", "ev_trait_0": "Sprinterský výkon",
        "ev_basis_text_0": "Asociace v populaci elitních sprinterů; malé vzorky.",
        "ev_usage_0": "Jen jako kontext, bez predikce.", "ev_source_labels_0": "S1",
        "akce": "ulozit"})
    source = card.sources.get()
    assert (source.label, source.title, source.url) == ("S1", "Frekvence", "https://doi.org/10.1086/377590")
    evidence = card.evidence.get()
    assert (evidence.code, evidence.trait, evidence.source_labels) == ("E01", "Sprinterský výkon", "S1")
    step = card_steps(card)[6]
    assert step["done"] and "1 zdrojů, 1 řádků důkazů" in step["text"]
    assert not any("zdroj" in w.text for w in services.checklist(card).warnings)

    # úprava podle id, smazání zaškrtnutím
    client.post(url, {"src_count": "1", "src_id_0": str(source.pk), "src_label_0": "S1",
                      "src_citation_0": source.citation + " (2. vydání)",
                      "ev_count": "1", "ev_id_0": str(evidence.pk), "ev_trait_0": "x",
                      "ev_delete_0": "on"})
    source.refresh_from_db()
    assert source.citation.endswith("(2. vydání)") and not card.evidence.exists()


def test_kontrola_posle_k_revizi_a_garant_schvali(org):
    lab, client = _user(org, Role.LAB, "laborant")
    metodik, m_client = _user(org, Role.LAB, "metodik")
    variant = _variant(org)
    variant.domain.guarantors.add(metodik)
    card = _card(variant)
    CardRevision.objects.create(card=card, part="Interpretace CC", proposal="Zmírnit.")
    url = _step(card, "kontrola")
    page = client.get(url)
    text = page.content.decode()
    assert page.status_code == 200 and "Bez blokujících nedostatků" in text
    assert "Poslat k revizi garantovi" in text and "metodik" in text
    step = card_steps(card)[7]
    assert not step["done"] and "pošlete kartu k revizi" in step["text"]

    revision = card.revisions.get()
    client.post(url, {f"rev_decision_{revision.pk}": "accepted", "akce": "ulozit"})
    revision.refresh_from_db()
    assert revision.decision == "accepted" and revision.decided_by == lab

    resp = client.post(url, {"akce": "k_revizi"})
    card.refresh_from_db()
    assert card.status == GeneCard.Status.REVIEW
    assert resp.url == reverse("genetics_card", args=[card.pk])
    assert "V revizi" in card_steps(card)[7]["text"]

    # laborant bez garance neschválí (403), garant ano; schválená karta je ke čtení
    assert client.post(url, {"akce": "schvalit"}).status_code == 403
    text = m_client.get(url).content.decode()
    assert 'value="schvalit"' in text and "Vrátit k úpravě" in text
    resp = m_client.post(url, {"akce": "schvalit"})
    card.refresh_from_db()
    assert card.status == GeneCard.Status.APPROVED and card.approved_by == metodik
    assert resp.url == reverse("genetics_card", args=[card.pk])
    assert card_steps(card)[7]["done"] and "Schváleno" in card_steps(card)[7]["text"]

    # blokující nedostatek: schválení neprojde, zpráva zůstane na kroku
    card2 = _card(_variant(org, gene="ACE", rsid="rs1799752", genotypes=["II", "ID", "DD"],
                           genotype_aliases={}), texts=False)
    services.submit_for_review(card2)
    url2 = _step(card2, "kontrola")
    text = m_client.get(url2).content.decode()
    assert "Blokuje schválení" in text and "disabled" in text
    resp = m_client.post(url2, {"akce": "schvalit"}, follow=True)
    card2.refresh_from_db()
    assert card2.status == GeneCard.Status.REVIEW and "nejde schválit" in resp.content.decode()
    m_client.post(url2, {"akce": "vratit"})
    card2.refresh_from_db()
    assert card2.status == GeneCard.Status.DRAFT


def test_nova_verze_otevre_pruvodce_a_ukaze_predchozi_zneni(org):
    _, client = _user(org, Role.LAB, "laborant")
    variant = _variant(org)
    card = _card(variant, status=GeneCard.Status.APPROVED, limitations="Verze 1.")
    Recommendation.objects.create(card=card, kind="regeneration", basis="general", text="Spánek 8 h.")
    CardSource.objects.create(card=card, label="S1", citation="Citace.")
    CardEvidence.objects.create(card=card, code="E01", trait="znak", basis_text="podklad")
    resp = client.post(reverse("genetics_card_action", args=[card.pk]), {"akce": "nova_verze"})
    new = variant.cards.get(version=2)
    assert resp.url == reverse("genetics_card_edit", args=[new.pk])
    page = client.get(resp.url)
    assert page.status_code == 200 and "předchozí verze (v1)" in page.content.decode().lower()
    assert new.sources.count() == 1 and new.evidence.count() == 1
    text = client.get(_step(new, "gen")).content.decode()
    assert "Předchozí verze (v1)" in text and "Verze 1." in text


# --- co zobrazí, to po odeslání beze změny uloží -------------------------------------------

class _Form(HTMLParser):
    """Posbírá hodnoty formuláře tak, jak by je odeslal prohlížeč."""

    def __init__(self):
        super().__init__()
        self.data = {}
        self._select = None
        self._chosen = False
        self._textarea = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "input" and a.get("name"):
            kind = a.get("type", "text")
            if kind == "checkbox":
                if "checked" in a:
                    self.data[a["name"]] = a.get("value") or "on"
            elif kind not in ("submit", "button", "file"):
                self.data[a["name"]] = a.get("value") or ""
        elif tag == "select":
            self._select, self._chosen = a.get("name"), False
            self.data.pop(self._select, None)
        elif tag == "option" and self._select:
            if "selected" in a:
                self.data[self._select] = a.get("value") or ""
                self._chosen = True
            elif not self._chosen and self._select not in self.data:
                self.data[self._select] = a.get("value") or ""  # prohlížeč pošle první možnost
        elif tag == "textarea":
            self._textarea = a.get("name")
            self.data[self._textarea] = ""

    def handle_data(self, data):
        if self._textarea:
            self.data[self._textarea] += data

    def handle_endtag(self, tag):
        if tag == "select":
            self._select = None
        if tag == "textarea":
            self._textarea = None


def _form_values(html: str) -> dict:
    parser = _Form()
    parser.feed(html)
    return parser.data


def test_kazdy_krok_odesle_zpet_presne_to_co_zobrazi(org):
    _, client = _user(org, Role.ADMIN, "spravce")
    variant = _variant(org, full_name="alfa-aktinin 3", notation="R577X", subtitle="Síla")
    card = _card(variant, limitations="Jeden gen výkon neurčuje.", effect="Účinek.",
                 frequency_note="Pozn.")
    Recommendation.objects.create(card=card, genotype="CC", kind="training", basis="variant",
                                  text="Plyometrie.", merge_key="plyometrie")
    Recommendation.objects.create(card=card, kind="regeneration", basis="general", text="Spánek 8 h.")
    scenario = ContextScenario.objects.create(card=card, kind=ContextScenario.Kind.QUESTIONNAIRE,
                                              statement="Lépe zvládám delší zátěž.")
    ScenarioText.objects.create(scenario=scenario, genotype="TT", text="Text TT.")
    ForbiddenStatement.objects.create(card=card, text="jste sprinter")
    ForbiddenStatement.objects.create(card=None, text="jste univerzální typ")
    CardSource.objects.create(card=card, label="S1", title="k čemu", citation="Dlouhá citace zdroje S1 pro kontrolu.", url="https://example.org")
    CardEvidence.objects.create(card=card, code="E01", trait="znak", basis_text="podklad", usage="použití", source_labels="S1")
    CardRevision.objects.create(card=card, part="část", proposal="návrh")

    for slug in STEPS:
        url = _step(card, slug)
        form = _form_values(client.get(url).content.decode())
        assert client.post(url, {**form, "akce": "ulozit"}).status_code == 302, slug

    variant.refresh_from_db()
    card.refresh_from_db()
    assert (variant.gene, variant.rsid, variant.full_name, variant.notation, variant.subtitle) == (
        "ACTN3", "rs1815739", "alfa-aktinin 3", "R577X", "Síla")
    assert variant.genotypes == ["CC", "CT", "TT"]
    assert variant.genotype_aliases == {"CC": "RR", "CT": "RX", "TT": "XX"}
    assert (card.limitations, card.effect, card.frequency_note) == (
        "Jeden gen výkon neurčuje.", "Účinek.", "Pozn.")
    assert card.genotype_texts.get(genotype="CC").client_text == "Zjištěn genotyp CC."
    assert list(card.recommendations.order_by("order").values_list("text", "genotype", "basis",
                                                                  "merge_key")) == [
        ("Plyometrie.", "CC", "variant", "plyometrie"), ("Spánek 8 h.", "", "general", "")]
    scenario.refresh_from_db()
    assert scenario.statement == "Lépe zvládám delší zátěž." and not scenario.is_active
    assert dict(scenario.texts.values_list("genotype", "text")) == {"TT": "Text TT."}
    assert list(card.forbidden_statements.values_list("text", flat=True)) == ["jste sprinter"]
    assert list(ForbiddenStatement.objects.filter(card__isnull=True).values_list("text", flat=True)) == [
        "jste univerzální typ"]
    source = card.sources.get()
    assert (source.label, source.title, source.url) == ("S1", "k čemu", "https://example.org")
    evidence = card.evidence.get()
    assert (evidence.code, evidence.trait, evidence.basis_text, evidence.usage, evidence.source_labels) == (
        "E01", "znak", "podklad", "použití", "S1")
    assert card.revisions.get().decision == "open"
    assert card.status == GeneCard.Status.DRAFT
