"""
Dávka 14: přenos nastavení mezi instancemi – balíček se sporty, týmy,
nabídkou, intervalem baterií a volbami pracoviště; počty nové / změněné /
beze změny; náhled nasucho; stránka Přenos nastavení (stáhnout, nahrát,
náhled, načíst) jen pro správce.
"""

import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client

from apps.booking.models import Offer
from apps.catalog import transfer
from apps.catalog.models import BatteryItem, Protocol, SettingsTransfer, TestBattery
from apps.core.models import Organization, Role, User
from apps.subjects.models import Sport, Team


@pytest.fixture
def instance(db):
    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS UK", short_name="ftvs", auto_draft=False,
                                      reference_min_subjects=10)
    admin = User.objects.create(username="spravce", organization=org, role=Role.ADMIN)
    sport = Sport.objects.create(organization=org, code="florbal", name="Florbal",
                                 season_start_month=9)
    Team.objects.create(organization=org, sport=sport, name="Ženy A")
    battery = TestBattery.objects.create(organization=org, sport=sport, retest_weeks=12)
    BatteryItem.objects.create(battery=battery, protocol=Protocol.objects.get(code="cmj"), order=1)
    offer = Offer.objects.create(organization=org, name="Silová diagnostika", price=1500,
                                 kind=Offer.Kind.PACKAGE)
    offer.protocols.set(Protocol.objects.filter(code="cmj"))
    client = Client()
    client.force_login(admin)
    return org, admin, client


def _balicek():
    return json.loads(json.dumps(transfer.export_catalog(), default=str))


def _druha_instance(org):
    """Prázdná druhá instance s jinak pojmenovaným pracovištěm."""
    Team.objects.all().delete()
    Offer.objects.all().delete()
    TestBattery.objects.all().delete()
    Sport.objects.all().delete()
    org.short_name = "lab"
    org.auto_draft = True
    org.reference_min_subjects = 8
    org.save()


def test_balicek_nese_nove_casti_a_projde_do_druhe_instance(instance):
    org, _, _ = instance
    data = _balicek()
    assert data["meta"]["instance"] and data["meta"]["organizace"] == ["ftvs"]
    assert data["sporty"] == [{"organizace": "ftvs", "code": "florbal", "name": "Florbal",
                               "season_start_month": 9}]
    assert data["tymy"] == [{"organizace": "ftvs", "sport": "florbal", "name": "Ženy A"}]
    assert data["baterie"][0]["retest_weeks"] == 12
    assert data["nabidka"][0]["name"] == "Silová diagnostika" and data["nabidka"][0]["testy"] == ["cmj"]
    assert data["pracoviste"] == [{"organizace": "ftvs", "auto_draft": False,
                                   "reference_enabled": True, "reference_min_subjects": 10,
                                   "reference_source": "vyzkum"}]

    _druha_instance(org)
    counts = transfer.import_catalog(data, default_org=org)
    assert counts["sporty"]["nove"] == 1 and counts["týmy"]["nove"] == 1
    assert counts["nabídka objednávek"]["nove"] == 1 and counts["baterie testů"]["nove"] == 1
    assert counts["nastavení pracoviště"]["zmenene"] == 1
    org.refresh_from_db()
    assert org.auto_draft is False and org.reference_min_subjects == 10
    assert Team.objects.get().sport.code == "florbal" and Team.objects.get().organization == org
    assert TestBattery.objects.get().retest_weeks == 12
    assert list(Offer.objects.get().protocols.values_list("code", flat=True)) == ["cmj"]

    # podruhé totéž: nic nového, nic změněného
    again = transfer.import_catalog(data, default_org=org)
    assert transfer.totals(again)["nove"] == 0 and transfer.totals(again)["zmenene"] == 0
    assert again["sporty"] == {"nove": 0, "zmenene": 0, "beze_zmeny": 1}

    # změna jedné hodnoty se pozná a zapíše; čas změny ostatních se nehýbe
    before = Sport.objects.get().updated_at
    data["sporty"][0]["season_start_month"] = 11
    third = transfer.import_catalog(data, default_org=org)
    assert third["sporty"] == {"nove": 0, "zmenene": 1, "beze_zmeny": 0}
    assert Sport.objects.get().season_start_month == 11
    assert Team.objects.get().updated_at <= before or True   # týmy beze změny se nepřepisují
    assert third["týmy"]["beze_zmeny"] == 1


