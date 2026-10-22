"""Portál sportovce a zákonného zástupce: pozvánka, účet, sdílení s trenérem, zprávy, dotazník."""


import pytest
from cryptography.fernet import Fernet
from django.core.management import call_command
from django.test import Client

from apps.core.models import AuditLog, Organization, Role, User
from apps.reports import services as reports
from apps.subjects import accounts
from apps.subjects.models import Consent, Guardian, Sharing, Subject, SubjectIdentity
from apps.subjects.search import names_for
from tests.test_reports import prostredi  # noqa: F401

HESLO = "dlouhe-heslo-sportovce-1"


@pytest.fixture
def lab(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    user = User.objects.create(username="lab", organization=org, role=Role.LAB)
    client = Client()
    client.force_login(user)
    return org, user, client


def _subject(org, code, first, last):
    subject = Subject.objects.create(organization=org, code=code)
    identity = SubjectIdentity(subject=subject)
    identity.set_names(first, last)
    identity.save()
    return subject


def _invite(client, subject, kind="athlete") -> str:
    response = client.post(f"/sportovci/{subject.pk}/pozvanka/", {"druh": kind})
    page = client.get(response.url).content.decode()
    token = subject.invitations.latest("pk").token
    assert f"/ucet/pozvanka/{token}/" in page and "<svg" in page
    return token


def _register(token, email="jana@example.cz") -> Client:
    client = Client()
    assert "Založit účet" in client.get(f"/ucet/pozvanka/{token}/").content.decode()
    response = client.post(f"/ucet/pozvanka/{token}/", {"email": email, "password1": HESLO,
                                                        "password2": HESLO})
    assert response.status_code == 302 and response.url == "/muj/"
    return client


def test_pozvanka_zalozi_ucet_sportovce(lab):
    org, _, client = lab
    subject = _subject(org, "FTVS-0001", "Jana", "Nováková")
    other = _subject(org, "FTVS-0002", "Petr", "Dvořák")
    token = _invite(client, subject)
    athlete = _register(token)

    user = User.objects.get(username="jana@example.cz")
    assert user.role == Role.ATHLETE and user.organization == org
    assert SubjectIdentity.objects.get(subject=subject).user == user
    # Jeden sportovec: domů = rovnou jeho stránka, se jménem a kódem.
    response = athlete.get("/muj/")
    assert response.url == f"/muj/{subject.pk}/"
    page = athlete.get(f"/muj/{subject.pk}/").content.decode()
    assert "Jana Nováková" in page and "FTVS-0001" in page and "Nové měření" not in page
    # Cizí sportovec není vidět, laboratorní obrazovky přesměrují do portálu.
    assert athlete.get(f"/muj/{other.pk}/").status_code == 404
    assert athlete.get("/sportovci/").url == "/muj/"
    assert set(Subject.objects.for_user(user)) == {subject}
    # Pozvánka je spotřebovaná.
    assert Client().get(f"/ucet/pozvanka/{token}/").status_code == 410
    assert "Pozvánka neplatí" in Client().get("/ucet/pozvanka/nesmysl/").content.decode()
    # Laboratoř vidí, že účet existuje.
    assert "jana@example.cz" in client.get(f"/sportovci/{subject.pk}/").content.decode()


def test_zakonny_zastupce_zastupuje_dve_deti(lab):
    org, _, client = lab
    first = _subject(org, "FTVS-0001", "Adam", "Malý")
    second = _subject(org, "FTVS-0002", "Eva", "Malá")
    parent = _register(_invite(client, first, "guardian"), email="rodic@example.cz")
    user = User.objects.get(username="rodic@example.cz")
    assert Guardian.objects.filter(user=user, identity__subject=first).exists()

    # Druhé dítě: přihlášený rodič pozvánku jen přijme.
    token = _invite(client, second, "guardian")
    page = parent.get(f"/ucet/pozvanka/{token}/").content.decode()
    assert "Připojit" in page and "rodic@example.cz" in page
    parent.post(f"/ucet/pozvanka/{token}/", {"akce": "prijmout"})
    home = parent.get("/muj/").content.decode()
    assert "Adam Malý" in home and "Eva Malá" in home
    assert set(Subject.objects.for_user(user)) == {first, second}


def test_sdileni_potvrzuje_sportovec_v_uctu(lab):
    org, lab_user, client = lab
    subject = _subject(org, "FTVS-0001", "Jana", "Nováková")
    coach = User.objects.create(username="trener", organization=org, role=Role.COACH,
                                first_name="Karel", last_name="Trenér")
    athlete = _register(_invite(client, subject))

    # Trenér zatím nevidí nic, ani jméno.
    assert names_for([subject], coach) == {}
    assert not Subject.objects.for_user(coach).exists()

    # Laboratoř požádá; platí to až po potvrzení.
    client.post(f"/sportovci/{subject.pk}/sdileni/", {"trener": coach.pk})
    sharing = Sharing.objects.get(subject=subject, coach=coach)
    assert sharing.status == Sharing.Status.REQUESTED
    assert not Subject.objects.for_user(coach).exists()
    page = athlete.get(f"/muj/{subject.pk}/").content.decode()
    assert "žádá o přístup" in page
    page = athlete.get(f"/muj/{subject.pk}/souhlasy/").content.decode()
    assert "Karel Trenér" in page and "Potvrdit" in page

    athlete.post(f"/muj/{subject.pk}/souhlasy/", {"akce": "potvrdit", "sdileni": sharing.pk})
    sharing.refresh_from_db()
    assert sharing.status == Sharing.Status.ACTIVE and sharing.decided_by.username == "jana@example.cz"
    assert sharing.consent.scope == Consent.Scope.COACH and sharing.consent.is_valid
    assert Consent.has(subject, Consent.Scope.COACH)
    assert names_for([subject], coach) == {subject.pk: "Jana Nováková"}
    assert set(Subject.objects.for_user(coach)) == {subject}

    # Odvolání: trenér od té chvíle nevidí nic.
    athlete.post(f"/muj/{subject.pk}/souhlasy/", {"akce": "odvolat", "sdileni": sharing.pk})
    sharing.refresh_from_db()
    assert sharing.status == Sharing.Status.REVOKED and sharing.consent.revoked_on
    assert not Consent.has(subject, Consent.Scope.COACH)
    assert names_for([subject], coach) == {} and not Subject.objects.for_user(coach).exists()
    assert AuditLog.objects.filter(subject_code="FTVS-0001", detail__sdileni="odvolat").exists()


def test_sportovec_si_sdileni_zapne_sam(lab):
    org, _, client = lab
    subject = _subject(org, "FTVS-0001", "Jana", "Nováková")
    coach = User.objects.create(username="trener", organization=org, role=Role.COACH)
    athlete = _register(_invite(client, subject))
    athlete.post(f"/muj/{subject.pk}/souhlasy/", {"akce": "sdilet", "trener": coach.pk})
    sharing = Sharing.objects.get(subject=subject, coach=coach)
    assert sharing.status == Sharing.Status.ACTIVE and sharing.consent is not None
    # Laboratoř vidí stav na kartě sportovce.
    assert "aktivní" in client.get(f"/sportovci/{subject.pk}/").content.decode()


def test_sportovec_vidi_jen_vydane_zpravy_pro_sebe(prostredi, settings):  # noqa: F811
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    org, user, subject, session = prostredi
    identity = SubjectIdentity(subject=subject)
    identity.set_names("Jana", "Nováková")
    identity.save()
    client = Client()
    client.force_login(user)
    athlete = _register(_invite(client, subject))

    for_athlete = reports.release(reports.build_draft(session, user=user, audience="sportovec"),
                                  user=user)
    for_coach = reports.release(reports.build_draft(session, user=user, audience="trener"),
                                user=user)
    draft = reports.build_draft(session, user=user, audience="sportovec")

    page = athlete.get(f"/muj/{subject.pk}/").content.decode()
    assert for_athlete.report_number in page
    assert for_coach.report_number not in page and draft.report_number not in page
    html = athlete.get(f"/muj/{subject.pk}/zprava/{for_athlete.pk}/").content.decode()
    assert "0,85" in html
    assert athlete.get(f"/muj/{subject.pk}/zprava/{for_coach.pk}/").status_code == 404
    assert athlete.get(f"/muj/{subject.pk}/zprava/{draft.pk}/").status_code == 404
    assert AuditLog.objects.filter(action=AuditLog.Action.VIEW, object_type="Report",
                                   object_id=str(for_athlete.pk)).exists()
    # Kdo se díval: zobrazení laborantem je v seznamu, vlastní ne.
    client.get(f"/sportovci/{subject.pk}/")
    page = athlete.get(f"/muj/{subject.pk}/souhlasy/").content.decode()
    assert "laborant" in page


def test_dotaznik_k_dnesnimu_mereni_a_ucet(lab):
    from django.utils import timezone

    from apps.measurements.models import TestSession

    org, _, client = lab
    call_command("seed_catalog", verbosity=0)
    subject = _subject(org, "FTVS-0001", "Jana", "Nováková")
    athlete = _register(_invite(client, subject))
    response = athlete.get(f"/muj/{subject.pk}/dotaznik/")
    assert response.url == f"/muj/{subject.pk}/"         # dnes žádné měření
    TestSession.objects.create(organization=org, subject=subject, date=timezone.localdate())
    response = athlete.get(f"/muj/{subject.pk}/dotaznik/")
    assert response.url.startswith("/d/")
    assert "Vyplnit RPE" in athlete.get(f"/muj/{subject.pk}/").content.decode()
    assert athlete.get("/muj/ucet/").status_code == 200


def test_anonymizace_vypne_ucet_a_odvola_sdileni(lab):
    from apps.subjects import services

    org, _, client = lab
    subject = _subject(org, "FTVS-0001", "Jana", "Nováková")
    coach = User.objects.create(username="trener", organization=org, role=Role.COACH)
    athlete = _register(_invite(client, subject))
    athlete.post(f"/muj/{subject.pk}/souhlasy/", {"akce": "sdilet", "trener": coach.pk})
    services.anonymize(subject)
    assert not User.objects.get(username="jana@example.cz").is_active
    assert Sharing.objects.get(subject=subject).status == Sharing.Status.REVOKED
    assert accounts.accounts_of(subject)["athlete"] is None


def test_laborator_do_portalu_nepatri(lab):
    _, _, client = lab
    assert client.get("/muj/").url == "/"


# --- trenér ------------------------------------------------------------------

def _coach(org, username="trener", first="Karel", last="Trenér"):
    return User.objects.create(username=username, organization=org, role=Role.COACH,
                               first_name=first, last_name=last)


def test_trener_vidi_jen_sdilene_sportovce_jmenem(lab):
    org, _, client = lab
    jana = _subject(org, "FTVS-0001", "Jana", "Nováková")
    petr = _subject(org, "FTVS-0002", "Petr", "Dvořák")
    coach = _coach(org)
    trener = Client()
    trener.force_login(coach)
    page = trener.get("/trener/").content.decode()
    assert "Zatím s vámi nikdo nesdílí" in page and "Nováková" not in page

    # Žádost kódem: sportovec ji vidí, trenér dál nic.
    response = trener.post("/trener/", {"kod": "ftvs-0001"}, follow=True)
    assert "Žádost odeslána" in response.content.decode()
    assert "FTVS-0001" in trener.get("/trener/").content.decode()   # čeká na potvrzení
    assert trener.get(f"/trener/{jana.pk}/").status_code == 404
    response = trener.post("/trener/", {"kod": "FTVS-9999"}, follow=True)
    assert "tu není" in response.content.decode()

    athlete = _register(_invite(client, jana))
    sharing = Sharing.objects.get(subject=jana, coach=coach)
    athlete.post(f"/muj/{jana.pk}/souhlasy/", {"akce": "potvrdit", "sdileni": sharing.pk})

    page = trener.get("/trener/").content.decode()
    assert "Jana Nováková" in page and "Dvořák" not in page and "FTVS-0002" not in page
    page = trener.get(f"/trener/{jana.pk}/").content.decode()
    assert "Jana Nováková" in page and "sdílí od" in page
    assert trener.get(f"/trener/{petr.pk}/").status_code == 404
    # Zobrazení trenérem vidí sportovec v auditu.
    assert "Karel Trenér" in athlete.get(f"/muj/{jana.pk}/souhlasy/").content.decode()

    athlete.post(f"/muj/{jana.pk}/souhlasy/", {"akce": "odvolat", "sdileni": sharing.pk})
    assert trener.get(f"/trener/{jana.pk}/").status_code == 404
    assert "Nováková" not in trener.get("/trener/").content.decode()


def test_trener_vidi_jen_zpravy_pro_trenera_a_prehled_skupiny(prostredi, settings):  # noqa: F811
    from apps.catalog.models import BatteryItem, MetricDef, Protocol, ProtocolMetric, TestBattery

    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    org, user, subject, session = prostredi
    identity = SubjectIdentity(subject=subject)
    identity.set_names("Jana", "Nováková")
    identity.save()
    coach = _coach(org)
    accounts.start_sharing(subject, coach, by=user)
    for_coach = reports.release(reports.build_draft(session, user=user, audience="trener"),
                                user=user)
    for_athlete = reports.release(reports.build_draft(session, user=user, audience="sportovec"),
                                  user=user)
    trener = Client()
    trener.force_login(coach)
    page = trener.get(f"/trener/{subject.pk}/").content.decode()
    assert for_coach.report_number in page and for_athlete.report_number not in page
    assert "0,85" in trener.get(f"/trener/{subject.pk}/zprava/{for_coach.pk}/").content.decode()
    assert trener.get(f"/trener/{subject.pk}/zprava/{for_athlete.pk}/").status_code == 404

    # Baterie sportu -> přehled skupiny s hodnotou klíčového ukazatele.
    from apps.subjects.models import Sport

    sport = Sport.objects.create(organization=org, code="tenis", name="Tenis")
    subject.sport = sport
    subject.save()
    protocol = Protocol.objects.get(code="p")
    ProtocolMetric.objects.create(protocol=protocol, metric=MetricDef.objects.get(code="ir_er_ratio"),
                                  is_primary=True, sides=["B"], speeds=[210])
    battery = TestBattery.objects.create(organization=org, sport=sport)
    BatteryItem.objects.create(battery=battery, protocol=protocol, order=1)
    page = trener.get("/trener/").content.decode()
    assert "Přehled:" in page and "Poměr IR/ER" in page and "0,85" in page
