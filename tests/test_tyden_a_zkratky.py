"""
Dávka 13: Přehled na týden a méně klikání – zopakovat poslední den,
koncepty zpráv pro celou skupinu, export za celou skupinu z Dnešního
testování (náhled nabídne skupinu, po uložení návrat).
"""

from datetime import datetime, timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from apps.booking.models import BookingRequest, Slot
from apps.catalog.models import BatteryItem, MetricDef, Protocol, TestBattery
from apps.core import access
from apps.core.models import Organization, Role, User
from apps.ingest.models import ImportBatch
from apps.measurements import planning, week
from apps.measurements.models import Measurement, ProtocolRun, TestSession, Trial
from apps.reports.models import Report
from apps.subjects.models import Sport, Subject


@pytest.fixture
def lab(db):
    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    user = User.objects.create(username="laborant", organization=org, role=Role.LAB)
    access.grant(user, bookings=True)
    sport = Sport.objects.create(organization=org, name="Florbal", code="florbal")
    battery = TestBattery.objects.create(organization=org, sport=sport)
    for order, code in enumerate(["cmj", "sj"], start=1):
        BatteryItem.objects.create(battery=battery, protocol=Protocol.objects.get(code=code),
                                   order=order)
    subjects = [Subject.objects.create(organization=org, code=f"FTVS-000{n}", sport=sport)
                for n in (1, 2, 3)]
    client = Client()
    client.force_login(user)
    return org, user, client, battery, subjects


def _day(subject, day, *, values=()):
    """Testovací den podle baterie; ``values`` = kódy testů, které dostanou hodnotu."""
    session = TestSession.objects.create(organization=subject.organization, subject=subject,
                                         date=day)
    planning.ensure_runs(session, planning.battery_protocols(subject))
    for run in session.protocol_runs.select_related("protocol"):
        if run.protocol.code in values:
            trial = Trial.objects.create(protocol_run=run, number=1)
            metric = run.protocol.protocol_metrics.select_related("metric").first().metric
            Measurement.objects.create(trial=trial, metric=metric, side="B", value=30)
    return session


# --- Přehled na týden ----------------------------------------------------------------------


def test_tyden_ukaze_skupiny_objednavky_a_terminy(lab):
    org, user, client, battery, (a, b, c) = lab
    today = timezone.localdate()
    monday = week.monday_of(today)
    _day(a, monday, values=("cmj", "sj"))          # hotovo
    _day(b, monday)                                 # čeká na hodnoty
    slot = Slot.objects.create(organization=org, start=timezone.make_aware(
        datetime.combine(monday + timedelta(days=2), datetime.min.time().replace(hour=9))),
        capacity=5, location="Hala")
    BookingRequest.objects.create(organization=org, slot=slot, kind=BookingRequest.Kind.TEAM,
                                  status=BookingRequest.Status.APPROVED, team_name="HC Slavia")
    c.next_test_date = monday + timedelta(days=3)
    c.save()

    data = week.overview(user, monday, today=today)
    assert data["summary"]["sessions"] == 2 and data["summary"]["done"] == 1
    assert data["summary"]["bookings"] == 1 and data["summary"]["due"] == 1
    po, _, st, ct = data["days"][:4]
    assert [g.label for g in po["groups"]] == ["Florbal"]
    assert po["groups"][0].done == 1 and po["groups"][0].waiting == 1
    assert f"baterie={battery.pk}" in po["groups"][0].url
    assert po["unreported"][0].subject == a                 # hodnoty má, zprávu ne
    assert st["bookings"][0].team_name == "HC Slavia" and st["bookings"][0].schvalena
    assert ct["due"][0].subject == c
    assert all(d["empty"] for d in data["days"][4:])

    html = client.get(f"/testovani/tyden/?od={monday:%Y-%m-%d}").content.decode()
    assert "HC Slavia" in html and "schváleno" in html
    assert "1 hotovo" in html and "1 čeká" in html
    assert "FTVS-0003" in html and "termín dalšího měření" in html
    assert f"/testovani/?datum={monday:%Y-%m-%d}&amp;baterie={battery.pk}" in html

    # předchozí týden je prázdný; neplatné ?od= znamená tento týden
    html = client.get(f"/testovani/tyden/?od={monday - timedelta(days=7):%Y-%m-%d}").content.decode()
    assert html.count("Nic naplánováno.") == 7
    assert week.parse_monday("nesmysl", today) == monday
    assert week.parse_monday((monday + timedelta(days=6)).isoformat(), today) == monday


