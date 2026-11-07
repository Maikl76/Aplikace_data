"""
Dávka 11: přístupy. Role je šablona, přístup se nastavuje u účtu: rozsah
dat (sporty, týmy, jména, genetika, vyšetření, objednávky) a oprávnění
(měření, sportovci, koncepty, vydávání, nastavení, exporty, články).
Laborant vidí jen přidělené sporty a nevydává; metodik vydává pro své
sporty bez jmen; správce vše. Jeden modul rozhoduje, for_user filtruje,
middleware hlídá sekce.
"""

import importlib
from datetime import date

import pytest
from cryptography.fernet import Fernet
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from apps.catalog.models import MetricDef, Norm, Protocol, TestBattery, TestFamily
from apps.core import access, colleagues
from apps.core.models import Access, AuditLog, Organization, Role, User
from apps.core.workplace import workplace_steps
from apps.ingest import services as ingest
from apps.ingest.models import ImportBatch, StagedMeasurement
from apps.measurements.models import TestSession
from apps.reports import services as report_services
from apps.reports.models import Audience, Report
from apps.rules.models import Rule
from apps.subjects.models import Sport, Subject, SubjectIdentity, Team
from tests.test_tym import zmer
from tests.test_zaloha_a_importy import _batch


@pytest.fixture
def lab(db, settings):
    """Dva sporty, v každém sportovkyně s měřením; správce."""
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    florbal = Sport.objects.create(organization=org, code="florbal", name="Florbal")
    hokej = Sport.objects.create(organization=org, code="hokej", name="Hokej")
    subjects = {}
    for code, sport, name in (("FTVS-0001", florbal, "Flora"), ("FTVS-0002", hokej, "Hana")):
        s = Subject.objects.create(organization=org, code=code, sport=sport, sex="F",
                                   birth_year=2000)
        identity = SubjectIdentity.objects.create(subject=s)
        identity.set_names(name, "Testová")
        identity.save()
        zmer(s, date(2026, 3, 1), "cmj_height", [30.0, 31.0])
        subjects[code] = s
    admin = User.objects.create(username="spravce", organization=org, role=Role.ADMIN,
                                is_staff=True)
    return {"org": org, "florbal": florbal, "hokej": hokej, "admin": admin, **subjects}


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def _user(org, role, username, **grant):
    user = User.objects.create(username=username, organization=org, role=role)
    if grant:
        access.grant(user, **grant)
    return user


def test_sablony_roli_a_spravce_ma_vse(lab):
    admin = lab["admin"]
    assert all(access.can(admin, key) for key in access.FLAGS) and access.manage(admin)
    laborant = _user(lab["org"], Role.LAB, "laborant")
    assert access.can(laborant, "measure") and access.can(laborant, "names")
    assert not access.can(laborant, "reports_release") and not access.can(laborant, "genetics")
    metodik = _user(lab["org"], Role.METHODOLOGIST, "metodik")
    assert access.can(metodik, "reports_release") and access.can(metodik, "settings_sports")
    assert not access.can(metodik, "names") and not access.can(metodik, "measure")
    assert not metodik.sees_identity and laborant.sees_identity
    researcher = _user(lab["org"], Role.RESEARCHER, "vyzkum")
    assert not any(access.can(researcher, key) for key in access.FLAGS)
    assert access.scope(laborant) is None            # bez nastavení: všechny sporty
    text = access.summary(laborant)
    assert text.startswith("všechny sporty · jména · ") and "měření" in text and "vydávání" not in text


