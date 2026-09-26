"""
Testy ukázkového režimu.

Ukázka běží na veřejné adrese, takže tyhle dvě pojistky musí držet:
nesmí tam vzniknout účet se známým heslem a nesmí tam jít nahrát soubor.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command

from apps.core.models import Organization, Role, User
from apps.ingest.models import ImportBatch


@pytest.fixture
def uzivatel(db):
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    return User.objects.create(username="laborant", organization=org, role=Role.LAB)


@pytest.mark.parametrize("demo,debug,ocekavano", [
    (False, True, True),    # vývoj na vlastním stroji – výchozí heslo se založí
    (True, True, False),    # ukázka, i když běží ve vývojovém nastavení
    (False, False, False),  # ostrý provoz
])
def test_slabe_heslo_jen_pri_vyvoji(db, settings, monkeypatch, demo, debug, ocekavano):
    # Výsledek nesmí záviset na tom, co má vývojář nastavené u sebe.
    monkeypatch.delenv("DEMO_ADMIN_PASSWORD", raising=False)
    settings.DEMO_MODE = demo
    settings.DEBUG = debug
    call_command("seed_demo", subjects=1, sessions=1, verbosity=0)

    spravce = User.objects.filter(username="admin").first()
    if not ocekavano:
        # Buď účet nevznikl vůbec, nebo rozhodně ne s výchozím heslem.
        assert spravce is None or not spravce.check_password("demo-heslo-1234")
    else:
        assert spravce.check_password("demo-heslo-1234")


def test_zadane_heslo_se_pouzije(db, settings):
    settings.DEMO_MODE = True
    call_command("seed_demo", subjects=1, sessions=1,
                 admin_password="Jine-silne-heslo-99", verbosity=0)

    spravce = User.objects.get(username="admin")
    assert spravce.check_password("Jine-silne-heslo-99")
    assert not spravce.check_password("demo-heslo-1234")


def test_v_ukazce_nelze_nahrat_soubor(client, uzivatel, settings):
    settings.DEMO_MODE = True
    client.force_login(uzivatel)

    client.post("/import/nahrat/", {
        "file": SimpleUploadedFile("data.xlsx", b"PK\x03\x04"),
        "adapter": "legacy_excel",
    })
    assert ImportBatch.objects.count() == 0


def test_mimo_ukazku_se_soubor_zpracuje(client, uzivatel, settings):
    """Kontrola, že pojistka nevypíná import i tam, kde má fungovat."""
    settings.DEMO_MODE = False
    client.force_login(uzivatel)

    client.post("/import/nahrat/", {
        "file": SimpleUploadedFile("data.xlsx", b"PK\x03\x04"),
        "adapter": "legacy_excel",
    })
    # Soubor je nesmyslný, takže import skončí chybou – ale vznikl,
    # což znamená, že se k adaptéru vůbec dostal.
    assert ImportBatch.objects.count() == 1


def test_varovny_pruh_jen_v_ukazce(client, uzivatel, settings):
    client.force_login(uzivatel)

    settings.DEMO_MODE = True
    assert "Nevkládejte sem reálná data" in client.get("/sportovci/").content.decode()

    settings.DEMO_MODE = False
    assert "Nevkládejte sem reálná data" not in client.get("/sportovci/").content.decode()


def test_zdravotni_endpoint_hlasi_databazi(client, db):
    odpoved = client.get("/zdravi/")
    assert odpoved.status_code == 200
    assert odpoved.json() == {"stav": "ok", "databaze": "ok"}


def test_bootstrap_naplni_prazdnou_instanci(db, settings):
    from apps.subjects.models import Subject

    settings.DEMO_MODE = True
    call_command("bootstrap_demo", subjects=2, sessions=1, verbosity=0)
    assert Subject.objects.count() == 2


def test_bootstrap_uz_naplnenou_instanci_nechá_být(db, settings):
    """Pouští se při každém nasazení, takže nesmí data přepsat."""
    from apps.subjects.models import Subject

    settings.DEMO_MODE = True
    call_command("bootstrap_demo", subjects=2, sessions=1, verbosity=0)
    Subject.objects.filter(code="FTVS-0001").update(note="ruční zásah")

    call_command("bootstrap_demo", subjects=9, sessions=3, verbosity=0)

    assert Subject.objects.count() == 2
    assert Subject.objects.get(code="FTVS-0001").note == "ruční zásah"


def test_bootstrap_mimo_ukazku_nedela_nic(db, settings):
    from apps.subjects.models import Subject

    settings.DEMO_MODE = False
    call_command("bootstrap_demo", verbosity=0)
    assert Subject.objects.count() == 0


def test_prihlasovaci_pole_jsou_videt(client, db):
    """Pole bez stylu je neviditelné – heslo nesmí vypadat, že chybí."""
    html = client.get("/ucet/prihlaseni/").content.decode()
    assert 'type="password"' in html
    assert html.count('class="input mt-1"') >= 2


def test_spatne_heslo_rekne_proc(client, uzivatel):
    uzivatel.set_password("spravne-heslo-123")
    uzivatel.save()
    html = client.post("/ucet/prihlaseni/", {
        "username": uzivatel.username, "password": "spatne",
    }).content.decode()
    assert "nesedí" in html


def test_spravne_heslo_prihlasi(client, uzivatel):
    uzivatel.set_password("spravne-heslo-123")
    uzivatel.save()
    odpoved = client.post("/ucet/prihlaseni/", {
        "username": uzivatel.username, "password": "spravne-heslo-123",
    })
    assert odpoved.status_code == 302
