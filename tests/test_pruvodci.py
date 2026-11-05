"""
Kroky napříč aplikací: společná součástka, Přehled jako „dnes“, Stav
pracoviště a připomínky. Kroky se počítají z dat, nic se neodškrtává.
"""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import MetricDef, Protocol, ProtocolMetric, TestBattery, TestFamily
from apps.core.models import Organization, Remark, Role, User
from apps.core.steps import next_step, step
from apps.measurements.models import Measurement, ProtocolRun, TestSession, Trial
from apps.reports.models import Audience, Report
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


def _protocol(org, code="cmj", *, rpe=False, key=True, mdc=1.0):
    protocol = Protocol.objects.create(organization=org, code=code, name=code.upper(),
                                       family=TestFamily.FORCE_PLATE, rpe_after=rpe)
    metric = MetricDef.objects.create(organization=org, code=f"{code}_vyska", name="Výška",
                                      family=TestFamily.FORCE_PLATE, unit="cm", mdc=mdc,
                                      plausible_min=0, plausible_max=100)
    ProtocolMetric.objects.create(protocol=protocol, metric=metric, is_primary=key)
    return protocol, metric


def _session(org, subject, protocol, day=None):
    session = TestSession.objects.create(organization=org, subject=subject,
                                         date=day or timezone.localdate())
    run = ProtocolRun.objects.create(session=session, protocol=protocol)
    return session, run


def _measure(run, metric, *values):
    for n, value in enumerate(values, start=1):
        trial = Trial.objects.create(protocol_run=run, number=n)
        Measurement.objects.create(trial=trial, metric=metric, value=value)


# --- společná součástka ----------------------------------------------------------------

def test_dalsi_krok_preskoci_volitelne():
    steps = [step(1, "a", True), step(2, "b", False, optional=True), step(3, "c", False)]
    assert next_step(steps)["title"] == "c"
    steps = [step(1, "a", True), step(2, "b", False, optional=True)]
    assert next_step(steps)["title"] == "b"
    assert next_step([step(1, "a", True)]) is None


# --- přehled: dnes ------------------------------------------------------------------------

def test_prehled_vede_dnem(org):
    lab, client = _user(org, Role.LAB, "laborant")
    protocol, metric = _protocol(org, rpe=True)
    subject = Subject.objects.create(organization=org, code="FTVS-0001")

    page = client.get(reverse("dashboard"))
    assert page.status_code == 200
    dnes = page.context["dnes"]
    assert [s["title"] for s in dnes] == ["Kdo dnes přijde", "Hodnoty", "Kontrola", "Zprávy", "Předání"]
    assert page.context["next_step"]["title"] == "Kdo dnes přijde"
    assert "Další krok: Kdo dnes přijde" in page.content.decode()

    session, run = _session(org, subject, protocol)
    page = client.get(reverse("dashboard"))
    assert page.context["next_step"]["title"] == "Hodnoty"
    assert page.context["next_step"]["url"] == reverse("session_detail", args=[session.pk])

    _measure(run, metric, 30, 31, 30.5)
    page = client.get(reverse("dashboard"))
    assert page.context["next_step"]["title"] == "Kontrola"  # chybí RPE po zátěžovém testu
    assert "chybí RPE" in page.context["next_step"]["text"]

    protocol.rpe_after = False
    protocol.save()
    page = client.get(reverse("dashboard"))
    assert page.context["next_step"]["title"] == "Zprávy"
    assert "bez zprávy" in page.context["next_step"]["text"]

    report = Report.objects.create(organization=org, subject=subject, session=session,
                                   report_number="FT-1", audience=Audience.CLINICIAN,
                                   status=Report.Status.RELEASED, released_at=timezone.now())
    page = client.get(reverse("dashboard"))
    assert page.context["next_step"] is None and "dnes nic nečeká" in page.content.decode()

    Consent.objects.create(subject=subject, scope=Consent.Scope.REPORT_HANDOVER,
                           granted_on=timezone.localdate())
    page = client.get(reverse("dashboard"))
    assert page.context["next_step"]["title"] == "Předání"
    assert page.context["next_step"]["url"] == reverse("report_detail", args=[report.pk])