def test_rozsah_po_sportech_filtruje_vsude(lab):
    org, flora, hana = lab["org"], lab["FTVS-0001"], lab["FTVS-0002"]
    laborant = _user(org, Role.LAB, "laborant")
    profile = access.grant(laborant, all_sports=False)
    profile.sports.set([lab["florbal"]])
    access.forget(laborant)
    assert access.scope(laborant).sports == frozenset({lab["florbal"].pk})
    assert access.sees_subject(laborant, flora) and not access.sees_subject(laborant, hana)

    assert set(Subject.objects.for_user(laborant)) == {flora}
    assert set(Sport.objects.for_user(laborant)) == {lab["florbal"]}
    assert set(TestSession.objects.for_user(laborant)) == set(flora.sessions.all())
    client = _client(laborant)
    assert client.get(reverse("subject_detail", args=[flora.pk])).status_code == 200
    assert client.get(reverse("subject_detail", args=[hana.pk])).status_code == 404
    page = client.get(reverse("subject_list")).content.decode()
    assert "Flora" in page and "Hana" not in page
    assert "FTVS-0002" not in client.get(reverse("subject_search") + "?q=Hana").content.decode()
    assert "FTVS-0001" in client.get(reverse("subject_search") + "?q=Flora").content.decode()
    assert "Hokej" not in client.get(reverse("today")).content.decode()
    # jen tým: ještě užší
    tym = Team.objects.create(organization=org, name="Ženy A", sport=lab["florbal"])
    profile.teams.set([tym])
    access.forget(laborant)
    assert not Subject.objects.for_user(laborant).exists()
    flora.team = tym
    flora.save()
    assert set(Subject.objects.for_user(laborant)) == {flora}
    # správce vidí vše, nový účet kolegy nic, dokud mu správce nepřidělí sporty
    assert Subject.objects.for_user(lab["admin"]).count() == 2
    novy = colleagues.create_colleague(org, role=Role.LAB, first_name="Nový", last_name="Kolega")
    assert not novy.access.all_sports and not novy.access.configured
    assert not Subject.objects.for_user(novy).exists() and not novy.is_staff


def test_vydava_metodik_sportu_laborant_jen_koncept(lab):
    org, flora, hana = lab["org"], lab["FTVS-0001"], lab["FTVS-0002"]
    laborant = _user(org, Role.LAB, "laborant")
    metodik = _user(org, Role.METHODOLOGIST, "metodik", all_sports=False)
    metodik.access.sports.set([lab["florbal"]])
    access.forget(metodik)
    report = report_services.build_draft(flora.sessions.get(), user=laborant,
                                         audience=Audience.ATHLETE)
    other = report_services.build_draft(hana.sessions.get(), user=lab["admin"],
                                        audience=Audience.ATHLETE)

    lab_client = _client(laborant)
    assert lab_client.post(reverse("report_release", args=[report.pk])).status_code == 403
    assert Report.objects.get(pk=report.pk).status == Report.Status.DRAFT
    detail = lab_client.get(reverse("report_detail", args=[report.pk])).content.decode()
    assert "Zprávy vydává správce nebo metodik sportu" not in detail   # stránka se otevře

    m_client = _client(metodik)
    assert m_client.get(reverse("report_detail", args=[other.pk])).status_code == 404  # cizí sport
    page = m_client.get(reverse("report_detail", args=[report.pk])).content.decode()
    assert "FTVS-0001" in page and "Flora" not in page                               # bez jmen
    m_client.post(reverse("report_release", args=[report.pk]))
    assert Report.objects.get(pk=report.pk).status == Report.Status.RELEASED
    # metodik neměří: bez tlačítka Nové měření a bez Importu, laborant naopak bez Objednávek
    menu = m_client.get(reverse("dashboard")).content.decode()
    assert 'href="/mereni/novy/"' not in menu and 'href="/import/"' not in menu
    assert m_client.post(reverse("session_create"), {}).status_code == 403
    access.grant(laborant, bookings=False)
    menu = lab_client.get(reverse("dashboard")).content.decode()
    assert 'href="/import/"' in menu and 'href="/objednavky/"' not in menu
    assert lab_client.get(reverse("booking_list")).status_code == 403


