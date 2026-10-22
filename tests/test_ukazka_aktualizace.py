"""
Aktualizace ukázky na PythonAnywhere nesmí přijít o data: režim deníku
SQLite podle disku, záloha s popisem, ukázkové účty bez mazání.
"""

import importlib
import sqlite3
import sys
from types import SimpleNamespace

import pytest
from django.core.management import call_command

from apps.core import sqlite as journal
from apps.core.models import Organization, Role, User
from apps.subjects.models import Guardian, Sharing, Subject, SubjectIdentity

# --- režim deníku ------------------------------------------------------------

def _db(path, mode):
    raw = sqlite3.connect(path, isolation_level=None)
    raw.execute(f"PRAGMA journal_mode={mode}")
    raw.execute("create table if not exists t(x)")
    raw.execute("insert into t values (1)")
    return raw


def test_wal_se_na_sitovem_disku_vrati_do_klasickeho_rezimu(tmp_path, settings):
    settings.SQLITE_WAL = False
    path = tmp_path / "db.sqlite3"
    _db(path, "wal").close()
    raw = sqlite3.connect(path, isolation_level=None)
    other = sqlite3.connect(path, isolation_level=None)
    other.execute("select * from t").fetchall()            # jiný proces má databázi otevřenou
    assert journal.set_journal_mode(raw) == "wal"            # bez chyby, zkusí se příště
    other.close()
    assert journal.set_journal_mode(raw) == "delete"
    assert raw.execute("select count(*) from t").fetchone()[0] == 1   # data zůstala
    raw.close()
    assert not (tmp_path / "db.sqlite3-wal").exists()


def test_wal_na_mistnim_disku_a_databaze_v_pameti(tmp_path, settings):
    settings.SQLITE_WAL = True
    raw = _db(tmp_path / "db.sqlite3", "delete")
    journal.on_connection_created(None, SimpleNamespace(vendor="sqlite", connection=raw))
    assert raw.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    raw.close()
    memory = sqlite3.connect(":memory:", isolation_level=None)
    assert journal.set_journal_mode(memory) == "memory"


def test_prikaz_rezim_databaze(db, capsys):
    call_command("rezim_databaze", opakovat=1)
    assert "Režim databáze: memory" in capsys.readouterr().out


def _load(module, monkeypatch, **env):
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    for name in ("config.settings.base", module):
        sys.modules.pop(name, None)
    return importlib.import_module(module)


def test_wal_vychozi_jen_na_windows(monkeypatch):
    base = _load("config.settings.base", monkeypatch, SQLITE_WAL=None)
    assert base.SQLITE_WAL is (__import__("os").name == "nt")
    assert "init_command" not in base.DATABASES["default"].get("OPTIONS", {})
    assert _load("config.settings.base", monkeypatch, SQLITE_WAL="True").SQLITE_WAL is True
    assert _load("config.settings.base", monkeypatch, SQLITE_WAL="False").SQLITE_WAL is False


# --- záloha s popisem --------------------------------------------------------------

def test_zaloha_s_popisem(db, settings, tmp_path):
    settings.BASE_DIR = tmp_path
    settings.MEDIA_ROOT = tmp_path / "media"
    _db(tmp_path / "db.sqlite3", "delete").close()
    cil = tmp_path / "zalohy"
    for _ in range(2):
        call_command("zalohovat", cil=str(cil), databaze="db.sqlite3",
                     popis="před aktualizací", verbosity=0)
    names = sorted(p.name for p in cil.iterdir())
    assert len(names) == 2 and all("-pred-aktualizaci" in n for n in names)


# --- ukázkové účty bez mazání --------------------------------------------------------

@pytest.fixture
def ukazka(db, settings):
    from cryptography.fernet import Fernet

    settings.DEMO_MODE = True
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    for i in (1, 2, 3):
        Subject.objects.create(organization=org, code=f"FTVS-{i:04d}")
    return org


def test_ukazkove_ucty_dopln_bez_mazani(ukazka, capsys):
    kolega = User.objects.create(username="kolega", organization=ukazka, role=Role.LAB)
    call_command("ukazkove_ucty", heslo="ukazka-heslo-12345")
    assert "založeno sportovec, rodic, trener" in capsys.readouterr().out
    assert User.objects.get(username="sportovec").check_password("ukazka-heslo-12345")
    assert SubjectIdentity.objects.get(subject__code="FTVS-0001").user.username == "sportovec"
    assert Guardian.objects.get().identity.subject.code == "FTVS-0002"
    assert Sharing.objects.filter(status=Sharing.Status.ACTIVE).count() == 2
    # Podruhé nic nového a na existující účty nesahá.
    call_command("ukazkove_ucty", heslo="jine-heslo-123456")
    assert "už jsou" in capsys.readouterr().out
    assert User.objects.get(username="sportovec").check_password("ukazka-heslo-12345")
    assert User.objects.filter(pk=kolega.pk).exists() and User.objects.count() == 4


def test_ukazkove_ucty_nesahaji_na_cizi_ucet_se_stejnym_jmenem(ukazka):
    trener = User.objects.create(username="trener", organization=ukazka, role=Role.LAB)
    call_command("ukazkove_ucty", heslo="ukazka-heslo-12345", verbosity=0)
    trener.refresh_from_db()
    assert trener.role == Role.LAB and not Sharing.objects.exists()
    assert User.objects.filter(username__in=["sportovec", "rodic"]).count() == 2


def test_ukazkove_ucty_jen_v_ukazce(ukazka, settings, capsys):
    settings.DEMO_MODE = False
    call_command("ukazkove_ucty", heslo="ukazka-heslo-12345")
    assert "Jen v ukázce" in capsys.readouterr().out and not User.objects.exists()
