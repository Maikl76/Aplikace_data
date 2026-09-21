"""
Testy vyhodnocování pravidel.

Důraz na to, co se nesmí pokazit: kontraindikace musí potlačit doporučení,
změna pod MDC nesmí spustit nález, a šablona nesmí otevřít cestu dovnitř
objektů.
"""

from datetime import date, timedelta

import pytest

from apps.catalog.models import Direction, MetricDef, Protocol, TestFamily
from apps.core.models import Organization
from apps.external.models import ExternalExam
from apps.measurements.models import Measurement, ProtocolRun, Side, TestSession, Trial
from apps.rules import engine
from apps.rules.models import Rule, Severity
from apps.subjects.models import Subject


@pytest.fixture
def org(db):
    return Organization.objects.create(name="FTVS", short_name="ftvs")


@pytest.fixture
def sportovec(org):
    return Subject.objects.create(organization=org, code="FTVS-0001", birth_year=2000)


@pytest.fixture
def pomer(db):
    return MetricDef.objects.create(
        code="ir_er_ratio", name="Poměr IR/ER", family=TestFamily.DYNAMOMETRY,
        unit="-", direction=Direction.OPTIMAL, decimals=2,
    )


@pytest.fixture
def vyska(db):
    return MetricDef.objects.create(
        code="cmj_height", name="Výška výskoku", family=TestFamily.FORCE_PLATE,
        unit="cm", direction=Direction.HIGHER, mdc=1.8, decimals=1,
    )


@pytest.fixture
def protokol(db):
    return Protocol.objects.create(code="p", name="Protokol",
                                   family=TestFamily.DYNAMOMETRY)


def _mereni(org, subject, protokol, den, metric, hodnota, **kv):
    session, _ = TestSession.objects.get_or_create(
        organization=org, subject=subject, date=den)
    run, _ = ProtocolRun.objects.get_or_create(session=session, protocol=protokol)
    trial, _ = Trial.objects.get_or_create(protocol_run=run, number=1)
    Measurement.objects.create(
        trial=trial, metric=metric, value=hodnota,
        side=kv.get("side", ""), mode=kv.get("mode", ""),
        speed=kv.get("speed"), segment=kv.get("segment", ""),
    )
    return session


@pytest.fixture
def pravidlo_pomer(db):
    return Rule.objects.create(
        code="ir_er", name="Poměr IR/ER", severity=Severity.MEDIUM,
        condition={"metric": "ir_er_ratio", "op": "<", "value": 1.0,
                   "where": {"speed": 210}},
        contraindication={"load_restriction": True},
        finding_template="Poměr IR/ER {value_txt} je pod {threshold_txt}.",
        recommendation_template="Posílit zevní rotátory.",
    )


# --- základní vyhodnocení --------------------------------------------------

def test_pravidlo_najde_nalez(org, sportovec, protokol, pomer, pravidlo_pomer):
    session = _mereni(org, sportovec, protokol, date(2026, 3, 1), pomer, 0.85, speed=210)
    nalezy = engine.evaluate_session(session)

    assert len(nalezy) == 1
    assert nalezy[0].text == "Poměr IR/ER 0,85 je pod 1,00."
    assert nalezy[0].values["value"] == 0.85
    assert nalezy[0].suppressed is False


def test_hodnota_nad_prahem_nalez_nevyvola(org, sportovec, protokol, pomer, pravidlo_pomer):
    session = _mereni(org, sportovec, protokol, date(2026, 3, 1), pomer, 1.25, speed=210)
    assert engine.evaluate_session(session) == []


def test_kvalifikator_omezi_platnost(org, sportovec, protokol, pomer, pravidlo_pomer):
    """Pravidlo míří na 210°/s, hodnota při 300°/s ho spustit nesmí."""
    session = _mereni(org, sportovec, protokol, date(2026, 3, 1), pomer, 0.85, speed=300)
    assert engine.evaluate_session(session) == []


# --- kontraindikace --------------------------------------------------------

def test_omezeni_zateze_potlaci_doporuceni(org, sportovec, protokol, pomer, pravidlo_pomer):
    """
    Nález se nezahazuje – uloží se s důvodem. Musí být doložitelné, že
    pravidlo sedělo a doporučení se nevydalo kvůli zdravotnímu omezení.
    """
    ExternalExam.objects.create(
        subject=sportovec, exam_type=ExternalExam.ExamType.MEDICAL,
        date=date(2026, 2, 1), load_restriction=ExternalExam.Restriction.FULL,
    )
    session = _mereni(org, sportovec, protokol, date(2026, 3, 1), pomer, 0.85, speed=210)
    nalez = engine.evaluate_session(session)[0]

    assert nalez.suppressed is True
    assert "omezení zátěže" in nalez.suppressed_reason.lower()
    assert nalez.text  # text zůstává, jen se z něj nestane doporučení


def test_prosle_omezeni_uz_nepotlacuje(org, sportovec, protokol, pomer, pravidlo_pomer):
    ExternalExam.objects.create(
        subject=sportovec, exam_type=ExternalExam.ExamType.MEDICAL,
        date=date(2025, 1, 1), load_restriction=ExternalExam.Restriction.FULL,
        restriction_valid_until=date(2025, 6, 1),
    )
    session = _mereni(org, sportovec, protokol, date(2026, 3, 1), pomer, 0.85, speed=210)
    assert engine.evaluate_session(session)[0].suppressed is False


# --- změna v čase ----------------------------------------------------------

