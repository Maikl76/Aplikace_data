"""
Smazání sportu ve Sportech a testech: nejdřív přehled, co zmizí s ním a co mu
brání (sportovci, nálezy ve zprávách); smí jen správce nebo účet se všemi sporty.
"""

from datetime import date

import pytest
from django.core.management import call_command

from apps.catalog.models import BatteryItem, MetricDef, Norm, Protocol, TestBattery
from apps.core import access
from apps.core.models import AuditLog, Organization, Role, User
from apps.evidence.models import Article
from apps.measurements.models import TestSession
from apps.rules.models import Finding, Rule
from apps.subjects.models import Sport, Subject, Team


@pytest.fixture
def lab(db, client):
    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    user = User.objects.create(username="lab", organization=org, role=Role.LAB)
    access.grant(user, settings_sports=True)
    client.force_login(user)
    hokej = Sport.objects.create(organization=org, code="hokej", name="Lední hokej")
    return org, user, hokej, client


def test_odkaz_jen_pro_spravu_sportu(lab):
    org, user, hokej, client = lab
    url = f"/sporty/{hokej.pk}/smazat/"
    assert url in client.get("/sporty/").content.decode()

    # účet s omezeným rozsahem (jen některé sporty) sport nesmaže
    profile = access.grant(user, all_sports=False)
    profile.sports.set([hokej])
    access.forget(user)
    assert url not in client.get("/sporty/").content.decode()
    response = client.post(url)
    assert response.status_code == 302 and Sport.objects.filter(pk=hokej.pk).exists()


def test_sport_se_sportovci_smazat_nejde(lab):
    org, _, hokej, client = lab
    Subject.objects.create(organization=org, code="FTVS-0001", sport=hokej, is_active=False)
    page = client.get(f"/sporty/{hokej.pk}/smazat/").content.decode()
    assert "Sport teď smazat nejde" in page
    assert "Sport má 1 sportovce (z toho 1 neaktivní)" in page
    assert f"?sport={hokej.pk}" in page and "Smazat sport Lední hokej</button>" not in page
    response = client.post(f"/sporty/{hokej.pk}/smazat/")
    assert response.status_code == 200 and Sport.objects.filter(pk=hokej.pk).exists()


def test_nalezy_z_pravidel_sportu_brani_smazani(lab):
    org, _, hokej, client = lab
    florbal = Sport.objects.create(organization=org, code="florbal", name="Florbal")
    rule = Rule.objects.create(organization=org, code="hokej_cmj", name="CMJ hokej",
                               applies_to_sport=hokej, finding_template="nález")
    host = Subject.objects.create(organization=org, code="FTVS-0002", sport=florbal)
    den = TestSession.objects.create(organization=org, subject=host, date=date(2026, 9, 1))
    Finding.objects.create(session=den, rule=rule, rule_version=1, severity="low", text="x")
    page = client.get(f"/sporty/{hokej.pk}/smazat/").content.decode()
    assert "vytvořila nálezy ve zprávách" in page
    client.post(f"/sporty/{hokej.pk}/smazat/")
    assert Sport.objects.filter(pk=hokej.pk).exists()


def test_smazani_sportu_s_bateriemi_tymy_normami_a_pravidly(lab):
    org, user, hokej, client = lab
    florbal = Sport.objects.create(organization=org, code="florbal", name="Florbal")
    battery = TestBattery.objects.create(organization=org, sport=hokej, category="dorost",
                                         name="Hokej – dorost")
    BatteryItem.objects.create(battery=battery, order=1,
                               protocol=Protocol.objects.get(code="cmj", organization=None))
    Team.objects.create(organization=org, sport=hokej, name="Junioři")
    Norm.objects.create(organization=org, sport=hokej, source_citation="Smyšlená 2020",
                        metric=MetricDef.objects.get(code="cmj_height", organization=None))
    Rule.objects.create(organization=org, code="hokej_cmj", name="CMJ hokej",
                        applies_to_sport=hokej, finding_template="nález")
    article = Article.objects.create(title="Smyšlená studie")
    article.sports.add(hokej, florbal)
    metodik = User.objects.create(username="metodik", first_name="Eva", last_name="Malá",
                                  organization=org, role=Role.METHODOLOGIST)
    access.grant(metodik, all_sports=False).sports.set([hokej])
    druhy = User.objects.create(username="druhy", organization=org, role=Role.LAB)
    access.grant(druhy, all_sports=False).sports.set([hokej, florbal])
    host = Subject.objects.create(organization=org, code="FTVS-0003", sport=florbal)
    den = TestSession.objects.create(organization=org, subject=host, date=date(2026, 9, 1),
                                     battery=battery)

    page = client.get(f"/sporty/{hokej.pk}/smazat/").content.decode()
    assert "Se sportem se smaže:" in page
    for line in ("baterie testů: Hokej – dorost", "týmy: Junioři",
                 "normy jen pro tento sport: 1", "pravidla jen pro tento sport: 1",
                 "sport z populace studie u článků: 1",
                 "sport z rozsahu dat účtů: Eva Malá, druhy",
                 "odkaz na baterii u testovacích dnů jiných sportovců, které podle ní vznikly: 1"):
        assert line in page, line
    assert "Eva Malá má v rozsahu dat jen tento sport" in page     # neviděla by nikoho

    response = client.post(f"/sporty/{hokej.pk}/smazat/")
    assert response.status_code == 302
    assert not Sport.objects.filter(pk=hokej.pk).exists()
    assert not TestBattery.objects.filter(pk=battery.pk).exists()
    assert not Team.objects.filter(name="Junioři").exists()
    assert not Norm.objects.filter(source_citation="Smyšlená 2020").exists()
    assert not Rule.objects.filter(code="hokej_cmj").exists()
    assert list(article.sports.all()) == [florbal]
    assert list(access.profile(druhy).sports.all()) == [florbal]
    den.refresh_from_db()
    assert den.battery is None and den.subject == host                 # den i sportovec zůstanou
    assert Protocol.objects.filter(code="cmj", organization=None).exists()
    entry = AuditLog.objects.get(action=AuditLog.Action.DELETE, object_type="Sport")
    assert entry.detail["sport"] == "Lední hokej" and entry.detail["baterie"] == 1
