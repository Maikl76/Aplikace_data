"""Účet bez pracoviště: dřív prázdná aplikace a chyba při přidání sportu i sportovce."""

import importlib

from django.contrib.admin.sites import site
from django.core.management import call_command
from django.test import Client, RequestFactory

from apps.core.models import Organization, Role, User
from apps.subjects.models import Sport, Subject


def test_jedine_pracoviste_se_uctu_doplni_samo(db):
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    user = User.objects.create_user("novy", password="dlouhe-heslo-123")       # bez organizace
    assert user.organization == org
    admin = User.objects.create_superuser("spravce", "s@example.cz", "dlouhe-heslo-123")
    assert admin.organization == org
    # Uložení jen některých polí pracoviště taky doplní.
    User.objects.filter(pk=user.pk).update(organization=None)
    user.refresh_from_db()
    user.save(update_fields=["last_login"])
    user.refresh_from_db()
    assert user.organization == org


def test_pri_vice_pracovistich_se_nehada(db):
    Organization.objects.create(name="FTVS", short_name="ftvs")
    Organization.objects.create(name="Jiná", short_name="jina")
    assert User.objects.create_user("novy", password="dlouhe-heslo-123").organization is None


def test_migrace_doplni_pracoviste_existujicim_uctum(db):
    from django.apps import apps

    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    user = User.objects.create_user("stary", password="dlouhe-heslo-123")
    User.objects.filter(pk=user.pk).update(organization=None)
    migration = importlib.import_module("apps.core.migrations.0003_ucty_bez_pracoviste")
    migration.assign_single_organization(apps, None)
    user.refresh_from_db()
    assert user.organization == org


def test_ucet_vidi_data_a_prida_sport_i_sportovce(db, settings):
    from cryptography.fernet import Fernet

    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    Subject.objects.create(organization=org, code="FTVS-0001")
    user = User.objects.create_user("lab", password="dlouhe-heslo-123", role=Role.LAB)
    client = Client()
    client.force_login(user)
    assert "FTVS-0001" in client.get("/sportovci/").content.decode()
    assert client.post("/sporty/", {"name": "Florbal"}).status_code == 302
    assert Sport.objects.filter(organization=org, name="Florbal").exists()
    response = client.post("/sportovci/novy/", {
        "first_name": "Karel", "last_name": "Test", "birth_date": "2001-02-03", "sex": "M",
        "sport": Sport.objects.get().pk, "level": "trained", "consents": ["testing"]})
    assert response.status_code == 302 and client.get(response.url).status_code == 200


def test_ucet_bez_pracoviste_pri_vice_pracovistich_dostane_vysvetleni(db):
    Organization.objects.create(name="FTVS", short_name="ftvs")
    Organization.objects.create(name="Jiná", short_name="jina")
    user = User.objects.create_user("lab", password="dlouhe-heslo-123", role=Role.LAB)
    client = Client()
    client.force_login(user)
    response = client.post("/sporty/", {"name": "Florbal"}, follow=True)
    assert response.status_code == 200 and "nemá přiřazené pracoviště" in response.content.decode()
    assert not Sport.objects.exists()


def test_v_administraci_je_pracoviste_povinne(db):
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    request = RequestFactory().get("/admin/core/user/add/")
    request.user = User.objects.create_superuser("spravce", "s@example.cz", "dlouhe-heslo-123")
    form = site._registry[User].get_form(request)
    assert form.base_fields["organization"].required
    assert form.base_fields["organization"].initial == org


def test_kontrola_ukazky(db, capsys):
    Organization.objects.create(name="FTVS", short_name="ftvs")
    call_command("kontrola_ukazky")
    out = capsys.readouterr().out
    assert "Zápis do databáze: funguje." in out and "vše v pořádku" in out
    User.objects.create_user("x", password="dlouhe-heslo-123")
    User.objects.filter(username="x").update(organization=None)
    call_command("kontrola_ukazky")
    out = capsys.readouterr().out
    assert "Účty bez pracoviště" in out and "x" in out and "problémů 1" in out
