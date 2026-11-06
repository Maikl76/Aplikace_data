"""
Dávka 8: režim u přístroje (průchod baterií test za testem na jedné obrazovce,
shrnutí dne, další sportovec) a kontrola hned při zadávání (rozptyl pokusů
a hodnoty mimo rozsah přímo v mřížce, další sloupec pokusu).
"""

import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import MetricDef, Protocol, TestBattery
from apps.core.models import Organization, Role, User
from apps.measurements import planning
from apps.measurements.forms import odd_trial, row_warnings
from apps.measurements.models import TestSession, Trial
from apps.subjects.models import Sport, Subject


@pytest.fixture
def lab(db):
    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    user = User.objects.create(username="laborant", organization=org, role=Role.LAB)
    sport = Sport.objects.create(organization=org, name="Florbal", code="florbal")
    battery = TestBattery.objects.create(organization=org, sport=sport)
    cmj, imtp = Protocol.objects.get(code="cmj"), Protocol.objects.get(code="imtp")
    battery.items.create(protocol=cmj, order=1)
    battery.items.create(protocol=imtp, order=2)
    MetricDef.objects.filter(code="cmj_height").update(trial_cv_limit=10, plausible_min=5,
                                                       plausible_max=80)
    Protocol.objects.filter(code="cmj").update(rpe_after=True)
    client = Client()
    client.force_login(user)
    return org, user, client, sport


def _day(org, sport, code, day=None):
    subject = Subject.objects.create(organization=org, code=code, sport=sport)
    session = TestSession.objects.create(organization=org, subject=subject,
                                         date=day or timezone.localdate())
    planning.ensure_runs(session, planning.battery_protocols(subject))
    runs = sorted(session.protocol_runs.all(), key=lambda r: r.protocol.code)   # cmj, imtp
    return subject, session, runs


def _field(run, code, trial):
    from apps.measurements.forms import field_name

    pm = run.protocol.protocol_metrics.get(metric__code=code)
    return field_name(pm, pm.qualifier_combinations()[0], trial)


def test_kontrola_hned_v_mrizce_a_dalsi_pokus(lab):
    org, user, client, sport = lab
    subject, session, (cmj, imtp) = _day(org, sport, "FTVS-0001")
    metric = MetricDef.objects.get(code="cmj_height")
    assert odd_trial([(1, 30.0), (2, 31.0), (3, 40.0)])[0] == 3
    assert row_warnings(metric, [(1, 30.0), (2, 30.5)], []) == []
    assert row_warnings(metric, [(1, 30.0), (2, 31.0), (3, 40.0)], [3]) == [
        "Pokusy se liší o 16 % (mez 10 %): pokus 3 se liší o 31 % od ostatních – změřit znovu?",
        "Pokus 3 mimo věrohodný rozsah (5–80 cm) – překlep, nebo chyba přístroje?",
    ]

    url = reverse("run_entry", args=[cmj.pk])
    html = client.get(url).content.decode()
    assert 'data-cv-limit="10' in html and 'data-min="5' in html and "js-hodnota" in html
    assert "+ přidat pokus" in html and 'name="pokusu" value="3"' in html

    # uložení přes HTMX vrátí mřížku i s upozorněním a hláškou
    response = client.post(url, {_field(cmj, "cmj_height", 1): "30", _field(cmj, "cmj_height", 2): "31",
                                 _field(cmj, "cmj_height", 3): "40", "pokusy_stav": "1", "pokusu": "3"},
                           HTTP_HX_REQUEST="true")
    html = response.content.decode()
    assert "pokus 3 se liší o 31 % od ostatních – změřit znovu?" in html
    text = client.get(url).content.decode()
    assert "U 1 ukazatele se pokusy liší víc než obvykle" in text   # hláška po uložení
    # mimo rozsah: v mřížce hned
    response = client.post(url, {_field(cmj, "cmj_height", 3): "150", "pokusy_stav": "1", "pokusu": "3"},
                           HTTP_HX_REQUEST="true")
    assert "Pokus 3 mimo věrohodný rozsah (5–80 cm)" in response.content.decode()

    # čtvrtý sloupec pokusu, neplatný 4. pokus se uloží
    html = client.get(url + "?pokusy=4").content.decode()
    assert "4. pokus" in html and 'name="pokusu" value="4"' in html
    client.post(url, {_field(cmj, "cmj_height", 3): "31.5", _field(cmj, "cmj_height", 4): "30.8",
                      "pokusy_stav": "1", "pokusu": "4", "neplatny|4": "1", "duvod|4": "nedoskok"})
    assert Trial.objects.get(protocol_run=cmj, number=4).invalid_reason == "nedoskok"
    assert "4. pokus" in client.get(url).content.decode()   # sloupec zůstává, pokus existuje


def test_rezim_u_pristroje_vede_test_za_testem(lab):
    org, user, client, sport = lab
    subject, session, (cmj, imtp) = _day(org, sport, "FTVS-0001")
    other, other_session, (o_cmj, o_imtp) = _day(org, sport, "FTVS-0002")

    detail = client.get(reverse("session_detail", args=[session.pk])).content.decode()
    assert "Režim u přístroje" in detail and reverse("run_device", args=[cmj.pk]) in detail
    today = client.get(reverse("today") + f"?baterie={TestBattery.objects.get().pk}").content.decode()
    assert "u přístroje" in today and reverse("run_device", args=[cmj.pk]) in today

    url = reverse("run_device", args=[cmj.pk])
    page = client.get(url)
    html = page.content.decode()
    assert page.templates[0].name == "measurements/device_entry.html"
    assert "Režim u přístroje" in html and "test 1 z 2" in html
    assert f"Uložit a další test: {imtp.protocol.name}" in html
    assert "app-sidebar" not in html and "Opustit režim" in html
    assert "RPE po testu" in html and "Zeptejte se, než sportovec odejde" in html

    # uložit a další: HTMX přesměruje na další test v režimu; z posledního na shrnutí dne
    response = client.post(url, {_field(cmj, "cmj_height", 1): "30", "pokusy_stav": "1",
                                 "pokusu": "3", "dalsi": "1"}, HTTP_HX_REQUEST="true")
    assert response.status_code == 204 and response["HX-Redirect"] == reverse("run_device", args=[imtp.pk])
    html = client.get(reverse("run_device", args=[imtp.pk])).content.decode()
    assert "test 2 z 2" in html and "Uložit a dokončit den" in html
    response = client.post(reverse("run_device", args=[imtp.pk]),
                           {_field(imtp, "imtp_peak_force", 1): "2000", "pokusy_stav": "1",
                            "pokusu": "3", "dalsi": "1"})
    assert response.status_code == 302
    assert response["Location"] == reverse("session_device_done", args=[session.pk])
    # bez HTMX a bez „další“ zůstává režim u přístroje
    response = client.post(url, {_field(cmj, "cmj_height", 2): "31", "pokusy_stav": "1", "pokusu": "3"})
    assert response["Location"] == url

    done = client.get(reverse("session_device_done", args=[session.pk])).content.decode()
    assert "den změřen" in done and "chybí RPE" in done   # CMJ má RPE po testu
    assert f"Další sportovec: FTVS-0002 · {o_cmj.protocol.name}" in done
    assert reverse("run_device", args=[o_cmj.pk]) in done
    # druhý sportovec má vše bez hodnot – shrnutí nabídne doměřit, dalšího už ne
    done = client.get(reverse("session_device_done", args=[other_session.pk])).content.decode()
    assert "zbývá 2 testy" in done and "Doměřit" in done and "Další sportovec" not in done
