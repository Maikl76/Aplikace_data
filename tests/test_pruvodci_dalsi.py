"""Kroky u sportovce, importu, sportů a testů, objednávek, článků a AI zpráv – fáze 3."""

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.booking.models import Offer, Slot
from apps.catalog.models import MetricDef, Protocol, ProtocolMetric, TestBattery, TestFamily
from apps.core.models import Organization, Role, User
from apps.evidence.models import Article
from apps.ingest.models import ImportBatch
from apps.measurements.models import Measurement, ProtocolRun, RawFile, TestSession, Trial
from apps.subjects.models import Consent, Sport, Subject


@pytest.fixture
def org(db):
    call_command("seed_roles", verbosity=0)
    return Organization.objects.create(name="FTVS", short_name="ftvs")


def _user(org, role, username):
    user = User.objects.create(username=username, organization=org, role=role)
    client = Client()
    client.force_login(user)
    return user, client


def _steps(page):
    return {s["title"]: s for s in page.context["steps"]}, page.context["next_step"]


def _protocol(org, code="cmj", mdc=1.0):
    protocol = Protocol.objects.create(organization=org, code=code, name=code.upper(),
                                       family=TestFamily.FORCE_PLATE)
    metric = MetricDef.objects.create(organization=org, code=f"{code}_m", name="Výška",
                                      family=TestFamily.FORCE_PLATE, unit="cm", mdc=mdc)
    ProtocolMetric.objects.create(protocol=protocol, metric=metric, is_primary=True)
    return protocol, metric


# --- sportovec ----------------------------------------------------------------------------

def test_sportovec_vede_kroky(org):
    lab, client = _user(org, Role.LAB, "laborant")
    subject = Subject.objects.create(organization=org, code="FTVS-0001")
    url = reverse("subject_detail", args=[subject.pk])
    steps, nxt = _steps(client.get(url))
    assert list(steps) == ["Údaje a souhlasy", "Účet v portálu", "Měření", "Zpráva",
                           "Předání nebo sdílení", "Externí vyšetření", "Cíle"]
    assert nxt["title"] == "Údaje a souhlasy" and "sport" in nxt["text"] and "souhlas" in nxt["text"]
    assert nxt["url"] == reverse("subject_edit", args=[subject.pk])

    subject.sport = Sport.objects.create(organization=org, name="Florbal", code="florbal")
    subject.birth_year = 1999
    subject.save()
    Consent.objects.create(subject=subject, scope=Consent.Scope.TESTING, granted_on=timezone.localdate())
    steps, nxt = _steps(client.get(url))
    assert steps["Údaje a souhlasy"]["done"] and nxt["title"] == "Měření"
    assert nxt["url"].startswith(reverse("session_create")) and nxt["button"] == "Nové měření"

    protocol, metric = _protocol(org)
    session = TestSession.objects.create(organization=org, subject=subject, date=timezone.localdate())
    run = ProtocolRun.objects.create(session=session, protocol=protocol)
    steps, nxt = _steps(client.get(url))
    assert nxt["title"] == "Měření" and nxt["button"] == "Zadat hodnoty"
    assert nxt["url"] == reverse("session_detail", args=[session.pk])

    trial = Trial.objects.create(protocol_run=run, number=1)
    Measurement.objects.create(trial=trial, metric=metric, value=30)
    steps, nxt = _steps(client.get(url))
    assert steps["Měření"]["done"] and nxt["title"] == "Zpráva"
    assert nxt["url"] == reverse("session_detail", args=[session.pk]) + "#nova-zprava"
    html = client.get(url).content.decode()
    assert 'id="mereni"' in html and 'id="zpravy"' in html and "Postup" in html

    # výzkumník vidí kroky bez tlačítek pro úpravy
    _, r_client = _user(org, Role.RESEARCHER, "vyzkumnik")
    steps, _ = _steps(r_client.get(url))
    assert steps["Údaje a souhlasy"]["button"] == ""


# --- import --------------------------------------------------------------------------------

def test_import_vede_kroky(org):
    lab, client = _user(org, Role.LAB, "laborant")
    steps, nxt = _steps(client.get(reverse("import_list")))
    assert list(steps) == ["Přístroje", "Nahrát export", "Zkontrolovat a uložit",
                           "Výsledky v testovacích dnech", "Sledovaná složka"]
    assert nxt["title"] == "Nahrát export" and nxt["url"] == "#nahrat"
    assert steps["Přístroje"]["optional"]

    raw = RawFile.objects.create(file=SimpleUploadedFile("export.xlsx", b"PK\x03\x04"),
                                 original_name="export.xlsx", size_bytes=4)
    batch = ImportBatch.objects.create(organization=org, raw_file=raw, adapter="legacy_excel",
                                       status=ImportBatch.Status.PARSED, uploaded_by=lab)
    steps, nxt = _steps(client.get(reverse("import_list")))
    assert nxt["title"] == "Zkontrolovat a uložit" and nxt["count"] == 1
    assert nxt["url"] == reverse("import_detail", args=[batch.pk])

    page = client.get(reverse("import_detail", args=[batch.pk]))
    steps, nxt = _steps(page)
    assert list(steps) == ["Nahráno", "Sportovci rozpoznáni", "Vyžaduje pozornost", "Uložit do databáze", "Kam se zapsalo"]
    assert nxt["title"] == "Uložit do databáze" and nxt["url"] == "#ulozit"

    batch.status = ImportBatch.Status.COMMITTED
    batch.save()
    steps, nxt = _steps(client.get(reverse("import_detail", args=[batch.pk])))
    assert steps["Uložit do databáze"]["done"] and steps["Kam se zapsalo"]["done"] and nxt is None