def test_sekce_podle_pristupu(lab):
    org, flora = lab["org"], lab["FTVS-0001"]
    laborant = _user(org, Role.LAB, "laborant")
    client = _client(laborant)
    # genetika: karty ano, data sportovce jen s přístupem
    assert client.get("/genetika/").status_code == 200
    assert client.get(reverse("genetics_subject", args=[flora.pk])).status_code == 403
    access.grant(laborant, genetics=True)
    assert client.get(reverse("genetics_subject", args=[flora.pk])).status_code == 200
    # nastavení: číst ano, měnit ne
    assert client.get(reverse("norms_settings")).status_code == 200
    assert client.get(reverse("norm_new")).status_code == 403
    assert client.post(reverse("sport_list"), {"name": "Tenis"}).status_code == 403
    assert client.get(reverse("mdc_settings")).status_code == 200
    assert client.post(reverse("mdc_settings"), {}).status_code == 403
    # vyšetření a exporty
    assert client.get(reverse("exam_new", args=[flora.pk])).status_code == 200
    access.grant(laborant, exams=False)
    assert client.get(reverse("exam_new", args=[flora.pk])).status_code == 403
    assert "Zapsat vyšetření" not in client.get(reverse("subject_detail", args=[flora.pk])).content.decode()
    TestBattery.objects.create(organization=org, sport=lab["florbal"])
    assert client.get(reverse("team") + "?format=csv").status_code == 403
    access.grant(laborant, exports=True)
    assert client.get(reverse("team") + "?format=csv").status_code == 200
    # správa jen správce
    assert client.get(reverse("colleagues")).status_code == 403
    assert client.get(reverse("workplace_org")).status_code == 403
    assert client.get("/zpravy/ai/").status_code == 403
    metodik = _user(org, Role.METHODOLOGIST, "metodik")
    m_client = _client(metodik)
    assert m_client.get(reverse("norm_new")).status_code == 200
    assert m_client.get(reverse("import_list")).status_code == 403
    assert m_client.post(reverse("subject_new"), {}).status_code == 403


def test_import_mimo_rozsah_se_neulozi(lab):
    org = lab["org"]
    laborant = _user(org, Role.LAB, "laborant", all_sports=False)
    laborant.access.sports.set([lab["florbal"]])
    access.forget(laborant)
    batch = _batch(org, laborant, status=ImportBatch.Status.PARSED, days_old=0)
    assert "nových sportovců" in ingest.scope_problem(batch, laborant)
    StagedMeasurement.objects.filter(batch=batch).update(subject=lab["FTVS-0002"])
    assert "mimo váš rozsah" in ingest.scope_problem(batch, laborant)
    StagedMeasurement.objects.filter(batch=batch).update(subject=lab["FTVS-0001"])
    assert ingest.scope_problem(batch, laborant) == ""
    assert ingest.scope_problem(batch, lab["admin"]) == ""
    # náhledy importů jiných lidí účet s rozsahem nevidí (nesou jména ze souboru)
    cizi = _batch(org, lab["admin"], status=ImportBatch.Status.PARSED, days_old=0, name="b.xlsx")
    assert set(ImportBatch.objects.for_user(laborant)) == {batch}
    assert cizi in ImportBatch.objects.for_user(lab["admin"])


