"""Baterie testů, nový testovací den podle baterie, Dnešní testování, Wingate W/kg."""

from datetime import date, datetime

import pytest
from django.core.management import call_command

from apps.catalog.models import BatteryItem, MetricDef, Protocol, TestBattery
from apps.core.models import Organization, Role, User
from apps.measurements.models import Measurement, ProtocolRun, TestSession, Trial
from apps.subjects.models import Sport, Subject


@pytest.fixture
def lab(db, client):
    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    user = User.objects.create(username="lab", organization=org, role=Role.LAB)
    hokej = Sport.objects.create(organization=org, code="hokej", name="Lední hokej")
    client.force_login(user)
    return org, user, hokej, client


def baterie(sport, category, codes):
    battery = TestBattery.objects.create(organization=sport.organization, sport=sport,
                                         category=category)
    for order, code in enumerate(codes, start=1):
        BatteryItem.objects.create(battery=battery, protocol=Protocol.objects.get(code=code),
                                   order=order)
    return battery


def test_baterie_podle_kategorie_jinak_sportu(lab):
    org, _, hokej, _ = lab
    obecna = baterie(hokej, "", ["cmj"])
    dorost = baterie(hokej, "dorost", ["wingate", "sj"])
    hrac = Subject.objects.create(organization=org, code="FTVS-0001", sport=hokej,
                                  category="Dorost")
    muz = Subject.objects.create(organization=org, code="FTVS-0002", sport=hokej)
    assert TestBattery.for_subject(hrac) == dorost        # kategorie bez ohledu na velikost písmen
    assert TestBattery.for_subject(muz) == obecna


def test_uprava_baterie_v_aplikaci(lab):
    org, _, hokej, client = lab
    battery = baterie(hokej, "", ["cmj", "imtp"])
    wingate = Protocol.objects.get(code="wingate")

    client.post(f"/sporty/baterie/{battery.pk}/pridat/", {"protocol": wingate.pk})
    assert [p.code for p in battery.protocols()] == ["cmj", "imtp", "wingate"]

    item = battery.items.get(protocol=wingate)
    client.post(f"/sporty/polozka/{item.pk}/nahoru/")
    assert [p.code for p in battery.protocols()] == ["cmj", "wingate", "imtp"]

    client.post(f"/sporty/polozka/{battery.items.get(protocol__code='cmj').pk}/odebrat/")
    assert [p.code for p in battery.protocols()] == ["wingate", "imtp"]
    assert client.get("/sporty/").status_code == 200


def test_novy_sport_dostane_prazdnou_baterii(lab):
    *_, client = lab
    client.post("/sporty/", {"name": "Florbal"})
    sport = Sport.objects.get(name="Florbal")
    assert TestBattery.objects.filter(sport=sport, category="").exists()


def test_novy_testovaci_den_predvyplni_baterii(lab):
    org, _, hokej, client = lab
    baterie(hokej, "", ["wingate", "sj", "dsi"])
    hrac = Subject.objects.create(organization=org, code="FTVS-0001", sport=hokej)

    html = client.get(f"/mereni/novy/?sportovec={hrac.pk}").content.decode()
    wingate = Protocol.objects.get(code="wingate")
    import re

    checked = set(re.findall(r'name="protocols" value="(\d+)" id="[^"]+" checked', html))
    assert checked == {str(wingate.pk), str(Protocol.objects.get(code="sj").pk)}  # DSI se neměří

    client.post("/mereni/novy/", {"subject": hrac.pk, "date": "2026-09-01",
                                  "protocols": [wingate.pk, Protocol.objects.get(code="sj").pk]})
    session = TestSession.objects.get()
    assert sorted(r.protocol.code for r in session.protocol_runs.all()) == ["sj", "wingate"]


def test_dnesni_testovani_zalozi_den_a_ukaze_stav(lab):
    org, _, hokej, client = lab
    battery = baterie(hokej, "", ["cmj", "sj"])
    a = Subject.objects.create(organization=org, code="FTVS-0001", sport=hokej)
    b = Subject.objects.create(organization=org, code="FTVS-0002", sport=hokej)

    client.post("/testovani/", {"datum": "2026-09-01", "baterie": battery.pk,
                                "sportovec": [a.pk, b.pk]})
    assert ProtocolRun.objects.count() == 4
    # druhé založení nic nezdvojí
    client.post("/testovani/", {"datum": "2026-09-01", "baterie": battery.pk,
                                "sportovec": [a.pk]})
    assert ProtocolRun.objects.count() == 4

    run = ProtocolRun.objects.get(session__subject=a, protocol__code="cmj")
    trial = Trial.objects.create(protocol_run=run, number=1)
    Measurement.objects.create(trial=trial, metric=MetricDef.objects.get(code="cmj_height"),
                               side="B", value=35)
    html = client.get(f"/testovani/?datum=2026-09-01&baterie={battery.pk}").content.decode()
    assert html.count("hotovo") >= 1 and "zadat" in html
    assert "1 <span class=\"kpi-unit\">/ 4</span>" in html