# --- sporty a testy ---------------------------------------------------------------------------

def test_sporty_a_testy_vedou_kroky(org):
    admin, client = _user(org, Role.ADMIN, "spravce")
    steps, nxt = _steps(client.get(reverse("sport_list")))
    assert list(steps) == ["Sporty", "Baterie testů", "Klíčové ukazatele", "MDC u klíčových ukazatelů",
                           "Normy a pravidla", "Popisy pro klienta"]
    assert nxt["title"] == "Sporty"

    sport = Sport.objects.create(organization=org, name="Florbal", code="florbal")
    steps, nxt = _steps(client.get(reverse("sport_list")))
    assert nxt["title"] == "Baterie testů" and nxt["count"] == 1

    protocol, metric = _protocol(org, mdc=None)
    battery = TestBattery.objects.create(organization=org, sport=sport)
    battery.items.create(protocol=protocol)
    steps, nxt = _steps(client.get(reverse("test_list")))
    assert steps["Baterie testů"]["done"] and steps["Klíčové ukazatele"]["done"]
    assert nxt["title"] == "MDC u klíčových ukazatelů" and nxt["admin_only"]
    # laborant vidí totéž, ale MDC „nastavuje správce“
    _, lab_client = _user(org, Role.LAB, "laborant")
    html = lab_client.get(reverse("sport_list")).content.decode()
    assert "nastavuje správce" in html and 'id="pridat-sport"' in html


# --- objednávky -----------------------------------------------------------------------------------

def test_objednavky_vedou_kroky(org):
    lab, client = _user(org, Role.LAB, "laborant")
    steps, nxt = _steps(client.get(reverse("booking_list")))
    assert list(steps) == ["Nabídka a ceny", "Volné termíny", "Odkaz pro klienty", "Žádosti ke schválení", "Po schválení"]
    assert nxt["title"] == "Nabídka a ceny"

    Offer.objects.create(organization=org, name="CMJ", price=500)
    steps, nxt = _steps(client.get(reverse("booking_offers")))
    assert steps["Nabídka a ceny"]["done"] and nxt["title"] == "Volné termíny"

    Slot.objects.create(organization=org, start=timezone.now() + timedelta(days=3))
    steps, nxt = _steps(client.get(reverse("booking_slots")))
    assert steps["Volné termíny"]["done"] and steps["Odkaz pro klienty"]["done"]
    assert "http://testserver" + reverse("booking_form") in steps["Odkaz pro klienty"]["text"]
    assert steps["Žádosti ke schválení"]["done"] and nxt["title"] == "Po schválení"


# --- články ---------------------------------------------------------------------------------------

def test_clanky_vedou_kroky(org):
    admin, client = _user(org, Role.ADMIN, "spravce")
    steps, nxt = _steps(client.get(reverse("article_list")))
    assert list(steps) == ["Přidat článek", "Co dostane model", "Témata", "Zařazení"]
    assert nxt["title"] == "Přidat článek"

    article = Article.objects.create(title="Studie CMJ", doi="10.1/x", year=2020,
                                     status=Article.Status.SUGGESTED)
    steps, nxt = _steps(client.get(reverse("article_list")))
    assert steps["Přidat článek"]["done"] and nxt["title"] == "Co dostane model" and nxt["count"] == 1
    assert steps["Témata"]["count"] == 1 and steps["Zařazení"]["count"] == 1

    page = client.get(reverse("article_edit", args=[article.pk]))
    steps = {s["title"]: s for s in page.context["steps"]}
    assert steps["Identifikace"]["done"] and not steps["Co dostane model"]["done"]
    assert "hlavní zjištění" in steps["Co dostane model"]["text"]
    assert not steps["Zařazení"]["done"] and "Stav článku" in page.content.decode()


# --- AI zprávy ------------------------------------------------------------------------------------

def test_ai_zpravy_vedou_kroky(org, settings):
    settings.LLM_ENABLED = False
    admin, client = _user(org, Role.ADMIN, "spravce")
    page = client.get(reverse("ai_settings"))
    assert page.status_code == 200
    steps, nxt = _steps(page)
    assert list(steps) == ["Model běží", "Pokyny pro model", "Vzorové zprávy", "Hodnocení textů", "Zkušební sada"]
    assert nxt["title"] == "Model běží" and "vypnutý" in nxt["text"]
    assert steps["Pokyny pro model"]["optional"] and steps["Zkušební sada"]["optional"]
    assert "Postup AI zpráv" in page.content.decode()
