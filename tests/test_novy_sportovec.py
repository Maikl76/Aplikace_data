"""Ruční založení sportovce: šifrovaná identita, duplicity, souhlasy, věk v den testování."""

from datetime import date

import pytest
from cryptography.fernet import Fernet
from django.test import Client

from apps.core.models import Organization, Role, User
from apps.subjects.models import Consent, Sport, Subject, SubjectExternalId, SubjectIdentity


@pytest.fixture
def lab(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    sport = Sport.objects.create(organization=org, name="Tenis", code="tenis")
    client = Client()
    client.force_login(User.objects.create(username="lab", organization=org, role=Role.LAB))
    return org, sport, client


def form(sport, **extra):
    data = {"first_name": "Jana", "last_name": "Nováková", "birth_date": "2009-05-20",
            "sex": "F", "sport": sport.pk, "category": "dorost", "level": "national",
            "dominant_side": "R", "email": "jana@example.cz", "phone": "",
            "consents": ["testing", "longitudinal"]}
    data.update(extra)
    return data


def test_zalozeni_ulozi_jmeno_a_datum_sifrovane(lab):
    org, sport, client = lab
    response = client.post("/sportovci/novy/", form(sport))
    subject = Subject.objects.get()
    assert response.url == f"/sportovci/{subject.pk}/"
    assert subject.code == "FTVS-0001" and subject.birth_year == 2009
    assert (subject.sport, subject.category, subject.sex) == (sport, "dorost", "F")
    identity = SubjectIdentity.objects.get()
    assert "Jana" not in identity.first_name_enc and "2009" not in identity.birth_date_enc
    assert identity.full_name == "Jana Nováková" and identity.birth_date == date(2009, 5, 20)
    assert identity.email == "jana@example.cz"
    assert {c.scope for c in subject.consents.all()} == {"testing", "longitudinal"}
    # Otisky jména – další export z VALD ji pozná a nezaloží podruhé.
    systems = set(SubjectExternalId.objects.values_list("system", flat=True))
    assert systems == {"hash_jmeno", "hash_jmeno_narozeni"}
    assert "Jana Nováková" in client.get(f"/sportovci/{subject.pk}/").content.decode()


def test_import_pozna_rucne_zalozeneho(lab):
    from apps.ingest.adapters.vald import identity_ids
    from apps.ingest.services import _match_subjects

    org, sport, client = lab
    client.post("/sportovci/novy/", form(sport))
    ids = identity_ids("Jana Novakova", date(2009, 5, 20))
    found, how, _ = _match_subjects(org, {"k": {"ids": ids}})["k"]
    assert found == Subject.objects.get() and how == "jméno a datum narození"


def test_duplicita_se_ohlasi_a_jde_potvrdit(lab):
    org, sport, client = lab
    client.post("/sportovci/novy/", form(sport))
    # Stejné jméno v jiném pořadí, bez diakritiky, stejné datum → upozornění, nic nevznikne.
    response = client.post("/sportovci/novy/", form(sport, first_name="Novakova",
                                                    last_name="Jana"))
    assert response.status_code == 200
    assert "už v aplikaci je" in response.content.decode()
    assert Subject.objects.count() == 1
    client.post("/sportovci/novy/", form(sport, confirm_duplicate="on"))
    assert Subject.objects.count() == 2


def test_stejne_jmeno_jiny_den_narozeni_jen_upozorni(lab):
    org, sport, client = lab
    client.post("/sportovci/novy/", form(sport))
    response = client.post("/sportovci/novy/", form(sport, birth_date="2011-01-02"), follow=True)
    assert Subject.objects.count() == 2
    assert "stejné jméno" in response.content.decode()


def test_uprava_opravi_jmeno_a_odvola_souhlas(lab):
    org, sport, client = lab
    client.post("/sportovci/novy/", form(sport))
    subject = Subject.objects.get()
    page = client.get(f"/sportovci/{subject.pk}/upravit/").content.decode()
    assert 'value="Nováková"' in page and 'value="2009-05-20"' in page
    client.post(f"/sportovci/{subject.pk}/upravit/",
                form(sport, last_name="Novákova", new_sport="Badminton", consents=["testing"]))
    subject.refresh_from_db()
    assert subject.identity.full_name == "Jana Novákova"
    assert subject.sport.name == "Badminton" and subject.code == "FTVS-0001"
    longitudinal = subject.consents.get(scope="longitudinal")
    assert longitudinal.revoked_on is not None and not longitudinal.is_valid
    assert Consent.has(subject, "testing")


def test_vyzkumnik_ani_trener_sportovce_nezaklada(lab):
    org, sport, _ = lab
    for role in (Role.RESEARCHER, Role.COACH):
        client = Client()
        client.force_login(User.objects.create(username=role, organization=org, role=role))
        client.post("/sportovci/novy/", form(sport))
        assert "Nový sportovec" not in client.get("/sportovci/").content.decode()
    assert not Subject.objects.exists()


def test_neplatne_datum_narozeni(lab):
    _, sport, client = lab
    response = client.post("/sportovci/novy/", form(sport, birth_date="2099-01-01"))
    assert "v budoucnosti" in response.content.decode()
    assert not Subject.objects.exists()


def test_vek_v_den_testovani_podle_data_narozeni(lab):
    org, sport, client = lab
    client.post("/sportovci/novy/", form(sport))
    subject = Subject.objects.get()
    assert subject.age_on(date(2025, 5, 19)) == 15
    assert subject.age_on(date(2025, 5, 20)) == 16
    # Bez data narození jen podle roku.
    bez = Subject.objects.create(organization=org, code="X-1", birth_year=2009)
    assert bez.age_on(date(2025, 5, 19)) == 16


def test_administrace_presmeruje_pridani_do_aplikace(lab, settings):
    org, _, _ = lab
    admin = Client()
    admin.force_login(User.objects.create(username="su", organization=org, role=Role.ADMIN,
                                          is_staff=True, is_superuser=True))
    assert admin.get("/admin/subjects/subject/add/").url == "/sportovci/novy/"
