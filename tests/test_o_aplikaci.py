"""Stránka O aplikaci: je v menu, dostupná pro každou roli a odkazy v ní vedou na existující stránky."""

import re

import pytest

from apps.core.models import Organization, Role, User


@pytest.fixture
def org(db):
    return Organization.objects.create(name="FTVS", short_name="ftvs")


@pytest.mark.parametrize("role", [Role.ADMIN, Role.LAB, Role.RESEARCHER])
def test_stranka_pro_kazdou_roli(client, org, role):
    user = User.objects.create(username=f"u-{role}", organization=org, role=role)
    client.force_login(user)
    html = client.get("/o-aplikaci/").content.decode()
    assert "Role a oprávnění" in html and "Rychlý start" in html
    assert f"Vaše role: {user.get_role_display()}" in html
    assert 'href="/o-aplikaci/"' in client.get("/").content.decode()     # položka v menu


def test_odkazy_vedou_na_existujici_stranky(client, org):
    user = User.objects.create(username="lab", organization=org, role=Role.LAB)
    client.force_login(user)
    html = client.get("/o-aplikaci/").content.decode()
    kapitoly = set(re.findall(r'<section id="([^"]+)"', html))
    for odkaz in set(re.findall(r'href="([^"]+)"', html)):
        if odkaz.startswith("#"):
            assert odkaz[1:] in kapitoly, f"chybí kapitola {odkaz}"
        elif odkaz.startswith("/") and not odkaz.startswith(("/admin", "/static")):
            assert client.get(odkaz).status_code == 200, odkaz


def test_bez_prihlaseni_presmeruje(client, db):
    assert client.get("/o-aplikaci/").status_code == 302
