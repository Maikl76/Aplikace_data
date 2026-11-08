"""
Knihovna článků ke genetice: soubor katalog/clanky/genetika.json je úplný
a příkaz nacist_clanky ho načte jen jednou, jako navržené články, a připojí
je ke zdrojům a důkazům genových karet.
"""

import json
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command

from apps.evidence.management.commands.nacist_clanky import load_file
from apps.evidence.models import Article, EvidenceLevel
from apps.genetics.models import CardEvidence, CardSource, GeneCard

SOUBOR = Path(settings.BASE_DIR) / "katalog" / "clanky" / "genetika.json"


def _data():
    return json.loads(SOUBOR.read_text(encoding="utf-8"))


def test_soubor_je_uplny_a_bez_duplicit():
    data = _data()
    assert data["format"] == "clanky/1"
    clanky = data["clanky"]
    assert len(clanky) >= 40
    dois = [a["doi"].lower() for a in clanky if a["doi"]]
    assert len(dois) == len(set(dois))
    assert sum(1 for a in clanky if not a["pmid"]) <= 1          # jen online časopis bez PubMedu
    levels = set(EvidenceLevel.values)
    for a in clanky:
        assert a["title"] and a["authors"] and a["journal"] and a["year"], a["title"]
        assert a["evidence_level"] in levels, a["title"]
        assert len(a["key_finding"]) > 60 and a["limitations"], a["title"]
        assert "genetika" in a["tags"] and a["curator_note"], a["title"]
        assert a["population_sex"] in ("", "F", "M", "B")
    # každá karta v repozitáři má aspoň jeden článek napojený na své zdroje
    varianty = {k["varianta"] for a in clanky for k in a["karty"]}
    assert varianty >= {"rs1799752", "rs1815739", "rs12722", "rs762551", "rs9939609", "rs1800795",
                        "rs4988235", "rs8192678", "rs1049434", "rs7903146"}


def test_nacteni_je_navrzene_a_jednorazove(db):
    call_command("nacist_clanky", verbosity=0)
    n = Article.objects.count()
    assert n == len(_data()["clanky"])
    assert set(Article.objects.values_list("status", flat=True)) == {Article.Status.SUGGESTED}
    guest = Article.objects.get(pmid="29509641")
    assert guest.doi == "10.1249/MSS.0000000000001596" and guest.year == 2018
    assert guest.evidence_level == EvidenceLevel.RCT and "AA" in guest.key_finding
    assert guest.url.startswith("https://doi.org/")

    # podruhé nic nového; ručně upravený text zůstane
    guest.key_finding = "Upraveno kurátorem."
    guest.status = Article.Status.APPROVED
    guest.save()
    call_command("nacist_clanky", verbosity=0)
    assert Article.objects.count() == n
    guest.refresh_from_db()
    assert guest.key_finding == "Upraveno kurátorem." and guest.status == Article.Status.APPROVED


def test_clanky_se_pripoji_ke_zdrojum_karet(db):
    call_command("nacist_navrhy_karet", verbosity=0)
    assert GeneCard.objects.exists()
    call_command("nacist_clanky", verbosity=0)
    guest = Article.objects.get(pmid="29509641")
    sources = CardSource.objects.filter(card__variant__rsid="rs762551", label="S3")
    assert sources.exists() and all(s.article == guest for s in sources)
    # důkaz jen z tohoto zdroje dostane článek; důkaz z více zdrojů s různými články ne
    cmj = CardEvidence.objects.filter(card__variant__rsid="rs9939609", source_labels="S1").first()
    assert cmj is not None and cmj.article.pmid == "17434869"
    mixed = CardEvidence.objects.filter(card__variant__rsid="rs1815739", source_labels="S1, S2").first()
    assert mixed is not None and mixed.article is None
    # neověřený zdroj S5 karty IL6 zůstane bez článku, ale k němu připravený článek v knihovně je
    assert CardSource.objects.filter(card__variant__rsid="rs1800795", label="S5",
                                     article__isnull=True).exists()
    assert Article.objects.filter(pmid="18758806").exists()


