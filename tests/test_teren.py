"""Terénní zadávání: pravidlo pokusů, čas min:s, RPE (operátor i sportovec přes QR), prostředí."""

import re
from datetime import date

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.catalog.models import BatteryItem, MetricDef, Protocol, TestBattery
from apps.core.models import Organization, Role, User
from apps.measurements import questionnaires
from apps.measurements.forms import parse_value
from apps.measurements.models import (
    Measurement,
    ProtocolRun,
    QuestionnaireResponse,
    TestSession,
    Trial,
)
from apps.subjects.models import Sport, Subject


@pytest.fixture
def lab(db, client):
    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    user = User.objects.create(username="lab", organization=org, role=Role.LAB)
    sport = Sport.objects.create(organization=org, code="hokej", name="Lední hokej")
    hrac = Subject.objects.create(organization=org, code="FTVS-0001", sport=sport)
    client.force_login(user)
    return org, hrac, client


def run_for(subject, code, day=date(2026, 9, 1)):
    session, _ = TestSession.objects.get_or_create(organization=subject.organization,
                                                   subject=subject, date=day)
    run, _ = ProtocolRun.objects.get_or_create(session=session,
                                               protocol=Protocol.objects.get(code=code))
    return run


def test_cas_jde_psat_i_jako_minuty():
    assert parse_value("4,52") == 4.52
    assert parse_value("1:23,45") == pytest.approx(83.45)
    assert parse_value("6:05.2") == pytest.approx(365.2)
    assert parse_value("1:75") is None          # 75 s není platný čas
    assert parse_value("") is None
    assert parse_value("abc") is None


def test_hodnota_dne_podle_pravidla(lab):
    sprint = MetricDef.objects.get(code="sprint_30m")
    assert sprint.trial_rule == MetricDef.TrialRule.BEST
    assert sprint.day_value([4.61, 4.52, 4.58]) == 4.52          # nižší čas je lepší
    grip = MetricDef.objects.get(code="grip_strength")
    assert grip.day_value([50.0, 54.0]) == 54.0
    cmj = MetricDef.objects.get(code="cmj_height")
    assert cmj.day_value([30.0, 32.0]) == 31.0                    # výchozí průměr
    cmj.trial_rule = MetricDef.TrialRule.LAST
    assert cmj.day_value([30.0, 32.0, 29.0]) == 29.0


def test_sprint_ve_zprave_a_trendu_bere_nejlepsi_pokus(lab):
    from apps.analytics.queries import primary_metric_series
    from apps.reports.results import protocol_results

    _, hrac, client = lab
    run = run_for(hrac, "sprint30")
    client.post(f"/mereni/provedeni/{run.pk}/", {
        f"v|{pm.pk}|B||||{n}": value
        for pm in run.protocol.protocol_metrics.filter(metric__code="sprint_30m")
        for n, value in [(1, "4,61"), (2, "4,52"), (3, "4,58")]})

    block = protocol_results(run.session)[0]
    row = next(r for r in block["rows"] if r["metric"].code == "sprint_30m")
    assert row["value_txt"] == "4,52"
    series = primary_metric_series(hrac, limit_metrics=10)
    assert next(s for s in series if s["metric"].code == "sprint_30m")["points"][0][1] == 4.52


def test_zadani_casu_stopkami_rpe_a_dalsi_test(lab):
    org, hrac, client = lab
    # Pořadí testů podle baterie: nejdřív Wingate, pak sprint.
    battery = TestBattery.objects.create(organization=org, sport=hrac.sport)
    for order, code in enumerate(["wingate", "sprint30"], start=1):
        BatteryItem.objects.create(battery=battery, protocol=Protocol.objects.get(code=code),
                                   order=order)
    wingate = run_for(hrac, "wingate")
    sprint = run_for(hrac, "sprint30")
    html = client.get(f"/mereni/provedeni/{sprint.pk}/").content.decode()
    assert "stopky-tlacitko" in html and "Pauza 3:00" in html
    assert 'name="q_rpe"' not in html                      # sprint RPE nenabízí

    html = client.get(f"/mereni/provedeni/{wingate.pk}/").content.decode()
    assert 'name="q_rpe"' in html and "velmi těžké" in html
    assert "Uložit a další: Sprint 30 m" in html

    pmax = wingate.protocol.protocol_metrics.get(metric__code="wingate_pmax")
    response = client.post(f"/mereni/provedeni/{wingate.pk}/",
                           {f"v|{pmax.pk}|B||||1": "1200", "q_rpe": "9", "dalsi": "1"})
    assert response.url == f"/mereni/provedeni/{sprint.pk}/"
    answer = questionnaires.rpe_for_run(wingate)
    assert answer.value == 9 and answer.response.source == "operator"

    # Opravené RPE přepíše původní, nevznikne druhé.
    client.post(f"/mereni/provedeni/{wingate.pk}/", {"q_rpe": "8"})
    assert QuestionnaireResponse.objects.count() == 1
    assert questionnaires.rpe_for_run(wingate).value == 8


