"""
Individuální testování: položka v menu, sada testů (baterie sportu, jiná
baterie, jako minule, ručně), testy jen z katalogu pracoviště, pořadí podle
baterie dne a upozornění před měřením (omezení zátěže, souhlas, den už existuje).
"""

import re
from datetime import date, timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.catalog.models import BatteryItem, Protocol, TestBattery, TestFamily
from apps.core.models import Organization, Role, User
from apps.external.models import ExternalExam
from apps.measurements import views
from apps.measurements.models import ProtocolRun, TestSession
from apps.subjects.models import Consent, Sport, Subject

CHECKED = re.compile(r'name="protocols" value="(\d+)" id="[^"]+" checked')


@pytest.fixture
def lab(db, client):
    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    user = User.objects.create(username="lab", organization=org, role=Role.LAB)
    hokej = Sport.objects.create(organization=org, code="hokej", name="Lední hokej")
    client.force_login(user)
    return org, user, hokej, client


def protocol(code):
    return Protocol.objects.get(code=code, organization=None)


def baterie(sport, category, codes, name=""):
    battery = TestBattery.objects.create(organization=sport.organization, sport=sport,
                                         category=category, name=name)
    for order, code in enumerate(codes, start=1):
        BatteryItem.objects.create(battery=battery, protocol=protocol(code), order=order)
    return battery


def checked_codes(html):
    pks = {int(pk) for pk in CHECKED.findall(html)}
    return sorted(Protocol.objects.filter(pk__in=pks).values_list("code", flat=True))


def test_menu_individualni_testovani_nad_tymovym(lab):
    *_, client = lab
    page = client.get("/").content.decode()
    nav = page[page.index("<nav"):page.index("</nav>")]
    assert nav.index('href="/mereni/novy/"') < nav.index('href="/testovani/"')
    assert "Individuální testování" in nav
    # tlačítko vpravo nahoře se jmenuje stejně
    header = page[page.index('<header class="app-topbar'):page.index("</header>")]
    assert "Individuální testování</span>" in header and "Nové měření" not in header

    form = client.get("/mereni/novy/").content.decode()
    assert re.search(r'href="/mereni/novy/" class="nav-link active"', form)
    assert re.search(r'href="/mereni/" class="nav-link"', form)       # Přehled testování ne
    detail = client.get("/mereni/").content.decode()
    assert re.search(r'href="/mereni/" class="nav-link active"', detail)


def test_sada_testu_podle_kategorie_jina_baterie_a_poradi(lab):
    org, _, hokej, client = lab
    obecna = baterie(hokej, "", ["cmj", "imtp"])
    dorost = baterie(hokej, "dorost", ["wingate", "sj"])
    florbal = Sport.objects.create(organization=org, code="florbal", name="Florbal")
    host = baterie(florbal, "", ["grip"])
    hrac = Subject.objects.create(organization=org, code="FTVS-0001", sport=hokej,
                                  category="Dorost")

    html = client.get(f"/mereni/novy/?sportovec={hrac.pk}").content.decode()
    assert checked_codes(html) == ["sj", "wingate"]                     # baterie kategorie
    assert f'<option value="{dorost.pk}" selected>' in html
    assert "patří sportovci" in html
    assert f'<option value="{obecna.pk}">' in html                      # jiná baterie sportu
    assert "Baterie jiných sportů" in html and f'<option value="{host.pk}">' in html
    assert "1.</span> Wingate" in html                                  # pořadí baterie

    part = client.get("/mereni/novy/baterie/", {"subject": hrac.pk, "sada": obecna.pk})
    assert checked_codes(part.content.decode()) == ["cmj", "imtp"]
    part = client.get("/mereni/novy/baterie/", {"subject": hrac.pk, "sada": "rucne"})
    assert checked_codes(part.content.decode()) == []

    # založení podle obecné baterie + test mimo ni: den si baterii zapamatuje,
    # pořadí testů dne je pořadí baterie, ostatní za ní
    response = client.post("/mereni/novy/", {
        "subject": hrac.pk, "date": "2026-09-01", "sada": obecna.pk,
        "protocols": [protocol("grip").pk, protocol("imtp").pk, protocol("cmj").pk]})
    session = TestSession.objects.get(subject=hrac)
    assert response.status_code == 302 and session.battery == obecna
    assert [r.protocol.code for r in views._session_runs(session)] == ["cmj", "imtp", "grip"]
    assert [r.protocol.code for r in session.protocol_runs.order_by("pk")] == [
        "cmj", "imtp", "grip"]
    page = client.get(f"/mereni/{session.pk}/").content.decode()
    assert "baterie Lední hokej" in page            # jiná baterie, než jaká mu patří


