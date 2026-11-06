"""
Dávka 4c: externí vyšetření a omezení zátěže na kartě sportovce (formulář
ve třech částech, volitelný krok, novější „bez omezení“ ruší starší) a
odpojení účtu sportovce nebo zákonného zástupce z karty sportovce.
"""

from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Organization, Role, User
from apps.external.models import ExternalExam
from apps.subjects.models import Guardian, Sport, Subject, SubjectIdentity


@pytest.fixture
def org(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    return Organization.objects.create(name="FTVS", short_name="ftvs")


def _user(org, role, username):
    user = User.objects.create(username=username, organization=org, role=role,
                               is_staff=role == Role.ADMIN)
    client = Client()
    client.force_login(user)
    return user, client


def _exam(**extra):
    data = {"exam_type": "medical", "date": timezone.localdate().isoformat(), "provider": "AKESO",
            "external_reference": "", "load_restriction": "none", "restriction_valid_until": "",
            "note": ""}
    data.update(extra)
    return data


def test_externi_vysetreni_na_karte_sportovce(org):
    _, client = _user(org, Role.LAB, "laborant")
    _, researcher = _user(org, Role.RESEARCHER, "vyzkumnik")
    sport = Sport.objects.create(organization=org, name="Florbal", code="florbal")
    subject = Subject.objects.create(organization=org, code="FTVS-0001", sport=sport, sex="M")
    detail = reverse("subject_detail", args=[subject.pk])
    new = reverse("exam_new", args=[subject.pk])
    page = client.get(detail)
    text = page.content.decode()
    assert "Externí vyšetření a omezení zátěže" in text and new in text
    steps = {s["title"]: s for s in page.context["steps"]}
    assert not steps["Externí vyšetření"]["done"] and steps["Externí vyšetření"]["optional"]
    assert steps["Externí vyšetření"]["url"] == new
    assert researcher.get(new).status_code == 403
    page = client.get(new)
    assert page.status_code == 200 and "Omezení zátěže" in page.content.decode()

    today = timezone.localdate()
    text = client.post(new, _exam(date=(today + timedelta(days=1)).isoformat(),
                                  load_restriction="partial"), follow=True).content.decode()
    assert "v budoucnosti" in text and not ExternalExam.objects.exists()
    text = client.post(new, _exam(load_restriction="partial",
                                  restriction_valid_until=(today - timedelta(days=1)).isoformat()),
                       follow=True).content.decode()
    assert "dřív než datum" in text and not ExternalExam.objects.exists()

    until = today + timedelta(days=30)
    resp = client.post(new, _exam(provider="", external_reference="AK-123", load_restriction="partial",
                                  restriction_valid_until=until.isoformat(),
                                  note="kontrola za 6 týdnů"))
    exam = ExternalExam.objects.get()
    assert resp.status_code == 302 and resp.url.endswith("#vysetreni")
    assert (exam.provider, exam.load_restriction, exam.restriction_valid_until) == ("AKESO", "partial", until)
    assert exam.restriction_is_active and ExternalExam.active_restriction_for(subject) == exam
    page = client.get(detail)
    text = page.content.decode()
    assert "Platné omezení zátěže" in text and "kontrola za 6 týdnů" in text
    steps = {s["title"]: s for s in page.context["steps"]}
    assert steps["Externí vyšetření"]["done"]
    assert steps["Externí vyšetření"]["text"].startswith("Platné omezení zátěže (částečné omezení)")
    assert steps["Externí vyšetření"]["url"] == "#vysetreni"

    # novější „bez omezení“ starší omezení ruší; datum „platí do“ se u něj nedrží
    client.post(new, _exam(load_restriction="none",
                           restriction_valid_until=(today + timedelta(days=5)).isoformat()))
    newer = ExternalExam.objects.order_by("-pk").first()
    assert newer.restriction_valid_until is None and ExternalExam.active_restriction_for(subject) is None
    text = client.get(detail).content.decode()
    assert "Platné omezení zátěže" not in text and "bez omezení" in text

    # úprava a smazání
    edit = reverse("exam_edit", args=[subject.pk, exam.pk])
    page = client.get(edit)
    assert page.status_code == 200 and page.context["data"]["external_reference"] == "AK-123"
    client.post(edit, _exam(external_reference="AK-124", load_restriction="full"))
    exam.refresh_from_db()
    assert exam.external_reference == "AK-124" and exam.load_restriction == "full"
    assert researcher.post(reverse("exam_delete", args=[subject.pk, exam.pk])).status_code == 403
    client.post(reverse("exam_delete", args=[subject.pk, exam.pk]))
    assert ExternalExam.objects.count() == 1


def test_odebrani_uctu_sportovce_a_zastupce(org):
    _, client = _user(org, Role.LAB, "laborant")
    _, researcher = _user(org, Role.RESEARCHER, "vyzkumnik")
    subject = Subject.objects.create(organization=org, code="FTVS-0002")
    identity = SubjectIdentity.objects.create(subject=subject)
    athlete = User.objects.create(username="sportovec@example.cz", organization=org,
                                  role=Role.ATHLETE)
    identity.user = athlete
    identity.save()
    guardian = User.objects.create(username="rodic@example.cz", organization=org,
                                   role=Role.ATHLETE)
    Guardian.objects.create(identity=identity, user=guardian)
    sibling = SubjectIdentity.objects.create(
        subject=Subject.objects.create(organization=org, code="FTVS-0003"))
    Guardian.objects.create(identity=sibling, user=guardian)
    detail = reverse("subject_detail", args=[subject.pk])
    text = client.get(detail).content.decode()
    assert "rodic@example.cz" in text and "odebrat" in text
    assert "odebrat" not in researcher.get(detail).content.decode()

    url = reverse("subject_account_remove", args=[subject.pk])
    researcher.post(url, {"druh": "guardian", "uzivatel": guardian.pk})
    assert Guardian.objects.filter(identity=identity, user=guardian).exists()
    # zástupce s dalším dítětem zůstává aktivní; sportovec bez sportovce se vypne
    text = client.post(url, {"druh": "guardian", "uzivatel": guardian.pk}, follow=True).content.decode()
    guardian.refresh_from_db()
    assert not Guardian.objects.filter(identity=identity, user=guardian).exists()
    assert guardian.is_active and "nepatří." in text
    text = client.post(url, {"druh": "athlete", "uzivatel": athlete.pk}, follow=True).content.decode()
    identity.refresh_from_db()
    athlete.refresh_from_db()
    assert identity.user is None and not athlete.is_active and "je vypnutý" in text
    text = client.post(url, {"druh": "athlete", "uzivatel": athlete.pk}, follow=True).content.decode()
    assert "není účtem sportovce" in text
    assert "Takový účet tu není" in client.post(url, {"druh": "athlete", "uzivatel": "0"},
                                                follow=True).content.decode()
