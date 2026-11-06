"""
Dávka 4b: interakce variant v aplikaci – přehled s pátým (volitelným)
krokem nastavení, formulář ve čtyřech částech, hypotézu posuzuje správce,
varianta mimo panel se označí; kombinace z karty a na kartě.
"""

import pytest
from cryptography.fernet import Fernet
from django.urls import reverse

from apps.core.models import Organization, Role
from apps.genetics.models import Domain, GeneInteraction, GenePanel, PanelItem
from apps.genetics.seed import seed_domains
from tests.test_genetika import _card, _user, _variant


@pytest.fixture
def org(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.GENETICS_ENCRYPTION_KEY = Fernet.generate_key().decode()
    seed_domains()
    return Organization.objects.create(name="FTVS", short_name="ftvs")


def _form(actn3, ace, **extra):
    data = {"title": "ACE × ACTN3 – silově-vytrvalostní profil",
            "assumption": "Za předpokladu kombinace ACE DD nebo ID + ACTN3 CC nebo CT",
            "text": "Kombinace naznačuje sklon k silově-vytrvalostnímu profilu; podklad je slabý.",
            "variants": [actn3.rsid, ace.rsid], "areas": [Domain.objects.get(code="vykon").name],
            "status": "hypothesis"}
    data.update(extra)
    return data


def test_interakce_variant_v_aplikaci(org):
    _, client = _user(org, Role.ADMIN, "spravce")
    _, lab = _user(org, Role.LAB, "laborant")
    _, researcher = _user(org, Role.RESEARCHER, "vyzkumnik")
    actn3 = _variant(org)
    ace = _variant(org, gene="ACE", rsid="rs1799752", genotypes=["II", "ID", "DD"],
                   genotype_aliases={})
    panel = GenePanel.objects.create(organization=org, code="panel", name="Panel laboratoře")
    PanelItem.objects.create(panel=panel, variant=actn3)
    url = reverse("genetics_interactions")
    page = client.get(url)
    assert page.status_code == 200 and "Nová kombinace" in page.content.decode()
    assert page.context["step"]["done"] and page.context["step"]["optional"]
    steps = client.get(reverse("genetics_home")).context["steps"]
    assert steps[4]["title"] == "Interakce variant" and steps[4]["optional"]
    assert url in client.get(reverse("genetics_home")).content.decode()
    new = reverse("genetics_interaction_new")
    assert researcher.get(new).status_code == 403
    assert "Nová kombinace" not in researcher.get(url).content.decode()

    # laborant: chyby zápisu; založení jde jen jako hypotéza
    text = lab.post(new, _form(actn3, ace, text="", variants=[actn3.rsid]),
                    follow=True).content.decode()
    assert "Doplňte text" in text and "aspoň dvě varianty" in text
    assert not GeneInteraction.objects.exists()
    resp = lab.post(new, _form(actn3, ace, status="approved"))
    inter = GeneInteraction.objects.get()
    assert resp.status_code == 302 and resp.url.endswith(f"#interakce-{inter.pk}")
    assert inter.status == "hypothesis" and inter.variants == [actn3.rsid, ace.rsid]
    assert inter.areas == [Domain.objects.get(code="vykon").name] and inter.organization == org
    page = client.get(url)
    text = page.content.decode()
    assert inter.title in text and "hypotéza" in text and "mimo panel" in text
    assert not page.context["step"]["done"] and page.context["step"]["count"] == 1
    assert "1 hypotéz čeká na posouzení" in page.context["step"]["text"]

    # stav mění jen správce; schválená kombinace je na kartě s odkazem
    edit = reverse("genetics_interaction_edit", args=[inter.pk])
    text = lab.post(edit, _form(actn3, ace, status="approved"), follow=True).content.decode()
    assert "mění správce" in text
    inter.refresh_from_db()
    assert inter.status == "hypothesis"
    client.post(edit, _form(actn3, ace, status="approved"))
    inter.refresh_from_db()
    assert inter.status == "approved"
    card = _card(actn3)
    inter.source_card = card
    inter.save()
    text = client.get(reverse("genetics_card", args=[card.pk])).content.decode()
    assert inter.title in text and "Nová kombinace" in text and edit in text
    page = client.get(new + f"?karta={card.pk}")
    assert page.context["data"]["variants"] == [actn3.rsid]
    # varianta mimo panel drží krok nehotový; po doplnění do panelu je hotovo
    assert not client.get(url).context["step"]["done"]
    PanelItem.objects.create(panel=panel, variant=ace)
    assert client.get(url).context["step"]["done"]

    # mazat smí správce; volitelný krok nebrání „hotovo“ v Nastavení
    assert lab.post(reverse("genetics_interaction_delete", args=[inter.pk])).status_code == 403
    client.post(reverse("genetics_interaction_delete", args=[inter.pk]))
    assert not GeneInteraction.objects.exists()
    steps = {s["title"]: s for s in client.get(reverse("workplace")).context["steps"]}
    assert "z 4 kroků" in steps["Genetika"]["text"]
