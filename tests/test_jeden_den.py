"""Jeden sportovec má v jeden den jeden testovací den."""

from datetime import date

import pytest
from django.core.management import call_command
from django.db import IntegrityError, connection
from django.db.migrations.executor import MigrationExecutor

from apps.catalog.models import Protocol
from apps.core.models import Organization, Role, User
from apps.measurements.models import TestSession
from apps.subjects.models import Sport, Subject


@pytest.fixture
def lab(db, client):
    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    user = User.objects.create(username="lab", organization=org, role=Role.LAB)
    sport = Sport.objects.create(organization=org, code="hokej", name="Lední hokej")
    subject = Subject.objects.create(organization=org, code="FTVS-0001", sport=sport)
    client.force_login(user)
    return org, subject, client


def test_druhy_den_tehoz_data_databaze_odmitne(lab):
    org, subject, _ = lab
    TestSession.objects.create(organization=org, subject=subject, date=date(2026, 3, 1))
    with pytest.raises(IntegrityError):
        TestSession.objects.create(organization=org, subject=subject, date=date(2026, 3, 1))


def test_formular_otevre_existujici_den_a_prida_testy(lab):
    org, subject, client = lab
    session = TestSession.objects.create(organization=org, subject=subject, date=date(2026, 3, 1))
    cmj = Protocol.objects.get(code="cmj")
    response = client.post("/mereni/novy/", {"subject": subject.pk, "date": "2026-03-01",
                                            "protocols": [cmj.pk]}, follow=True)
    assert TestSession.objects.count() == 1
    assert response.redirect_chain[-1][0] == f"/mereni/{session.pk}/"
    assert "už existoval" in response.content.decode()
    assert session.protocol_runs.filter(protocol=cmj).exists()

    # Jiná chyba zároveň: formulář se vrátí s vysvětlením, nic se nezakládá.
    response = client.post("/mereni/novy/", {"subject": subject.pk, "date": "2026-03-01",
                                            "fatigue_rating": "abc"})
    assert response.status_code == 200
    assert "už má v ten den testovací den" in response.content.decode()
    assert TestSession.objects.count() == 1


def test_zalozeni_dne_ze_skupiny_se_opakuje_bez_chyby(lab):
    from apps.catalog.models import BatteryItem, TestBattery

    org, subject, client = lab
    battery = TestBattery.objects.create(organization=org, sport=subject.sport)
    BatteryItem.objects.create(battery=battery, protocol=Protocol.objects.get(code="cmj"), order=1)
    for _ in range(2):
        response = client.post("/testovani/", {"datum": "2026-03-01", "baterie": battery.pk,
                                               "sportovec": [subject.pk]})
        assert response.status_code == 302
    assert TestSession.objects.filter(subject=subject).count() == 1


@pytest.mark.django_db(transaction=True)
def test_migrace_slije_duplicitni_dny():
    """Stav před migrací: dva dny téhož data – slijí se do staršího, nic se neztratí."""
    from apps.reports.models import Report

    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    sport = Sport.objects.create(organization=org, code="hokej", name="Lední hokej")
    subject = Subject.objects.create(organization=org, code="FTVS-0001", sport=sport)
    cmj, sls = Protocol.objects.get(code="cmj").pk, Protocol.objects.get(code="sls").pk

    executor = MigrationExecutor(connection)
    executor.migrate([("measurements", "0003_prostredi_a_dotazniky")])
    try:
        # Ostatní aplikace v aktuálním stavu, jen měření před touto migrací.
        nodes = [n for n in executor.loader.graph.leaf_nodes() if n[0] != "measurements"]
        old_apps = executor.loader.project_state(
            nodes + [("measurements", "0003_prostredi_a_dotazniky")]).apps
        OldSession = old_apps.get_model("measurements", "TestSession")
        OldRun = old_apps.get_model("measurements", "ProtocolRun")
        OldReport = old_apps.get_model("reports", "Report")
        first = OldSession.objects.create(organization_id=org.pk, subject_id=subject.pk,
                                          date=date(2026, 3, 1), note="ručně")
        second = OldSession.objects.create(organization_id=org.pk, subject_id=subject.pk,
                                           date=date(2026, 3, 1), location="hala")
        OldRun.objects.create(session=first, protocol_id=cmj)
        OldRun.objects.create(session=second, protocol_id=cmj)
        OldRun.objects.create(session=second, protocol_id=sls)
        OldReport.objects.create(organization_id=org.pk, session=second, report_number="FT-1",
                                 subject_id=subject.pk, audience="trainer")
    finally:
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    session = TestSession.objects.get(subject=subject)
    assert session.pk == first.pk and session.note == "ručně" and session.location == "hala"
    runs = list(session.protocol_runs.order_by("pk"))
    assert [(r.protocol.code, r.is_primary) for r in runs] == [
        ("cmj", True), ("cmj", False), ("sls", True)]
    assert Report.objects.get().session_id == session.pk
