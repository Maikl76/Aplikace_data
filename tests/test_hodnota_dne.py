"""
Stejný ukazatel ve dvou testech téhož dne (hmotnost na plošině při CMJ
i ve složení těla) se nesmí slévat do jednoho průměru.
"""

from datetime import date

import pytest
from django.core.management import call_command

from apps.analytics import queries
from apps.analytics.team import columns_for, team_table
from apps.catalog.models import MetricDef, Protocol, ProtocolMetric
from apps.core.models import Organization, Role, User
from apps.measurements.models import Measurement, ProtocolRun, TestSession, Trial
from apps.reports.results import protocol_results
from apps.subjects.models import Sport, Subject


@pytest.fixture
def veslar(db):
    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    User.objects.create(username="lab", organization=org, role=Role.LAB)
    sport = Sport.objects.create(organization=org, code="veslovani", name="Veslování")
    return Subject.objects.create(organization=org, code="FTVS-0001", sport=sport)


def zmer(subject, day, protocol, code, values, *, side="B"):
    session, _ = TestSession.objects.get_or_create(organization=subject.organization,
                                                   subject=subject, date=day)
    run, _ = ProtocolRun.objects.get_or_create(session=session,
                                               protocol=Protocol.objects.get(code=protocol))
    metric = MetricDef.objects.get(code=code)
    for number, value in enumerate(values, start=1):
        trial, _ = Trial.objects.get_or_create(protocol_run=run, number=number)
        Measurement.objects.create(trial=trial, metric=metric, side=side, value=value)
    return session


def test_hodnota_dne_z_testu_kde_je_ukazatel_klicovy(veslar):
    # Plošina váží při každém pokusu, složení těla jednou – a právě tam je hmotnost klíčová.
    zmer(veslar, date(2026, 3, 1), "cmj", "body_mass", [73.0, 73.1, 70.4])
    session = zmer(veslar, date(2026, 3, 1), "bodycomp", "body_mass", [72.9])
    zmer(veslar, date(2026, 3, 1), "cmj", "cmj_height", [30.0, 32.0])

    values = queries.session_metric_values(session)
    hmotnost = values[("body_mass", "B", "", None, "")]
    assert hmotnost["value"] == 72.9 and hmotnost["protocol"] == "bodycomp"
    assert values[("cmj_height", "B", "", None, "")]["value"] == 31.0

    serie = {s["metric"].code: s for s in queries.primary_metric_series(veslar)}
    assert serie["body_mass"]["points"] == [(date(2026, 3, 1), 72.9)]


def test_minule_srovnava_v_ramci_tehoz_testu(veslar):
    zmer(veslar, date(2026, 3, 1), "cmj", "body_mass", [73.0, 73.0])
    zmer(veslar, date(2026, 3, 1), "bodycomp", "body_mass", [72.0])
    zmer(veslar, date(2026, 9, 1), "cmj", "body_mass", [75.0])
    session = zmer(veslar, date(2026, 9, 1), "bodycomp", "body_mass", [74.5])

    # Bez testu hodnota dne (složení těla), s testem jen ten test.
    key = ("body_mass", "B", "", None, "")
    assert queries.previous_session_values(session)[key]["value"] == 72.0
    cmj = Protocol.objects.get(code="cmj")
    assert queries.previous_session_values(session, protocol=cmj)[key]["value"] == 73.0

    bloky = {b["protocol"].code: b["rows"] for b in protocol_results(session)}
    radek = {r["metric"].code: r for r in bloky["cmj"]}["body_mass"]
    assert radek["previous_txt"] == "73,0" and radek["delta_txt"] == "+2,0"
    radek = {r["metric"].code: r for r in bloky["bodycomp"]}["body_mass"]
    assert radek["previous_txt"] == "72,0" and radek["delta_txt"] == "+2,5"


def test_bez_klicoveho_testu_rozhodne_kod_testu(veslar):
    # Hmotnost klíčová nikde: vyhraje test s abecedně prvním kódem, pokaždé stejně.
    ProtocolMetric.objects.filter(metric__code="body_mass").update(is_primary=False)
    zmer(veslar, date(2026, 3, 1), "imtp", "body_mass", [80.0])
    session = zmer(veslar, date(2026, 3, 1), "cmj", "body_mass", [79.0])
    values = queries.session_metric_values(session)
    assert values[("body_mass", "B", "", None, "")]["value"] == 79.0


def test_tymovy_prehled_bere_jen_hodnoty_sloupcoveho_testu(veslar):
    from apps.catalog.models import BatteryItem, TestBattery

    battery = TestBattery.objects.create(organization=veslar.organization, sport=veslar.sport)
    for order, code in enumerate(["cmj", "bodycomp"], start=1):
        BatteryItem.objects.create(battery=battery, protocol=Protocol.objects.get(code=code),
                                   order=order)
    zmer(veslar, date(2026, 3, 1), "cmj", "body_mass", [73.0, 73.1, 70.4])
    zmer(veslar, date(2026, 3, 1), "bodycomp", "body_mass", [72.9])

    cols = columns_for(battery.protocols())
    assert [(c["protocol"].code, c["metric"].code) for c in cols] == [
        ("cmj", "cmj_height"), ("bodycomp", "body_mass")]
    row = team_table([veslar], cols, today=date(2026, 3, 2))["rows"][0]
    assert row["cells"][0] is None                      # výška výskoku neměřena
    assert row["cells"][1]["value_txt"] == "72,9"       # ne průměr s plošinou
