"""
Dávka 5: plán opakování měření – interval u baterie nebo u sportovce,
konkrétní termín, naplánovaný den; Kdo je na řadě na Přehledu a v seznamu;
karta sportovce s plánem a ruční připomínkou; připomínky e‑mailem jednou
denně z Přehledu a z příkazu; portál sportovce a trenéra.
"""

from datetime import date, timedelta
from io import StringIO

import pytest
from cryptography.fernet import Fernet
from django.core import mail
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import MetricDef, Protocol, TestBattery, TestFamily
from apps.core.models import Organization, Role, User
from apps.measurements.models import Measurement, ProtocolRun, TestSession, Trial
from apps.subjects import crypto, retest
from apps.subjects.models import Guardian, RetestReminder, Sharing, Sport, Subject, SubjectIdentity


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


def _catalog(org):
    protocol = Protocol.objects.create(organization=org, code="cmj", name="CMJ",
                                       family=TestFamily.FORCE_PLATE)
    metric = MetricDef.objects.create(organization=org, code="cmj_vyska", name="Výška výskoku",
                                      family=TestFamily.FORCE_PLATE, unit="cm")
    return protocol, metric


def _measured(org, subject, protocol, metric, day, value=30):
    session = TestSession.objects.create(organization=org, subject=subject, date=day)
    run = ProtocolRun.objects.create(session=session, protocol=protocol)
    trial = Trial.objects.create(protocol_run=run, number=1)
    Measurement.objects.create(trial=trial, metric=metric, value=value)
    return session


def test_termin_z_baterie_vlastniho_intervalu_a_zapsaneho_data(org):
    sport = Sport.objects.create(organization=org, name="Florbal", code="florbal")
    TestBattery.objects.create(organization=org, sport=sport, retest_weeks=12)
    TestBattery.objects.create(organization=org, sport=sport, category="dorost")
    protocol, metric = _catalog(org)
    subject = Subject.objects.create(organization=org, code="FTVS-0001", sport=sport)
    today = date(2026, 6, 1)
    plan = retest.plan_for(subject, today=today)
    assert plan.status == "none" and "po prvním měření" in plan.text() and plan.weeks == 12

    _measured(org, subject, protocol, metric, date(2026, 3, 1))
    plan = retest.plan_for(subject, today=today)
    assert (plan.weeks, plan.source, plan.last_date) == (12, "baterie", date(2026, 3, 1))
    assert plan.due == date(2026, 5, 24) and plan.status == "overdue" and plan.days_left == -8
    assert plan.badge() == ("badge-bad", "prošlo o 8 dnů") and "Termín prošel o 8 dnů" in plan.text()
    # vlastní interval má přednost před baterií
    subject.retest_weeks = 16
    subject.save()
    plan = retest.plan_for(subject, today=today)
    assert plan.due == date(2026, 6, 21) and plan.status == "soon" and plan.source == "sportovec"
    assert plan.badge() == ("badge-warn", "do 20 dnů") and "zbývá 20 dnů" in plan.text()
    # zapsaný termín má přednost; po měření po něm přestane platit a počítá se interval
    subject.next_test_date = date(2026, 9, 1)
    subject.save()
    plan = retest.plan_for(subject, today=today)
    assert plan.due == date(2026, 9, 1) and plan.explicit and plan.status == "ok"
    assert plan.badge() == ("badge", "do 01.09.2026") and "zapsaný termín" in plan.text()
    _measured(org, subject, protocol, metric, date(2026, 9, 5))
    plan = retest.plan_for(subject, today=date(2026, 9, 10))
    assert not plan.explicit and plan.due == date(2026, 12, 26) and plan.status == "ok"
    # naplánovaný den bez hodnot = domluveno
    TestSession.objects.create(organization=org, subject=subject, date=date(2026, 9, 20))
    plan = retest.plan_for(subject, today=date(2026, 9, 10))
    assert plan.status == "planned" and plan.badge() == ("badge-good", "naplánováno 20.09.")
    assert not plan.is_due
    # baterie kategorie bez intervalu = bez plánu (stejný výběr baterie jako u testů)
    junior = Subject.objects.create(organization=org, code="FTVS-0002", sport=sport,
                                    category="Dorost")
    _measured(org, junior, protocol, metric, date(2026, 3, 1))
    assert retest.plan_for(junior, today=today).status == "none"


