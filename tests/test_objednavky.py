"""Objednávky: veřejný formulář, kapacita termínů, schválení → sportovci a testovací dny."""

import re
from datetime import date, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from django.core import mail
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from apps.booking.models import BookingRequest, Offer, Participant, Slot
from apps.catalog.models import Protocol
from apps.core.models import Organization, Role, User
from apps.ingest.adapters.vald import identity_ids
from apps.measurements.models import TestSession
from apps.subjects.models import Consent, Subject, SubjectExternalId, SubjectIdentity


@pytest.fixture
def lab(db, settings):
    from django.core.cache import cache

    cache.clear()          # omezení počtu objednávek z jedné adresy
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    silova = Offer.objects.create(organization=org, kind=Offer.Kind.PACKAGE,
                                  name="Silová diagnostika", price=1500)
    silova.protocols.set(Protocol.objects.filter(code__in=["cmj", "imtp"]))
    wingate = Offer.objects.create(organization=org, name="Wingate", price=1200)
    wingate.protocols.set(Protocol.objects.filter(code="wingate"))
    start = timezone.make_aware(datetime.combine(timezone.localdate() + timedelta(days=7),
                                                 datetime.min.time().replace(hour=9)))
    slot = Slot.objects.create(organization=org, start=start, location="Laboratoř 1")
    team_slot = Slot.objects.create(organization=org, start=start + timedelta(days=1),
                                    capacity=3, location="Hala")
    staff = Client()
    staff.force_login(User.objects.create(username="lab", organization=org, role=Role.LAB))
    return org, {"silova": silova, "wingate": wingate}, slot, team_slot, staff


def jednotlivec(slot, offers, **extra):
    data = {"kdo": "jednotlivec", "nabidka": [o.pk for o in offers], "termin": slot.pk,
            "jmeno": "Jana", "prijmeni": "Nováková", "narozeni": "1998-03-12", "pohlavi": "F",
            "zraneni": "", "email": "jana@example.cz", "telefon": "777123456",
            "sport": "Atletika", "cil": "progres", "uroven": "national", "obdobi": "prep",
            "souhlas": "on", "souhlas_lekar": "on"}
    data.update(extra)
    return data


def test_formular_se_zobrazi_s_nabidkou_cenami_a_terminy(lab):
    html = Client().get("/objednavka/").content.decode()
    assert "Silová diagnostika" in html and "1500 Kč" in html and "Laboratoř 1" in html


def test_jednotlivec_odesle_a_laborant_schvali(lab):
    org, offers, slot, _, staff = lab
    response = Client().post("/objednavka/", jednotlivec(slot, [offers["silova"],
                                                                offers["wingate"]]))
    assert response.status_code == 200 and "objednávka je odeslaná" in response.content.decode()
    booking = BookingRequest.objects.get()
    assert booking.status == "nova" and booking.price_total == 2700
    assert booking.email == "jana@example.cz"
    assert "Nováková" not in booking.contact_name_enc          # uloženo šifrovaně
    assert mail.outbox[-1].to == ["jana@example.cz"]

    # laboratoř vidí žádost v seznamu i s počtem v menu
    seznam = staff.get("/objednavky/").content.decode()
    assert booking.number in seznam and "Jana Nováková" in seznam
    assert 'class="nav-pocet"' in seznam
    assert "nový – založí se" in staff.get(f"/objednavky/{booking.pk}/").content.decode()

    staff.post(f"/objednavky/{booking.pk}/vyridit/", {"akce": "schvalit", "zprava": "Vezměte si obuv."})
    booking.refresh_from_db()
    assert booking.status == "schvalena"
    subject = Subject.objects.get()
    assert subject.identity.full_name == "Jana Nováková" and subject.sport.name == "Atletika"
    assert subject.level == "national" and subject.birth_year == 1998
    session = TestSession.objects.get(subject=subject)
    assert session.date == timezone.localtime(slot.start).date()
    assert session.location == "Laboratoř 1" and session.season_phase == "prep"
    assert sorted(r.protocol.code for r in session.protocol_runs.all()) == ["cmj", "imtp", "wingate"]
    assert Consent.has(subject, Consent.Scope.TESTING)
    assert Consent.has(subject, Consent.Scope.REPORT_HANDOVER)
    assert "Vezměte si obuv." in mail.outbox[-1].body


