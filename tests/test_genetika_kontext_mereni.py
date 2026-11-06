"""
Dávka 4a: průvodce kartou bez administrace – scénář s měřením dostane
podmínku ze stavitele (stejný zápis jako u pravidel) a zdroje i důkazy
jdou napojit na článek z knihovny, který předvyplní citaci a odkaz.
"""

import pytest
from cryptography.fernet import Fernet
from django.urls import reverse

from apps.catalog.models import MetricDef
from apps.core.models import Organization, Role
from apps.evidence.models import Article
from apps.genetics.card_steps import card_steps
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


def _condition(prefix, **extra):
    data = {f"{prefix}_kind": "z", f"{prefix}_metric": "vo2max", f"{prefix}_op": ">",
            f"{prefix}_value": "1", f"{prefix}_side": "", f"{prefix}_mode": "",
            f"{prefix}_speed": "", f"{prefix}_segment": ""}
    data.update({f"{prefix}_{k}": v for k, v in extra.items()})
    return data


def test_scenar_s_merenim_ze_stavitele(org):
    _, client = _user(org, Role.LAB, "laborant")
    MetricDef.objects.create(organization=None, code="vo2max", name="VO2max", family="spiro",
                             unit="ml/kg/min")
    variant = _variant(org)
    card = _card(variant)
    url = _step(card, "kontext")
    page = client.get(url)
    assert page.status_code == 200
    text = page.content.decode()
    assert 'name="nsc_kind_0"' in text and 'name="nsc_c_0_metric"' in text
    assert "administrac" not in text

    # nový scénář s měřením: podmínka ze stavitele, zapnutý, text pro genotyp
    data = {"akce": "ulozit", "nsc_count": "1", "nsc_kind_0": "measurement", "nsc_active_0": "on",
            "nsc_statement_0": "Nadprůměrná aerobní kapacita v laboratorním testu.",
            "nsc_text_0_CC": "Změřená aerobní kapacita je uvedena vedle genotypu.",
            **_condition("nsc_c_0")}
    client.post(url, data)
    scenario = card.scenarios.get()
    assert scenario.kind == "measurement" and scenario.is_active
    assert scenario.condition == {"z": "vo2max", "op": ">", "value": 1}
    assert scenario.texts.get(genotype="CC").text.startswith("Změřená")
    text = client.get(url).content.decode()
    assert "z-skóre VO2max vůči normě &gt; 1" in text and f'name="sc_c_{scenario.pk}_value"' in text

    # úprava prahu; chybný ukazatel se nahlásí a podmínka zůstane; prázdná podmínka vypne
    data = {"akce": "ulozit", "nsc_count": "0", f"sc_statement_{scenario.pk}": scenario.statement,
            f"sc_active_{scenario.pk}": "on",
            f"sc_text_{scenario.pk}_CC": "Změřená aerobní kapacita je uvedena vedle genotypu.",
            **_condition(f"sc_c_{scenario.pk}", value="1,5")}
    client.post(url, data)
    scenario.refresh_from_db()
    assert scenario.condition["value"] == 1.5
    bad = {**data, f"sc_c_{scenario.pk}_metric": "neexistuje"}
    text = client.post(url, bad, follow=True).content.decode()
    assert "v katalogu není" in text
    scenario.refresh_from_db()
    assert scenario.condition["value"] == 1.5 and scenario.is_active
    blank = {**data, f"sc_c_{scenario.pk}_metric": "", f"sc_c_{scenario.pk}_value": ""}
    text = client.post(url, blank, follow=True).content.decode()
    assert "nejde zapnout bez podmínky nad měřením" in text
    scenario.refresh_from_db()
    assert scenario.condition == {} and not scenario.is_active
    # krok 5 počítá zapnutý scénář bez podmínky jako rozbitý
    scenario.is_active = True
    scenario.save()
    steps = {s["title"]: s for s in card_steps(card)}
    assert steps["Kontext z dotazníku"]["count"] == 1 and "podmínky" in steps["Kontext z dotazníku"]["text"]


def test_zdroje_a_dukazy_s_clankem_z_knihovny(org):
    _, client = _user(org, Role.LAB, "laborant")
    article = Article.objects.create(title="ACTN3 and sprint", authors="Yang N., MacArthur D.",
                                     journal="Am J Hum Genet", year=2003, doi="10.1086/377590",
                                     status=Article.Status.APPROVED)
    variant = _variant(org)
    card = _card(variant)
    url = _step(card, "zdroje")
    text = client.get(url).content.decode()
    assert 'name="src_article_0"' in text and "Yang N." in text and "administrac" not in text

    data = {"akce": "ulozit", "src_count": "1", "src_label_0": "S1", "src_title_0": "frekvence",
            "src_citation_0": "", "src_url_0": "", "src_article_0": str(article.pk),
            "ev_count": "1", "ev_code_0": "E01", "ev_trait_0": "sprint", "ev_basis_text_0": "x",
            "ev_usage_0": "", "ev_source_labels_0": "S1", "ev_article_0": str(article.pk)}
    client.post(url, data)
    source = card.sources.get()
    assert source.article == article and source.url == "https://doi.org/10.1086/377590"
    assert source.citation == "Yang N., MacArthur D. (2003). ACTN3 and sprint. Am J Hum Genet."
    evidence = card.evidence.get()
    assert evidence.article == article
    text = client.get(url).content.decode()
    assert f'value="{article.pk}" data-citace="Yang N., MacArthur D. (2003). ACTN3 and sprint. Am J Hum Genet." data-doi="10.1086/377590" selected' in text

    # prázdný výběr vazbu zruší, citace zůstane
    data.update({"src_id_0": str(source.pk), "src_citation_0": source.citation, "src_article_0": "",
                 "ev_id_0": str(evidence.pk), "ev_article_0": ""})
    client.post(url, data)
    source.refresh_from_db()
    evidence.refresh_from_db()
    assert source.article is None and evidence.article is None and source.citation.startswith("Yang")
