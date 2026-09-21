"""Testy pseudonymizace a souhlasů."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.models import Organization, Role, User
from apps.subjects.models import Consent, Sex, Subject


@pytest.fixture
def org(db):
    return Organization.objects.create(name="FTVS", short_name="ftvs")


@pytest.fixture
def sportovec(org):
    return Subject.objects.create(organization=org, code="FTVS-0001", sex=Sex.FEMALE,
                                  birth_year=2000)


def test_sportovec_vystupuje_pod_pseudonymem(sportovec, org):
    """V provozních tabulkách nesmí být jméno – ani nepřímo přes __str__."""
    trener = User.objects.create(username="trener", organization=org, role=Role.COACH)
    assert str(sportovec) == "FTVS-0001"
    assert sportovec.display_for(trener) == "FTVS-0001"


def test_odvolany_souhlas_neplati(sportovec):
    dnes = timezone.localdate()
    souhlas = Consent.objects.create(
        subject=sportovec, scope=Consent.Scope.REPORT_HANDOVER,
        granted_on=dnes - timedelta(days=30), revoked_on=dnes - timedelta(days=1),
    )
    assert souhlas.is_valid is False
    assert Consent.has(sportovec, Consent.Scope.REPORT_HANDOVER) is False


def test_prosly_souhlas_neplati(sportovec):
    dnes = timezone.localdate()
    Consent.objects.create(
        subject=sportovec, scope=Consent.Scope.TESTING,
        granted_on=dnes - timedelta(days=500), valid_until=dnes - timedelta(days=10),
    )
    assert Consent.has(sportovec, Consent.Scope.TESTING) is False


def test_platny_souhlas(sportovec):
    Consent.objects.create(subject=sportovec, scope=Consent.Scope.TESTING,
                           granted_on=timezone.localdate() - timedelta(days=10))
    assert Consent.has(sportovec, Consent.Scope.TESTING) is True


def test_scoping_podle_organizace(sportovec, org):
    jina = Organization.objects.create(name="Jiné pracoviště", short_name="jine")
    cizi_uzivatel = User.objects.create(username="cizi", organization=jina, role=Role.LAB)
    nas_uzivatel = User.objects.create(username="nas", organization=org, role=Role.LAB)

    assert Subject.objects.for_user(cizi_uzivatel).count() == 0
    assert Subject.objects.for_user(nas_uzivatel).count() == 1
