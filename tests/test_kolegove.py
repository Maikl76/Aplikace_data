"""
Účty kolegů: správce založí účet s rolí a předá jednorázový odkaz, kterým si
kolega nastaví heslo. Bez poštovního serveru, bez administrace.
"""

import re

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from apps.core import colleagues
from apps.core.models import AuditLog, Organization, Role, User

HESLO = "Silne-heslo-kolegy-2026"


@pytest.fixture
def org(db):
    call_command("seed_roles", verbosity=0)
    return Organization.objects.create(name="FTVS", short_name="ftvs")


def _user(org, role, username, **extra):
    user = User.objects.create(username=username, organization=org, role=role, **extra)
    client = Client()
    client.force_login(user)
    return user, client


def _link(html: str) -> str:
    match = re.search(r'value="(http://testserver/ucet/nastavit-heslo/[^"]+)"', html)
    assert match, "stránka neukázala odkaz"
    return match.group(1)


def _novy(client, **data):
    base = {"akce": "novy", "first_name": "Eva", "last_name": "Metodička", "role": Role.LAB,
            "username": "", "email": ""}
    return client.post(reverse("colleagues"), {**base, **data}, follow=True)


def test_spravce_zalozi_kolegu_a_dostane_odkaz(org):
    admin, client = _user(org, Role.ADMIN, "spravce")
    page = _novy(client, email="Eva@Example.cz")
    assert page.status_code == 200
    user = User.objects.get(username="eva.metodicka")
    # do administrace Djanga smí jen správce; laborant má přístup jen v aplikaci
    assert (user.role, user.organization, user.is_staff, user.is_active) == (Role.LAB, org, False, True)
    assert user.email == "eva@example.cz" and not user.has_usable_password()
    assert list(user.groups.values_list("name", flat=True)) == ["Diagnostik"]
    html = page.content.decode()
    assert "eva.metodicka" in html and "čeká na heslo" in html
    link = _link(html)
    assert colleagues.user_from_password_link(link.rsplit("/", 2)[1]) == user
    assert AuditLog.objects.filter(action=AuditLog.Action.CREATE, object_type="User").exists()
    # odkaz se ukáže jen jednou; další načtení stránky ho neopakuje
    assert "nastavit-heslo" not in client.get(reverse("colleagues")).content.decode()


def test_odkaz_nastavi_heslo_jen_jednou_a_prihlasi(org):
    _, client = _user(org, Role.ADMIN, "spravce")
    link = _link(_novy(client).content.decode())
    user = User.objects.get(username="eva.metodicka")

    kolega = Client()
    page = kolega.get(link)
    assert page.status_code == 200 and "Nastavení hesla" in page.content.decode()
    assert "eva.metodicka" in page.content.decode()
    html = kolega.post(link, {"password1": HESLO, "password2": "jine"}).content.decode()
    assert "neshodují" in html
    html = kolega.post(link, {"password1": "kratke", "password2": "kratke"}).content.decode()
    assert "12" in html  # příliš krátké
    resp = kolega.post(link, {"password1": HESLO, "password2": HESLO})
    assert resp.status_code == 302 and resp.url == reverse("dashboard")
    user.refresh_from_db()
    assert user.check_password(HESLO)
    assert kolega.get(reverse("dashboard")).status_code == 200  # přihlášený
    # odkaz je spotřebovaný
    assert Client().get(link).status_code == 410
    assert Client().login(username="eva.metodicka", password=HESLO)
    # cizí nebo pozměněný odkaz neplatí
    assert Client().get(link[:-6] + "xxxxx/").status_code == 410


def test_trener_dostane_portal_bez_administrace(org):
    _, client = _user(org, Role.ADMIN, "spravce")
    link = _link(_novy(client, first_name="Karel", last_name="Trenér", role=Role.COACH)
                 .content.decode())
    user = User.objects.get(username="karel.trener")
    assert user.role == Role.COACH and not user.is_staff and not user.groups.exists()
    kolega = Client()
    kolega.post(link, {"password1": HESLO, "password2": HESLO})
    resp = kolega.get(reverse("dashboard"))
    assert resp.status_code == 302 and resp.url == reverse("coach_home")


