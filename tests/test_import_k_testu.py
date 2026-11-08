"""
Dávka 15: nahrání exportu k tomuto testu (hodnoty do přesně tohoto
provedení, návrat na test, upozornění na jiné testy v souboru) a údaj
„import z…“ / „jen ruční zadání“ u testů dne.
"""

from datetime import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from apps.catalog.models import ImportProfile, Protocol, TestFamily
from apps.core.models import Organization, Role, User
from apps.ingest import capabilities
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
    grip = Protocol.objects.create(organization=org, code="grip", name="Síla stisku ruky",
                                   family=TestFamily.DYNAMOMETRY, device="ruční dynamometr")
    client = Client()
    client.force_login(user)
    return org, user, client, session, grip


def test_u_testu_je_napsano_z_ceho_jde_nacist(lab):
    org, user, client, session, grip = lab
    cmj_p = Protocol.objects.get(code="cmj")
    first = ProtocolRun.objects.create(session=session, protocol=cmj_p)
    manual = ProtocolRun.objects.create(session=session, protocol=grip)

    sources = capabilities.import_sources([cmj_p, grip], org)
    assert sources[cmj_p.pk] == ["VALD ForceDecks"]
    assert grip.pk not in sources
    assert capabilities.hint(sources.get(grip.pk)) == "jen ruční zadání"

    html = client.get(f"/mereni/{session.pk}/").content.decode()
    assert "import: VALD ForceDecks" in html and "jen ruční zadání" in html

    html = client.get(f"/mereni/provedeni/{first.pk}/").content.decode()
    assert "Nahrát export k tomuto testu" in html and 'name="provedeni"' in html
    assert f'name="protocol" value="{cmj_p.pk}"' in html
    html = client.get(f"/mereni/provedeni/{manual.pk}/").content.decode()
    assert "jen ruční zadání" in html and "Nahrát export" not in html

    # test s ručně zadanými hodnotami: export by založil druhé provedení, tlačítko se nenabízí
    from apps.catalog.models import MetricDef
    from apps.measurements.models import Measurement, Trial

    trial = Trial.objects.create(protocol_run=first, number=1)
    Measurement.objects.create(trial=trial, metric=MetricDef.objects.get(code="cmj_height"),
                               side="B", value=31)
    html = client.get(f"/mereni/provedeni/{first.pk}/").content.decode()
    assert "Nahrát export" not in html


def test_export_k_testu_vyplni_prave_toto_provedeni_a_vrati_se(lab):
    org, user, client, session, grip = lab
    cmj_p = Protocol.objects.get(code="cmj")
    first = ProtocolRun.objects.create(session=session, protocol=cmj_p)
    second = ProtocolRun.objects.create(session=session, protocol=cmj_p, is_primary=False)
    when = datetime.combine(session.date, datetime.min.time().replace(hour=11))

    response = client.post("/import/nahrat/", {
        "adapter": "auto", "provedeni": second.pk, "protocol": cmj_p.pk,
        "file": SimpleUploadedFile("cmj.xlsx", forcedecks([
            ("Neznámý Hráč", "uuid-7", "19.05.2003", when, "Trial 1", cmj(33))]))})
    batch = ImportBatch.objects.get()
    assert response.status_code == 302 and response.url == f"/import/{batch.pk}/"
    assert batch.summary["cil"]["run"] == second.pk and batch.summary["cil"]["protokol"] == "cmj"
    assert batch.summary["cil"]["zpet"] == f"/mereni/provedeni/{second.pk}/"

    html = client.get(f"/import/{batch.pk}/").content.decode()
    assert "Nahráno k testu <strong>Countermovement jump</strong>" in html
    assert "Soubor obsahuje i jiné testy" not in html

    key = next(iter(batch.summary["subjects"]))
    response = client.post(f"/import/{batch.pk}/ulozit/", {f"prirazeni_{key}": session.subject.pk})
    assert response.url == f"/mereni/provedeni/{second.pk}/"
    first.refresh_from_db()
    second.refresh_from_db()
    assert second.external_ref.startswith("vald:") and second.trials.exists()
    assert first.external_ref == "" and not first.trials.exists()
    assert session.protocol_runs.filter(protocol=cmj_p).count() == 2


def test_soubor_s_jinym_testem_nez_odkud_se_nahral(lab):
    org, user, client, session, grip = lab
    cmj_p = Protocol.objects.get(code="cmj")
    run = ProtocolRun.objects.create(session=session, protocol=cmj_p)
    when = datetime.combine(session.date, datetime.min.time().replace(hour=11))
    # export je SLS, nahraný ze stránky CMJ: náhled to řekne, hodnoty jdou k SLS dne
    profile = ImportProfile.objects.get(device="vald_forcedecks", protocol__code="sls")
    columns = [c.column for c in profile.columns.all()][:3]
    rows = [("Neznámý Hráč", "uuid-7", "19.05.2003", when, "Trial 1",
             {c: 10.0 for c in columns})]
    client.post("/import/nahrat/", {
        "adapter": "auto", "provedeni": run.pk, "protocol": cmj_p.pk,
        "file": SimpleUploadedFile("sls.xlsx", forcedecks(rows, test_type=profile.test_type,
                                                          columns=columns))})
    batch = ImportBatch.objects.get()
    html = client.get(f"/import/{batch.pk}/").content.decode()
    assert "Soubor obsahuje i jiné testy:" in html and "Stoj na jedné noze" in html
    key = next(iter(batch.summary["subjects"]))
    client.post(f"/import/{batch.pk}/ulozit/", {f"prirazeni_{key}": session.subject.pk})
    run.refresh_from_db()
    assert run.external_ref == ""                                   # CMJ zůstal prázdný
    assert session.protocol_runs.filter(protocol__code="sls").exists()