def test_tyden_na_prehledu_a_bez_objednavek_pro_metodika(lab):
    org, user, client, battery, (a, *_) = lab
    today = timezone.localdate()
    _day(a, today)
    html = client.get("/").content.decode()
    assert 'id="tyden"' in html and "/testovani/tyden/" in html
    assert f'#den-{today:%Y-%m-%d}' in html

    metodik = User.objects.create(username="metodik", organization=org, role=Role.METHODOLOGIST)
    access.grant(metodik, configured=True)
    other = Client()
    other.force_login(metodik)
    html = other.get("/testovani/tyden/").content.decode()
    assert "objednávek" not in html            # bez přístupu k objednávkám se neukazují
    assert "založit testování" not in html     # metodik hodnoty nezadává


# --- Zopakovat poslední den ----------------------------------------------------------------


def test_zopakovat_den_zalozi_dnesek_se_stejnymi_testy(lab):
    org, user, client, battery, (a, *_) = lab
    today = timezone.localdate()
    old = _day(a, today - timedelta(days=28), values=("cmj", "sj"))
    old.location = "Laboratoř 2"
    old.save()
    # navíc test mimo baterii a jeden odvozený – odvozený se nezakládá
    ProtocolRun.objects.create(session=old, protocol=Protocol.objects.get(code="imtp"))
    ProtocolRun.objects.create(session=old, protocol=Protocol.objects.get(code="dsi"))

    html = client.get(f"/sportovci/{a.pk}/").content.decode()
    assert "Zopakovat poslední den" in html

    response = client.post(f"/mereni/{old.pk}/zopakovat/", follow=True)
    new = TestSession.objects.get(subject=a, date=today)
    assert response.redirect_chain[-1][0] == f"/mereni/{new.pk}/"
    assert sorted(r.protocol.code for r in new.protocol_runs.all()) == ["cmj", "imtp", "sj"]
    assert new.location == "Laboratoř 2" and new.operator == user
    assert not Measurement.objects.filter(trial__protocol_run__session=new).exists()
    assert "Založen testovací den" in response.content.decode()

    # podruhé se nic nezdvojí; dnešní den už existuje, tlačítko na kartě zmizí
    response = client.post(f"/mereni/{old.pk}/zopakovat/", follow=True)
    assert TestSession.objects.filter(subject=a).count() == 2
    assert "už existoval" in response.content.decode()
    assert "Zopakovat poslední den" not in client.get(f"/sportovci/{a.pk}/").content.decode()
    # na minulém dni je tlačítko, na dnešním ne
    assert "Zopakovat dnes" in client.get(f"/mereni/{old.pk}/").content.decode()
    assert "Zopakovat dnes" not in client.get(f"/mereni/{new.pk}/").content.decode()


# --- Koncepty pro celou skupinu ------------------------------------------------------------


def test_koncepty_pro_hotove_dny_skupiny(lab):
    org, user, client, battery, (a, b, c) = lab
    today = timezone.localdate()
    MetricDef.objects.filter(code="cmj_height").update(plausible_min=5, plausible_max=80)
    _day(a, today, values=("cmj", "sj"))     # hotovo
    _day(b, today, values=("cmj",))          # nekompletní
    _day(c, today, values=("cmj", "sj"))     # hotovo

    html = client.get(f"/testovani/?datum={today:%Y-%m-%d}&baterie={battery.pk}").content.decode()
    assert "Koncepty pro 2 dny" in html and "bez zprávy" in html

    response = client.post("/testovani/koncepty/", {"datum": today.isoformat(),
                                                    "baterie": battery.pk, "pro": "trener"},
                           follow=True)
    assert Report.objects.count() == 2
    assert set(Report.objects.values_list("subject__code", flat=True)) == {"FTVS-0001", "FTVS-0003"}
    assert Report.objects.filter(audience="trener", status=Report.Status.DRAFT).count() == 2
    text = response.content.decode()
    assert "Vznikly 2 koncepty zpráv ke kontrole." in text
    assert "1 den ještě nemá hodnoty u všech testů." in text

    # podruhé nic nevznikne – dny už zprávu mají
    response = client.post("/testovani/koncepty/", {"datum": today.isoformat(),
                                                    "baterie": battery.pk}, follow=True)
    assert Report.objects.count() == 2
    assert "2 dny už zprávu mají." in response.content.decode()
    html = client.get(f"/testovani/?datum={today:%Y-%m-%d}&baterie={battery.pk}").content.decode()
    assert ">zpráva</a>" in html and "Koncepty pro 0 dnů" in html

    # bez oprávnění ke konceptům: odepřeno
    researcher = User.objects.create(username="vyzkum", organization=org, role=Role.RESEARCHER)
    access.grant(researcher, configured=True)
    other = Client()
    other.force_login(researcher)
    assert other.post("/testovani/koncepty/", {"datum": today.isoformat(),
                                               "baterie": battery.pk}).status_code == 403