def test_kolegove_jen_pro_spravce(org):
    for role in (Role.LAB, Role.RESEARCHER):
        _, client = _user(org, role, f"ucet-{role}")
        assert client.get(reverse("colleagues")).status_code == 403
    assert Client().get(reverse("colleagues")).status_code == 302
    _, client = _user(org, Role.LAB, "laborant")
    assert client.post(reverse("colleagues"), {"akce": "novy", "first_name": "X",
                                               "last_name": "Y", "role": Role.LAB}).status_code == 403
    assert not User.objects.filter(username="x.y").exists()
    # nabídka v menu jen správci
    _, admin_client = _user(org, Role.ADMIN, "spravce")
    assert 'href="/kolegove/"' in admin_client.get(reverse("dashboard")).content.decode()
    assert 'href="/kolegove/"' not in client.get(reverse("dashboard")).content.decode()


def test_prihlasovaci_jmeno_navrh_a_kolize(org):
    _, client = _user(org, Role.ADMIN, "spravce")
    _novy(client, first_name="Jana", last_name="Nováková")
    _novy(client, first_name="Jana", last_name="Nováková")
    assert User.objects.filter(username__in=["jana.novakova", "jana.novakova2"]).count() == 2
    html = _novy(client, first_name="Petr", last_name="Nový", username="jana.novakova").content.decode()
    assert "už někdo má" in html and not User.objects.filter(first_name="Petr").exists()
    html = _novy(client, first_name="Petr", last_name="Nový", username="Petr Nový").content.decode()
    assert "bez diakritiky" in html and not User.objects.filter(first_name="Petr").exists()
    html = _novy(client, first_name="", last_name="Nový").content.decode()
    assert "povinn" in html.lower() and not User.objects.filter(last_name="Nový").exists()
    assert not User.objects.filter(role=Role.ATHLETE).exists()
    html = _novy(client, first_name="Jan", last_name="Sportovec", role=Role.ATHLETE).content.decode()
    assert not User.objects.filter(last_name="Sportovec").exists()


def test_vypnuti_zapnuti_a_novy_odkaz(org):
    admin, client = _user(org, Role.ADMIN, "spravce")
    kolega, _ = _user(org, Role.LAB, "laborant")
    kolega.set_password("Stare-heslo-1234567")
    kolega.save()
    url = reverse("colleagues")

    client.post(url, {"akce": "vypnout", "ucet": kolega.pk})
    kolega.refresh_from_db()
    assert not kolega.is_active
    assert not Client().login(username="laborant", password="Stare-heslo-1234567")
    assert colleagues.user_from_password_link(colleagues.password_link_token(kolega)) is None
    assert "vypnutý" in client.get(url).content.decode()

    client.post(url, {"akce": "zapnout", "ucet": kolega.pk})
    kolega.refresh_from_db()
    assert kolega.is_active

    # nový odkaz = zapomenuté heslo bez e‑mailu; po nastavení staré heslo neplatí
    link = _link(client.post(url, {"akce": "odkaz", "ucet": kolega.pk}, follow=True).content.decode())
    Client().post(link, {"password1": HESLO, "password2": HESLO})
    assert Client().login(username="laborant", password=HESLO)
    assert not Client().login(username="laborant", password="Stare-heslo-1234567")

    # sám sebe správce nevypne
    client.post(url, {"akce": "vypnout", "ucet": admin.pk})
    admin.refresh_from_db()
    assert admin.is_active
    # účet jiného pracoviště není vidět ani ovladatelný
    jine = Organization.objects.create(name="Jiné", short_name="jine")
    cizi = User.objects.create(username="cizi", organization=jine, role=Role.LAB)
    assert client.post(url, {"akce": "vypnout", "ucet": cizi.pk}).status_code == 404
    assert "cizi" not in client.get(url).content.decode()


def test_skupiny_se_srovnaji_i_pri_zmene_role_v_administraci(org):
    """Stejné srovnání skupin používá administrace i stránka Kolegové."""
    from apps.core.roles import sync_groups

    user = User.objects.create(username="u", organization=org, role=Role.LAB)
    sync_groups(user)
    assert list(user.groups.values_list("name", flat=True)) == ["Diagnostik"]
    user.role = Role.RESEARCHER
    sync_groups(user)
    assert list(user.groups.values_list("name", flat=True)) == ["Výzkumník"]
    user.role = Role.COACH
    sync_groups(user)
    assert not user.groups.exists()
    assert Group.objects.filter(name="Správce").exists()