def test_stejne_testy_jako_minule(lab):
    org, _, hokej, client = lab
    baterie(hokej, "", ["cmj"])
    hrac = Subject.objects.create(organization=org, code="FTVS-0001", sport=hokej)
    minule = TestSession.objects.create(organization=org, subject=hrac,
                                        date=timezone.localdate() - timedelta(days=40))
    for code in ("sprint30", "grip"):
        ProtocolRun.objects.create(session=minule, protocol=protocol(code))

    html = client.get(f"/mereni/novy/?sportovec={hrac.pk}").content.decode()
    assert f"Stejné testy jako {minule.date:%d.%m.%Y} · 2 testy" in html
    assert f"Poslední testovací den {minule.date:%d.%m.%Y}" in html
    part = client.get("/mereni/novy/baterie/", {"subject": hrac.pk, "sada": "minule"})
    assert checked_codes(part.content.decode()) == ["grip", "sprint30"]

    # sport bez baterie: výchozí sada je „jako minule“
    bez = Sport.objects.create(organization=org, code="judo", name="Judo")
    hrac.sport = bez
    hrac.save()
    html = client.get(f"/mereni/novy/?sportovec={hrac.pk}").content.decode()
    assert checked_codes(html) == ["grip", "sprint30"]
    assert "Sport Judo zatím nemá baterii testů" in html


def test_testy_ciziho_pracoviste_se_nenabizeji(lab):
    org, _, hokej, client = lab
    cizi = Organization.objects.create(name="Jiná laboratoř", short_name="jina")
    tajny = Protocol.objects.create(organization=cizi, code="tajny", name="Cizí test",
                                    family=TestFamily.OTHER)
    vlastni = Protocol.objects.create(organization=org, code="vlastni", name="Náš test",
                                      family=TestFamily.OTHER)
    hrac = Subject.objects.create(organization=org, code="FTVS-0001", sport=hokej)

    html = client.get(f"/mereni/novy/?sportovec={hrac.pk}").content.decode()
    assert "Náš test" in html and "Cizí test" not in html
    response = client.post("/mereni/novy/", {"subject": hrac.pk, "date": "2026-09-01",
                                             "protocols": [tajny.pk]})
    assert response.status_code == 200 and not TestSession.objects.exists()

    session = TestSession.objects.create(organization=org, subject=hrac, date=date(2026, 9, 2))
    page = client.get(f"/mereni/{session.pk}/").content.decode()
    assert "Náš test" in page and "Cizí test" not in page        # přidání testu do dne
    client.post(f"/mereni/{session.pk}/protokol/", {"protocol": tajny.pk})
    assert not session.protocol_runs.exists()
    client.post(f"/mereni/{session.pk}/protokol/", {"protocol": vlastni.pk})
    assert session.protocol_runs.get().protocol == vlastni


