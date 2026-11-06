"""Kroky testovacího dne a zprávy – fáze 2 průvodců."""

import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import (
    MetricDef,
    Protocol,
    ProtocolMetric,
    Question,
    Questionnaire,
    TestBattery,
    TestFamily,
)
from apps.core.models import Organization, Role, User
from apps.measurements import questionnaires
from apps.measurements.models import (
    Measurement,
    ProtocolRun,
    QuestionnaireResponse,
    TestSession,
    Trial,
)
from apps.reports import services as report_services
from apps.reports.models import Audience, Report
from apps.subjects.models import Consent, Sport, Subject


@pytest.fixture
def org(db):
    call_command("seed_roles", verbosity=0)
    return Organization.objects.create(name="FTVS", short_name="ftvs")


def _user(org, role, username):
    user = User.objects.create(username=username, organization=org, role=role)
    client = Client()
    client.force_login(user)
    return user, client


def _protocol(org, code, *, rpe=False):
    protocol = Protocol.objects.create(organization=org, code=code, name=code.upper(),
                                       family=TestFamily.FORCE_PLATE, rpe_after=rpe)
    metric = MetricDef.objects.create(organization=org, code=f"{code}_m", name=f"Ukazatel {code}",
                                      family=TestFamily.FORCE_PLATE, unit="cm", mdc=1.0,
                                      trial_cv_limit=10)
    ProtocolMetric.objects.create(protocol=protocol, metric=metric, is_primary=True)
    return protocol, metric


def _measure(run, metric, *values):
    for n, value in enumerate(values, start=1):
        trial = Trial.objects.create(protocol_run=run, number=n)
        Measurement.objects.create(trial=trial, metric=metric, value=value)


@pytest.fixture
def den(org):
    """Florbal s baterií CMJ (s RPE) + IMTP, sportovec a dnešní testovací den jen s CMJ."""
    sport = Sport.objects.create(organization=org, name="Florbal", code="florbal")
    cmj, cmj_m = _protocol(org, "cmj", rpe=True)
    imtp, imtp_m = _protocol(org, "imtp")
    battery = TestBattery.objects.create(organization=org, sport=sport)
    battery.items.create(protocol=cmj, order=1)
    battery.items.create(protocol=imtp, order=2)
    subject = Subject.objects.create(organization=org, code="FTVS-0001", sport=sport)
    session = TestSession.objects.create(organization=org, subject=subject, date=timezone.localdate())
    run = ProtocolRun.objects.create(session=session, protocol=cmj)
    rpe = Questionnaire.objects.create(organization=None, code=questionnaires.RPE, name="RPE")
    Question.objects.create(questionnaire=rpe, code="rpe", text="RPE", order=1)
    return {"sport": sport, "cmj": cmj, "cmj_m": cmj_m, "imtp": imtp, "imtp_m": imtp_m,
            "subject": subject, "session": session, "run": run, "rpe": rpe}


def _steps(client, session):
    page = client.get(reverse("session_detail", args=[session.pk]))
    assert page.status_code == 200
    return {s["title"]: s for s in page.context["steps"]}, page.context["next_step"], page


def test_testovaci_den_vede_kroky(org, den):
    lab, client = _user(org, Role.LAB, "laborant")
    session, run = den["session"], den["run"]

    steps, nxt, page = _steps(client, session)
    assert list(steps) == ["Testy podle baterie", "Prostředí a únava", "Hodnoty", "RPE", "Kontrola", "Zpráva",
                           "Doporučení z minula"]
    assert nxt["title"] == "Testy podle baterie" and "chybí IMTP" in nxt["text"]
    assert "Postup dne" in page.content.decode() and 'id="nova-zprava"' in page.content.decode()
    assert steps["Prostředí a únava"]["optional"] and not steps["RPE"]["optional"]

    imtp_run = ProtocolRun.objects.create(session=session, protocol=den["imtp"])
    steps, nxt, _ = _steps(client, session)
    assert steps["Testy podle baterie"]["done"]
    assert nxt["title"] == "Hodnoty" and nxt["count"] == 2
    assert nxt["url"] == reverse("run_entry", args=[run.pk])  # první v pořadí baterie

    _measure(run, den["cmj_m"], 30, 31, 30.5)
    steps, nxt, _ = _steps(client, session)
    assert nxt["title"] == "Hodnoty" and nxt["url"] == reverse("run_entry", args=[imtp_run.pk])

    _measure(imtp_run, den["imtp_m"], 2000, 2050, 1990)
    steps, nxt, _ = _steps(client, session)
    assert steps["Hodnoty"]["done"] and steps["Kontrola"]["done"]
    assert nxt["title"] == "RPE" and "CMJ" in nxt["text"] and nxt["url"] == "#dotazniky"

    question = den["rpe"].questions.get()
    questionnaires.save(session, den["rpe"], {question: 7}, run=run,
                        source=QuestionnaireResponse.Source.OPERATOR)
    steps, nxt, _ = _steps(client, session)
    assert steps["RPE"]["done"] and nxt["title"] == "Zpráva"
    assert nxt["url"] == "#nova-zprava" and nxt["button"] == "Vytvořit zprávu"

    report = report_services.build_draft(session, user=lab, audience=Audience.ATHLETE)
    steps, nxt, _ = _steps(client, session)
    assert nxt["title"] == "Zpráva" and nxt["url"] == reverse("report_detail", args=[report.pk])
    report_services.release(report, user=lab)
    steps, nxt, _ = _steps(client, session)
    assert steps["Zpráva"]["done"] and nxt["title"] == "Prostředí a únava"  # jen volitelné zbývá

    session.temperature_c = 21
    session.save()
    steps, nxt, page = _steps(client, session)
    assert nxt is None and "vše hotovo" in page.content.decode()


