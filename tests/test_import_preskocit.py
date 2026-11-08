"""
Export s více sportovci: v kontrole lze sportovce přeskočit (neimportovat)
a při nahrání od jednoho sportovce načíst jen jeho.
"""

from datetime import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from apps.catalog.models import Protocol
from apps.core.models import Organization, Role, User
from apps.ingest import services
from apps.ingest.models import ImportBatch
from apps.measurements.models import ProtocolRun, TestSession
from apps.subjects.models import Sport, Subject
from tests.test_vald import cmj, forcedecks


@pytest.fixture
def lab(db):
    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    user = User.objects.create(username="laborant", organization=org, role=Role.LAB)
    sport = Sport.objects.create(organization=org, name="Tenis", code="tenis")
    subject = Subject.objects.create(organization=org, code="FTVS-0001", sport=sport)
    session = TestSession.objects.create(organization=org, subject=subject,
                                         date=timezone.localdate())
    run = ProtocolRun.objects.create(session=session, protocol=Protocol.objects.get(code="cmj"))
    client = Client()
    client.force_login(user)
    return org, user, client, subject, run


def _export(day):
    when = datetime.combine(day, datetime.min.time().replace(hour=10))
    return SimpleUploadedFile("cmj.xlsx", forcedecks([
        ("Alfa Testová", "uuid-a", "01.01.2000", when, "Trial 1", cmj(30)),
        ("Beta Nová", "uuid-b", "02.02.2001", when, "Trial 1", cmj(28)),
    ]))


def _keys(batch):
    return {info["hint"]: key for key, info in batch.summary["subjects"].items()}


def test_sportovce_ze_souboru_lze_preskocit(lab):
    org, user, client, subject, run = lab
    client.post("/import/nahrat/", {"adapter": "auto", "file": _export(run.session.date)})
    batch = ImportBatch.objects.get()
    html = client.get(f"/import/{batch.pk}/").content.decode()
    assert "neimportovat – přeskočit" in html
    assert "Načíst jen tohoto sportovce" not in html      # bez cíle není koho
    keys = _keys(batch)

    response = client.post(f"/import/{batch.pk}/ulozit/", {
        f"prirazeni_{keys['Alfa Testová']}": subject.pk,
        f"prirazeni_{keys['Beta Nová']}": "preskocit"}, follow=True)
    assert Subject.objects.count() == 1                   # Beta se nezaložila
    run.refresh_from_db()
    assert run.trials.exists() and run.external_ref.startswith("vald:")
    text = response.content.decode()
    assert "1 sportovec ze souboru přeskočen" in text
    batch.refresh_from_db()
    assert batch.summary["preskocit"] == [keys["Beta Nová"]]


def test_preskoceni_se_da_vratit_a_nepocita_se_jako_nepoznany(lab):
    org, user, client, subject, run = lab
    client.post("/import/nahrat/", {"adapter": "auto", "file": _export(run.session.date)})
    batch = ImportBatch.objects.get()
    keys = _keys(batch)
    services.apply_assignments(batch, {keys["Beta Nová"]: services.SKIP}, user)
    rows = services.assignment_choices(batch, user)
    assert next(r for r in rows if r["hint"] == "Beta Nová")["preskocit"] is True
    from apps.ingest.steps import import_detail_steps

    steps = import_detail_steps(batch, rows, [])
    assert steps[1]["count"] == 1                          # jen Alfa je nepoznaná
    services.apply_assignments(batch, {keys["Beta Nová"]: None}, user)
    assert services.skipped_keys(batch) == set()


def test_nacist_jen_tohoto_sportovce_z_testu(lab):
    org, user, client, subject, run = lab
    client.post("/import/nahrat/", {"adapter": "auto", "provedeni": run.pk,
                                    "protocol": run.protocol_id,
                                    "file": _export(run.session.date)})
    batch = ImportBatch.objects.get()
    html = client.get(f"/import/{batch.pk}/").content.decode()
    assert "Načíst jen tohoto sportovce (FTVS-0001)" in html
    keys = _keys(batch)

    response = client.post(f"/import/{batch.pk}/ulozit/", {
        f"prirazeni_{keys['Alfa Testová']}": subject.pk,
        f"prirazeni_{keys['Beta Nová']}": "", "jen_cil": "1"}, follow=True)
    assert response.redirect_chain[0][0] == f"/mereni/provedeni/{run.pk}/"
    assert Subject.objects.count() == 1
    run.refresh_from_db()
    assert run.trials.exists()
    assert "1 sportovec ze souboru přeskočen" in response.content.decode()