def test_upozorneni_pred_merenim(lab):
    org, _, hokej, client = lab
    baterie(hokej, "", ["cmj"])
    hrac = Subject.objects.create(organization=org, code="FTVS-0001", sport=hokej)
    today = timezone.localdate()

    html = client.get(f"/mereni/novy/?sportovec={hrac.pk}").content.decode()
    assert "nemá platný souhlas s funkčním testováním" in html
    assert "Platné omezení zátěže" not in html
    assert "Zatím žádný testovací den" in html

    Consent.objects.create(subject=hrac, scope=Consent.Scope.TESTING,
                           granted_on=today - timedelta(days=1))
    ExternalExam.objects.create(subject=hrac, exam_type=ExternalExam.ExamType.MEDICAL,
                                date=today - timedelta(days=3),
                                load_restriction=ExternalExam.Restriction.FULL,
                                restriction_valid_until=today + timedelta(days=10),
                                note="bez skoků")
    den = TestSession.objects.create(organization=org, subject=hrac, date=today)
    ProtocolRun.objects.create(session=den, protocol=protocol("cmj"))
    html = client.get(f"/mereni/novy/?sportovec={hrac.pk}").content.decode()
    assert "nemá platný souhlas" not in html
    assert "Platné omezení zátěže (plné omezení zátěže)" in html and "bez skoků." in html
    assert "border-left-color: var(--bad)" in html
    assert f"Na {today:%d.%m.%Y} už testovací den existuje (1 test)" in html
    assert f"Před {today:%d.%m.%Y} žádný testovací den." in html
    # i v testovacím dni, kde se měří
    page = client.get(f"/mereni/{den.pk}/").content.decode()
    assert "Platné omezení zátěže" in page and "bez skoků" in page

    # po změně data zůstane zaškrtnutí, jak ho operátor upravil
    part = client.get("/mereni/novy/baterie/", {
        "subject": hrac.pk, "date": (today + timedelta(days=1)).isoformat(),
        "zachovat": "1", "protocols": [protocol("grip").pk]}).content.decode()
    assert checked_codes(part) == ["grip"] and "už testovací den existuje" not in part


def test_den_uz_existuje_doplni_testy_i_baterii(lab):
    org, _, hokej, client = lab
    battery = baterie(hokej, "", ["cmj", "sj"])
    hrac = Subject.objects.create(organization=org, code="FTVS-0001", sport=hokej)
    den = TestSession.objects.create(organization=org, subject=hrac, date=date(2026, 9, 1))
    ProtocolRun.objects.create(session=den, protocol=protocol("cmj"))

    client.post("/mereni/novy/", {"subject": hrac.pk, "date": "2026-09-01",
                                  "sada": battery.pk,
                                  "protocols": [protocol("cmj").pk, protocol("sj").pk]})
    den.refresh_from_db()
    assert TestSession.objects.count() == 1 and den.battery == battery
    assert sorted(r.protocol.code for r in den.protocol_runs.all()) == ["cmj", "sj"]


def test_chyba_ve_formulari_zachova_zaskrtnute_testy(lab):
    org, _, hokej, client = lab
    baterie(hokej, "", ["cmj", "imtp"])
    response = client.post("/mereni/novy/", {"date": "2026-09-01",
                                             "protocols": [protocol("grip").pk]})
    assert response.status_code == 200
    assert checked_codes(response.content.decode()) == ["grip"]


def test_tymove_testovani_zapamatuje_baterii(lab):
    org, _, hokej, client = lab
    battery = baterie(hokej, "", ["cmj"])
    hrac = Subject.objects.create(organization=org, code="FTVS-0001", sport=hokej)
    client.post("/testovani/", {"datum": "2026-09-01", "baterie": battery.pk,
                                "sportovec": [hrac.pk]})
    assert TestSession.objects.get(subject=hrac).battery == battery


def test_zopakovani_dne_prenese_baterii(lab):
    from apps.measurements import planning

    org, user, hokej, _ = lab
    battery = baterie(hokej, "", ["cmj"])
    hrac = Subject.objects.create(organization=org, code="FTVS-0001", sport=hokej)
    minule = TestSession.objects.create(organization=org, subject=hrac, date=date(2026, 9, 1),
                                        battery=battery)
    ProtocolRun.objects.create(session=minule, protocol=protocol("cmj"))
    session, created, added = planning.repeat_session(minule, day=date(2026, 10, 1), user=user)
    assert created and added == 1 and session.battery == battery


def test_baterie_nabizi_jen_testy_katalogu_pracoviste(lab):
    from apps.core import access

    org, user, hokej, client = lab
    access.grant(user, settings_sports=True)
    battery = baterie(hokej, "", ["cmj"])
    cizi = Organization.objects.create(name="Jiná laboratoř", short_name="jina")
    tajny = Protocol.objects.create(organization=cizi, code="tajny", name="Cizí test",
                                    family=TestFamily.OTHER)
    page = client.get("/sporty/").content.decode()
    assert "Cizí test" not in page and "Sprint 30 m" in page
    response = client.post(f"/sporty/baterie/{battery.pk}/pridat/", {"protocol": tajny.pk})
    assert response.status_code == 404 and not battery.items.filter(protocol=tajny).exists()
