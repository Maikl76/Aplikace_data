"""
Průvodce genetikou: nastavení ve čtyřech krocích, postup u sportovce v pěti
krocích a stránka „Jak to funguje“. Běžná práce nepotřebuje administraci.
Průvodce kartou (nová karta, osm kroků) testuje test_genetika_karta.py.
"""

from datetime import date

import pytest
from cryptography.fernet import Fernet
from django.urls import reverse

from apps.core.models import Organization, Role
from apps.genetics import services
from apps.genetics.models import Domain, GenePanel, GeneVariant, PanelItem
from apps.genetics.seed import seed_domains
from tests.test_genetika import KARTY, _docx, _subject, _user, _variant


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
        "Garanti oblastí", "Genové karty", "Panel a laboratoř", "Revize a schválení karet",
        "Interakce variant"]
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
    assert "Nastavit garanty" not in text and reverse("genetics_card_new") not in text
    assert "Nová karta" not in text and "Načíst z Wordu" not in text
    Domain.objects.get(code="vykon").guarantors.clear()
    _, lab_client = _user(org, Role.LAB, "laborant")
    text = lab_client.get(reverse("genetics_home")).content.decode()
    assert "Nastavit garanty" not in text and "nastavuje správce" in text
    assert "Nová karta" in text and "Načíst z Wordu" in text
    assert reverse("genetics_setup_guarantors") not in text


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


def test_zkusebni_provoz_nahrava_karty_stejne_jako_laborator(org, tmp_path, settings):
    settings.DEMO_MODE = True
    _, client = _user(org, Role.LAB, "laborant")
    url = reverse("genetics_setup_cards")
    assert 'name="soubor"' in client.get(url).content.decode()
    path = _docx(tmp_path / "karty.docx", KARTY)
    with path.open("rb") as handle:
        text = client.post(url, {"soubor": handle}, follow=True).content.decode()
    assert "Načteno" in text and GeneVariant.objects.filter(rsid="rs1799752").exists()


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


# --- sportovec: pět kroků --------------------------------------------------------------

def test_u_sportovce_vede_postup_peti_kroky(org):
    lab, client = _user(org, Role.LAB, "laborant")
    subject = _subject(org, "FTVS-0001", birth=date(1990, 5, 1))
    url = reverse("genetics_subject", args=[subject.pk])
    page = client.get(url)
    assert page.status_code == 200
    assert [s["title"] for s in page.context["steps"]] == [
        "Souhlas", "Vzorek a výsledek", "Ověření", "Dotazník", "Zpráva"]
    assert page.context["next_step"]["url"] == "#souhlas"
    assert "Další krok: Souhlas" in page.content.decode()

    services.grant_consent(subject, by=lab)
    page = client.get(url)
    assert page.context["steps"][0]["done"] and page.context["next_step"]["url"] == "#vzorek"
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
