"""Role v aplikaci, zámek po špatném hesle, dokument souhlasu, povinný tajný klíč."""

import importlib
import sys
from datetime import timedelta

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import Client, override_settings
from django.utils import timezone

from apps.core.models import AuditLog, Organization, Role, User
from apps.subjects.models import Consent, Sport, Subject


@pytest.fixture
def org(db):
    return Organization.objects.create(name="FTVS", short_name="ftvs")


def _user(org, role, username=None):
    user = User.objects.create(username=username or f"u-{role}", organization=org, role=role)
    user.set_password("tajne-heslo-1234")
    user.save()
    return user


# --- role ------------------------------------------------------------------

@pytest.mark.parametrize("role", [Role.COACH])
def test_trener_se_zatim_neprihlasi(client, org, role):
    user = _user(org, role)
    response = client.post("/ucet/prihlaseni/", {"username": user.username,
                                                 "password": "tajne-heslo-1234"})
    assert response.status_code == 200
    assert "zatím nejsou v provozu" in response.content.decode()
    # Ani s už existujícím přihlášením se do aplikace nedostane.
    client.force_login(user)
    response = client.get("/", follow=True)
    assert response.redirect_chain[0][0].startswith("/ucet/prihlaseni/")
    assert "zatím nejsou v provozu" in response.content.decode()


def test_vyzkumnik_jen_cte(client, org):
    sport = Sport.objects.create(organization=org, code="tenis", name="Tenis")
    client.force_login(_user(org, Role.RESEARCHER))
    page = client.get("/sportovci/")
    assert page.status_code == 200 and "jen čtení" in page.content.decode()

    response = client.post("/sportovci/novy/", {"code": "FTVS-0001", "sport": sport.pk})
    assert response.status_code == 403 and "Jen čtení" in response.content.decode()
    assert not Subject.objects.exists()
    # Odhlásit se smí.
    assert client.post("/ucet/odhlaseni/").status_code == 302


def test_laborant_smi_zapisovat(client, org):
    client.force_login(_user(org, Role.LAB))
    assert client.post("/mereni/novy/", {}).status_code == 200    # formulář s chybami, ne 403


# --- zámek po špatném hesle --------------------------------------------------

@override_settings(AXES_ENABLED=True, AXES_FAILURE_LIMIT=3)
def test_po_spatnych_pokusech_se_ucet_zamkne(org):
    from axes.models import AccessAttempt

    user = _user(org, Role.LAB)
    client = Client()
    for _ in range(3):
        client.post("/ucet/prihlaseni/", {"username": user.username, "password": "spatne"})
    response = client.post("/ucet/prihlaseni/", {"username": user.username,
                                                 "password": "tajne-heslo-1234"})
    assert response.status_code == 429          # django-axes: Too Many Requests
    assert "dočasně zamčené" in response.content.decode()
    assert AccessAttempt.objects.filter(username=user.username).exists()

    # Z jiné adresy (jiný počítač) účet zamčený není.
    other = Client(REMOTE_ADDR="10.0.0.9")
    response = other.post("/ucet/prihlaseni/", {"username": user.username,
                                                "password": "tajne-heslo-1234"})
    assert response.status_code == 302


# --- dokument souhlasu --------------------------------------------------------

def test_dokument_souhlasu_jen_pres_aplikaci(client, org, settings, tmp_path):
    from cryptography.fernet import Fernet

    settings.MEDIA_ROOT = tmp_path
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    sport = Sport.objects.create(organization=org, code="tenis", name="Tenis")
    subject = Subject.objects.create(organization=org, code="FTVS-0001", sport=sport)
    consent = Consent.objects.create(subject=subject, scope=Consent.Scope.TESTING,
                                     granted_on=timezone.localdate() - timedelta(days=1))
    consent.document.save("souhlas.pdf", ContentFile(b"%PDF-1.4 test"))

    lab = _user(org, Role.LAB)
    client.force_login(lab)
    page = client.get(f"/sportovci/{subject.pk}/upravit/").content.decode()
    assert f"/sportovci/souhlas/{consent.pk}/dokument/" in page
    response = client.get(f"/sportovci/souhlas/{consent.pk}/dokument/")
    assert response.status_code == 200
    assert b"".join(response.streaming_content).startswith(b"%PDF")
    assert AuditLog.objects.filter(action=AuditLog.Action.EXPORT, object_type="Consent",
                                   subject_code="FTVS-0001").exists()

    # Přímá adresa /media/ nic nevydá a výzkumník dokument neotevře.
    assert client.get(consent.document.url).status_code == 404
    client.force_login(_user(org, Role.RESEARCHER))
    assert client.get(f"/sportovci/souhlas/{consent.pk}/dokument/").status_code == 403

    # Cizí organizace souhlas nevidí.
    other = Organization.objects.create(name="Jiná", short_name="jina")
    client.force_login(_user(other, Role.ADMIN, "cizi"))
    assert client.get(f"/sportovci/souhlas/{consent.pk}/dokument/").status_code == 404


# --- nastavení ------------------------------------------------------------------

def _load(module, monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for name in ("config.settings.base", module):
        sys.modules.pop(name, None)
    return importlib.import_module(module)


def test_produkce_vyzaduje_tajny_klic(monkeypatch):
    for bad in ("", "zmente-me-na-nahodny-retezec", "VLOZTE_VYGENEROVANY_KLIC", "kratky"):
        with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY"):
            _load("config.settings.prod", monkeypatch, DJANGO_SECRET_KEY=bad,
                  DJANGO_ALLOWED_HOSTS="ukazka.cz")
    prod = _load("config.settings.prod", monkeypatch, DJANGO_SECRET_KEY="x" * 50,
                 DJANGO_ALLOWED_HOSTS="ukazka.cz")
    assert prod.SECRET_KEY == "x" * 50 and prod.DEBUG is False


def test_laborator_vypne_ladici_rezim_promennou(monkeypatch):
    dev = _load("config.settings.dev", monkeypatch, DJANGO_DEBUG="False")
    assert dev.DEBUG is False
    assert dev.STORAGES["staticfiles"]["BACKEND"].endswith("CompressedStaticFilesStorage")
    assert dev.WHITENOISE_USE_FINDERS is True
    dev = _load("config.settings.dev", monkeypatch, DJANGO_DEBUG="True")
    assert dev.DEBUG is True


def test_zajisti_klic_doplni_oba_klice(settings, tmp_path):
    settings.BASE_DIR = tmp_path
    env = tmp_path / ".env"
    env.write_text("DJANGO_SECRET_KEY=zmente-me-na-nahodny-retezec\nDJANGO_DEBUG=True\n")
    call_command("zajisti_klic", verbosity=0)
    text = env.read_text()
    assert "zmente-me" not in text and "IDENTITY_ENCRYPTION_KEY=" in text
    secret = next(line for line in text.splitlines() if line.startswith("DJANGO_SECRET_KEY="))
    assert len(secret) > 50
    call_command("zajisti_klic", verbosity=0)
    assert env.read_text() == text          # podruhé se nic nemění
