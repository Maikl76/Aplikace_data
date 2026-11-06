"""
Dávka 8: sledovaná složka s exporty z přístroje. Hlídač nový soubor načte
do importu; když sportovce jednoznačně pozná a den je naplánovaný, uloží ho
sám; jinak import čeká na kontrolu. Složka se nikam nepřesouvá, totéž se
nezpracuje dvakrát.
"""

import os
import time
from datetime import date, datetime
from io import StringIO

import pytest
from cryptography.fernet import Fernet
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from apps.catalog.models import Protocol
from apps.core.models import AuditLog, Organization, Role, User
from apps.ingest import watch
from apps.ingest.models import ImportBatch, WatchedFile
from apps.measurements.models import Measurement, ProtocolRun, TestSession
from apps.subjects.models import Subject, SubjectExternalId
from tests.test_vald import T1, cmj, forcedecks


@pytest.fixture
def lab(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    user = User.objects.create(username="laborant", organization=org, role=Role.LAB)
    return org, user


def _planned(org, code="FTVS-0001", vald_id="uuid-1", day=date(2026, 8, 21)):
    """Sportovec, kterého VALD zná, s naplánovaným dnem (prázdný test CMJ)."""
    subject = Subject.objects.create(organization=org, code=code)
    SubjectExternalId.objects.create(subject=subject, system="vald", value=vald_id)
    session = TestSession.objects.create(organization=org, subject=subject, date=day)
    ProtocolRun.objects.create(session=session, protocol=Protocol.objects.get(code="cmj"))
    return subject, session


def _write(directory, name, data, *, old=True):
    path = directory / name
    path.write_bytes(data)
    if old:   # soubor, který přístroj už dopsal (hlídač čerstvé nechává na příště)
        stamp = time.time() - 60
        os.utime(path, (stamp, stamp))
    return path


def test_jednoznacny_export_se_ulozi_sam_ostatni_cekaji(lab, tmp_path):
    org, user = lab
    subject, session = _planned(org)
    _write(tmp_path, "export1.xlsx", forcedecks([
        ("Petr Novák", "uuid-1", "19.05.2003", T1, "Trial 1", cmj(33.0)),
        ("Petr Novák", "uuid-1", "19.05.2003", T1, "Trial 2", cmj(34.0)),
    ]))
    (tmp_path / "poznamky.txt").write_text("nic")
    _write(tmp_path, "~$export1.xlsx", b"zamek")

    outcomes = watch.scan(org, directory=tmp_path, settle=0)
    assert [(o.name, o.status) for o in outcomes] == [("export1.xlsx", "ulozeno")]
    assert "Uloženo" in outcomes[0].message and "testů" in outcomes[0].message
    run = session.protocol_runs.get()
    assert run.trials.count() == 2 and Measurement.objects.filter(trial__protocol_run=run).exists()
    batch = ImportBatch.objects.get()
    assert batch.status == ImportBatch.Status.COMMITTED
    assert batch.uploaded_by.username == watch.SYSTEM_USERNAME and not batch.uploaded_by.is_active
    assert AuditLog.objects.filter(action="create", object_type="ImportBatch",
                                   detail__sledovana_slozka="export1.xlsx").exists()
    org.refresh_from_db()
    assert org.import_checked_at is not None and watch.is_running(org)
    record = WatchedFile.objects.get()
    assert record.status == WatchedFile.Status.COMMITTED and record.batch == batch

    # podruhé nic: soubor je známý (název, velikost, čas změny)
    assert watch.scan(org, directory=tmp_path, settle=0) == []
    assert WatchedFile.objects.count() == 1

    # kopie téhož souboru = už importováno; neznámý sportovec čeká na kontrolu
    _write(tmp_path, "export1_kopie.xlsx", (tmp_path / "export1.xlsx").read_bytes())
    _write(tmp_path, "export2.xlsx", forcedecks([
        ("Jana Nová", "uuid-2", "01.01.2005", T1, "Trial 1", cmj(28.0)),
    ]))
    outcomes = {o.name: o for o in watch.scan(org, directory=tmp_path, settle=0)}
    assert outcomes["export1_kopie.xlsx"].status == "preskoceno"
    assert "už byl importován" in outcomes["export1_kopie.xlsx"].message
    assert outcomes["export2.xlsx"].status == "ceka"
    assert "nepozná jednoznačně" in outcomes["export2.xlsx"].message
    waiting = outcomes["export2.xlsx"].batch
    assert waiting.status == ImportBatch.Status.PARSED and Subject.objects.count() == 1

    # známý sportovec, ale den není naplánovaný – taky čeká
    _write(tmp_path, "export3.xlsx", forcedecks([
        ("Petr Novák", "uuid-1", "19.05.2003", datetime(2026, 9, 2, 10, 0), "Trial 1", cmj(35.0)),
    ]))
    outcomes = {o.name: o for o in watch.scan(org, directory=tmp_path, settle=0)}
    assert outcomes["export3.xlsx"].status == "ceka" and "naplánovaných" in outcomes["export3.xlsx"].message
    assert not TestSession.objects.filter(subject=subject, date=date(2026, 9, 2)).exists()

    # nerozpoznaný formát se ohlásí a víckrát se nezkouší; čerstvý soubor počká na příště
    _write(tmp_path, "cizi.csv", b"a;b;c\n1;2;3\n")
    _write(tmp_path, "prave_vznika.xlsx", b"PK", old=False)
    outcomes = {o.name: o for o in watch.scan(org, directory=tmp_path, settle=30)}
    assert outcomes["cizi.csv"].status == "chyba" and "nepodařilo rozpoznat" in outcomes["cizi.csv"].message
    assert "prave_vznika.xlsx" not in outcomes
    assert watch.scan(org, directory=tmp_path, settle=30) == []


def test_prikaz_karta_v_importu_a_kroky(lab, tmp_path, settings):
    org, user = lab
    _planned(org)
    _write(tmp_path, "export.xlsx", forcedecks([
        ("Petr Novák", "uuid-1", "19.05.2003", T1, "Trial 1", cmj(31.0))]))
    client = Client()
    client.force_login(user)

    settings.IMPORT_WATCH_DIR = ""
    out = StringIO()
    call_command("hlidat_slozku", "--jednou", stdout=out)
    assert "není nastavená" in out.getvalue()
    page = client.get(reverse("import_list"))
    steps = {s["title"]: s for s in page.context["steps"]}
    assert not steps["Sledovaná složka"]["done"] and steps["Sledovaná složka"]["optional"]
    assert "Nahrávání odpadne" in steps["Sledovaná složka"]["text"]
    assert "IMPORT_WATCH_DIR" in page.content.decode()

    settings.IMPORT_WATCH_DIR = str(tmp_path)
    page = client.get(reverse("import_list"))
    assert "hlídač neběží" in page.content.decode()
    out = StringIO()
    call_command("hlidat_slozku", "--jednou", stdout=out)
    text = out.getvalue()
    assert "Sleduji složku" in text and "export.xlsx: uloženo samo" in text
    assert Measurement.objects.count() > 0

    page = client.get(reverse("import_list"))
    html = page.content.decode()
    steps = {s["title"]: s for s in page.context["steps"]}
    assert steps["Sledovaná složka"]["done"] and "se kontroluje" in steps["Sledovaná složka"]["text"]
    assert "hlídač běží" in html and "uloženo samo" in html and "export.xlsx" in html
    assert "Sledovaná složka" in html   # „Nahrál“ v historii importů
    # raise hodnoty bez pracoviště: příkaz skončí srozumitelně
    Organization.objects.create(name="Druhé", short_name="druhe")
    with pytest.raises(Exception, match="Pracoviště nejde určit"):
        call_command("hlidat_slozku", "--jednou", stdout=StringIO())
