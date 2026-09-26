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


# --- vyhledávání a karta ---------------------------------------------------------

def _sportovec_se_jmenem(settings, org, code, first, last):
    from cryptography.fernet import Fernet

    from apps.subjects.models import SubjectIdentity

    if not settings.IDENTITY_ENCRYPTION_KEY:
        settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    subject = Subject.objects.create(organization=org, code=code)
    identity = SubjectIdentity(subject=subject)
    identity.set_names(first, last)
    identity.save()
    return subject


def test_hledani_podle_jmena_bez_diakritiky(db, settings):
    from apps.core.models import Organization, Role, User
    from apps.subjects import search

    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    lab = User.objects.create(username="lab", organization=org, role=Role.LAB)
    _sportovec_se_jmenem(settings, org, "FTVS-0001", "Matěj", "Čížek")
    _sportovec_se_jmenem(settings, org, "FTVS-0002", "Jan", "Novák")

    assert [s.jmeno for s in search.search(lab, "cizek")] == ["Matěj Čížek"]
    assert [s.code for s in search.search(lab, "0002")] == ["FTVS-0002"]


def test_jmeno_vidi_jen_opravnena_role(db, settings):
    from apps.core.models import Organization, Role, User
    from apps.subjects import search

    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    vyzkumnik = User.objects.create(username="vyzkum", organization=org, role=Role.RESEARCHER)
    _sportovec_se_jmenem(settings, org, "FTVS-0001", "Matěj", "Čížek")

    assert search.search(vyzkumnik, "cizek") == []
    assert search.search(vyzkumnik, "0001")[0].zobrazeni == "FTVS-0001"


def test_karta_a_naseptavac_se_zobrazi(client, db, settings):
    from django.core.management import call_command

    from apps.core.models import User

    call_command("seed_demo", subjects=2, sessions=3, admin_password="test-heslo-123",
                 verbosity=0)
    client.force_login(User.objects.get(username="admin"))
    subject = Subject.objects.first()

    html = client.get(f"/sportovci/{subject.pk}/").content.decode()
    assert "Klíčové ukazatele" in html and 'class="spark"' in html
    assert "-data-dark" in html                      # grafy i pro tmavý režim
    assert "FTVS-0001" in client.get("/sportovci/hledat/?q=0001").content.decode()
    assert client.get("/").status_code == 200