def test_sportovec_vyplni_rpe_pres_odkaz_bez_prihlaseni(lab, settings):
    from django.test import Client

    settings.ALLOWED_HOSTS = ["*"]
    _, hrac, lab_client = lab
    wingate = run_for(hrac, "wingate")
    qr = lab_client.get(f"/mereni/{wingate.session_id}/dotaznik/qr/?beh={wingate.pk}",
                        HTTP_HOST="lab.ftvs.cz").content.decode()
    assert "<svg" in qr and "127.0.0.1" not in qr
    url = re.search(r'href="(http://lab\.ftvs\.cz/d/[^"]+)"', qr).group(1)
    path = url.replace("http://lab.ftvs.cz", "")

    phone = Client()                                       # nepřihlášený telefon
    page = phone.get(path).content.decode()
    assert "Wingate test 30 s" in page and "FTVS-0001" not in page
    phone.post(path, {"q_rpe": "10"})
    answer = questionnaires.rpe_for_run(wingate)
    assert answer.value == 10 and answer.response.source == "sportovec"

    assert phone.get("/d/podvrzeny-odkaz/").status_code == 410


def test_rpe_a_prostredi_ve_zprave_a_pro_model(lab):
    from apps.reports import facts, services
    from apps.reports.models import Report

    _, hrac, client = lab
    wingate = run_for(hrac, "wingate")
    session = wingate.session
    pmax = wingate.protocol.protocol_metrics.get(metric__code="wingate_pmax")
    client.post(f"/mereni/provedeni/{wingate.pk}/", {f"v|{pmax.pk}|B||||1": "1200"})
    client.post(f"/mereni/{session.pk}/prostredi/", {"temperature_c": "22,5",
                                                     "humidity_pct": "48"})
    client.post(f"/mereni/{session.pk}/dotaznik/", {"dotaznik": "rpe", "beh": wingate.pk,
                                                    "q_rpe": "9"})
    client.post(f"/mereni/{session.pk}/dotaznik/", {"dotaznik": "rpe", "q_rpe": "6"})
    session.refresh_from_db()
    assert session.temperature_c == 22.5 and session.humidity_pct == 48

    detail = client.get(f"/mereni/{session.pk}/").content.decode()
    assert "celý testovací den" in detail and "22,5 °C" in detail

    data = facts.build(session, [], [])
    assert data["podminky"] == {"teplota_c": 22.5, "vlhkost_procent": 48}
    assert {r["po_testu"] for r in data["rpe"]} == {"Wingate test 30 s", "celý testovací den"}

    context = services.report_context(Report(subject=hrac, session=session))
    assert ("Prostředí", "22,5 °C, vlhkost 48 %") in context["conditions"]
    assert any(label.startswith("RPE") and value.startswith("6/10")
               for label, value in context["conditions"])
    block = next(b for b in context["results"] if b["protocol"].code == "wingate")
    assert block["rpe_txt"] == "RPE 9/10"
    # Test bez naměřených hodnot (jen naplánovaný) se do zprávy nedostane.
    run_for(hrac, "sprint30")
    codes = [b["protocol"].code for b in services.report_context(
        Report(subject=hrac, session=session))["results"]]
    assert "sprint30" not in codes


def test_qr_karta_vede_na_dnesni_testovani(lab):
    org, hrac, client = lab
    battery = TestBattery.objects.create(organization=org, sport=hrac.sport)
    BatteryItem.objects.create(battery=battery, protocol=Protocol.objects.get(code="cmj"),
                               order=1)
    karta = client.get(f"/sportovci/{hrac.pk}/qr/").content.decode()
    assert "<svg" in karta and "FTVS-0001" in karta
    assert "<svg" in client.get(f"/sportovci/qr-karty/?baterie={battery.pk}").content.decode()

    confirm = client.get(f"/sportovci/{hrac.pk}/dnes/").content.decode()
    assert "Countermovement jump" in confirm
    response = client.post(f"/sportovci/{hrac.pk}/dnes/")
    session = TestSession.objects.get(subject=hrac, date=timezone.localdate())
    assert response.url == f"/mereni/{session.pk}/"
    assert [r.protocol.code for r in session.protocol_runs.all()] == ["cmj"]
    # Podruhé už rovnou otevře existující den.
    assert client.get(f"/sportovci/{hrac.pk}/dnes/").url == f"/mereni/{session.pk}/"


def test_katalog_prenese_dotazniky(lab):
    from apps.catalog.models import Questionnaire
    from apps.catalog.transfer import export_catalog, import_catalog

    data = export_catalog()
    rpe = next(q for q in data["dotazniky"] if q["code"] == "rpe")
    assert rpe["otazky"][0]["anchors"]["10"] == "maximální"
    Questionnaire.objects.filter(code="rpe").update(name="změněno")
    import_catalog(data)
    assert Questionnaire.objects.get(code="rpe").name.startswith("RPE")


def test_mereni_bez_rpe_nic_nezaklada(lab):
    _, hrac, client = lab
    run = run_for(hrac, "cmj")
    pm = run.protocol.protocol_metrics.get(metric__code="cmj_height")
    client.post(f"/mereni/provedeni/{run.pk}/", {f"v|{pm.pk}|B||||1": "35", "q_rpe": "5"})
    assert not QuestionnaireResponse.objects.exists()
    assert Measurement.objects.filter(trial__in=Trial.objects.filter(protocol_run=run)).count() == 1
