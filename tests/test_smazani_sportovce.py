"""Deaktivace, smazání a anonymizace (výmaz osobních údajů) sportovce v aplikaci."""

from datetime import date, datetime

import pytest
from django.core.files.base import ContentFile
from django.test import Client
from django.utils import timezone

from apps.core.models import AuditLog, Role, User
from apps.measurements.models import TestSession
from apps.subjects.models import Consent, Subject, SubjectExternalId, SubjectIdentity
from tests.test_novy_sportovec import form, lab  # noqa: F401  (fixtura)


@pytest.fixture
def admin(lab):  # noqa: F811
    org, sport, _ = lab
    client = Client()
    client.force_login(User.objects.create(username="sp", organization=org, role=Role.ADMIN))
    return client


def _new(client, sport, **extra):
    client.post("/sportovci/novy/", form(sport, **extra))
    return Subject.objects.order_by("-pk").first()


def test_deaktivace_a_seznam(lab):  # noqa: F811
    org, sport, client = lab
    subject = _new(client, sport)
    response = client.post(f"/sportovci/{subject.pk}/akce/", {"akce": "deaktivovat"})
    assert response.url == f"/sportovci/{subject.pk}/"
    subject.refresh_from_db()
    assert not subject.is_active
    page = client.get("/sportovci/").content.decode()
    assert "Nováková" not in page and "i neaktivní (1)" in page
    page = client.get("/sportovci/?neaktivni=1").content.decode()
    assert "Nováková" in page and "neaktivní" in page
    assert "neaktivní" in client.get(f"/sportovci/{subject.pk}/").content.decode()
    client.post(f"/sportovci/{subject.pk}/akce/", {"akce": "aktivovat"})
    subject.refresh_from_db()
    assert subject.is_active


def test_smazat_jen_bez_dat_a_jen_spravce(lab, admin, settings, tmp_path):  # noqa: F811
    org, sport, lab_client = lab
    settings.MEDIA_ROOT = tmp_path
    subject = _new(lab_client, sport)
    consent = subject.consents.first()
    consent.document.save("souhlas.pdf", ContentFile(b"%PDF"))
    path = consent.document.path

    # Laborant smazat nesmí, a tlačítko ani nevidí.
    assert "Smazat sportovce" not in lab_client.get(f"/sportovci/{subject.pk}/upravit/").content.decode()
    lab_client.post(f"/sportovci/{subject.pk}/akce/", {"akce": "smazat",
                                                       "potvrzeni": subject.code})
    assert Subject.objects.filter(pk=subject.pk).exists()

    page = admin.get(f"/sportovci/{subject.pk}/upravit/").content.decode()
    assert "Smazat sportovce" in page and "Anonymizovat" in page
    # Bez opsaného kódu nic.
    admin.post(f"/sportovci/{subject.pk}/akce/", {"akce": "smazat", "potvrzeni": "x"})
    assert Subject.objects.filter(pk=subject.pk).exists()
    response = admin.post(f"/sportovci/{subject.pk}/akce/", {
        "akce": "smazat", "potvrzeni": subject.code.lower()})
    assert response.url == "/sportovci/"
    assert not Subject.objects.filter(pk=subject.pk).exists()
    assert not SubjectIdentity.objects.exists() and not Consent.objects.exists()
    import os
    assert not os.path.exists(path)
    assert AuditLog.objects.filter(action=AuditLog.Action.DELETE).exists()

    # Se měřením smazat nejde.
    other = _new(lab_client, sport, first_name="Petr", last_name="Dvořák")
    TestSession.objects.create(organization=org, subject=other, date=date(2026, 3, 1))
    page = admin.get(f"/sportovci/{other.pk}/upravit/").content.decode()
    assert "Smazat nejde" in page
    response = admin.post(f"/sportovci/{other.pk}/akce/", {"akce": "smazat",
                                                           "potvrzeni": other.code}, follow=True)
    assert "nelze smazat" in response.content.decode()
    assert Subject.objects.filter(pk=other.pk).exists()


def test_anonymizace_vymaze_osobni_udaje(lab, admin):  # noqa: F811
    from apps.booking.models import BookingRequest, Participant, Slot
    from apps.ingest.models import ImportBatch, StagedMeasurement

    org, sport, lab_client = lab
    subject = _new(lab_client, sport)
    session = TestSession.objects.create(organization=org, subject=subject, date=date(2026, 3, 1))
    SubjectExternalId.objects.create(subject=subject, system="vald", value="abc-123")
    slot = Slot.objects.create(organization=org, start=timezone.make_aware(datetime(2026, 3, 1, 9)))
    request = BookingRequest.objects.create(organization=org, slot=slot, goal_note="Jana chce…")
    request.set_contact("Jana Nováková", "jana@example.cz", "777")
    request.save()
    participant = Participant(request=request, subject=subject, session=session)
    participant.set_data("Jana", "Nováková", date(2009, 5, 20), injury="kotník")
    participant.save()
    from apps.measurements.models import RawFile

    raw = RawFile.objects.create(file="raw/vald.csv", original_name="vald.csv", content_hash="x")
    batch = ImportBatch.objects.create(organization=org, raw_file=raw, adapter="vald",
                                       uploaded_by=User.objects.get(username="lab"))
    StagedMeasurement.objects.create(batch=batch, subject=subject, subject_hint="Nováková Jana",
                                     subject_key="k")

    response = admin.post(f"/sportovci/{subject.pk}/akce/", {"akce": "anonymizovat",
                                                             "potvrzeni": subject.code},
                          follow=True)
    assert "1 původních souborů" in response.content.decode()
    subject.refresh_from_db()
    assert not subject.is_active and "vymazány" in subject.note and not subject.source_key
    assert not SubjectIdentity.objects.exists() and not SubjectExternalId.objects.exists()
    participant.refresh_from_db()
    assert participant.full_name == "" and participant.injury == ""
    assert participant.birth_date is None and participant.age_on(date(2026, 1, 1)) is None
    request.refresh_from_db()
    assert request.email == "" and request.goal_note == ""
    assert StagedMeasurement.objects.get().subject_hint == ""
    # Měření zůstalo pod kódem.
    assert TestSession.objects.filter(subject=subject).exists()
    page = admin.get(f"/sportovci/{subject.pk}/").content.decode()
    assert "Nováková" not in page and subject.code in page
    assert "údaje vymazány" in admin.get(f"/objednavky/{request.pk}/").content.decode()