def test_editor_pristupu_a_krok_ve_stavu_pracoviste(lab):
    org, admin = lab["org"], lab["admin"]
    laborant = _user(org, Role.LAB, "laborant")
    client = _client(admin)
    steps = {s["title"]: s for s in workplace_steps(admin)}
    assert not steps["Přístupy kolegů"]["done"] and steps["Přístupy kolegů"]["count"] == 1
    page = client.get(reverse("colleagues")).content.decode()
    assert "přístup nepotvrzen" in page and "všechny sporty · jména" in page

    url = reverse("colleague_access", args=[laborant.pk])
    assert _client(laborant).get(url).status_code == 403
    assert "Na které sporty vidí" in client.get(url).content.decode()
    client.post(url, {"role": Role.LAB, "rozsah": "sporty", "sporty": [lab["hokej"].pk],
                      "metodiky": "vse", "names": "on", "measure": "on", "reports_draft": "on",
                      "akce": "ulozit"})
    laborant.refresh_from_db()
    a = Access.objects.get(user=laborant)
    assert a.configured and not a.all_sports and list(a.sports.all()) == [lab["hokej"]]
    assert a.names and a.measure and not a.exams and not a.bookings and not a.reports_release
    assert set(Subject.objects.for_user(laborant)) == {lab["FTVS-0002"]}
    log = AuditLog.objects.filter(action=AuditLog.Action.UPDATE, detail__nastaveni="pristup").get()
    assert log.detail["sporty"] == ["Hokej"] and log.detail["exams"] is False
    steps = {s["title"]: s for s in workplace_steps(admin)}
    assert steps["Přístupy kolegů"]["done"]
    # změna role přepíše oprávnění šablonou, rozsah zůstane; „podle role“ to udělá kdykoli
    client.post(url, {"role": Role.METHODOLOGIST, "rozsah": "sporty", "sporty": [lab["hokej"].pk],
                      "metodiky": "rodiny", "rodiny": ["force_plate"], "reports_release": "on",
                      "settings_sports": "on", "akce": "ulozit"})
    laborant = User.objects.get(pk=laborant.pk)   # čerstvý objekt bez zapamatovaného přístupu
    a.refresh_from_db()
    assert laborant.role == Role.METHODOLOGIST and not laborant.is_staff
    assert a.reports_release and a.settings_sports and not a.names and a.families == ["force_plate"]
    assert access.families(laborant) == {"force_plate"}
    client.post(url, {"role": Role.METHODOLOGIST, "akce": "podle_role"})
    a.refresh_from_db()
    assert a.settings_tests and a.exports and list(a.sports.all()) == [lab["hokej"]]
    # vlastní roli správce nemění
    client.post(reverse("colleague_access", args=[admin.pk]), {"role": Role.LAB, "akce": "ulozit"})
    admin.refresh_from_db()
    assert admin.role == Role.ADMIN


def test_migrace_zachova_dnesni_chovani(db):
    from django.apps import apps

    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    stary = User.objects.create(username="stary", organization=org, role=Role.LAB, is_staff=True)
    vyzkum = User.objects.create(username="v", organization=org, role=Role.RESEARCHER, is_staff=True)
    migration = importlib.import_module("apps.core.migrations.0009_pristupy")
    migration.forwards(apps, None)
    stary.refresh_from_db()
    a = Access.objects.get(user=stary)
    assert a.all_sports and not a.configured and a.genetics and a.reports_release and a.names
    assert not stary.is_staff and not vyzkum.access.names and not User.objects.get(pk=vyzkum.pk).is_staff
    assert access.unconfigured(org) == [stary, vyzkum]


