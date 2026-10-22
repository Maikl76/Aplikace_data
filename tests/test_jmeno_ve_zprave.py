"""Volitelné jméno sportovce ve zprávě – jen vědomě, jen rukou, která jméno smí vidět.

Roli bez práva na jméno zastupuje výzkumník (trenér se zatím nepřihlásí vůbec).
"""

from datetime import date

import pytest
from cryptography.fernet import Fernet
from django.test import Client

from apps.catalog.models import MetricDef, Protocol, TestFamily
from apps.core.models import Organization, Role, User
from apps.measurements.models import Measurement, ProtocolRun, TestSession, Trial
from apps.reports import services
from apps.subjects.models import Sex, Subject, SubjectIdentity


@pytest.fixture
def zprava(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    lab = User.objects.create(username="lab", organization=org, role=Role.LAB)
    coach = User.objects.create(username="vyzkum", organization=org, role=Role.RESEARCHER)
    subject = Subject.objects.create(organization=org, code="FTVS-0001", sex=Sex.FEMALE,
                                     birth_year=2000)
    identity = SubjectIdentity(subject=subject)
    identity.set_names("Jana", "Nováková")
    identity.save()
    metric = MetricDef.objects.create(code="cmj_height", name="Výška výskoku",
                                      family=TestFamily.FORCE_PLATE, unit="cm", decimals=1)
    protocol = Protocol.objects.create(code="cmj", name="CMJ", family=TestFamily.FORCE_PLATE)
    session = TestSession.objects.create(organization=org, subject=subject, date=date(2026, 3, 1))
    trial = Trial.objects.create(protocol_run=ProtocolRun.objects.create(session=session,
                                                                         protocol=protocol),
                                 number=1)
    Measurement.objects.create(trial=trial, metric=metric, side="B", value=30.0)
    report = services.build_draft(session, user=lab)
    lab_client, coach_client = Client(), Client()
    lab_client.force_login(lab)
    coach_client.force_login(coach)
    return report, lab_client, coach_client


def test_standardne_jen_kod(zprava):
    report, lab, coach = zprava
    html = lab.get(f"/zpravy/{report.pk}/nahled/").content.decode()
    assert "FTVS-0001" in html and "Nováková" not in html
    page = lab.get(f"/zpravy/{report.pk}/").content.decode()
    assert 'name="show_name"' in page and "Jana Nováková" in page
    # Výzkumník jméno nevidí, zaškrtávátko nemá a nic jím nezmění.
    page = coach.get(f"/zpravy/{report.pk}/").content.decode()
    assert 'name="show_name"' not in page and "Nováková" not in page
    coach.post(f"/zpravy/{report.pk}/", {"summary": report.summary, "custom_note": "",
                                        "show_name": "1"})
    report.refresh_from_db()
    assert report.show_name is False


def test_laborant_zapne_jmeno_a_trener_zpravu_neotevre(zprava):
    report, lab, coach = zprava
    lab.post(f"/zpravy/{report.pk}/", {"summary": report.summary, "custom_note": "pozn.",
                                      "show_name": "1"})
    report.refresh_from_db()
    assert report.show_name is True and report.custom_note == "pozn."
    html = lab.get(f"/zpravy/{report.pk}/nahled/").content.decode()
    assert "Jana Nováková (FTVS-0001)" in html
    assert "26 let v den měření" in html         # věk k datu měření, ne dnešní

    response = coach.get(f"/zpravy/{report.pk}/nahled/")
    assert response.status_code == 302 and response.url == f"/zpravy/{report.pk}/"
    page = coach.get(f"/zpravy/{report.pk}/").content.decode()
    assert "jen správce nebo laborant" in page and "Nováková" not in page

    # Vydání: snímek i PDF nesou jméno, strojová příloha jen kód.
    services.release(report, user=User.objects.get(username="lab"))
    report.refresh_from_db()
    assert "Jana Nováková" in report.rendered_html
    assert "Nováková" not in report.data_json.read().decode()
    assert coach.get(f"/zpravy/{report.pk}/pdf/").status_code == 302
    assert lab.get(f"/zpravy/{report.pk}/pdf/").status_code in (200, 404)

    # Nová verze volbu zdědí; odškrtnutí ji vypne.
    nova = services.supersede(report, user=User.objects.get(username="lab"))
    assert nova.show_name is True
    lab.post(f"/zpravy/{nova.pk}/", {"summary": nova.summary, "custom_note": ""})
    nova.refresh_from_db()
    assert nova.show_name is False
    assert "Nováková" not in lab.get(f"/zpravy/{nova.pk}/nahled/").content.decode()


def test_bez_klice_nebo_identity_zustane_kod(zprava, settings):
    report, lab, _ = zprava
    report.show_name = True
    report.save()
    settings.IDENTITY_ENCRYPTION_KEY = ""
    assert services.subject_name(report) == ""
    assert "Nováková" not in lab.get(f"/zpravy/{report.pk}/nahled/").content.decode()
