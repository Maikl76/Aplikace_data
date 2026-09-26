"""Týmový přehled a sjednocené obrazovky (měření, import, zprávy)."""

from datetime import date

import pytest
from django.core.management import call_command

from apps.analytics.team import columns_for, team_table
from apps.catalog.models import BatteryItem, MetricDef, Protocol, TestBattery
from apps.core.models import Organization, Role, User
from apps.measurements.models import Measurement, ProtocolRun, TestSession, Trial
from apps.subjects.models import Sport, Subject


@pytest.fixture
def tym(db, client):
    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    user = User.objects.create(username="lab", organization=org, role=Role.LAB)
    hokej = Sport.objects.create(organization=org, code="hokej", name="Lední hokej")
    battery = TestBattery.objects.create(organization=org, sport=hokej)
    for order, code in enumerate(["cmj", "sls"], start=1):
        BatteryItem.objects.create(battery=battery, protocol=Protocol.objects.get(code=code),
                                   order=order)
    MetricDef.objects.filter(code="cmj_height").update(mdc=2.0)
    hraci = [Subject.objects.create(organization=org, code=f"FTVS-{i:04d}", sport=hokej)
             for i in range(1, 6)]
    client.force_login(user)
    return org, battery, hraci, client


def zmer(subject, day, code, values, *, protocol="cmj", side="B"):
    session, _ = TestSession.objects.get_or_create(organization=subject.organization,
                                                   subject=subject, date=day)
    run, _ = ProtocolRun.objects.get_or_create(session=session,
                                               protocol=Protocol.objects.get(code=protocol))
    metric = MetricDef.objects.get(code=code)
    for number, value in enumerate(values, start=1):
        trial, _ = Trial.objects.get_or_create(protocol_run=run, number=number)
        Measurement.objects.create(trial=trial, metric=metric, side=side, value=value)


def test_sloupce_podle_klicovych_metrik_baterie(tym):
    _, battery, *_ = tym
    cols = columns_for(battery.protocols())
    assert [(c["metric"].code, c["side"]) for c in cols] == [
        ("cmj_height", "B"), ("sls_cop_area", "L"), ("sls_cop_area", "R")]


def test_posledni_hodnota_zmena_proti_mdc_a_postaveni_v_tymu(tym):
    _, battery, hraci, _ = tym
    zmer(hraci[0], date(2026, 3, 1), "cmj_height", [30.0, 32.0])     # průměr 31
    zmer(hraci[0], date(2026, 9, 1), "cmj_height", [34.0, 34.0])     # +3 > MDC
    zmer(hraci[1], date(2026, 3, 1), "cmj_height", [40.0])
    zmer(hraci[1], date(2026, 9, 1), "cmj_height", [41.0])           # +1 < MDC
    for subject, value in [(hraci[2], 38.0), (hraci[3], 39.0), (hraci[4], 50.0)]:
        zmer(subject, date(2026, 9, 1), "cmj_height", [value])
    zmer(hraci[0], date(2026, 9, 1), "sls_cop_area", [400], protocol="sls", side="L")
    # Opakované měření po zátěži se do přehledu nepočítá.
    run = ProtocolRun.objects.create(session=hraci[4].sessions.get(), is_primary=False,
                                     protocol=Protocol.objects.get(code="cmj"))
    Measurement.objects.create(trial=Trial.objects.create(protocol_run=run, number=1),
                               metric=MetricDef.objects.get(code="cmj_height"), side="B",
                               value=10.0)

    cols = columns_for(battery.protocols())
    table = team_table(hraci, cols, today=date(2026, 9, 26))
    radky = {r["subject"].code: r["cells"] for r in table["rows"]}

    prvni = radky["FTVS-0001"][0]
    assert prvni["value_txt"] == "34,0"
    assert prvni["verdict"]["text"] == "zlepšení" and prvni["verdict"]["delta_txt"] == "+3,0"
    assert radky["FTVS-0002"][0]["verdict"]["text"] == "v pásmu chyby měření"
    assert radky["FTVS-0005"][0]["value"] == 50.0                    # ne 10 z opakování
    assert radky["FTVS-0005"][0]["tier"] == "top"                    # vysoko nad průměrem
    assert radky["FTVS-0001"][0]["tier"] == "low"
    assert radky["FTVS-0001"][1]["value_txt"] == "400"               # levá
    assert radky["FTVS-0001"][2] is None                             # pravá neměřena
    assert radky["FTVS-0001"][1].get("tier") is None                 # 1 hodnota = bez srovnání

    souhrn = table["summary"][0]
    assert souhrn["n"] == 5 and souhrn["mean_txt"] == "40,4"


def test_nizsi_je_lepe_otoci_poradi(tym):
    _, battery, hraci, _ = tym
    for subject, value in zip(hraci, [100, 110, 120, 130, 400], strict=True):
        zmer(subject, date(2026, 9, 1), "sls_cop_area", [value], protocol="sls", side="L")
    cols = columns_for(battery.protocols())
    rows = team_table(hraci, cols, today=date(2026, 9, 26))["rows"]
    assert rows[4]["cells"][1]["tier"] == "low"      # největší plocha = nejhorší stabilita


def test_stranka_a_csv(tym):
    _, battery, hraci, client = tym
    zmer(hraci[0], date(2026, 9, 1), "cmj_height", [35.5])
    html = client.get("/tym/").content.decode()
    assert "Týmový přehled" in html and "35,5" in html and "FTVS-0005" in html

    response = client.get(f"/tym/?baterie={battery.pk}&format=csv")
    text = response.content.decode("utf-8-sig")
    assert response["Content-Type"].startswith("text/csv")
    assert text.splitlines()[0].startswith("Sportovec;Výška výskoku (CMJ) [cm]")
    assert "FTVS-0001;35,5;01.09.2026" in text


def test_bez_baterie_poradi(db, client):
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    client.force_login(User.objects.create(username="x", organization=org, role=Role.LAB))
    assert "Sporty a testy" in client.get("/tym/").content.decode()


def test_sjednocene_obrazovky_se_vykresli(tym):
    from apps.reports.models import Report

    _, _, hraci, client = tym
    zmer(hraci[0], date(2026, 9, 1), "cmj_height", [35.5])
    session = hraci[0].sessions.get()
    run = session.protocol_runs.get()

    seznam = client.get("/mereni/").content.decode()
    assert "FTVS-0001" in seznam and "1/1" in seznam
    assert "FTVS-0005" not in client.get("/mereni/?q=0001").content.decode()

    detail = client.get(f"/mereni/{session.pk}/").content.decode()
    assert "1 hodnot" in detail and "Vytvořit zprávu" in detail
    assert "DSI" not in detail.split('name="protocol"')[1].split("</select>")[0]

    assert "Uložit hodnoty" in client.get(f"/mereni/provedeni/{run.pk}/").content.decode()
    assert "Historie importů" in client.get("/import/").content.decode()

    client.post(f"/zpravy/z-mereni/{session.pk}/")
    report = Report.objects.get()
    assert "koncept" in client.get("/zpravy/").content.decode()
    assert "koncept" not in client.get("/zpravy/?stav=released").content.decode().split("<tbody>")[1]
    assert "Otevřít celou zprávu" in client.get(f"/zpravy/{report.pk}/").content.decode()
