"""
Testy grafů.

Netestuje se, jestli je graf hezký, ale jestli neklame: osa nesmí zvětšovat
šum, jedna metrika s více kvalifikátory nesmí skončit ve dvou elementech
se stejným id, a asymetrie musí být ve společné jednotce.
"""

from datetime import date

import pytest

from apps.analytics import charts
from apps.catalog.models import Direction, MetricDef, TestFamily


@pytest.fixture
def vyska(db):
    return MetricDef.objects.create(
        code="cmj_height", name="Výška výskoku", family=TestFamily.FORCE_PLATE,
        unit="cm", direction=Direction.HIGHER, mdc=1.8, swc=1.0, decimals=1,
    )


def test_osa_nezvetsuje_sum(vyska):
    """
    Kolísání pod MDC nesmí vypadat jako vývoj. Osa proto pokrývá
    aspoň trojnásobek MDC.
    """
    body = [(date(2025, 1, 1), 40.0), (date(2025, 6, 1), 40.2),
            (date(2025, 9, 1), 40.1)]
    spec = charts.trend_chart(vyska, body)
    low, high = spec.figure["layout"]["yaxis"]["range"]
    assert high - low >= 3 * vyska.mdc


def test_velka_zmena_osu_neroztahuje_zbytecne(vyska):
    body = [(date(2025, 1, 1), 30.0), (date(2025, 9, 1), 48.0)]
    low, high = charts.trend_chart(vyska, body).figure["layout"]["yaxis"]["range"]
    assert 18 <= high - low <= 30


def test_kvalifikatory_rozlisi_id_i_titulek(vyska):
    body = [(date(2025, 1, 1), 40.0), (date(2025, 6, 1), 42.0)]
    levy = charts.trend_chart(vyska, body, qualifiers={
        "side": "L", "mode": "con", "speed": 210.0, "segment": ""})
    pravy = charts.trend_chart(vyska, body, qualifiers={
        "side": "R", "mode": "con", "speed": 210.0, "segment": ""})

    assert levy.element_id != pravy.element_id
    assert "levá" in levy.title and "pravá" in pravy.title
    assert "210°/s" in levy.title


def test_shrnuti_nelze_bez_mdc(db):
    bez_mdc = MetricDef.objects.create(
        code="vo2max", name="VO2max", family=TestFamily.SPIROERGOMETRY,
        unit="ml/kg/min", direction=Direction.HIGHER, decimals=1,
    )
    body = [(date(2025, 1, 1), 55.0), (date(2025, 9, 1), 60.0)]
    assert "nemá MDC" in charts.trend_chart(bez_mdc, body).subtitle


def test_ceska_desetinna_carka(vyska):
    body = [(date(2025, 1, 1), 40.0), (date(2025, 9, 1), 44.5)]
    spec = charts.trend_chart(vyska, body)
    assert spec.figure["layout"]["separators"] == ", "
    assert "4,5" in spec.subtitle


def _radek(metric, left, right, **qualifiers):
    q = {"side": "", "mode": "", "speed": None, "segment": ""} | qualifiers
    stronger = max(abs(left), abs(right)) or 1
    return {"metric": metric, "qualifiers": q, "left": left, "right": right,
            "index_pct": (left - right) / stronger * 100, "exceeds_threshold": False}


def test_asymetrie_je_ve_spolecne_jednotce(db):
    """
    Newtony a bezrozměrný poměr na jedné ose znamenají, že je vidět jen
    ta největší veličina. Proto se vynáší procentní rozdíl.
    """
    sila = MetricDef.objects.create(code="imtp", name="IMTP", unit="N",
                                    family=TestFamily.FORCE_PLATE)
    pomer = MetricDef.objects.create(code="ir_er", name="IR/ER", unit="-",
                                     family=TestFamily.DYNAMOMETRY)
    rows = [_radek(sila, 2800.0, 2950.0), _radek(pomer, 1.05, 1.12)]

    spec = charts.asymmetry_chart(rows)
    x = spec.figure["data"][0]["x"]

    assert all(abs(v) < 100 for v in x)          # procenta, ne newtony
    assert "%" in spec.figure["layout"]["xaxis"]["title"]["text"]
    # obě metriky jsou ve srovnatelném řádu, žádná nezmizí u nuly
    assert min(abs(v) for v in x) > 1


def test_prah_se_hlasi_stavovou_barvou_i_textem(db):
    metric = MetricDef.objects.create(code="grip", name="Stisk", unit="kg",
                                      family=TestFamily.DYNAMOMETRY)
    rows = [_radek(metric, 30.0, 45.0)]          # −33 %
    spec = charts.asymmetry_chart(rows, threshold_pct=10.0)

    assert charts.STATUS_WARNING in spec.figure["data"][0]["marker"]["color"]
    assert "nad prahem" in spec.subtitle


def test_asymetrie_omezi_pocet_radku(db):
    metric = MetricDef.objects.create(code="m", name="M", unit="kg",
                                      family=TestFamily.DYNAMOMETRY)
    rows = [_radek(metric, 100.0 - i, 100.0) for i in range(1, 26)]
    spec = charts.asymmetry_chart(rows, limit=10)
    assert len(spec.figure["data"][0]["x"]) == 10