def test_prehled_kontrola_hlida_nestabilni_a_mimo_rozsah(org):
    _, client = _user(org, Role.LAB, "laborant")
    protocol, metric = _protocol(org)
    metric.trial_cv_limit = 10
    metric.save()
    subject = Subject.objects.create(organization=org, code="FTVS-0001")
    session, run = _session(org, subject, protocol)
    _measure(run, metric, 10, 40, 25)  # velký rozptyl pokusů
    page = client.get(reverse("dashboard"))
    krok = page.context["dnes"][2]
    assert not krok["done"] and krok["count"] == 1 and "nestabilní" in krok["text"]
    assert krok["url"] == reverse("session_detail", args=[session.pk])

    Measurement.objects.filter(trial__protocol_run=run).update(quality=Measurement.Quality.OUT_OF_RANGE)
    krok = client.get(reverse("dashboard")).context["dnes"][2]
    assert "mimo věrohodný rozsah" in krok["text"] and krok["count"] == 4


def test_vyzkumnik_vidi_den_bez_tlacitek(org):
    _, client = _user(org, Role.RESEARCHER, "vyzkumnik")
    page = client.get(reverse("dashboard"))
    assert page.status_code == 200 and not page.context["may_act"]
    assert "Dnešní testování</a>" not in page.content.decode()


# --- stav pracoviště ------------------------------------------------------------------------

def test_stav_pracoviste_pocita_z_dat(org):
    admin, client = _user(org, Role.ADMIN, "spravce")
    page = client.get(reverse("workplace"))
    assert page.status_code == 200
    steps = {s["title"]: s for s in page.context["steps"]}
    assert not steps["Kolegové"]["done"] and steps["Kolegové"]["admin_only"]
    assert not steps["Sporty a baterie"]["done"]
    assert steps["Přístroje a import"]["optional"] and steps["Objednávky"]["optional"]
    assert page.context["next_step"]["title"] == "Kolegové"
    assert "Nastavení pracoviště" in page.content.decode()
    # přehled správce upozorní, kolik kroků čeká
    assert client.get(reverse("dashboard")).context["nastaveni_ceka"] >= 3

    User.objects.create(username="kolega", organization=org, role=Role.LAB)
    sport = Sport.objects.create(organization=org, name="Florbal", code="florbal")
    protocol, metric = _protocol(org, mdc=None)
    battery = TestBattery.objects.create(organization=org, sport=sport)
    battery.items.create(protocol=protocol)
    steps = {s["title"]: s for s in client.get(reverse("workplace")).context["steps"]}
    assert steps["Kolegové"]["done"] and steps["Sporty a baterie"]["done"]
    assert steps["Testy a klíčové ukazatele"]["done"]
    assert not steps["MDC u klíčových ukazatelů"]["done"] and "1 z 1" in steps["MDC u klíčových ukazatelů"]["text"]
    metric.mdc = 1.5
    metric.save()
    steps = {s["title"]: s for s in client.get(reverse("workplace")).context["steps"]}
    assert steps["MDC u klíčových ukazatelů"]["done"]

    # bez klíčového ukazatele
    ProtocolMetric.objects.update(is_primary=False)
    steps = {s["title"]: s for s in client.get(reverse("workplace")).context["steps"]}
    assert not steps["Testy a klíčové ukazatele"]["done"] and "bez klíčového ukazatele" in steps["Testy a klíčové ukazatele"]["text"]


def test_stav_pracoviste_vidi_i_laborant_a_vyzkumnik(org):
    _, lab_client = _user(org, Role.LAB, "laborant")
    html = lab_client.get(reverse("workplace")).content.decode()
    assert "nastavuje správce" in html and "Stav pracoviště" in html
    assert reverse("colleagues") not in html
    _, r_client = _user(org, Role.RESEARCHER, "vyzkumnik")
    page = r_client.get(reverse("workplace"))
    assert page.status_code == 200 and not page.context["may_act"]
    assert "nastaveni_ceka" not in lab_client.get(reverse("dashboard")).context or \
        lab_client.get(reverse("dashboard")).context["nastaveni_ceka"] == 0


