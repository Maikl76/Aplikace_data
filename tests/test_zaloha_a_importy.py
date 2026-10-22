"""Záloha laboratorního počítače, úklid starých importů, audit exportu a zobrazení zprávy."""

import sqlite3
from datetime import date, timedelta

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.utils import timezone

from apps.core.models import AuditLog, Role, User
from apps.ingest import services
from apps.ingest.models import ImportBatch, StagedMeasurement
from apps.measurements.models import RawFile
from tests.test_tym import tym, zmer  # noqa: F401  (fixtura a pomocník)


def test_zaloha_sqlite_env_a_souboru(db, settings, tmp_path):
    """Testovací databáze je v paměti – zálohuje se tu skutečný soubor SQLite vedle ní."""
    settings.BASE_DIR = tmp_path / "app"
    settings.BASE_DIR.mkdir()
    (settings.BASE_DIR / ".env").write_text("IDENTITY_ENCRYPTION_KEY=abc\n")
    settings.MEDIA_ROOT = tmp_path / "media"
    (settings.MEDIA_ROOT / "consents").mkdir(parents=True)
    (settings.MEDIA_ROOT / "consents" / "souhlas.pdf").write_bytes(b"%PDF")
    zdroj = sqlite3.connect(settings.BASE_DIR / "db.sqlite3")
    zdroj.execute("PRAGMA journal_mode=WAL")
    zdroj.execute("create table core_organization (id integer primary key, name text)")
    zdroj.execute("insert into core_organization (name) values ('FTVS')")
    zdroj.commit()                       # spojení zůstane otevřené – jako běžící aplikace

    cil = tmp_path / "zalohy"
    for _ in range(3):
        call_command("zalohovat", cil=str(cil), ponechat=2, databaze="db.sqlite3", verbosity=0)
    zdroj.close()
    slozky = sorted(p for p in cil.iterdir() if p.is_dir())
    assert len(slozky) == 2                                   # starší se mažou
    last = slozky[-1]
    assert (last / ".env").read_text() == "IDENTITY_ENCRYPTION_KEY=abc\n"
    assert (last / "media" / "consents" / "souhlas.pdf").read_bytes() == b"%PDF"
    copy = sqlite3.connect(last / "db.sqlite3")
    assert copy.execute("select count(*) from core_organization").fetchone()[0] == 1
    copy.close()


def _batch(org, user, *, status, days_old, name="export.xlsx"):
    raw = RawFile.objects.create(file=ContentFile(b"data", name=name), original_name=name,
                                 content_hash=name)
    batch = ImportBatch.objects.create(organization=org, raw_file=raw, adapter="vald",
                                       uploaded_by=user, status=status,
                                       summary={"subjects": {"k": {"jmeno": "Jana Nováková"}}})
    StagedMeasurement.objects.create(batch=batch, subject_hint="Nováková Jana", subject_key="k")
    ImportBatch.objects.filter(pk=batch.pk).update(
        created_at=timezone.now() - timedelta(days=days_old))
    return batch


def test_stare_nedokoncene_importy_se_smazou_i_se_souborem(tym):  # noqa: F811
    org, _, _, client = tym
    user = User.objects.get(username="lab")
    stary = _batch(org, user, status=ImportBatch.Status.PARSED, days_old=31, name="a.xlsx")
    zruseny = _batch(org, user, status=ImportBatch.Status.CANCELLED, days_old=40, name="b.xlsx")
    cerstvy = _batch(org, user, status=ImportBatch.Status.PARSED, days_old=3, name="c.xlsx")
    ulozeny = _batch(org, user, status=ImportBatch.Status.COMMITTED, days_old=200, name="d.xlsx")
    soubor = stary.raw_file.file.name
    storage = stary.raw_file.file.storage

    assert client.get("/import/").status_code == 200           # úklid běží při otevření stránky
    zbyle = set(ImportBatch.objects.values_list("pk", flat=True))
    assert zbyle == {cerstvy.pk, ulozeny.pk}
    assert not RawFile.objects.filter(original_name__in=["a.xlsx", "b.xlsx"]).exists()
    assert not storage.exists(soubor)
    assert not StagedMeasurement.objects.filter(subject_hint="Nováková Jana",
                                                batch__in=[stary.pk, zruseny.pk]).exists()
    assert services.expire_stale() == 0


def test_export_csv_a_zobrazeni_zpravy_jsou_v_auditu(tym):  # noqa: F811
    from apps.reports import services as reports

    org, battery, hraci, client = tym
    zmer(hraci[0], date(2026, 9, 1), "cmj_height", [35.5])
    client.get(f"/tym/?baterie={battery.pk}&format=csv")
    export = AuditLog.objects.get(action=AuditLog.Action.EXPORT)
    assert export.object_type == "TestBattery" and "FTVS-0001" in export.detail["sportovci"]

    session = hraci[0].sessions.get()
    report = reports.build_draft(session, user=User.objects.get(username="lab"))
    client.get(f"/zpravy/{report.pk}/")
    assert AuditLog.objects.filter(action=AuditLog.Action.VIEW, object_type="Report",
                                   object_id=str(report.pk), subject_code="FTVS-0001").exists()


def test_vyzkumnik_ma_v_auditu_jen_cteni(tym):  # noqa: F811
    org, battery, hraci, _ = tym
    from django.test import Client

    c = Client()
    c.force_login(User.objects.create(username="v", organization=org, role=Role.RESEARCHER))
    assert c.get(f"/tym/?baterie={battery.pk}&format=csv").status_code == 200
    assert AuditLog.objects.filter(action=AuditLog.Action.EXPORT, user__username="v").exists()
