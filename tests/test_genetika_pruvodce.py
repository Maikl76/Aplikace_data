"""
Průvodce genetikou: nastavení ve čtyřech krocích, editor karty v aplikaci,
postup u sportovce v pěti krocích a stránka „Jak to funguje“. Běžná práce
nepotřebuje administraci.
"""

from datetime import date
from html.parser import HTMLParser

import pytest
from cryptography.fernet import Fernet
from django.urls import reverse

from apps.core.models import Organization, Role
from apps.genetics import services
from apps.genetics.models import (
    ContextScenario,
    Domain,
    ForbiddenStatement,
    GeneCard,
    GenePanel,
    GeneVariant,
    PanelItem,
    Recommendation,
)
from apps.genetics.seed import seed_domains
from tests.test_genetika import KARTY, _card, _docx, _subject, _user, _variant


@pytest.fixture
def org(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.GENETICS_ENCRYPTION_KEY = Fernet.generate_key().decode()
    seed_domains()
    return Organization.objects.create(name="FTVS", short_name="ftvs")


# --- přehled: čtyři kroky ---------------------------------------------------------

def test_prehled_vede_ctyrmi_kroky_a_ukazuje_dalsi(org):
    admin, client = _user(org, Role.ADMIN, "spravce")
    page = client.get(reverse("genetics_home"))
    assert page.status_code == 200
    assert [s["title"] for s in page.context["steps"]] == [
        "Garanti oblastí", "Karty z podkladů", "Panel a laboratoř", "Revize a schválení karet"]
    assert page.context["next_step"]["n"] == 1
    text = page.content.decode()
    assert "Průvodce nastavením" in text and "Další krok: Garanti oblastí" in text
    assert "Jak to funguje" in text and "/admin/genetics/" not in text  # bez „Stav týmu“ ani odkaz

    for domain in Domain.objects.filter(is_active=True):
        domain.guarantors.add(admin)
    page = client.get(reverse("genetics_home"))
    assert page.context["steps"][0]["done"] and page.context["next_step"]["n"] == 2

    # výzkumník kroky vidí, ale bez tlačítek; laborant garanty nenastavuje
    _, r_client = _user(org, Role.RESEARCHER, "vyzkumnik")
    text = r_client.get(reverse("genetics_home")).content.decode()
    assert "Nastavit garanty" not in text and "Načíst z Wordu" not in text
    Domain.objects.get(code="vykon").guarantors.clear()
    _, lab_client = _user(org, Role.LAB, "laborant")
    text = lab_client.get(reverse("genetics_home")).content.decode()
    assert "Nastavit garanty" not in text and "nastavuje správce" in text
    assert "Načíst z Wordu" in text and reverse("genetics_setup_guarantors") not in text


def test_garanty_nastavuje_spravce_formularem(org):
    admin, client = _user(org, Role.ADMIN, "spravce")
    metodik, lab_client = _user(org, Role.LAB, "metodik")
    _user(org, Role.COACH, "trener")
    url = reverse("genetics_setup_guarantors")
    assert lab_client.get(url).status_code == 403
    page = client.get(url)
    assert page.status_code == 200
    assert "trener" not in page.content.decode()  # garantem jen správce nebo diagnostik
    vykon = Domain.objects.get(code="vykon")
    assert client.post(url, {f"garant_{vykon.pk}": [str(metodik.pk), str(admin.pk)]}).status_code == 302
    assert set(vykon.guarantors.all()) == {metodik, admin}
    client.post(url, {})
    assert vykon.guarantors.count() == 0


# --- karty z Wordu --------------------------------------------------------------------

def test_karty_se_nahraji_z_wordu_v_aplikaci(org, tmp_path):
    _, client = _user(org, Role.LAB, "laborant")
    url = reverse("genetics_setup_cards")
    assert client.get(url).status_code == 200
    path = _docx(tmp_path / "karty.docx", KARTY)
    with path.open("rb") as handle:
        text = client.post(url, {"soubor": handle}, follow=True).content.decode()
    assert "Načteno" in text and "ACE / rs1799752" in text and "návrhy k revizi" in text
    ace = GeneVariant.objects.get(rsid="rs1799752")
    assert ace.organization is None and ace.cards.count() == 2
    # průvodce: krok 2 hotový, krok 3 čeká na laboratoř
    steps = client.get(reverse("genetics_home")).context["steps"]
    assert steps[1]["done"] and not steps[2]["done"]
    # podruhé se nic nepřepíše
    with path.open("rb") as handle:
        text = client.post(url, {"soubor": handle}, follow=True).content.decode()
    assert "nepřepsáno" in text and GeneVariant.objects.filter(rsid="rs1799752").count() == 1
    # jiný soubor
    other = tmp_path / "poznamky.txt"
    other.write_text("x")
    with other.open("rb") as handle:
        text = client.post(url, {"soubor": handle}, follow=True).content.decode()
    assert "Vyberte soubor Word" in text
    # poškozený .docx
    broken = tmp_path / "rozbity.docx"
    broken.write_bytes(b"to neni zip")
    with broken.open("rb") as handle:
        text = client.post(url, {"soubor": handle}, follow=True).content.decode()
    assert "Soubor nejde načíst" in text


def test_v_ukazce_se_karty_nenahravaji(org, tmp_path, settings):
    settings.DEMO_MODE = True
    _, client = _user(org, Role.LAB, "laborant")
    url = reverse("genetics_setup_cards")
    assert "nenahrávají" in client.get(url).content.decode()
    path = _docx(tmp_path / "karty.docx", KARTY)
    with path.open("rb") as handle:
        text = client.post(url, {"soubor": handle}, follow=True).content.decode()
    assert "veřejná ukázka" in text and not GeneVariant.objects.exists()


def test_karty_nahrava_jen_spravce_nebo_laborant(org):
    _, client = _user(org, Role.RESEARCHER, "vyzkumnik")
    assert client.get(reverse("genetics_setup_cards")).status_code == 403
    assert client.get(reverse("genetics_setup_panel")).status_code == 403


# --- panel a laboratoř ---------------------------------------------------------------

def test_panel_a_laborator_formularem(org):
    _, client = _user(org, Role.LAB, "laborant")
    variant = _variant(org)
    url = reverse("genetics_setup_panel")
    assert client.get(url).status_code == 200
    panel = GenePanel.objects.get()  # bez panelu vznikne „Panel laboratoře“
    item = PanelItem.objects.get(panel=panel, variant=variant)
    assert item.genotype_map == {"RR": "CC", "RX": "CT", "XX": "TT"}  # z jiných zápisů varianty

    text = client.post(url, {
        "laborator": "Genetická laboratoř XY", f"aktivni_{variant.pk}": "on",
        f"zapis_{variant.pk}": "r/r = CC; rx -> ct, XX=TT", f"oznaceni_{variant.pk}": "ACTN3 R577X",
    }, follow=True).content.decode()
    assert "Panel a laboratoř jsou uložené" in text
    panel.refresh_from_db()
    item.refresh_from_db()
    variant.refresh_from_db()
    assert panel.provider == "Genetická laboratoř XY" and variant.is_active
    assert item.genotype_map == {"R/R": "CC", "RX": "CT", "XX": "TT"}
    assert item.lab_label == "ACTN3 R577X" and item.normalize("r/r") == "CC"
    steps = client.get(reverse("genetics_home")).context["steps"]
    assert steps[2]["done"]

    # neznámý genotyp se nahlásí, mapování zůstane; nezaškrtnuté = varianta vypnutá
    text = client.post(url, {"laborator": "XY", f"zapis_{variant.pk}": "RR=GG"},
                       follow=True).content.decode()
    assert "neprošly" in text and "GG" in text
    item.refresh_from_db()
    variant.refresh_from_db()
    assert item.genotype_map == {"R/R": "CC", "RX": "CT", "XX": "TT"} and not variant.is_active


# --- editor karty ----------------------------------------------------------------------

def test_editor_karty_ulozi_a_posle_k_revizi(org):
    _, client = _user(org, Role.LAB, "laborant")
    _, r_client = _user(org, Role.RESEARCHER, "vyzkumnik")
    variant = _variant(org)
    card = _card(variant, texts=False)
    url = reverse("genetics_card_edit", args=[card.pk])
    assert r_client.get(url).status_code == 403
    page = client.get(url)
    assert page.status_code == 200
    assert "Ke schválení chybí" in page.content.decode()
    assert reverse("genetics_card_edit", args=[card.pk]) in \
        client.get(reverse("genetics_card", args=[card.pk])).content.decode()

    data = {
        "biology_client": "Gen ACTN3 ovlivňuje bílkovinu rychlých svalových vláken.",
        "limitations": "Jeden gen výkon neurčuje.",
        "text_CC": "Genotyp CC: bílkovina se tvoří.", "text_CT": "Genotyp CT: tvoří se méně.",
        "text_TT": "Genotyp TT: bílkovina se netvoří.", "freq_CC": "30 % (Evropa, zdroj S1)",
        "rec_count": "2",
        "rec_genotype_0": "TT", "rec_kind_0": "training", "rec_basis_0": "variant",
        "rec_text_0": "Zařaďte plyometrii.", "rec_key_0": "plyometrie",
        "rec_text_1": "",
        "forbidden": "máte více rychlých vláken\n\n„Jste sprinter.“",
        "akce": "ulozit",
    }
    resp = client.post(url, data)
    assert resp.status_code == 302 and resp.url == url
    card.refresh_from_db()
    assert card.biology_client.startswith("Gen ACTN3") and card.limitations == "Jeden gen výkon neurčuje."
    assert card.genotype_texts.get(genotype="CC").frequency == "30 % (Evropa, zdroj S1)"
    assert card.genotype_texts.get(genotype="TT").client_text == "Genotyp TT: bílkovina se netvoří."
    rec = card.recommendations.get()
    assert (rec.genotype, rec.kind, rec.basis, rec.merge_key) == ("TT", "training", "variant", "plyometrie")
    assert list(card.forbidden_statements.values_list("text", flat=True)) == [
        "máte více rychlých vláken", "Jste sprinter"]
    assert services.checklist(card).ok

    # existující doporučení se upraví podle id, nový řádek přibude
    data.update({"rec_count": "3", "rec_id_0": str(rec.pk),
                 "rec_text_0": "Zařaďte plyometrii dvakrát týdně.",
                 "rec_kind_1": "regeneration", "rec_basis_1": "general", "rec_text_1": "Spánek 8 h."})
    client.post(url, data)
    rec.refresh_from_db()
    assert rec.text == "Zařaďte plyometrii dvakrát týdně." and card.recommendations.count() == 2
    other = card.recommendations.exclude(pk=rec.pk).get()
    assert other.basis == "general" and other.genotype == ""

    # smazání zaškrtnutím a odeslání k revizi
    data.update({"rec_delete_0": "on", "rec_id_1": str(other.pk), "akce": "k_revizi"})
    resp = client.post(url, data)
    card.refresh_from_db()
    assert card.status == GeneCard.Status.REVIEW
    assert resp.url == reverse("genetics_card", args=[card.pk])
    assert list(card.recommendations.values_list("text", flat=True)) == ["Spánek 8 h."]

    # v revizi jde dál upravovat; schválená karta ne
    assert client.get(url).status_code == 200
    card.status = GeneCard.Status.APPROVED
    card.save()
    resp = client.get(url, follow=True)
    assert resp.redirect_chain[-1][0] == reverse("genetics_card", args=[card.pk])
    assert "jen ke čtení" in resp.content.decode()


def test_editor_zapina_scenar_jen_s_odpovedi_ktera_ho_spousti(org):
    _, client = _user(org, Role.LAB, "laborant")
    card = _card(_variant(org))
    scenario = ContextScenario.objects.create(
        card=card, kind=ContextScenario.Kind.QUESTIONNAIRE,
        statement="Lépe zvládám delší souvislou zátěž.")
    url = reverse("genetics_card_edit", args=[card.pk])
    page = client.get(url)
    assert "vykonovy_profil|vytrvalost" in page.content.decode()
    base = {"biology_client": card.biology_client, "text_CC": "a", "text_CT": "b", "text_TT": "c",
            "rec_count": "0", "akce": "ulozit"}

    text = client.post(url, {**base, f"sc_active_{scenario.pk}": "on"}, follow=True).content.decode()
    scenario.refresh_from_db()
    assert not scenario.is_active and "nejde zapnout bez odpovědi" in text

    client.post(url, {**base, f"sc_active_{scenario.pk}": "on",
                      f"sc_trigger_{scenario.pk}": "vykonovy_profil|vytrvalost"})
    scenario.refresh_from_db()
    assert scenario.is_active and scenario.question.code == "vykonovy_profil"
    assert scenario.answer_match == {"choices": ["vytrvalost"]}

    client.post(url, {**base, f"sc_active_{scenario.pk}": "on",
                      f"sc_trigger_{scenario.pk}": "obtize_nyni|1"})
    scenario.refresh_from_db()
    assert scenario.question.code == "obtize_nyni" and scenario.answer_match == {"value": 1}

    client.post(url, {**base, f"sc_trigger_{scenario.pk}": "obtize_nyni|1"})
    scenario.refresh_from_db()
    assert not scenario.is_active


def test_nova_verze_otevre_rovnou_editor(org):
    lab, client = _user(org, Role.LAB, "laborant")
    variant = _variant(org)
    card = _card(variant, status=GeneCard.Status.APPROVED)
    resp = client.post(reverse("genetics_card_action", args=[card.pk]), {"akce": "nova_verze"})
    new = variant.cards.get(version=2)
    assert resp.url == reverse("genetics_card_edit", args=[new.pk])


# --- sportovec: pět kroků --------------------------------------------------------------

def test_u_sportovce_vede_postup_peti_kroky(org):
    lab, client = _user(org, Role.LAB, "laborant")
    subject = _subject(org, "FTVS-0001", birth=date(1990, 5, 1))
    url = reverse("genetics_subject", args=[subject.pk])
    page = client.get(url)
    assert page.status_code == 200
    assert [s["title"] for s in page.context["steps"]] == [
        "Souhlas", "Vzorek a výsledek", "Ověření", "Dotazník", "Zpráva"]
    assert page.context["next_step"]["anchor"] == "souhlas"
    assert "Další krok: Souhlas" in page.content.decode()

    services.grant_consent(subject, by=lab)
    page = client.get(url)
    assert page.context["steps"][0]["done"] and page.context["next_step"]["anchor"] == "vzorek"
    text = page.content.decode()
    assert "Další krok: Vzorek a výsledek" in text and 'id="vzorek"' in text and 'id="zprava"' in text


# --- návod ----------------------------------------------------------------------------------

def test_navod_je_v_aplikaci_a_v_o_aplikaci(org):
    _, client = _user(org, Role.LAB, "laborant")
    page = client.get(reverse("genetics_guide"))
    assert page.status_code == 200
    text = page.content.decode()
    assert "Jak genetika v aplikaci funguje" in text and "Kdo co dělá" in text
    assert "Stav nastavení" in text and "Garanti oblastí" in text
    about = client.get(reverse("about")).content.decode()
    assert reverse("genetics_guide") in about and 'id="genetika"' in about


# --- editor: co zobrazí, to po odeslání beze změny uloží ------------------------------------

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


def test_editor_odesle_zpet_presne_to_co_zobrazi(org):
    _, client = _user(org, Role.LAB, "laborant")
    card = _card(_variant(org), limitations="Jeden gen výkon neurčuje.")
    Recommendation.objects.create(card=card, genotype="CC", kind="training", basis="variant",
                                  text="Plyometrie.", merge_key="plyometrie")
    Recommendation.objects.create(card=card, kind="regeneration", basis="general", text="Spánek 8 h.")
    ForbiddenStatement.objects.create(card=card, text="jste sprinter")
    url = reverse("genetics_card_edit", args=[card.pk])
    form = _form_values(client.get(url).content.decode())
    assert form["rec_count"] == "4" and form["rec_text_0"] == "Plyometrie." and form["rec_text_3"] == ""
    assert form["rec_id_0"] and "rec_id_2" not in form and "rec_delete_0" not in form
    assert form["rec_basis_1"] == "general" and form["rec_genotype_0"] == "CC"

    client.post(url, {**form, "akce": "ulozit"})
    card.refresh_from_db()
    assert list(card.recommendations.order_by("order").values_list("text", "genotype", "basis",
                                                                  "merge_key")) == [
        ("Plyometrie.", "CC", "variant", "plyometrie"), ("Spánek 8 h.", "", "general", "")]
    assert list(card.forbidden_statements.values_list("text", flat=True)) == ["jste sprinter"]
    assert card.genotype_texts.get(genotype="CC").client_text == "Zjištěn genotyp CC."
    assert card.limitations == "Jeden gen výkon neurčuje." and card.biology_client
