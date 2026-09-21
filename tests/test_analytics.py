"""
Testy analytické vrstvy.

Těžiště je na tom, co odlišuje novou platformu od původní aplikace:
rozlišení skutečné změny od šumu měření a obecný výpočet asymetrie.
"""

import pytest

from apps.analytics.services import asymmetry_index, compare_to_previous
from apps.catalog.models import Direction, MetricDef, TestFamily


@pytest.fixture
def vyska_vyskoku(db):
    return MetricDef.objects.create(
        code="cmj_height", name="Výška výskoku", family=TestFamily.FORCE_PLATE,
        unit="cm", direction=Direction.HIGHER, mdc=1.8, swc=1.0,
    )


def test_zmena_pod_mdc_se_nehlasi_jako_zlepseni(vyska_vyskoku):
    """Původní interpretuj_graf() by řekl 'zlepšení'. To je šum měření."""
    vysledek = compare_to_previous(vyska_vyskoku, current=38.4, previous=38.0)
    assert vysledek.is_real is False
    assert "nepřesahuje" in vysledek.text


def test_zmena_nad_mdc_je_skutecna(vyska_vyskoku):
    vysledek = compare_to_previous(vyska_vyskoku, current=41.2, previous=38.0)
    assert vysledek.is_real is True
    assert vysledek.is_improvement is True
    assert "zlepšení" in vysledek.text


def test_bez_mdc_se_nic_netvrdi(vyska_vyskoku):
    """Když MDC chybí, zpráva to přizná místo aby si vymyslela závěr."""
    vyska_vyskoku.mdc = None
    vysledek = compare_to_previous(vyska_vyskoku, current=41.2, previous=38.0)
    assert vysledek.is_real is False
    assert "není stanovena MDC" in vysledek.text


def test_nizsi_je_lepsi(db):
    tuk = MetricDef.objects.create(
        code="body_fat", name="Tělesný tuk", family=TestFamily.BODY_COMPOSITION,
        unit="%", direction=Direction.LOWER, mdc=1.1,
    )
    assert compare_to_previous(tuk, current=14.0, previous=16.0).is_improvement is True
    assert compare_to_previous(tuk, current=18.0, previous=16.0).is_improvement is False


@pytest.mark.parametrize("left,right,ocekavano", [
    (100, 100, 0.0),
    (90, 100, -10.0),
    (100, 90, 10.0),
    (0, 0, 0.0),
])
def test_index_asymetrie(left, right, ocekavano):
    assert asymmetry_index(left, right) == pytest.approx(ocekavano)