# --- Export za celou skupinu ---------------------------------------------------------------


def test_export_za_skupinu_nabidne_sportovce_a_vrati_se(lab):
    from tests.test_vald import cmj, forcedecks

    org, user, client, battery, (a, b, c) = lab
    today = timezone.localdate()
    planned = _day(a, today)
    when = datetime.combine(today, datetime.min.time().replace(hour=10))
    response = client.post("/import/nahrat/", {
        "adapter": "auto", "testovani_datum": today.isoformat(), "testovani_baterie": battery.pk,
        "file": SimpleUploadedFile("cmj.xlsx", forcedecks([
            ("Nova Sportovkyne", "uuid-9", "19.05.2003", when, "Trial 1", cmj(33))]))})
    batch = ImportBatch.objects.get()
    assert response.status_code == 302 and response.url == f"/import/{batch.pk}/"
    assert batch.summary["cil"]["skupina"] == "Florbal"
    assert sorted(batch.summary["cil"]["subjects"]) == sorted([a.pk, b.pk, c.pk])

    html = client.get(f"/import/{batch.pk}/").content.decode()
    assert "Nahráno z Dnešního testování" in html and "skupina <strong>Florbal</strong>" in html
    assert "FTVS-0002 – skupina Florbal" in html       # i sportovec bez založeného dne
    assert f"FTVS-0001 (FTVS-0001) – testování {today:%d.%m.}" in html or \
        f"FTVS-0001 – testování {today:%d.%m.}" in html

    key = next(iter(batch.summary["subjects"]))
    response = client.post(f"/import/{batch.pk}/ulozit/", {f"prirazeni_{key}": a.pk})
    assert response.status_code == 302
    assert response.url == f"/testovani/?datum={today:%Y-%m-%d}&baterie={battery.pk}"
    run = planned.protocol_runs.get(protocol__code="cmj")
    assert run.external_ref.startswith("vald:") and run.trials.exists()
    assert TestSession.objects.filter(subject=a).count() == 1


def test_export_z_testovaciho_dne_se_vrati_na_den(lab):
    from tests.test_vald import cmj, forcedecks

    org, user, client, battery, (a, *_) = lab
    today = timezone.localdate()
    session = _day(a, today)
    when = datetime.combine(today, datetime.min.time().replace(hour=10))
    client.post("/import/nahrat/", {
        "adapter": "auto", "testovaci_den": session.pk,
        "file": SimpleUploadedFile("cmj.xlsx", forcedecks([
            ("Nova Sportovkyne", "uuid-9", "19.05.2003", when, "Trial 1", cmj(33))]))})
    batch = ImportBatch.objects.get()
    assert batch.summary["cil"]["zpet"] == f"/mereni/{session.pk}/"
    html = client.get(f"/import/{batch.pk}/").content.decode()
    assert "Nahráno z testovacího dne" in html
    key = next(iter(batch.summary["subjects"]))
    response = client.post(f"/import/{batch.pk}/ulozit/", {f"prirazeni_{key}": a.pk})
    assert response.url == f"/mereni/{session.pk}/"


def test_navrat_po_ulozeni_jen_do_aplikace(lab, rf):
    from apps.ingest.views import _back_url

    org, user, *_ = lab
    batch = ImportBatch(organization=org)
    request = rf.get("/")
    for bad in ("https://example.com/x", "//example.com", "javascript:alert(1)", ""):
        batch.summary = {"cil": {"zpet": bad}}
        assert _back_url(request, batch) == "/import/"
    batch.summary = {"cil": {"zpet": "/testovani/?datum=2026-11-09"}}
    assert _back_url(request, batch) == "/testovani/?datum=2026-11-09"
