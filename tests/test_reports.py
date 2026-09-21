"""
Testy generování a vydávání zprávy.

Těžiště: vydaná zpráva je nevratná, bez souhlasu se nepředá, a text
nesmí obsahovat čísla bez opory v nálezech.
"""

from datetime import date

import pytest

from apps.catalog.models import MetricDef, Protocol, TestFamily
from apps.core.models import Organization, Role, User
from apps.evidence.models import Article, EvidenceLevel
from apps.measurements.models import Measurement, ProtocolRun, TestSession, Trial
from apps.reports import narrative, services
from apps.reports.models import Report, ReportDelivery
from apps.rules.models import Rule, RuleArticle, Severity
from apps.subjects.models import Consent, Sex, Subject


@pytest.fixture
def prostredi(db):
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    user = User.objects.create(username="laborant", organization=org, role=Role.LAB)
    subject = Subject.objects.create(organization=org, code="FTVS-0001",
                                     sex=Sex.FEMALE, birth_year=2000)
    metric = MetricDef.objects.create(code="ir_er_ratio", name="Poměr IR/ER",
                                      family=TestFamily.DYNAMOMETRY, unit="-", decimals=2)
    protocol = Protocol.objects.create(code="p", name="Protokol",
                                       family=TestFamily.DYNAMOMETRY)
    session = TestSession.objects.create(organization=org, subject=subject,
                                         date=date(2026, 3, 1))
    run = ProtocolRun.objects.create(session=session, protocol=protocol)
    trial = Trial.objects.create(protocol_run=run, number=1)
    Measurement.objects.create(trial=trial, metric=metric, value=0.85, speed=210)

    Rule.objects.create(
        code="ir_er", name="Poměr IR/ER", severity=Severity.MEDIUM,
        condition={"metric": "ir_er_ratio", "op": "<", "value": 1.0},
        finding_template="Poměr IR/ER {value_txt} je pod {threshold_txt}.",
        recommendation_template="Posílit zevní rotátory ramene.",
    )
    return org, user, subject, session


# --- koncept ---------------------------------------------------------------

def test_koncept_obsahuje_nalezy_i_doporuceni(prostredi):
    org, user, subject, session = prostredi
    report = services.build_draft(session, user=user)

    assert report.status == Report.Status.DRAFT
    assert report.report_number.startswith("FT-")
    assert "0,85" in report.summary
    assert "Posílit zevní rotátory" in report.summary
    assert report.input_fingerprint
    assert "ir_er@1" in report.rules_version


def test_bez_nalezu_to_zprava_rekne(prostredi):
    org, user, subject, session = prostredi
    Rule.objects.all().delete()
    report = services.build_draft(session, user=user)
    assert "nebyl nalezen žádný stav" in report.summary


def test_cisla_zprav_jdou_po_sobe(prostredi):
    org, user, subject, session = prostredi
    prvni = services.build_draft(session, user=user)
    druha = services.build_draft(session, user=user)
    assert druha.report_number != prvni.report_number
    assert druha.report_number.endswith("0002")


# --- evidence --------------------------------------------------------------

def test_neschvaleny_clanek_se_neciituje(prostredi):
    org, user, subject, session = prostredi
    rule = Rule.objects.get(code="ir_er")
    navrzeny = Article.objects.create(title="Nezkontrolovaná studie",
                                      status=Article.Status.SUGGESTED)
    RuleArticle.objects.create(rule=rule, article=navrzeny)

    report = services.build_draft(session, user=user)
    assert services.report_context(report)["citations"] == []


def test_odlisna_populace_se_ohlasi(prostredi):
    org, user, subject, session = prostredi
    rule = Rule.objects.get(code="ir_er")
    clanek = Article.objects.create(
        title="Studie na mužích", authors="Novák, J.", year=2023,
        status=Article.Status.APPROVED, evidence_level=EvidenceLevel.RCT,
        population_sex="M", population_sport="fotbal",
    )
    RuleArticle.objects.create(rule=rule, article=clanek)

    report = services.build_draft(session, user=user)
    context = services.report_context(report)

    assert len(context["citations"]) == 1
    assert context["citations"][0]["population_matches"] is False
    assert "odlišné populace" in context["population_warnings"][0]


