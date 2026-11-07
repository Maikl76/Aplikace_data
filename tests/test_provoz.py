"""
Dávka 10: provozní automatizace – denní údržba (záloha, úklid starých importů,
připomínky měření), týdenní stav správci e-mailem bez jmen, stránka Provoz
a zálohy, krok ve Stavu pracoviště, příkaz udrzba a pojistka z Přehledu.
"""

import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core import mail
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.core import backup, maintenance
from apps.core.models import Organization, Role, User
from apps.core.workplace import workplace_steps
from apps.ingest.models import ImportBatch
from tests.test_zaloha_a_importy import _batch

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def org(db, settings, tmp_path, monkeypatch):
    settings.EMAIL_HOST = "smtp.test"
    settings.STATUS_MAIL_WEEKDAY = timezone.localdate().weekday()

    def fake_backup(*, root=None, keep=10, label="", database=None):
        target = Path(root) / f"ftvs-zaloha-test-{label}"
        target.mkdir(parents=True, exist_ok=True)
        (target / "db.sqlite3").write_bytes(b"x" * 1000)
        return backup.BackupResult(target, 0.001, 0, True, 0)

    monkeypatch.setattr(backup, "backup_sqlite", fake_backup)
    monkeypatch.setattr(backup, "default_root", lambda: tmp_path / "zalohy")
    monkeypatch.setattr(maintenance.shutil, "disk_usage",
                        lambda path: SimpleNamespace(free=50e9, total=100e9, used=50e9))
    return Organization.objects.create(name="FTVS", short_name="ftvs")


def _user(org, role, username, email=""):
    user = User.objects.create(username=username, organization=org, role=role, email=email,
                               is_staff=role == Role.ADMIN)
    client = Client()
    client.force_login(user)
    return user, client


def test_denni_udrzba_zaloha_uklid_pripominky_a_stav_spravci(org):
    admin, _ = _user(org, Role.ADMIN, "spravce", "spravce@example.cz")
    lab, _ = _user(org, Role.LAB, "lab")
    old = _batch(org, lab, status=ImportBatch.Status.PARSED, days_old=31, name="a.xlsx")
    fresh = _batch(org, lab, status=ImportBatch.Status.PARSED, days_old=1, name="b.xlsx")
    today = timezone.localdate()

    out = maintenance.daily(org)
    assert out.log["zaloha"]["ok"] and out.log["importy_smazano"] == 1
    assert not ImportBatch.objects.filter(pk=old.pk).exists()
    assert ImportBatch.objects.filter(pk=fresh.pk).exists()
    org.refresh_from_db()
    assert org.maintenance_at and org.backup_at and "ftvs-zaloha-test-denni" in org.backup_note
    assert org.reminders_checked_on == today
    # stav správci: dnes je jeho den → odešel, jen správci, bez jmen
    assert org.status_mailed_on == today and len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["spravce@example.cz"] and "Stav pracoviště FTVS" in message.subject
    assert "Nováková" not in message.body and "Záloha: naposledy" in message.body
    assert "Čeká:" in message.body and "Chyby za týden: žádné" in message.body
    # podruhé týž den nic; znovu jen s force, stav podruhé neodejde
    assert maintenance.daily(org) is None
    assert maintenance.daily(org, force=True) is not None and len(mail.outbox) == 1

    info = maintenance.status(org)
    assert info["warnings"] == [] and info["backup"]["ok"] and info["errors"] == []
    steps = {s["title"]: s for s in workplace_steps(admin)}
    assert steps["Provoz a zálohy"]["done"] and "Záloha" in steps["Provoz a zálohy"]["text"]


def test_selhana_zaloha_je_videt_ve_stavu_i_v_kroku(org, monkeypatch):
    admin, _ = _user(org, Role.ADMIN, "spravce")

    def failing(**kwargs):
        raise backup.BackupError("disk je plný")

    monkeypatch.setattr(backup, "backup_sqlite", failing)
    out = maintenance.daily(org)
    assert out.log["zaloha"] == {"ok": False, "chyba": "disk je plný"}
    info = maintenance.status(org)
    assert any("selhala" in w for w in info["warnings"]) and "záloha selhala" in info["errors"]
    steps = {s["title"]: s for s in workplace_steps(admin)}
    assert not steps["Provoz a zálohy"]["done"] and "selhala" in steps["Provoz a zálohy"]["text"]
    # ještě nikdy neběžela = taky varování
    fresh = Organization.objects.create(name="Druhé", short_name="druhe")
    assert "Denní údržba ještě neběžela." in maintenance.status(fresh)["warnings"]


def test_stranka_provoz_a_prikaz_udrzba(org):
    _, admin = _user(org, Role.ADMIN, "spravce", "spravce@example.cz")
    _, lab = _user(org, Role.LAB, "laborant")
    page = admin.get(reverse("operations")).content.decode()
    assert "Provoz a zálohy" in page and "Zálohovat teď" in page and "Co správce dostane" in page
    assert "Denní údržba ještě neproběhla" in page or "neběžela" in page
    lab_page = lab.get(reverse("operations")).content.decode()
    assert "Zálohovat teď" not in lab_page and "spouští ručně správce" in lab_page
    assert lab.post(reverse("operations"), {"akce": "stav"}).status_code == 403

    text = admin.post(reverse("operations"), {"akce": "stav"}, follow=True).content.decode()
    assert len(mail.outbox) == 1 and "odešel správci (1 adres)" in text
    text = admin.post(reverse("operations"), {"akce": "zaloha"}, follow=True).content.decode()
    org.refresh_from_db()
    assert org.backup_at and "Záloha hotová" in text and "rucni" in org.backup_note
    admin.post(reverse("operations"), {"akce": "udrzba"})
    org.refresh_from_db()
    assert org.maintenance_at and org.maintenance_log["zaloha"]["ok"]

    out = io.StringIO()
    call_command("udrzba", "--jednou", stdout=out)
    assert "dnes už údržba proběhla" in out.getvalue()
    call_command("udrzba", "--jednou", "--znovu", stdout=out)
    assert "záloha" in out.getvalue() and "ftvs-zaloha-test-denni" in out.getvalue()
    call_command("udrzba", "--stav", stdout=out)
    assert len(mail.outbox) == 2 and "odeslán (1 adres)" in out.getvalue()


def test_prehled_spusti_udrzbu_jako_pojistku(org, settings):
    _, lab = _user(org, Role.LAB, "laborant")
    lab.get(reverse("dashboard"))
    org.refresh_from_db()
    assert org.maintenance_at is not None and org.reminders_checked_on == timezone.localdate()

    settings.MAINTENANCE_IN_WEB = False
    org.maintenance_at = None
    org.reminders_checked_on = None
    org.save()
    lab.get(reverse("dashboard"))
    org.refresh_from_db()
    assert org.maintenance_at is None and org.reminders_checked_on == timezone.localdate()


def test_spustit_bat_spousti_udrzbu():
    text = (ROOT / "spustit.bat").read_text()
    assert 'start "Denni udrzba" /min python manage.py udrzba' in text
    assert "pripomenout_mereni" not in text