def test_zmena_pod_mdc_nespusti_pravidlo(org, sportovec, protokol, vyska):
    Rule.objects.create(
        code="pokles", name="Pokles", severity=Severity.HIGH,
        condition={"change": "cmj_height", "op": "<", "value": 0, "require_mdc": True},
        finding_template="Pokles o {delta_txt} {unit}.",
    )
    den = date(2026, 3, 1)
    _mereni(org, sportovec, protokol, den - timedelta(days=90), vyska, 40.0)
    session = _mereni(org, sportovec, protokol, den, vyska, 39.5)   # −0,5 < MDC 1,8

    assert engine.evaluate_session(session) == []


def test_zmena_nad_mdc_pravidlo_spusti(org, sportovec, protokol, vyska):
    Rule.objects.create(
        code="pokles", name="Pokles", severity=Severity.HIGH,
        condition={"change": "cmj_height", "op": "<", "value": 0, "require_mdc": True},
        finding_template="Pokles o {delta_txt} {unit} (MDC {mdc_txt}).",
    )
    den = date(2026, 3, 1)
    _mereni(org, sportovec, protokol, den - timedelta(days=90), vyska, 40.0)
    session = _mereni(org, sportovec, protokol, den, vyska, 36.0)

    nalez = engine.evaluate_session(session)[0]
    assert "−4,0" in nalez.text
    assert nalez.severity == Severity.HIGH


# --- asymetrie -------------------------------------------------------------

def test_asymetrie_napric_metrikami(org, sportovec, protokol, db):
    stisk = MetricDef.objects.create(code="grip", name="Stisk", unit="kg",
                                     family=TestFamily.DYNAMOMETRY, decimals=1)
    Rule.objects.create(
        code="asym", name="Asymetrie", severity=Severity.MEDIUM,
        condition={"asymmetry": "*", "op": ">", "value": 10},
        finding_template="{metric}: rozdíl {index_txt} %, silnější {silnejsi}.",
    )
    den = date(2026, 3, 1)
    session = _mereni(org, sportovec, protokol, den, stisk, 30.0, side=Side.LEFT)
    _mereni(org, sportovec, protokol, den, stisk, 45.0, side=Side.RIGHT)

    nalez = engine.evaluate_session(session)[0]
    assert "pravá" in nalez.text
    assert nalez.values["index_pct"] == pytest.approx(-33.3, abs=0.1)


# --- čitelnost textu -------------------------------------------------------

def test_zaokrouhleni_nesmi_udelat_protimluv(org, sportovec, protokol, pomer):
    """
    Hodnota 0,997 proti prahu 1,0 by po zaokrouhlení na dvě místa dala
    větu „1,00 je pod 1,00“. Text musí přidat desetinné místo.
    """
    Rule.objects.create(
        code="pomer", name="Poměr", severity=Severity.MEDIUM,
        condition={"metric": "ir_er_ratio", "op": "<", "value": 1.0},
        finding_template="Poměr {value_txt} je pod {threshold_txt}.",
    )
    session = _mereni(org, sportovec, protokol, date(2026, 3, 1), pomer, 0.997)
    text = engine.evaluate_session(session)[0].text

    assert text == "Poměr 0,997 je pod 1,000."


def test_rychlost_se_pise_jako_cele_cislo(org, sportovec, protokol, pomer):
    Rule.objects.create(
        code="rychlost", name="Rychlost", severity=Severity.LOW,
        condition={"metric": "ir_er_ratio", "op": "<", "value": 2.0},
        finding_template="Při {speed_txt} °/s.",
    )
    session = _mereni(org, sportovec, protokol, date(2026, 3, 1), pomer, 1.0, speed=210)
    assert engine.evaluate_session(session)[0].text == "Při 210 °/s."


# --- bezpečnost šablon -----------------------------------------------------

def test_sablona_nesmi_dovnitr_objektu():
    with pytest.raises(engine.RuleError):
        engine.formatter.format_safe("{value.__class__}", {"value": 1.0})
    with pytest.raises(engine.RuleError):
        engine.formatter.format_safe("{value[0]}", {"value": [1.0]})


def test_chybejici_pole_sablonu_neshodi():
    assert engine.formatter.format_safe("{neexistuje}", {}) == "[?]"


def test_spatne_zapsane_pravidlo_se_preskoci(org, sportovec, protokol, pomer):
    """Chybné pravidlo nesmí shodit celé vyhodnocení ostatních."""
    Rule.objects.create(code="rozbite", name="Rozbité", severity=Severity.LOW,
                        condition={"metric": "ir_er_ratio", "op": "???", "value": 1},
                        finding_template="x")
    Rule.objects.create(code="ok", name="OK", severity=Severity.LOW,
                        condition={"metric": "ir_er_ratio", "op": "<", "value": 1.0},
                        finding_template="Nález {value_txt}.")
    session = _mereni(org, sportovec, protokol, date(2026, 3, 1), pomer, 0.85)

    nalezy = engine.evaluate_session(session)
    assert [n.rule.code for n in nalezy] == ["ok"]


def test_pravidlo_pro_jiny_sport_se_nepouzije(org, sportovec, protokol, pomer, db):
    from apps.subjects.models import Sport

    jiny = Sport.objects.create(organization=org, code="veslovani", name="Veslování")
    Rule.objects.create(code="jen_veslo", name="Jen veslování", severity=Severity.LOW,
                        applies_to_sport=jiny,
                        condition={"metric": "ir_er_ratio", "op": "<", "value": 1.0},
                        finding_template="x")
    session = _mereni(org, sportovec, protokol, date(2026, 3, 1), pomer, 0.85)
    assert engine.evaluate_session(session) == []