# --- připomínky -----------------------------------------------------------------------------

def test_pripominka_vznikne_kde_ji_kolega_napadne_a_spravce_ji_vyridi(org):
    lab, lab_client = _user(org, Role.LAB, "laborant")
    admin, admin_client = _user(org, Role.ADMIN, "spravce")
    html = lab_client.get(reverse("genetics_home")).content.decode()
    assert reverse("remark_new") in html and "Připomínka" in html

    url = reverse("remark_new") + "?stranka=/genetika/&oddil=Pr%C5%AFvodce+nastaven%C3%ADm&krok=2+Karty"
    page = lab_client.get(url)
    assert page.status_code == 200 and page.context["context_text"] == "Průvodce nastavením · 2 Karty"
    resp = lab_client.post(reverse("remark_new"), {
        "stranka": "/genetika/", "oddil": "Průvodce nastavením · 2 Karty",
        "text": "Načtení z Wordu by mělo říct, co se změnilo."})
    assert resp.status_code == 302 and resp.url == "/genetika/"
    remark = Remark.objects.get()
    assert (remark.user, remark.organization, remark.page) == (lab, org, "/genetika/")
    assert remark.status == Remark.Status.OPEN
    # prázdná se neuloží, cizí adresa se nepoužije jako cíl návratu
    lab_client.post(reverse("remark_new"), {"stranka": "/genetika/", "text": "  "})
    resp = lab_client.post(reverse("remark_new"), {"stranka": "https://jinde.cz/x", "text": "x"})
    assert Remark.objects.count() == 2 and resp.url == reverse("dashboard")
    assert Remark.objects.latest("pk").page == ""

    # seznam jen správce; v menu počet nových
    assert lab_client.get(reverse("remarks")).status_code == 403
    html = admin_client.get(reverse("dashboard")).content.decode()
    assert 'href="/pripominky/"' in html and "nav-pocet" in html
    page = admin_client.get(reverse("remarks"))
    assert page.status_code == 200 and "Načtení z Wordu" in page.content.decode()
    admin_client.post(reverse("remarks"), {"pripominka": remark.pk, "akce": "vyridit",
                                          "odpoved": "Hotovo: hlášení po načtení."})
    remark.refresh_from_db()
    assert remark.status == Remark.Status.DONE and remark.resolved_by == admin
    assert remark.answer.startswith("Hotovo")
    assert "Načtení z Wordu" not in admin_client.get(reverse("remarks")).content.decode()
    assert "Načtení z Wordu" in admin_client.get(reverse("remarks") + "?stav=done").content.decode()


def test_pripominku_posle_i_sportovec_z_portalu(org):
    athlete, client = _user(org, Role.ATHLETE, "sportovec")
    page = client.get(reverse("remark_new") + "?stranka=/muj/")
    assert page.status_code == 200
    resp = client.post(reverse("remark_new"), {"stranka": "/muj/", "text": "Nerozumím souhlasům."})
    assert resp.status_code == 302 and resp.url == "/muj/"
    assert Remark.objects.filter(user=athlete).exists()
    assert client.get(reverse("remarks")).status_code == 302  # seznam není pro portál


def test_stare_koncepty_drzi_krok_zpravy_i_bez_dnesniho_mereni(org):
    _, client = _user(org, Role.LAB, "laborant")
    protocol, metric = _protocol(org)
    subject = Subject.objects.create(organization=org, code="FTVS-0001")
    session, run = _session(org, subject, protocol, day=timezone.localdate() - timedelta(days=3))
    _measure(run, metric, 30, 31, 30.5)
    Report.objects.create(organization=org, subject=subject, session=session, report_number="FT-2",
                          audience=Audience.ATHLETE, status=Report.Status.DRAFT)
    dnes = client.get(reverse("dashboard")).context["dnes"]
    zpravy = dnes[3]
    assert not zpravy["done"] and zpravy["count"] == 1 and "konceptů" in zpravy["text"]