def test_import_vyplni_zalozeny_test(lab):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.ingest import services
    from tests.test_vald import cmj, forcedecks

    org, user, hokej, _ = lab
    services.commit_batch(services.stage_file(
        uploaded_file=SimpleUploadedFile("a.xlsx", forcedecks([
            ("Petr Novák", "u-1", "19.05.2003", datetime(2026, 8, 21, 11, 0), "Trial 1",
             cmj(30))])), user=user, organization=org), user=user)
    # druhý den: naplánováno podle baterie, pak import
    subject = Subject.objects.get()
    session = TestSession.objects.create(organization=org, subject=subject,
                                         date=date(2026, 8, 22))
    planned = ProtocolRun.objects.create(session=session, protocol=Protocol.objects.get(code="cmj"))
    services.commit_batch(services.stage_file(
        uploaded_file=SimpleUploadedFile("b.xlsx", forcedecks([
            ("Petr Novák", "u-1", "19.05.2003", datetime(2026, 8, 22, 10, 0), "Trial 1",
             cmj(31))])), user=user, organization=org), user=user)

    assert session.protocol_runs.filter(protocol__code="cmj").count() == 1
    planned.refresh_from_db()
    assert planned.external_ref.startswith("vald:") and planned.trials.exists()


def test_wingate_relativni_hodnoty(lab):
    from apps.analytics.derived import recompute

    org, *_ = lab
    subject = Subject.objects.create(organization=org, code="FTVS-0001")
    session = TestSession.objects.create(organization=org, subject=subject, date=date(2026, 7, 24))

    def zapis(protocol_code, values):
        run = ProtocolRun.objects.create(session=session,
                                         protocol=Protocol.objects.get(code=protocol_code))
        trial = Trial.objects.create(protocol_run=run, number=1)
        for code, value in values.items():
            Measurement.objects.create(trial=trial, metric=MetricDef.objects.get(code=code),
                                       side="B", value=value)

    zapis("bodycomp", {"body_mass": 82.4, "lean_mass": 77.0})
    zapis("wingate", {"wingate_pmax": 1120, "wingate_pmin": 406, "wingate_work": 25.8})
    recompute(session)

    def hodnota(code):
        return Measurement.objects.get(metric__code=code).value

    assert hodnota("wingate_pmax_th") == 13.59       # 1120 / 82,4
    assert hodnota("wingate_pmax_ath") == 14.55
    assert hodnota("wingate_work_th") == 313.1       # 25,8 kJ → J / 82,4
    # relativní hodnoty jsou v tabulce Wingate, ne ve zvláštním protokolu
    assert Measurement.objects.get(metric__code="wingate_pmax_th").trial.protocol_run.protocol.code == "wingate"


def test_eur_z_cmj_a_sj(lab):
    from apps.analytics.derived import recompute

    org, *_ = lab
    subject = Subject.objects.create(organization=org, code="FTVS-0001")
    session = TestSession.objects.create(organization=org, subject=subject, date=date(2026, 7, 24))
    for code, metric, value in (("cmj", "cmj_height", 38.0), ("sj", "sj_height", 34.0)):
        run = ProtocolRun.objects.create(session=session, protocol=Protocol.objects.get(code=code))
        trial = Trial.objects.create(protocol_run=run, number=1)
        Measurement.objects.create(trial=trial, metric=MetricDef.objects.get(code=metric),
                                   side="B", value=value)
    recompute(session)
    assert Measurement.objects.get(metric__code="eur").value == 1.118


def test_baterie_se_prenese_s_katalogem(lab):
    from apps.catalog.transfer import export_catalog, import_catalog

    _, _, hokej, _ = lab
    baterie(hokej, "dorost", ["wingate", "sj"])
    data = export_catalog()
    TestBattery.objects.all().delete()
    import_catalog(data)
    battery = TestBattery.objects.get(category="dorost")
    assert [p.code for p in battery.protocols()] == ["wingate", "sj"]


def test_sport_bez_baterie_si_ji_muze_zalozit(lab):
    *_, hokej, client = lab
    assert "Založit baterii pro celý sport" in client.get("/sporty/").content.decode()
    client.post(f"/sporty/{hokej.pk}/baterie/", {"category": ""})
    assert TestBattery.objects.filter(sport=hokej, category="").count() == 1
    assert "Založit baterii pro celý sport" not in client.get("/sporty/").content.decode()