def test_spatny_soubor_se_odmitne(db):
    with pytest.raises(ValueError):
        load_file({"format": "neco-jineho", "clanky": []})
    with pytest.raises(ValueError):
        load_file({"format": "clanky/1", "clanky": [{"title": "X", "evidence_level": "nesmysl"}]})


# --- v aplikaci: hledání podle štítků, krok Zdroje u karty, karta --------------------------

@pytest.fixture
def org(db, settings):
    from cryptography.fernet import Fernet

    from apps.core.models import Organization
    from apps.genetics.seed import seed_domains

    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.GENETICS_ENCRYPTION_KEY = Fernet.generate_key().decode()
    seed_domains()
    return Organization.objects.create(name="FTVS", short_name="ftvs")


def test_seznam_hleda_podle_stitku_a_ukaze_je(org):
    from django.urls import reverse

    from apps.core.models import Role
    from apps.evidence.steps import library_steps
    from tests.test_genetika import _user

    _, client = _user(org, Role.ADMIN, "spravce")
    call_command("nacist_navrhy_karet", verbosity=0)
    call_command("nacist_clanky", verbosity=0)
    page = client.get(reverse("article_list") + "?q=rs762551")
    text = page.content.decode()
    assert page.status_code == 200
    assert "Guest" in text and "Kilpel" not in text          # FTO článek štítek CYP1A2 nemá
    assert 'href="?q=rs762551"' in text                     # štítek je odkaz na hledání
    assert "navrženo" in text and "karta CYP1A2" in text    # vazba na kartu je vidět
    # vazba na kartu je téma: knihovna článek nehlásí jako nepoužitý
    bez_vazby = client.get(reverse("article_list") + "?chybi=vazba").content.decode()
    assert "10.1249/MSS.0000000000001596" not in bez_vazby    # Guest 2018 má kartu
    assert "33388079" in bez_vazby                            # stanovisko ISSN kartu nemá
    tema = library_steps()[2]
    assert tema["done"] or "genovou kartu" in tema["text"]
    guest = Article.objects.get(pmid="29509641")
    assert guest.card_genes == ["CYP1A2"]


def test_krok_zdroje_udrzi_navrzeny_clanek(org):
    from django.urls import reverse

    from apps.core.models import Role
    from tests.test_genetika import _card, _user, _variant

    _, client = _user(org, Role.LAB, "laborant")
    card = _card(_variant(org, gene="CYP1A2", rsid="rs762551"))
    article = Article.objects.create(title="Caffeine, CYP1A2 genotype, and endurance performance",
                                     authors="Guest N, Corey P", year=2018,
                                     status=Article.Status.SUGGESTED)
    source = CardSource.objects.create(card=card, label="S3", citation="Guest N. et al. (2018).",
                                       article=article, order=1)
    url = reverse("genetics_card_step", args=[card.pk, "zdroje"])
    text = client.get(url).content.decode()
    assert "navržený, čeká na zařazení" in text and f'value="{article.pk}" selected' in text

    data = {"src_count": "1", "src_id_0": str(source.pk), "src_label_0": "S3",
            "src_citation_0": source.citation, "src_article_0": str(article.pk), "akce": "ulozit"}
    client.post(url, data)
    source.refresh_from_db()
    assert source.article == article                        # uložení kroku vazbu nesmaže

    article.status = Article.Status.REJECTED
    article.save()
    client.post(url, data)
    source.refresh_from_db()
    assert source.article is None                           # zamítnutý článek se nepřipojí

    # karta ukazuje článek u zdroje
    article.status = Article.Status.SUGGESTED
    article.save()
    source.article = article
    source.save()
    text = client.get(reverse("genetics_card", args=[card.pk])).content.decode()
    assert "článek v knihovně" in text and "Guest N (2018)" in text