def test_testovaci_den_kontrola_nestabilnich_pokusu(org, den):
    _, client = _user(org, Role.LAB, "laborant")
    session, run = den["session"], den["run"]
    ProtocolRun.objects.create(session=session, protocol=den["imtp"])
    _measure(run, den["cmj_m"], 10, 40, 25)
    steps, nxt, page = _steps(client, session)
    assert not steps["Kontrola"]["done"] and "liší víc" in steps["Kontrola"]["text"]
    assert steps["Kontrola"]["url"] == "#pokusy" and 'id="pokusy"' in page.content.decode()


def test_zprava_vede_kroky(org, den):
    lab, client = _user(org, Role.LAB, "laborant")
    session, run = den["session"], den["run"]
    _measure(run, den["cmj_m"], 30, 31, 30.5)
    report = report_services.build_draft(session, user=lab, audience=Audience.CLINICIAN)
    url = reverse("report_detail", args=[report.pk])

    page = client.get(url)
    steps = {s["title"]: s for s in page.context["steps"]}
    assert list(steps) == ["Koncept", "Souhrn", "Doporučení", "Kontrola", "Vydání", "Předání"]
    assert steps["Koncept"]["done"] and steps["Souhrn"]["done"] and steps["Doporučení"]["done"]
    assert not steps["Kontrola"]["done"] and "souhlas" in steps["Kontrola"]["text"]
    assert page.context["next_step"]["title"] == "Kontrola"
    assert steps["Vydání"]["button"] == ""  # bez souhlasu zprávu pro lékaře vydat nejde
    assert "Postup zprávy" in page.content.decode()

    Consent.objects.create(subject=den["subject"], scope=Consent.Scope.REPORT_HANDOVER,
                           granted_on=timezone.localdate())
    page = client.get(url)
    steps = {s["title"]: s for s in page.context["steps"]}
    assert steps["Kontrola"]["done"] and page.context["next_step"]["title"] == "Vydání"
    assert steps["Vydání"]["button"] == "Vydat" and steps["Vydání"]["url"] == "#vydat"
    assert not steps["Předání"]["optional"]

    # číslo bez opory ve výsledcích blokuje jen jako upozornění
    client.post(url, {"summary": "Výskok 99 cm je skvělý.", "custom_note": ""})
    page = client.get(url)
    steps = {s["title"]: s for s in page.context["steps"]}
    assert not steps["Kontrola"]["done"] and "99" in steps["Kontrola"]["text"]
    assert steps["Vydání"]["button"] == "Vydat"

    # návrh od modelu čeká na kontrolu
    Report.objects.filter(pk=report.pk).update(note_pending_review=True, summary="Souhrn bez čísel.")
    page = client.get(url)
    steps = {s["title"]: s for s in page.context["steps"]}
    assert not steps["Doporučení"]["done"] and steps["Vydání"]["button"] == ""
    client.post(url, {"summary": "Souhrn bez čísel.", "custom_note": "Doporučuji odpočinek."})

    report.refresh_from_db()
    report_services.release(report, user=lab)
    page = client.get(url)
    steps = {s["title"]: s for s in page.context["steps"]}
    assert steps["Vydání"]["done"] and page.context["next_step"]["title"] == "Předání"
    assert steps["Předání"]["button"] == "Zaznamenat předání"
    assert 'id="predani"' in page.content.decode() and 'id="vydat"' not in page.content.decode()

    report_services.deliver(report, recipient="AKESO", channel="handover", user=lab)
    page = client.get(url)
    steps = {s["title"]: s for s in page.context["steps"]}
    assert steps["Předání"]["done"] and "AKESO" in steps["Předání"]["text"]
    assert page.context["next_step"] is None


def test_zprava_pro_sportovce_ma_predani_volitelne(org, den):
    lab, client = _user(org, Role.LAB, "laborant")
    _measure(den["run"], den["cmj_m"], 30, 31, 30.5)
    report = report_services.build_draft(den["session"], user=lab, audience=Audience.ATHLETE)
    report_services.release(report, user=lab)
    page = client.get(reverse("report_detail", args=[report.pk]))
    steps = {s["title"]: s for s in page.context["steps"]}
    assert steps["Předání"]["optional"] and page.context["next_step"]["title"] == "Předání"
    assert "vše hotovo" not in page.content.decode()