def test_klient_ktery_uz_u_nas_byl_dostane_testovani_ke_stare_karte(lab):
    org, offers, slot, _, staff = lab
    stary = Subject.objects.create(organization=org, code="FTVS-0007")
    for system, value in identity_ids("Jana Nováková", date(1998, 3, 12)).items():
        SubjectExternalId.objects.create(subject=stary, system=system, value=value)
    Client().post("/objednavka/", jednotlivec(slot, [offers["silova"]]))
    booking = BookingRequest.objects.get()
    assert "už u nás byl" in staff.get(f"/objednavky/{booking.pk}/").content.decode()
    staff.post(f"/objednavky/{booking.pk}/vyridit/", {"akce": "schvalit"})
    assert Subject.objects.count() == 1
    assert TestSession.objects.get().subject == stary


def test_tym_s_nezletilym_a_kapacita_terminu(lab):
    org, offers, _, team_slot, staff = lab
    mladsi = (timezone.localdate() - timedelta(days=16 * 365)).isoformat()
    tym = {"kdo": "tym", "tym": "HC Slavia U17", "nabidka": [offers["wingate"].pk],
           "termin": team_slot.pk, "kontakt": "Petr Trenér", "email": "trener@example.cz",
           "jmeno": ["Adam", "Bořek", ""], "prijmeni": ["Adámek", "Bořil", ""],
           "narozeni": [mladsi, mladsi, ""], "pohlavi": ["M", "M", ""],
           "zraneni": ["", "výron kotníku, srpen", ""], "souhlas": "on",
           "sport": "Lední hokej", "kategorie": "dorost"}

    bez_zastupce = Client().post("/objednavka/", tym)
    assert bez_zastupce.status_code == 400 and "zákonného zástupce" in bez_zastupce.content.decode()

    Client().post("/objednavka/", {**tym, "souhlas_zastupce": "on"})
    booking = BookingRequest.objects.get()
    assert booking.kind == "tym" and booking.participants.count() == 2   # prázdný řádek pryč
    assert booking.price_total == 2400
    assert team_slot.free() == 1

    # další tým o dvou lidech se na termín s jedním volným místem nevejde
    plno = Client().post("/objednavka/", {**tym, "souhlas_zastupce": "on", "tym": "Jiný"})
    assert plno.status_code == 400 and "zbývá jen 1" in plno.content.decode()

    staff.post(f"/objednavky/{booking.pk}/vyridit/", {"akce": "schvalit"})
    hraci = Subject.objects.all()
    assert hraci.count() == 2 and {s.category for s in hraci} == {"dorost"}
    assert "výron kotníku" in TestSession.objects.get(subject__identity__isnull=False,
                                                      note__contains="výron").note
    # kontakt trenéra se do identity hráčů neukládá
    assert not any(i.email_enc for i in SubjectIdentity.objects.all())


def test_zamitnuti_uvolni_termin(lab):
    _, offers, slot, _, staff = lab
    Client().post("/objednavka/", jednotlivec(slot, [offers["wingate"]]))
    booking = BookingRequest.objects.get()
    assert slot.free() == 0
    assert str(slot.pk) not in re.findall(r'name="termin" value="(\d+)"',
                                          Client().get("/objednavka/").content.decode())
    staff.post(f"/objednavky/{booking.pk}/vyridit/", {"akce": "zamitnout", "zprava": "Nemoc."})
    booking.refresh_from_db()
    assert booking.status == "zamitnuta" and slot.free() == 1
    assert not Subject.objects.exists()
    stav = Client().get(f"/objednavka/stav/{booking.token}/").content.decode()
    assert "nebylo možné potvrdit" in stav and "Nemoc." in stav