def test_karta_seznam_prehled_a_pripominky(org, settings):
    settings.EMAIL_HOST = "smtp.test"
    _, client = _user(org, Role.LAB, "laborant")
    _, researcher = _user(org, Role.RESEARCHER, "vyzkumnik")
    sport = Sport.objects.create(organization=org, name="Florbal", code="florbal")
    TestBattery.objects.create(organization=org, sport=sport, retest_weeks=12)
    protocol, metric = _catalog(org)
    subject = Subject.objects.create(organization=org, code="FTVS-0001", sport=sport)
    identity = SubjectIdentity.objects.create(subject=subject)
    identity.set_names("Jana", "Nová")
    identity.email_enc = crypto.encrypt("jana@example.cz")
    identity.save()
    guardian = User.objects.create(username="rodic@example.cz", email="rodic@example.cz",
                                   organization=org, role=Role.ATHLETE)
    Guardian.objects.create(identity=identity, user=guardian)
    today = timezone.localdate()
    _measured(org, subject, protocol, metric, today - timedelta(weeks=12) + timedelta(days=5))

    detail = reverse("subject_detail", args=[subject.pk])
    page = client.get(detail)
    text = page.content.decode()
    assert 'id="plan"' in text and "zbývá 5 dnů" in text and "Připomenout e‑mailem" in text
    assert "Plán opakování" in text
    steps = {s["title"]: s for s in page.context["steps"]}
    assert steps["Měření"]["done"] and "zbývá 5 dnů" in steps["Měření"]["text"]
    page = client.get(reverse("subject_list") + "?na_rade=1")
    assert page.context["due_count"] == 1 and [s.pk for s in page.context["subjects"]] == [subject.pk]
    assert "do 5 dnů" in page.content.decode()
    assert "Nikdo neodpovídá" not in page.content.decode()

    # Přehled: Kdo je na řadě, volitelný krok a denní kontrola, která připomínku rozešle
    page = client.get(reverse("dashboard"))
    text = page.content.decode()
    assert "Kdo je na řadě" in text and "Jana Nová" in text and "do 5 dnů" in text
    steps = {s["title"]: s for s in page.context["dnes"]}
    assert not steps["Na řadě"]["done"] and steps["Na řadě"]["count"] == 1 and steps["Na řadě"]["optional"]
    assert [p.subject for p in page.context["pripominky_dnes"]["sent"]] == [subject]
    assert len(mail.outbox) == 1 and sorted(mail.outbox[0].to) == ["jana@example.cz", "rodic@example.cz"]
    assert "termín do" in mail.outbox[0].subject and "http://testserver/objednavka/" in mail.outbox[0].body
    assert "Jana" not in mail.outbox[0].body and "FTVS-0001" not in mail.outbox[0].body
    reminder = RetestReminder.objects.get()
    assert reminder.subject == subject and reminder.sent_by is None and reminder.recipients == 2
    org.refresh_from_db()
    assert org.reminders_checked_on == today
    client.get(reverse("dashboard"))
    assert len(mail.outbox) == 1   # podruhé týž den nic
    assert retest.run_due(org)["sent"] == [] and len(mail.outbox) == 1   # do 30 dnů znovu ne

    # ruční připomínka z karty (výzkumník ne), plán opakování
    url = reverse("subject_retest", args=[subject.pk])
    researcher.post(url, {"akce": "pripomenout"})
    assert len(mail.outbox) == 1
    text = client.post(url, {"akce": "pripomenout"}, follow=True).content.decode()
    assert "odešla (2 adresy)" in text and len(mail.outbox) == 2
    assert RetestReminder.objects.filter(manual=True, sent_by__username="laborant").count() == 1
    assert "Připomínky odeslány" in text
    client.post(url, {"rezim": "vlastni", "tydny": "20"})
    subject.refresh_from_db()
    assert subject.retest_weeks == 20 and subject.next_test_date is None
    client.post(url, {"rezim": "datum", "datum": (today + timedelta(days=60)).isoformat()})
    subject.refresh_from_db()
    assert subject.next_test_date == today + timedelta(days=60) and subject.retest_weeks == 20
    text = client.post(url, {"rezim": "vlastni", "tydny": "0"}, follow=True).content.decode()
    assert "1 až 104" in text
    client.post(url, {"rezim": "baterie"})
    subject.refresh_from_db()
    assert subject.retest_weeks is None and subject.next_test_date is None
    # naplánovaný den: bez tlačítka připomínky, mimo „na řadě“
    TestSession.objects.create(organization=org, subject=subject, date=today + timedelta(days=3))
    text = client.get(detail).content.decode()
    assert "naplánováno" in text and "Připomenout e‑mailem" not in text
    assert client.get(reverse("subject_list") + "?na_rade=1").context["due_count"] == 0
    assert client.get(reverse("dashboard")).context["na_rade"] == []


