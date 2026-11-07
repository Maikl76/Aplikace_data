"""
Dávka 10: interní referenční hodnoty laboratoře – z vlastních měření podle
sportu, pohlaví a věku, od minimálního počtu sportovců a podle souhlasů;
jen v laboratoři (karta sportovce, týmový přehled), nikdy do zprávy ani
do portálu.
"""

from datetime import date

import pytest
from cryptography.fernet import Fernet
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from apps.analytics import reference
from apps.catalog.models import BatteryItem, MetricDef, Protocol, TestBattery
from apps.core.models import Organization, Role, User
from apps.measurements.models import TestSession
from apps.reports import services as report_services
from apps.reports.models import Audience
from apps.subjects.models import Consent, Sex, Sport, Subject
from tests.test_koncept_a_doruceni import _account
from tests.test_tym import zmer

Q = {"side": ""}


@pytest.fixture
def lab(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    sport = Sport.objects.create(organization=org, code="florbal", name="Florbal")
    battery = TestBattery.objects.create(organization=org, sport=sport)
    BatteryItem.objects.create(battery=battery, protocol=Protocol.objects.get(code="cmj"), order=1)
    women = []
    for i in range(10):
        s = Subject.objects.create(organization=org, code=f"FTVS-{i + 1:04d}", sport=sport,
                                   sex=Sex.FEMALE, birth_year=2006)       # 20 let
        zmer(s, date(2026, 3, 1), "cmj_height", [20.0 + i])               # 20 … 29
        if i < 9:                                                        # desátá bez souhlasu
            Consent.objects.create(subject=s, scope=Consent.Scope.RESEARCH,
                                   granted_on=date(2026, 1, 1))
        women.append(s)
    return org, sport, battery, women


def _user(org, role, username):
    user = User.objects.create(username=username, organization=org, role=role,
                               is_staff=role == Role.ADMIN)
    client = Client()
    client.force_login(user)
    return user, client


def test_pasmo_podle_skupiny_souhlasu_a_minima(lab):
    org, sport, _, women = lab
    metric = MetricDef.objects.get(code="cmj_height")
    index = reference.ReferenceIndex(org)
    band = index.band_for(women[0], metric, Q)
    assert band.n == 9 and (band.p25, band.p50, band.p75) == (22, 24, 26)   # jen se souhlasem
    assert band.age_band == "18–23 let" and band.group_text == "Florbal · ženy · 18–23 let"
    assert band.position(28.0) == {"text": "nad P75", "tier": "top"}
    assert band.position(20.0)["tier"] == "low" and band.position(24.0)["tier"] == ""
    assert index.summary()["included"] == 9 and index.summary()["candidates"] == 10

    # muž bez skupiny; sportovkyně jiného věku padne na tentýž sport a pohlaví bez věku
    man = Subject.objects.create(organization=org, code="M-1", sport=sport, sex=Sex.MALE,
                                 birth_year=2006)
    assert index.band_for(man, metric, Q) is None
    older = Subject.objects.create(organization=org, code="S-30", sport=sport, sex=Sex.FEMALE,
                                   birth_year=1996)
    fallback = index.band_for(older, metric, Q)
    assert fallback.n == 9 and fallback.age_band == "" and "všechny věky" in fallback.group_text

    # minimum nad počet se souhlasem → nic; všichni aktivní → 10 sportovkyň
    org.reference_min_subjects = 10
    org.save()
    assert reference.ReferenceIndex(org).band_for(women[0], metric, Q) is None
    org.reference_source = Organization.ReferenceSource.ALL
    org.save()
    band = reference.ReferenceIndex(org).band_for(women[0], metric, Q)
    assert band.n == 10 and band.p50 == 24.5

    # odvolaný souhlas nevstupuje; vypnuto = nic
    org.reference_source = Organization.ReferenceSource.RESEARCH
    org.reference_min_subjects = 8
    org.save()
    Consent.objects.filter(subject=women[0]).update(revoked_on=date(2026, 2, 1))
    assert reference.ReferenceIndex(org).band_for(women[1], metric, Q).n == 8
    rows = reference.ReferenceIndex(org).overview()
    assert [(r["age_band"], r["n"], r["ok"]) for r in rows] == [("18–23 let", 8, True),
                                                               ("všechny věky", 8, True)]
    org.reference_enabled = False
    org.save()
    assert reference.ReferenceIndex(org).band_for(women[1], metric, Q) is None


def test_pasmo_jen_v_laboratori_ne_v_portalu_ani_ve_zprave(lab):
    org, _, battery, women = lab
    lab_user, client = _user(org, Role.LAB, "laborant")
    best = women[8]                                                   # 28 cm → nad P75
    page = client.get(reverse("subject_detail", args=[best.pk])).content.decode()
    assert "Interní reference laboratoře" in page and "nad P75" in page
    assert "Florbal · ženy · 18–23 let · n = 9" in page
    assert "Šedé pásmo = interní reference laboratoře" in page       # graf bez normy
    team = client.get(reverse("team") + f"?baterie={battery.pk}").content.decode()
    assert 'id="interni-reference"' in team and "Florbal · ženy · 18–23 let" in team
    assert "22,0–26,0 (9)" in team and "nad P75" in team

    # portál sportovce ani trenéra pásmo nedostane
    _, athlete = _account(best)
    athlete_client = Client()
    athlete_client.force_login(athlete)
    portal = athlete_client.get(reverse("portal_subject", args=[best.pk])).content.decode()
    assert portal and "interní" not in portal.lower()

    # zpráva (šablona i text) o interní referenci mlčí
    session = TestSession.objects.get(subject=best)
    report = report_services.build_draft(session, user=lab_user, audience=Audience.ATHLETE)
    html = report_services.render_html(report).lower()
    assert "interní" not in html and "p25" not in html
    assert "interní" not in (report.summary or "").lower()


def test_nastaveni_referenci_a_kroky(lab):
    org, _, _, _ = lab
    _, admin = _user(org, Role.ADMIN, "spravce")
    _, laborant = _user(org, Role.LAB, "laborant")
    page = admin.get(reverse("reference_settings"))
    html = page.content.decode()
    assert "Skupiny a jejich pásma" in html and "používá se" in html and "Florbal" in html
    steps = {s["title"]: s for s in page.context["steps"]}
    assert steps["Zdroj dat"]["done"] and "9 z 10" in steps["Zdroj dat"]["text"]
    assert steps["Skupiny"]["done"] and steps["Použití"]["done"]

    assert laborant.post(reverse("reference_settings"), {"zapnuto": "on"}).status_code == 403
    admin.post(reverse("reference_settings"),
               {"zapnuto": "on", "zdroj": "vsichni", "minimum": "12"})
    org.refresh_from_db()
    assert org.reference_source == "vsichni" and org.reference_min_subjects == 12
    assert org.reference_enabled
    steps = {s["title"]: s for s in admin.get(reverse("reference_settings")).context["steps"]}
    assert not steps["Zdroj dat"]["done"] and not steps["Skupiny"]["done"]
    assert "0 z 2 skupin" in steps["Skupiny"]["text"]

    admin.post(reverse("reference_settings"), {"zdroj": "vyzkum", "minimum": "1"})
    org.refresh_from_db()
    assert not org.reference_enabled and org.reference_min_subjects == reference.MIN_SUBJECTS_FLOOR
    steps = {s["title"]: s for s in admin.get(reverse("reference_settings")).context["steps"]}
    assert not steps["Použití"]["done"] and "vypnuté" in steps["Použití"]["text"]
    assert "Interní reference" in admin.get(reverse("workplace")).content.decode()