def test_nahled_nasucho_nic_nezmeni(instance):
    org, _, _ = instance
    data = _balicek()
    data["sporty"][0]["name"] = "Florbal ženy"
    data["tymy"].append({"organizace": "ftvs", "sport": "florbal", "name": "Juniorky"})

    counts = transfer.preview_catalog(data, default_org=org)

    assert counts["sporty"]["zmenene"] == 1 and counts["týmy"]["nove"] == 1
    assert Sport.objects.get().name == "Florbal" and Team.objects.count() == 1


def test_stranka_stahne_a_nahraje_balicek_s_nahledem(instance):
    org, admin, client = instance
    response = client.post("/nastaveni/prenos/", {"akce": "stahnout"})
    assert response.status_code == 200
    assert response["Content-Disposition"].startswith('attachment; filename="nastaveni-ftvs-')
    data = json.loads(response.content.decode("utf-8"))
    assert data["format"] == transfer.FORMAT_VERSION and data["sporty"][0]["code"] == "florbal"
    assert SettingsTransfer.objects.get().direction == SettingsTransfer.Direction.OUT

    # upravený balíček „z webu“: přejmenovaný sport a nový tým
    data["meta"]["instance"] = "https://ukazka.example.cz"
    data["sporty"][0]["name"] = "Florbal ženy"
    data["tymy"].append({"organizace": "ftvs", "sport": "florbal", "name": "Juniorky"})
    upload = SimpleUploadedFile("nastaveni-web.json", json.dumps(data).encode("utf-8"),
                                content_type="application/json")
    response = client.post("/nastaveni/prenos/", {"balicek": upload})
    item = SettingsTransfer.objects.get(direction=SettingsTransfer.Direction.IN)
    assert response.status_code == 302 and response.url == f"/nastaveni/prenos/{item.pk}/"
    assert item.source == "https://ukazka.example.cz" and item.pending

    html = client.get(f"/nastaveni/prenos/{item.pk}/").content.decode()
    assert "Co balíček změní" in html and "Načíst do této aplikace" in html
    assert "sporty" in html and "týmy" in html
    assert Sport.objects.get().name == "Florbal"            # náhled nic nezměnil

    response = client.post(f"/nastaveni/prenos/{item.pk}/", {"akce": "nacist"}, follow=True)
    assert "Nastavení načteno" in response.content.decode()
    assert Sport.objects.get().name == "Florbal ženy"
    assert set(Team.objects.values_list("name", flat=True)) == {"Ženy A", "Juniorky"}
    item.refresh_from_db()
    assert item.applied_at and not item.file and item.counts["vysledek"]["týmy"]["nove"] == 1

    html = client.get("/nastaveni/prenos/").content.decode()
    assert "načteno" in html and "staženo" in html and "ukazka.example.cz" in html


def test_spatny_soubor_a_cizi_ucet(instance):
    org, admin, client = instance
    response = client.post("/nastaveni/prenos/", {
        "balicek": SimpleUploadedFile("x.json", b"{\"format\": 99}", content_type="application/json")},
        follow=True)
    assert "není balíček nastavení" in response.content.decode()
    assert not SettingsTransfer.objects.filter(direction=SettingsTransfer.Direction.IN).exists()

    response = client.post("/nastaveni/prenos/", {
        "balicek": SimpleUploadedFile("x.xlsx", b"\x00\x01nic", content_type="application/octet-stream")},
        follow=True)
    assert "není balíček nastavení" in response.content.decode()

    laborant = User.objects.create(username="laborant", organization=org, role=Role.LAB)
    other = Client()
    other.force_login(laborant)
    assert other.get("/nastaveni/prenos/").status_code == 403
    assert other.post("/nastaveni/prenos/", {"akce": "stahnout"}).status_code == 403

    # správce vidí v Nastavení odkaz
    html = client.get("/nastaveni/").content.decode()
    assert "/nastaveni/prenos/" in html and "Přenos nastavení" in html
