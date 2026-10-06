"""Průvodce „Nový test“: protokol, metriky se stranami a částmi těla, baterie."""

import pytest
from django.core.management import call_command
from django.test import Client

from apps.catalog.models import BatteryItem, MetricDef, Protocol, TestBattery
from apps.core.models import Organization, Role, User
from apps.measurements.forms import build_grid
from apps.measurements.models import ProtocolRun, TestSession
from apps.subjects.models import Sport, Subject


@pytest.fixture
def lab(db):
    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    sport = Sport.objects.create(organization=org, name="Fotbal", code="fotbal")
    battery = TestBattery.objects.create(organization=org, sport=sport)
    client = Client()
    client.force_login(User.objects.create(username="spravce", organization=org, role=Role.ADMIN))
    return org, battery, client


def novy(battery, **extra):
    data = {
        "name": "Sprint 20 m", "family": "field", "device": "fotobuňky", "trials": "3",
        "rest": "120", "rpe": "", "active": "on", "baterie": [battery.pk],
        "radek": ["0", "1"],
        # existující metrika z katalogu
        "m0_metric": str(MetricDef.objects.get(code="sprint_10m").pk), "m0_sides": ["B"],
        # nová metrika
        "m1_metric": "nova", "m1_new_name": "Čas na 20 m", "m1_new_unit": "s",
        "m1_new_dir": "lower", "m1_new_rule": "nejlepsi", "m1_new_decimals": "2",
        "m1_new_min": "2,5", "m1_new_max": "5", "m1_primary": "on", "m1_sides": ["B"],
    }
    data.update(extra)
    return data


def test_zalozi_test_s_novou_metrikou_a_zaradi_do_baterie(lab):
    org, battery, client = lab
    response = client.post("/sporty/testy/novy/", novy(battery))
    assert response.url == "/sporty/testy/"
    protocol = Protocol.objects.get(name="Sprint 20 m")
    assert (protocol.code, protocol.default_trials, protocol.rest_seconds) == ("sprint_20_m", 3, 120)
    assert protocol.organization == org
    pms = list(protocol.protocol_metrics.select_related("metric").order_by("order"))
    assert [pm.metric.code for pm in pms] == ["sprint_10m", "cas_na_20_m"]
    new = pms[1].metric
    assert (new.unit, new.direction, new.trial_rule) == ("s", "lower", "nejlepsi")
    assert (new.plausible_min, new.plausible_max, new.family) == (2.5, 5.0, "field")
    assert pms[1].is_primary and pms[1].sides == ["B"]
    assert BatteryItem.objects.filter(battery=battery, protocol=protocol).exists()


def test_strany_a_casti_tela_vytvori_radky_zadavani(lab):
    org, battery, client = lab
    client.post("/sporty/testy/novy/", novy(
        battery, name="Síla stisku", radek=["0"], m0_metric=str(MetricDef.objects.get(code="grip_strength").pk),
        m0_sides=["L", "R"], m0_segments=["paze"], m0_segment_other="předloktí",
        m0_modes=["iso"], m0_speeds="60; 180"))
    protocol = Protocol.objects.get(name="Síla stisku")
    pm = protocol.protocol_metrics.get()
    assert pm.sides == ["L", "R"] and pm.segments == ["paze", "předloktí"]
    assert pm.modes == ["iso"] and pm.speeds == [60, 180]
    subject = Subject.objects.create(organization=org, code="S-1")
    session = TestSession.objects.create(organization=org, subject=subject, date="2026-01-01")
    run = ProtocolRun.objects.create(session=session, protocol=protocol)
    assert len(build_grid(run)) == 2 * 2 * 1 * 2   # části × strany × režim × rychlosti


def test_uprava_meni_poradi_odebira_metriku_a_baterii(lab):
    _, battery, client = lab
    client.post("/sporty/testy/novy/", novy(battery))
    protocol = Protocol.objects.get(name="Sprint 20 m")
    page = client.get(f"/sporty/testy/{protocol.pk}/").content.decode()
    assert "Sprint 20 m" in page and "Čas na 20 m" in page
    new_metric = MetricDef.objects.get(code="cas_na_20_m")
    client.post(f"/sporty/testy/{protocol.pk}/", {
        "name": "Sprint 20 m", "family": "field", "trials": "4", "active": "on",
        "radek": ["5"], "m5_metric": str(new_metric.pk), "m5_sides": ["B"]})
    protocol.refresh_from_db()
    assert protocol.default_trials == 4 and protocol.rest_seconds is None
    assert [pm.metric_id for pm in protocol.protocol_metrics.all()] == [new_metric.pk]
    assert not BatteryItem.objects.filter(protocol=protocol).exists()
    # metrika z katalogu zůstala, jen už není v testu
    assert MetricDef.objects.filter(code="sprint_10m").exists()


@pytest.mark.parametrize("extra, chyba", [
    ({"name": ""}, "název testu"),
    ({"radek": []}, "aspoň jednu metriku"),
    ({"m1_new_name": ""}, "chybí název"),
    ({"name": "CMJ"}, "už v katalogu je"),
    ({"m1_metric": "SAME"}, "dvakrát"),
])
def test_chyby_se_ohlasi_a_formular_zustane(lab, extra, chyba):
    _, battery, client = lab
    if extra.get("name") == "CMJ":
        extra["name"] = Protocol.objects.get(code="cmj").name
    if extra.get("m1_metric") == "SAME":
        extra["m1_metric"] = novy(battery)["m0_metric"]
    before = Protocol.objects.count()
    response = client.post("/sporty/testy/novy/", novy(battery, **extra), follow=True)
    assert chyba in response.content.decode()
    assert Protocol.objects.count() == before


def test_laborant_testy_vidi_ale_nezaklada(lab):
    org, battery, _ = lab
    client = Client()
    client.force_login(User.objects.create(username="lab", organization=org, role=Role.LAB))
    page = client.get("/sporty/testy/").content.decode()
    assert "Sprint 30 m" in page and "Nový test" not in page
    client.post("/sporty/testy/novy/", novy(battery))
    assert not Protocol.objects.filter(name="Sprint 20 m").exists()


def test_test_se_prenese_s_katalogem(lab):
    from apps.catalog.transfer import export_catalog, import_catalog

    _, battery, client = lab
    client.post("/sporty/testy/novy/", novy(battery))
    data = export_catalog()
    Protocol.objects.filter(name="Sprint 20 m").update(default_trials=9)
    import_catalog(data)
    assert Protocol.objects.get(name="Sprint 20 m").default_trials == 3
