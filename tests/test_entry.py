"""Testy zadávací mřížky – formulář se generuje z definice protokolu."""

import pytest

from apps.catalog.models import MetricDef, Protocol, ProtocolMetric, TestFamily
from apps.core.models import Organization, Role, User
from apps.measurements.forms import build_grid, field_name, parse_field_name
from apps.measurements.models import Measurement, ProtocolRun, TestSession
from apps.subjects.models import Subject


@pytest.fixture
def izokinetika(db):
    protocol = Protocol.objects.create(
        code="iso", name="Izokinetika ramene", family=TestFamily.DYNAMOMETRY,
        default_trials=3,
    )
    metric = MetricDef.objects.create(code="ir", name="Vnitřní rotace", unit="Nm",
                                      family=TestFamily.DYNAMOMETRY,
                                      plausible_min=3, plausible_max=200)
    ProtocolMetric.objects.create(
        protocol=protocol, metric=metric,
        sides=["L", "R"], modes=["con", "ecc"], speeds=[210, 300],
    )
    return protocol


@pytest.fixture
def run(izokinetika):
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    subject = Subject.objects.create(organization=org, code="FTVS-0001")
    session = TestSession.objects.create(organization=org, subject=subject,
                                         date="2026-03-01")
    return ProtocolRun.objects.create(session=session, protocol=izokinetika)


def test_mrizka_vznikne_z_definice_protokolu(run):
    """2 strany × 2 režimy × 2 rychlosti = 8 řádků, každý po 3 pokusech."""
    rows = build_grid(run)
    assert len(rows) == 8
    assert all(len(r["cells"]) == 3 for r in rows)
    assert any("levá" in r["label"] and "210°/s" in r["label"] for r in rows)


def test_nazev_pole_nese_kvalifikatory(run):
    pm = run.protocol.protocol_metrics.first()
    combo = {"side": "R", "mode": "ecc", "speed": 300.0, "segment": ""}
    parsed = parse_field_name(field_name(pm, combo, 2))

    assert parsed["side"] == "R"
    assert parsed["mode"] == "ecc"
    assert parsed["speed"] == 300.0
    assert parsed["trial_number"] == 2


def test_cizi_pole_se_ignoruje():
    assert parse_field_name("csrfmiddlewaretoken") is None
    assert parse_field_name("v|nesmysl") is None


def test_ulozeni_zapise_hodnoty_s_kvalifikatory(run, client):
    org = run.session.organization
    user = User.objects.create_user("laborant", password="x", organization=org,
                                    role=Role.LAB)
    client.force_login(user)

    pm = run.protocol.protocol_metrics.first()
    data = {
        field_name(pm, {"side": "L", "mode": "con", "speed": 210.0, "segment": ""}, 1): "52,3",
        field_name(pm, {"side": "R", "mode": "con", "speed": 210.0, "segment": ""}, 1): "55.1",
    }
    client.post(f"/mereni/provedeni/{run.pk}/", data)

    assert Measurement.objects.count() == 2
    leva = Measurement.objects.get(side="L")
    assert leva.value == 52.3          # čárka i tečka jako oddělovač
    assert leva.speed == 210.0
    assert leva.quality == Measurement.Quality.OK


def test_nesmyslna_hodnota_se_ulozi_oznacena(run, client):
    org = run.session.organization
    user = User.objects.create_user("l2", password="x", organization=org, role=Role.LAB)
    client.force_login(user)

    pm = run.protocol.protocol_metrics.first()
    name = field_name(pm, {"side": "L", "mode": "con", "speed": 210.0, "segment": ""}, 1)
    client.post(f"/mereni/provedeni/{run.pk}/", {name: "9999"})

    m = Measurement.objects.get()
    assert m.quality == Measurement.Quality.OUT_OF_RANGE
    assert m.value == 9999


def test_opakovane_ulozeni_hodnotu_prepise(run, client):
    org = run.session.organization
    user = User.objects.create_user("l3", password="x", organization=org, role=Role.LAB)
    client.force_login(user)

    pm = run.protocol.protocol_metrics.first()
    name = field_name(pm, {"side": "L", "mode": "con", "speed": 210.0, "segment": ""}, 1)
    client.post(f"/mereni/provedeni/{run.pk}/", {name: "50"})
    client.post(f"/mereni/provedeni/{run.pk}/", {name: "51.5"})

    assert Measurement.objects.count() == 1
    assert Measurement.objects.get().value == 51.5