def test_overeni_emailu(lab, settings):
    settings.BOOKING_VERIFY_EMAIL = True
    _, offers, slot, _, staff = lab
    Client().post("/objednavka/", jednotlivec(slot, [offers["wingate"]]))
    booking = BookingRequest.objects.get()
    assert booking.status == "overeni"
    assert booking.number not in staff.get("/objednavky/").content.decode()   # zatím ne v „Nové“
    odkaz = re.search(r"https?://[^\s]+/objednavka/potvrdit/[^\s]+/", mail.outbox[-1].body).group(0)
    Client().get(odkaz.split("testserver")[1])
    booking.refresh_from_db()
    assert booking.status == "nova"


def test_omezeni_poctu_objednavek_z_jedne_adresy(lab):
    _, offers, _, team_slot, _ = lab
    team_slot.capacity = 20
    team_slot.save()
    klient = Client()
    for i in range(5):
        assert klient.post("/objednavka/", jednotlivec(
            team_slot, [offers["wingate"]], prijmeni=f"Nováková{i}")).status_code == 200
    assert klient.post("/objednavka/", jednotlivec(team_slot, [offers["wingate"]])).status_code == 429


def test_chyby_formulare_a_ochrana(lab):
    _, offers, slot, _, _ = lab
    chyba = Client().post("/objednavka/", jednotlivec(slot, [], email="spatny"))
    text = chyba.content.decode()
    assert chyba.status_code == 400 and "platný e-mail" in text and "aspoň jeden test" in text
    assert 'value="spatny"' in text                                        # vyplněné zůstane
    robot = Client().post("/objednavka/", jednotlivec(slot, [offers["wingate"]], web="spam"))
    assert robot.status_code == 200 and not BookingRequest.objects.exists()


def test_vyzkumnik_objednavky_nevidi(lab):
    org, *_ = lab
    c = Client()
    c.force_login(User.objects.create(username="v", organization=org, role=Role.RESEARCHER))
    assert c.get("/objednavky/").status_code == 403
    assert "Objednávky" not in c.get("/").content.decode()


def test_bez_klice_se_formular_nenabizi(lab, settings):
    settings.IDENTITY_ENCRYPTION_KEY = ""
    assert Client().get("/objednavka/").status_code == 503


def test_sprava_nabidky_a_hromadne_vypsani_terminu(lab):
    org, _, _, _, staff = lab
    staff.post("/objednavky/nabidka/nova/", {
        "kind": "balicek", "name": "Komplexní diagnostika", "description": "vše", "price": 3500,
        "duration_min": 120, "protocols": [Protocol.objects.get(code="cmj").pk], "order": 1,
        "is_active": "on"})
    assert Offer.objects.get(name="Komplexní diagnostika").price == 3500

    pondeli = timezone.localdate() + timedelta(days=(7 - timezone.localdate().weekday()))
    staff.post("/objednavky/terminy/", {
        "date_from": pondeli.isoformat(), "date_to": (pondeli + timedelta(days=6)).isoformat(),
        "weekdays": ["0", "2"], "time_from": "08:00", "time_to": "10:00", "step_min": 60,
        "duration_min": 60, "capacity": 1, "location": "Lab 2"})
    nove = Slot.objects.filter(location="Lab 2")
    assert nove.count() == 6                                   # po + st × 8, 9, 10 h
    assert {timezone.localtime(s.start).weekday() for s in nove} == {0, 2}
    assert "Lab 2" in staff.get("/objednavky/terminy/").content.decode()

    # termín s objednávkou se nesmaže, jen se přestane nabízet
    slot = nove.first()
    booking = BookingRequest.objects.create(organization=org, slot=slot)
    p = Participant(request=booking)
    p.set_data("A", "B", date(2000, 1, 1))
    p.save()
    staff.post("/objednavky/terminy/", {"akce": "smazat", "slot": slot.pk})
    slot.refresh_from_db()
    assert not slot.is_active
