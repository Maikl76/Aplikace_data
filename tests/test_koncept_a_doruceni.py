"""
Dávka 6: koncept zprávy vzniká sám, jakmile mají všechny testy dne hodnoty
(u přístroje i z importu), pro trenéra při sdílení, jinak pro sportovce;
vypíná se u pracoviště. Vydání = doručení: upozornění e‑mailem účtům
v portálu, znovu na vyžádání; laboratoř vidí, kdy byla zpráva v portálu
poprvé otevřena.
"""

from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from django.core import mail
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import MetricDef, Protocol, ProtocolMetric, TestBattery, TestFamily
from apps.core.models import Organization, Role, User
from apps.measurements.models import Measurement, ProtocolRun, TestSession, Trial
from apps.reports import auto as report_auto
from apps.reports import notify
from apps.reports import services as report_services
from apps.reports.models import Audience, Report
from apps.subjects.models import Guardian, Sharing, Sport, Subject, SubjectIdentity


@pytest.fixture
def org(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    return Organization.objects.create(name="FTVS", short_name="ftvs")


def _user(org, role, username, email=""):
    user = User.objects.create(username=username, organization=org, role=role, email=email,
                               is_staff=role == Role.ADMIN)
    client = Client()
    client.force_login(user)
    return user, client


def _protocol(org, code):
    protocol = Protocol.objects.create(organization=org, code=code, name=code.upper(),
                                       family=TestFamily.FORCE_PLATE)
    metric = MetricDef.objects.create(organization=org, code=f"{code}_m", name=f"Ukazatel {code}",
                                      family=TestFamily.FORCE_PLATE, unit="cm", mdc=1.0)
    ProtocolMetric.objects.create(protocol=protocol, metric=metric, is_primary=True)
    return protocol, metric


def _measure(run, metric, *values):
    for n, value in enumerate(values, start=1):
        trial = Trial.objects.create(protocol_run=run, number=n)
        Measurement.objects.create(trial=trial, metric=metric, value=value)


def _day(org):
    """Florbal s baterií CMJ + IMTP, sportovkyně a dnešní den s oběma testy bez hodnot."""
    sport = Sport.objects.create(organization=org, name="Florbal", code="florbal")
    cmj, cmj_m = _protocol(org, "cmj")
    imtp, imtp_m = _protocol(org, "imtp")
    battery = TestBattery.objects.create(organization=org, sport=sport)
    battery.items.create(protocol=cmj, order=1)
    battery.items.create(protocol=imtp, order=2)
    subject = Subject.objects.create(organization=org, code="FTVS-0001", sport=sport, sex="F")
    session = TestSession.objects.create(organization=org, subject=subject,
                                         date=timezone.localdate())
    return {"sport": sport, "cmj": cmj, "cmj_m": cmj_m, "imtp": imtp, "imtp_m": imtp_m,
            "subject": subject, "session": session,
            "run_cmj": ProtocolRun.objects.create(session=session, protocol=cmj),
            "run_imtp": ProtocolRun.objects.create(session=session, protocol=imtp)}


def _account(subject, email="jana@example.cz"):
    identity = SubjectIdentity.objects.create(subject=subject)
    identity.set_names("Jana", "Nová")
    athlete = User.objects.create(username=email, email=email, organization=subject.organization,
                                  role=Role.ATHLETE)
    identity.user = athlete
    identity.save()
    return identity, athlete


def test_koncept_vznikne_sam_po_dokonceni_dne(org):
    lab, client = _user(org, Role.LAB, "laborant")
    d = _day(org)
    cmj_pm = ProtocolMetric.objects.get(protocol=d["cmj"])
    imtp_pm = ProtocolMetric.objects.get(protocol=d["imtp"])
    detail = reverse("session_detail", args=[d["session"].pk])
    assert "Koncept vzniká sám" in client.get(detail).content.decode()

    client.post(reverse("run_entry", args=[d["run_cmj"].pk]), {f"v|{cmj_pm.pk}|||||1": "30"})
    assert not Report.objects.exists()   # IMTP ještě bez hodnot
    text = client.post(reverse("run_entry", args=[d["run_imtp"].pk]),
                       {f"v|{imtp_pm.pk}|||||1": "2000"}, follow=True).content.decode()
    report = Report.objects.get()
    assert report.auto_created and report.status == Report.Status.DRAFT
    assert report.audience == Audience.ATHLETE and report.session == d["session"]
    assert "Koncept zprávy FT-" in text and "připravený ke kontrole" in text
    # další hodnoty další koncept nezaloží; krok Zpráva vede ke konceptu
    client.post(reverse("run_entry", args=[d["run_cmj"].pk]), {f"v|{cmj_pm.pk}|||||2": "31"})
    assert Report.objects.count() == 1
    steps = {s["title"]: s for s in client.get(detail).context["steps"]}
    assert "1 konceptů čeká" in steps["Zpráva"]["text"]
    assert "koncept vznikl sám" in client.get(reverse("report_detail", args=[report.pk])).content.decode()

    # sdílení s trenérem = koncept pro trenéra; bez hodnot nic
    coach = User.objects.create(username="trener", organization=org, role=Role.COACH)
    Sharing.objects.create(subject=d["subject"], coach=coach, status=Sharing.Status.ACTIVE)
    older = TestSession.objects.create(organization=org, subject=d["subject"],
                                       date=timezone.localdate() - timedelta(days=30))
    run = ProtocolRun.objects.create(session=older, protocol=d["cmj"])
    assert report_auto.ensure_draft(older, user=lab) is None
    _measure(run, d["cmj_m"], 29)
    draft = report_auto.ensure_draft(older, user=lab)
    assert draft is not None and draft.audience == Audience.COACH and draft.auto_created
    assert report_auto.ensure_draft(older, user=lab) is None

    # vypnutí u pracoviště: nic nevzniká, poznámka zmizí
    _, admin = _user(org, Role.ADMIN, "spravce")
    page = admin.get(reverse("workplace_org"))
    assert 'name="auto_draft"' in page.content.decode() and "checked" in page.content.decode()
    admin.post(reverse("workplace_org"), {"nazev": org.name})
    org.refresh_from_db()
    assert not org.auto_draft
    another = TestSession.objects.create(organization=org, subject=d["subject"],
                                         date=timezone.localdate() - timedelta(days=60))
    _measure(ProtocolRun.objects.create(session=another, protocol=d["cmj"]), d["cmj_m"], 28)
    assert report_auto.ensure_draft(another, user=lab) is None
    assert "Koncept vzniká sám" not in client.get(detail).content.decode()
    admin.post(reverse("workplace_org"), {"nazev": org.name, "auto_draft": "on"})
    org.refresh_from_db()
    assert org.auto_draft


def test_vydani_upozorni_ucty_a_otevreni_v_portalu(org, settings):
    from apps.core import access

    settings.EMAIL_HOST = "smtp.test"
    lab, client = _user(org, Role.LAB, "laborant")
    access.grant(lab, reports_release=True)   # vydávání zapnul správce (jinak vydává metodik)
    d = _day(org)
    _measure(d["run_cmj"], d["cmj_m"], 30)
    identity, athlete = _account(d["subject"])
    guardian = User.objects.create(username="rodic@example.cz", email="rodic@example.cz",
                                   organization=org, role=Role.ATHLETE)
    Guardian.objects.create(identity=identity, user=guardian)

    report = report_services.build_draft(d["session"], user=lab, audience=Audience.ATHLETE)
    assert notify.notice(report) == ""   # koncept nic neoznamuje
    text = client.post(reverse("report_release", args=[report.pk]), follow=True).content.decode()
    report.refresh_from_db()
    assert report.status == Report.Status.RELEASED and report.notified_count == 2 and report.notified_at
    assert len(mail.outbox) == 1 and sorted(mail.outbox[0].to) == ["jana@example.cz", "rodic@example.cz"]
    body = mail.outbox[0].body
    assert f"http://testserver/muj/{d['subject'].pk}/zprava/{report.pk}/" in body
    assert "Jana" not in body and "FTVS-0001" not in body and "neobsahuje žádné výsledky" in body
    assert "Upozornění odešlo e‑mailem (2 adresy)" in text
    assert "V portálu zatím neotevřeno" in text and "upozornit e‑mailem znovu" in text
    assert "ne</span>" in client.get(reverse("report_list")).content.decode()

    # sportovkyně zprávu otevře; laboratoř to vidí u zprávy, v seznamu i na kartě
    athlete_client = Client()
    athlete_client.force_login(athlete)
    assert athlete_client.get(reverse("portal_report", args=[d["subject"].pk, report.pk])).status_code == 200
    report.refresh_from_db()
    assert report.opened_at and report.opened_by == athlete
    athlete_client.get(reverse("portal_report", args=[d["subject"].pk, report.pk]))
    assert Report.objects.get(pk=report.pk).opened_by == athlete   # první otevření zůstává
    assert "Otevřeno v portálu" in client.get(reverse("report_detail", args=[report.pk])).content.decode()
    assert "otevřeno" in client.get(reverse("subject_detail", args=[d["subject"].pk])).content.decode()
    assert timezone.localtime(report.opened_at).strftime("%d.%m.%Y") in client.get(reverse("report_list")).content.decode()
    text = client.post(reverse("report_notify", args=[report.pk]), follow=True).content.decode()
    assert len(mail.outbox) == 2 and "Upozornění odešlo (2 adresy)" in text

    # zpráva pro trenéra jde jen trenérům se sdílením, s odkazem do portálu trenéra
    coach = User.objects.create(username="trener", organization=org, role=Role.COACH,
                                email="trener@example.cz")
    Sharing.objects.create(subject=d["subject"], coach=coach, status=Sharing.Status.ACTIVE)
    coach_report = report_services.build_draft(d["session"], user=lab, audience=Audience.COACH)
    client.post(reverse("report_release", args=[coach_report.pk]))
    assert mail.outbox[-1].to == ["trener@example.cz"] and "/trener/" in mail.outbox[-1].body
    coach_client = Client()
    coach_client.force_login(coach)
    coach_client.get(reverse("coach_report", args=[d["subject"].pk, coach_report.pk]))
    assert Report.objects.get(pk=coach_report.pk).opened_by == coach

    # bez účtu v portálu upozornění neodejde a laboratoř ví proč; bez pošty také
    nobody = Subject.objects.create(organization=org, code="FTVS-0002", sport=d["sport"])
    session = TestSession.objects.create(organization=org, subject=nobody, date=timezone.localdate())
    _measure(ProtocolRun.objects.create(session=session, protocol=d["cmj"]), d["cmj_m"], 25)
    lonely = report_services.build_draft(session, user=lab, audience=Audience.ATHLETE)
    text = client.post(reverse("report_release", args=[lonely.pk]), follow=True).content.decode()
    assert "nemá účet v portálu" in text and len(mail.outbox) == 3
    text = client.post(reverse("report_notify", args=[lonely.pk]), follow=True).content.decode()
    assert "nemá účet v portálu" in text and len(mail.outbox) == 3
    settings.EMAIL_HOST = ""
    lonely.refresh_from_db()
    assert "poštovní server není nastavený" in notify.notice(lonely)