def test_metodik_nastavuje_jen_sve_sporty_a_metodiky(lab):
    org, admin, florbal, hokej = lab["org"], lab["admin"], lab["florbal"], lab["hokej"]
    metodik = _user(org, Role.METHODOLOGIST, "metodik", all_sports=False, all_families=False,
                    families=[TestFamily.FORCE_PLATE])
    metodik.first_name, metodik.last_name = "Eva", "Metodická"
    metodik.save()
    metodik.access.sports.set([florbal])
    access.forget(metodik)
    client = _client(metodik)
    cmj = Protocol.objects.get(code="cmj")
    other = Protocol.objects.exclude(family=TestFamily.FORCE_PLATE).order_by("code").first()

    # testy: jen rodina v rozsahu, odpovědnost u testu i sportu
    assert client.get(reverse("test_edit", args=[cmj.pk])).status_code == 200
    assert client.get(reverse("test_edit", args=[other.pk])).status_code == 302
    page = client.get(reverse("test_list")).content.decode()
    assert "jen čtení" in page and "metodik: Eva Metodická" in page
    sports_page = _client(admin).get(reverse("sport_list")).content.decode()
    assert "Odpovídá metodik: Eva Metodická" in sports_page and "Bez metodika" in sports_page
    assert "Přidat sport" not in client.get(reverse("sport_list")).content.decode()
    client.post(reverse("sport_list"), {"name": "Tenis"})
    assert not Sport.objects.filter(name="Tenis").exists()

    # MDC: uloží se jen ukazatel své metodiky
    cmj_height = MetricDef.objects.get(code="cmj_height")
    foreign = MetricDef.objects.exclude(family=TestFamily.FORCE_PLATE).order_by("code").first()
    client.post(reverse("mdc_settings"), {f"mdc_{cmj_height.pk}": "1,5", f"zdroj_{cmj_height.pk}": "studie",
                                          f"mdc_{foreign.pk}": "2", f"zdroj_{foreign.pk}": "studie"})
    assert MetricDef.objects.get(pk=cmj_height.pk).mdc == 1.5
    assert MetricDef.objects.get(pk=foreign.pk).mdc is None

    # normy a pravidla: cizí sport jen ke čtení, napříč sporty jen správce
    mine = Norm.objects.create(organization=org, metric=cmj_height, sport=florbal, mean=30, sd=3,
                               source_citation="Citace dostatečně dlouhá pro normu florbal")
    theirs = Norm.objects.create(organization=org, metric=cmj_height, sport=hokej, mean=40, sd=3,
                                 source_citation="Citace dostatečně dlouhá pro normu hokej")
    assert client.get(reverse("norm_edit", args=[mine.pk])).status_code == 200
    assert client.get(reverse("norm_edit", args=[theirs.pk])).status_code == 403
    assert client.post(reverse("norm_delete", args=[theirs.pk])).status_code == 403
    assert Norm.objects.filter(pk=theirs.pk).exists()
    assert "jen čtení" in client.get(reverse("norms_settings")).content.decode()
    client.post(reverse("norm_new"), {"metric": cmj_height.pk, "sport": "", "mean": "31", "sd": "2",
                                      "source_citation": "Citace dostatečně dlouhá pro normu napříč"})
    assert Norm.objects.count() == 2                       # napříč sporty metodik nezapíše
    client.post(reverse("norm_new"), {"metric": cmj_height.pk, "sport": florbal.pk, "mean": "31",
                                      "sd": "2", "source_citation": "Citace dostatečně dlouhá pro normu"})
    assert Norm.objects.filter(sport=florbal).count() == 2
    rule = Rule.objects.create(organization=org, code="hokej_r", name="Hokej", applies_to_sport=hokej,
                               condition={"metric": "cmj_height", "op": "<", "value": 20},
                               finding_template="nález")
    assert client.get(reverse("rule_edit", args=[rule.pk])).status_code == 403
    assert "jen čtení" in client.get(reverse("rules_settings")).content.decode()
    assert "všechny sporty" not in client.get(reverse("rule_new")).content.decode()

    # Přehled říká rozsah
    home = client.get(reverse("dashboard")).content.decode()
    assert "Váš rozsah: <strong>Florbal</strong>" in home and "pod kódy" in home


def test_ukazkovy_ucet_metodika(lab):
    from apps.portal.demo import create_demo_accounts

    org = lab["org"]
    Subject.objects.create(organization=org, code="FTVS-0003", sport=lab["hokej"])
    created = create_demo_accounts(org, "kontrola-heslo-123")
    assert "metodik" in created
    metodik = User.objects.get(username="metodik")
    assert metodik.role == Role.METHODOLOGIST and not metodik.is_staff
    a = metodik.access
    assert a.configured and not a.all_sports and a.families == ["force_plate"]
    assert set(a.sports.all()) == {lab["florbal"], lab["hokej"]}
    assert not access.can(metodik, "names") and access.can(metodik, "reports_release")
    assert create_demo_accounts(org, "x") == []           # podruhé nic nezakládá
