"""Katalog se přenese na jiný počítač (jinou databázi) a nic se neztratí."""

import json

import pytest
from django.core.management import call_command

from apps.catalog.models import MetricDef, Norm, Protocol, ProtocolMetric, TestFamily
from apps.catalog.transfer import ImportError_, export_catalog, import_catalog
from apps.core.models import Organization
from apps.evidence.models import Article
from apps.rules.models import Rule, RuleArticle
from apps.subjects.models import Sport


@pytest.fixture
def katalog(db):
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    tenis = Sport.objects.create(organization=org, code="tenis", name="Tenis")
    metric = MetricDef.objects.create(code="ir_er_ratio", name="Poměr IR/ER",
                                      family=TestFamily.DYNAMOMETRY, mdc=0.08, decimals=2)
    protocol = Protocol.objects.create(code="iso", name="Izokinetika",
                                       family=TestFamily.DYNAMOMETRY, default_trials=5)
    ProtocolMetric.objects.create(protocol=protocol, metric=metric, is_primary=True,
                                  sides=["L", "R"], speeds=[210])
    Norm.objects.create(metric=metric, sport=tenis, sex="F", mean=1.1, sd=0.1,
                        speed=210, source_citation="Autor 2020")
    article = Article.objects.create(title="Rotátory ramene", doi="10.1/abc", year=2020)
    rule = Rule.objects.create(organization=org, code="ir_er", name="Poměr IR/ER",
                               condition={"metric": "ir_er_ratio", "op": "<", "value": 1.0},
                               finding_template="x", is_active=False)
    RuleArticle.objects.create(rule=rule, article=article, relevance_note="kohorta")
    return org


def _vymaz_katalog():
    RuleArticle.objects.all().delete()
    Rule.objects.all().delete()
    Article.objects.all().delete()
    Norm.objects.all().delete()
    ProtocolMetric.objects.all().delete()
    Protocol.objects.all().delete()
    MetricDef.objects.all().delete()
    Sport.objects.all().delete()


def test_katalog_projde_tam_a_zpet(katalog):
    data = json.loads(json.dumps(export_catalog(), default=str))
    _vymaz_katalog()

    import_catalog(data)

    metric = MetricDef.objects.get(code="ir_er_ratio")
    assert metric.mdc == 0.08
    pm = ProtocolMetric.objects.get()
    assert pm.protocol.default_trials == 5 and pm.sides == ["L", "R"] and pm.is_primary
    norm = Norm.objects.get()
    assert norm.sport.code == "tenis" and norm.mean == 1.1
    rule = Rule.objects.get()
    assert rule.organization == katalog and rule.is_active is False
    assert rule.rule_articles.get().article.doi == "10.1/abc"


def test_opakovany_import_nic_nezdvoji_a_aktualizuje(katalog):
    data = export_catalog()
    data["metriky"][0]["mdc"] = 0.1

    counts = import_catalog(data)

    assert MetricDef.objects.count() == 1 and Norm.objects.count() == 1
    assert MetricDef.objects.get().mdc == 0.1
    assert counts["metriky"] == [0, 1]


def test_cizi_organizace_se_prevede_na_zadanou(katalog):
    data = export_catalog()
    _vymaz_katalog()
    katalog.short_name = "jina"
    katalog.save()

    with pytest.raises(ImportError_):
        import_catalog(data)
    import_catalog(data, default_org=katalog)
    assert Rule.objects.get().organization == katalog


def test_prikazy_export_a_import(katalog, tmp_path):
    soubor = tmp_path / "katalog.json"
    call_command("export_katalog", soubor=str(soubor))
    _vymaz_katalog()
    call_command("import_katalog", soubor=str(soubor))
    assert Rule.objects.count() == 1
    assert "Poměr IR/ER" in soubor.read_text(encoding="utf-8")