def test_portal_trener_baterie_a_prikaz(org, settings):
    settings.EMAIL_HOST = "smtp.test"
    _, client = _user(org, Role.ADMIN, "spravce")
    sport = Sport.objects.create(organization=org, name="Florbal", code="florbal")
    battery = TestBattery.objects.create(organization=org, sport=sport)
    # interval u baterie z karty baterie (HTMX vrátí kartu), chybný vstup se nahlásí
    resp = client.post(reverse("battery_interval", args=[battery.pk]), {"tydny": "8"},
                       HTTP_HX_REQUEST="true")
    battery.refresh_from_db()
    assert resp.status_code == 200 and battery.retest_weeks == 8
    assert "8 týdnů po posledním měření" in resp.content.decode()
    text = client.post(reverse("battery_interval", args=[battery.pk]), {"tydny": "500"},
                       follow=True).content.decode()
    battery.refresh_from_db()
    assert "1 až 104" in text and battery.retest_weeks == 8
    assert 'name="tydny"' in client.get(reverse("sport_list")).content.decode()

    protocol, metric = _catalog(org)
    subject = Subject.objects.create(organization=org, code="FTVS-0001", sport=sport)
    identity = SubjectIdentity.objects.create(subject=subject)
    identity.set_names("Jana", "Nová")
    athlete = User.objects.create(username="jana@example.cz", email="jana@example.cz",
                                  organization=org, role=Role.ATHLETE)
    identity.user = athlete
    identity.save()
    coach = User.objects.create(username="trener", organization=org, role=Role.COACH)
    Sharing.objects.create(subject=subject, coach=coach, status=Sharing.Status.ACTIVE)
    today = timezone.localdate()
    _measured(org, subject, protocol, metric, today - timedelta(weeks=9))   # týden po termínu

    athlete_client = Client()
    athlete_client.force_login(athlete)
    text = athlete_client.get(reverse("portal_subject", args=[subject.pk])).content.decode()
    assert 'id="pristi-mereni"' in text and "už prošel" in text and "Objednat se" in text
    coach_client = Client()
    coach_client.force_login(coach)
    assert "prošlo o 7 dnů" in coach_client.get(reverse("coach_home")).content.decode()

    # příkaz: jen vypsat, pak odeslat; opakované spuštění nic nepošle dvakrát
    out = StringIO()
    call_command("pripomenout_mereni", "--jen-vypsat", stdout=out)
    assert "FTVS-0001" in out.getvalue() and "1 adres" in out.getvalue() and not mail.outbox
    out = StringIO()
    call_command("pripomenout_mereni", stdout=out)
    assert "odesláno 1" in out.getvalue() and len(mail.outbox) == 1
    assert mail.outbox[0].to == ["jana@example.cz"] and "termín prošel" in mail.outbox[0].subject
    assert "domluvte s laboratoří" in mail.outbox[0].body   # bez PUBLIC_BASE_URL bez odkazu
    out = StringIO()
    call_command("pripomenout_mereni", stdout=out)
    assert "odesláno 0" in out.getvalue() and len(mail.outbox) == 1
    # bez poštovního serveru příkaz jen vysvětlí
    settings.EMAIL_HOST = ""
    out = StringIO()
    call_command("pripomenout_mereni", stdout=out)
    assert "není nastavený" in out.getvalue()
