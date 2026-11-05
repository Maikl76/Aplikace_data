"""Kroky v portálu sportovce a trenéra – fáze 4 průvodců."""

import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Organization, Role, User
from apps.measurements.models import TestSession
from apps.subjects import accounts
from apps.subjects.models import Consent, Sharing, Subject, SubjectIdentity


@pytest.fixture
def org(db):
    call_command("seed_roles", verbosity=0)
    return Organization.objects.create(name="FTVS", short_name="ftvs")


def _steps(page):
    assert page.status_code == 200
    return {s["title"]: s for s in page.context["steps"]}, page.context["next_step"]


def test_portal_sportovce_vede_kroky(org):
    subject = Subject.objects.create(organization=org, code="FTVS-0001")
    athlete = User.objects.create(username="sportovec", organization=org, role=Role.ATHLETE)
    SubjectIdentity.objects.create(subject=subject, user=athlete)
    coach = User.objects.create(username="trener", organization=org, role=Role.COACH)
    client = Client()
    client.force_login(athlete)
    url = reverse("portal_subject", args=[subject.pk])

    steps, nxt = _steps(client.get(url))
    assert list(steps) == ["Účet", "Souhlasy", "Sdílení s trenérem", "Dotazník", "Výsledky"]
    assert steps["Účet"]["done"] and nxt["title"] == "Souhlasy"
    assert nxt["url"] == reverse("portal_consents", args=[subject.pk])
    assert steps["Sdílení s trenérem"]["optional"] and steps["Dotazník"]["optional"]

    Consent.objects.create(subject=subject, scope=Consent.Scope.TESTING, granted_on=timezone.localdate())
    steps, nxt = _steps(client.get(url))
    assert steps["Souhlasy"]["done"] and nxt["title"] == "Výsledky"

    sharing = accounts.request_sharing(subject, coach, by=coach)
    steps, nxt = _steps(client.get(url))
    assert nxt["title"] == "Sdílení s trenérem" and nxt["count"] == 1
    assert nxt["url"].endswith("#sdileni") and nxt["button"] == "Rozhodnout"
    assert 'id="sdileni"' in client.get(reverse("portal_consents", args=[subject.pk])).content.decode()

    accounts.confirm_sharing(sharing, by=athlete)
    steps, nxt = _steps(client.get(url))
    assert steps["Sdílení s trenérem"]["done"] and "aktivní" in steps["Sdílení s trenérem"]["text"]

    TestSession.objects.create(organization=org, subject=subject, date=timezone.localdate())
    steps, nxt = _steps(client.get(url))
    assert nxt["title"] == "Dotazník" and nxt["button"] == "Vyplnit RPE"
    assert nxt["url"] == reverse("portal_questionnaire", args=[subject.pk])
    assert "Co je na řadě" in client.get(url).content.decode()


def test_portal_trenera_vede_kroky(org):
    coach = User.objects.create(username="trener", organization=org, role=Role.COACH)
    subject = Subject.objects.create(organization=org, code="FTVS-0001")
    athlete = User.objects.create(username="sportovec", organization=org, role=Role.ATHLETE)
    SubjectIdentity.objects.create(subject=subject, user=athlete)
    client = Client()
    client.force_login(coach)

    steps, nxt = _steps(client.get(reverse("coach_home")))
    assert list(steps) == ["Žádost o sdílení", "Potvrzení sportovcem", "Přehled týmu"]
    assert nxt["title"] == "Žádost o sdílení" and nxt["url"] == "#zadost"

    sharing = accounts.request_sharing(subject, coach, by=coach)
    steps, nxt = _steps(client.get(reverse("coach_home")))
    assert steps["Žádost o sdílení"]["done"]
    assert nxt["title"] == "Potvrzení sportovcem" and nxt["count"] == 1

    accounts.confirm_sharing(sharing, by=athlete)
    assert Sharing.objects.get(pk=sharing.pk).status == Sharing.Status.ACTIVE
    steps, nxt = _steps(client.get(reverse("coach_home")))
    assert steps["Potvrzení sportovcem"]["done"] and nxt["title"] == "Přehled týmu"
