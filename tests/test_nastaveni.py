"""
Nastavení, dávka 1: stránka Nastavení místo administrace (stav pracoviště
a kategorie), MDC u ukazatelů se zdrojem, sloupce exportů VALD (profily
importu) a pracoviště a týmy – všechno v aplikaci, administrace jen pro
pokročilé.
"""

import pytest
from cryptography.fernet import Fernet
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from apps.catalog.models import (
    ImportColumn,
    ImportProfile,
    MetricDef,
    Protocol,
    ProtocolMetric,
    TestBattery,
    TestFamily,
)
from apps.core.models import Organization, Role, User
from apps.subjects.models import Sport, Subject, Team
from tests.test_novy_sportovec import form as subject_form


@pytest.fixture
def org(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    return Organization.objects.create(name="FTVS", short_name="ftvs")


def _user(org, role, username):
    user = User.objects.create(username=username, organization=org, role=role,
                               is_staff=role == Role.ADMIN)
    client = Client()
    client.force_login(user)
    return user, client


def _battery(org):
    sport = Sport.objects.create(organization=org, name="Florbal", code="florbal")
    protocol = Protocol.objects.create(organization=org, code="cmj", name="CMJ",
                                       family=TestFamily.FORCE_PLATE)
    key = MetricDef.objects.create(organization=org, code="cmj_vyska", name="Výška",
                                   family=TestFamily.FORCE_PLATE, unit="cm")
    other = MetricDef.objects.create(organization=org, code="cmj_sila", name="Síla",
                                     family=TestFamily.FORCE_PLATE, unit="N")
    ProtocolMetric.objects.create(protocol=protocol, metric=key, is_primary=True)
    ProtocolMetric.objects.create(protocol=protocol, metric=other)
    TestBattery.objects.create(organization=org, sport=sport).items.create(protocol=protocol)
    return protocol, key, other


# --- stránka Nastavení -----------------------------------------------------------------------

def test_nastaveni_ma_stav_pracoviste_a_kategorie(org):
    _, client = _user(org, Role.ADMIN, "spravce")
    page = client.get(reverse("workplace"))
    assert page.status_code == 200 and page.request["PATH_INFO"] == "/nastaveni/"
    text = page.content.decode()
    assert "Stav pracoviště" in text and "Kam co patří" in text
    titles = [s["title"] for s in page.context["sections"]]
    assert titles[:4] == ["Pracoviště a kolegové", "Sporty a baterie testů", "Testy a ukazatele",
                          "Přístroje a import"]
    assert "Genetika" in titles and "Klíče a model" in titles
    for name in ("workplace_org", "mdc_settings", "import_profiles", "colleagues", "sport_list"):
        assert reverse(name) in text, name
    assert 'href="/admin/"' in text  # pro pokročilé, jen správce
    # starý odkaz vede sem
    assert client.get("/stav/").url == "/nastaveni/"
    # navigace: jedna položka Nastavení, žádný odkaz do administrace v menu
    assert ">Nastavení<" in text and "Katalog a nastavení" not in text

    _, lab = _user(org, Role.LAB, "laborant")
    text = lab.get(reverse("workplace")).content.decode()
    assert "nastavuje správce" in text and reverse("workplace_org") not in text
    assert reverse("sport_list") in text and 'href="/admin/"' not in text
    _, researcher = _user(org, Role.RESEARCHER, "vyzkumnik")
    page = researcher.get(reverse("workplace"))
    assert page.status_code == 200 and not page.context["may_act"]


# --- MDC u ukazatelů ---------------------------------------------------------------------------

def test_mdc_se_zapisuje_se_zdrojem(org):
    _, client = _user(org, Role.ADMIN, "spravce")
    _, lab = _user(org, Role.LAB, "laborant")
    protocol, key, other = _battery(org)
    MetricDef.objects.create(organization=org, code="jiny", name="Jiný ukazatel",
                             family=TestFamily.FIELD, unit="s")
    url = reverse("mdc_settings")
    page = client.get(url)
    assert page.status_code == 200
    text = page.content.decode()
    assert [r["metric"].pk for r in page.context["rows"]] == [key.pk, other.pk]  # klíčový první
    assert page.context["rows"][0]["key"] and "klíčový" in text and "CMJ" in text
    assert [r["metric"].name for r in page.context["others"]] == ["Jiný ukazatel"]
    assert "1 klíčových, 1 bez MDC" in text

    # hodnota bez zdroje se neuloží, s čárkou ano; ostatní řádky se uloží
    text = client.post(url, {f"mdc_{key.pk}": "1,5", f"zdroj_{key.pk}": "",
                             f"mdc_{other.pk}": "12", f"swc_{other.pk}": "20",
                             f"zdroj_{other.pk}": "reliabilita FTVS 2025, n = 30"},
                       follow=True).content.decode()
    assert "doplňte zdroj" in text and "1 ukazatelů změněno" in text
    key.refresh_from_db()
    other.refresh_from_db()
    assert key.mdc is None
    assert (other.mdc, other.swc, other.mdc_source) == (12.0, 20.0, "reliabilita FTVS 2025, n = 30")

    client.post(url, {f"mdc_{key.pk}": "1,5", f"zdroj_{key.pk}": "Smith 2020",
                      f"mdc_{other.pk}": "12", f"swc_{other.pk}": "20",
                      f"zdroj_{other.pk}": "reliabilita FTVS 2025, n = 30"})
    key.refresh_from_db()
    assert key.mdc == 1.5 and key.mdc_source == "Smith 2020"
    steps = {s["title"]: s for s in client.get(url).context["steps"]}
    assert steps["MDC u klíčových ukazatelů"]["done"]
    assert steps["MDC u klíčových ukazatelů"]["url"] == url
    assert "0 bez MDC" in client.get(url).content.decode()

    # nesmysl se nahlásí; laborant jen čte
    text = client.post(url, {f"mdc_{key.pk}": "hodně", f"zdroj_{key.pk}": "x"}, follow=True).content.decode()
    assert "musí být číslo" in text
    key.refresh_from_db()
    assert key.mdc == 1.5
    assert lab.get(url).status_code == 200 and "readonly" in lab.get(url).content.decode()
    assert lab.post(url, {f"mdc_{key.pk}": "9", f"zdroj_{key.pk}": "x"}).status_code == 403
    # stav pracoviště vede na tuhle stránku
    steps = {s["title"]: s for s in client.get(reverse("workplace")).context["steps"]}
    assert steps["MDC u klíčových ukazatelů"]["url"] == url


# --- sloupce exportů (profily importu) ------------------------------------------------------------

def test_profily_importu_v_aplikaci(org):
    call_command("seed_catalog", verbosity=0)
    _, client = _user(org, Role.ADMIN, "spravce")
    _, lab = _user(org, Role.LAB, "laborant")
    url = reverse("import_profiles")
    page = client.get(url)
    assert page.status_code == 200
    text = page.content.decode()
    assert "VALD ForceDecks" in text and "Countermovement Jump" in text and 'id="vald_forcedecks"' in text
    assert "Ukazatele testu Countermovement jump" in text
    cmj = ImportProfile.objects.get(device="vald_forcedecks", test_type="Countermovement Jump")
    column = cmj.columns.get(column="Body Weight [kg]")
    height = MetricDef.objects.get(code="cmj_height", organization__isnull=True)
    sj = Protocol.objects.get(code="sj", organization__isnull=True)

    data = {}
    for p in ImportProfile.objects.exclude(device__startswith="vlastni:"):
        data[f"p{p.pk}_protocol"] = str(p.protocol_id)
        data[f"p{p.pk}_active"] = "on"
        for c in p.columns.all():
            data.update({f"c{c.pk}_column": c.column, f"c{c.pk}_metric": str(c.metric_id),
                         f"c{c.pk}_factor": str(c.factor)})
            if c.with_sides:
                data[f"c{c.pk}_sides"] = "on"
    # přejmenovat sloupec, vypnout strany, přidat nový sloupec, založit nový typ testu
    data.pop(f"c{column.pk}_sides", None)
    data.update({f"c{column.pk}_column": "Body Weight (kg)", f"c{column.pk}_factor": "1",
                 f"n{cmj.pk}_0_column": "Jump Height (Flight Time) [cm]",
                 f"n{cmj.pk}_0_metric": str(height.pk), f"n{cmj.pk}_0_factor": "1",
                 f"n{cmj.pk}_1_column": "Body Weight (kg)", f"n{cmj.pk}_1_metric": str(height.pk),
                 "np_device": "vald_forcedecks", "np_test_type": "Drop Jump", "np_protocol": str(sj.pk)})
    text = client.post(url, data, follow=True).content.decode()
    assert "uložené" in text and "už v profilu je" in text  # duplicitní nový řádek
    column.refresh_from_db()
    assert column.column == "Body Weight (kg)" and not column.with_sides
    new = cmj.columns.get(column="Jump Height (Flight Time) [cm]")
    assert new.metric == height and new.with_sides is False and new.factor == 1.0
    assert ImportProfile.objects.get(device="vald_forcedecks", test_type="Drop Jump").protocol == sj
    assert "Drop Jump" in client.get(url).content.decode()

    # smazání sloupce a vypnutí profilu; laborant jen čte
    data = {k: v for k, v in data.items() if not k.startswith("np_") and not k.startswith(f"n{cmj.pk}_")}
    data.update({f"c{new.pk}_delete": "on", f"c{new.pk}_column": new.column,
                 f"c{new.pk}_metric": str(height.pk)})
    data.pop(f"p{cmj.pk}_active")
    client.post(url, data)
    cmj.refresh_from_db()
    assert not cmj.is_active and not ImportColumn.objects.filter(pk=new.pk).exists()
    assert lab.get(url).status_code == 200 and lab.post(url, data).status_code == 403


# --- pracoviště a týmy ---------------------------------------------------------------------------

def test_pracoviste_a_tymy(org):
    _, client = _user(org, Role.ADMIN, "spravce")
    _, lab = _user(org, Role.LAB, "laborant")
    sport = Sport.objects.create(organization=org, name="Florbal", code="florbal")
    url = reverse("workplace_org")
    assert lab.get(url).status_code == 403
    page = client.get(url)
    assert page.status_code == 200 and "ftvs" in page.content.decode()

    client.post(url, {"nazev": "FTVS UK – laboratoř", "nt_name": "U19", "nt_sport": str(sport.pk)})
    org.refresh_from_db()
    team = Team.objects.get(organization=org)
    assert org.name == "FTVS UK – laboratoř" and (team.name, team.sport) == ("U19", sport)

    text = client.post(url, {"nazev": org.name, f"t{team.pk}_name": "U19 muži",
                             f"t{team.pk}_sport": str(sport.pk), "nt_name": "bez sportu"},
                       follow=True).content.decode()
    team.refresh_from_db()
    assert team.name == "U19 muži" and "Nový tým: napište název a vyberte sport" in text
    assert Team.objects.count() == 1

    # tým se vybírá na kartě sportovce; tým jiného sportu neprojde
    hokej = Sport.objects.create(organization=org, name="Hokej", code="hokej")
    page = client.post(reverse("subject_new"), subject_form(sport, team=team.pk))
    subject = Subject.objects.get()
    assert page.status_code == 302 and subject.team == team
    text = client.post(reverse("subject_edit", args=[subject.pk]),
                       subject_form(hokej, team=team.pk)).content.decode()
    assert "patří ke sportu Florbal" in text
    subject.refresh_from_db()
    assert subject.team == team and subject.sport == sport
    assert client.get(reverse("workplace_org")).context["teams"][0].sportovcu == 1

    client.post(url, {"nazev": org.name, f"t{team.pk}_delete": "on"})
    subject.refresh_from_db()
    assert not Team.objects.exists() and subject.team is None  # sportovec zůstal, jen bez týmu