# --- pojistka na čísla -----------------------------------------------------

def test_kontrola_odhali_nepodlozene_cislo(prostredi):
    """
    Pojistka pro případ, že text píše jazykový model: číslo, které
    nepochází z nálezů, se do zprávy nesmí dostat.
    """
    org, user, subject, session = prostredi
    report = services.build_draft(session, user=user)
    nalezy = list(session.findings.all())

    assert narrative.verify_numbers(report.summary, nalezy) == []
    vymyslene = "Poměr IR/ER 0,85 je pod 1,00 a VO2max byl 62,4 ml/kg/min."
    assert "62,4" in narrative.verify_numbers(vymyslene, nalezy)


def test_kontrola_propousti_cisla_z_nalezu(prostredi):
    org, user, subject, session = prostredi
    services.build_draft(session, user=user)
    nalezy = list(session.findings.all())
    assert narrative.verify_numbers("Hodnota 0,85 oproti prahu 1,00.", nalezy) == []


# --- vydání a předání ------------------------------------------------------

def test_vydana_zprava_se_needituje(prostredi):
    org, user, subject, session = prostredi
    report = services.build_draft(session, user=user)
    services.release(report, user=user)

    report.refresh_from_db()
    assert report.status == Report.Status.RELEASED
    assert report.released_at and report.released_by == user
    assert report.is_editable is False
    assert report.data_json  # strojově čitelná příloha vedle PDF

    with pytest.raises(services.ReportError, match="Vydat lze jen koncept"):
        services.release(report, user=user)


def test_bez_souhlasu_se_zprava_nepreda(prostredi):
    org, user, subject, session = prostredi
    report = services.release(services.build_draft(session, user=user), user=user)

    with pytest.raises(services.ReportError, match="nemá platný souhlas"):
        services.deliver(report, recipient="AKESO",
                         channel=ReportDelivery.Channel.SECURE_LINK, user=user)
    assert ReportDelivery.objects.count() == 0


def test_se_souhlasem_se_preda_a_zaznamena(prostredi):
    org, user, subject, session = prostredi
    Consent.objects.create(subject=subject, scope=Consent.Scope.REPORT_HANDOVER,
                           granted_on=date(2026, 1, 1))
    report = services.release(services.build_draft(session, user=user), user=user)

    delivery = services.deliver(report, recipient="AKESO",
                                channel=ReportDelivery.Channel.SECURE_LINK, user=user)
    assert delivery.consent_verified is True
    assert delivery.delivered_by == user


def test_koncept_se_predat_neda(prostredi):
    org, user, subject, session = prostredi
    Consent.objects.create(subject=subject, scope=Consent.Scope.REPORT_HANDOVER,
                           granted_on=date(2026, 1, 1))
    report = services.build_draft(session, user=user)
    with pytest.raises(services.ReportError, match="Předat lze jen vydanou"):
        services.deliver(report, recipient="AKESO",
                         channel=ReportDelivery.Channel.SECURE_LINK, user=user)


def test_oprava_vznikne_jako_nova_verze(prostredi):
    org, user, subject, session = prostredi
    puvodni = services.release(services.build_draft(session, user=user), user=user)

    nova = services.supersede(puvodni, user=user)
    services.release(nova, user=user)

    puvodni.refresh_from_db()
    assert nova.version == 2
    assert nova.supersedes == puvodni
    assert puvodni.status == Report.Status.SUPERSEDED


def test_strojove_citelna_priloha_nese_nalezy(prostredi):
    org, user, subject, session = prostredi
    report = services.release(services.build_draft(session, user=user), user=user)

    data = services._machine_readable(report)
    assert data["sportovec"]["kod"] == "FTVS-0001"
    assert data["nalezy"][0]["pravidlo"] == "ir_er"
    assert data["nalezy"][0]["hodnoty"]["value"] == 0.85
    assert "jméno" not in str(data).lower()
