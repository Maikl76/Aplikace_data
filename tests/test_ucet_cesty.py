"""Druhá cesta k účtu: odkaz na uložený e‑mail a pozvánka po schválení objednávky."""

import re
from datetime import date

import pytest
from cryptography.fernet import Fernet
from django.core import mail
from django.core.cache import cache
from django.test import Client

from apps.core.models import Organization, Role, User
from apps.subjects import accounts, crypto
from apps.subjects.models import AccountInvitation, Subject, SubjectIdentity
from tests.test_objednavky import jednotlivec, lab  # noqa: F401  (objednávky)

HESLO = "dlouhe-heslo-sportovce-1"


@pytest.fixture
def trezor(db, settings):
    cache.clear()
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.EMAIL_HOST = "smtp.test"
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    User.objects.create(username="lab", organization=org, role=Role.LAB, email="lab@ftvs.cz")
    return org


def _identity(org, code, first, last, email, birth=None):
    subject = Subject.objects.create(organization=org, code=code)
    identity = SubjectIdentity(subject=subject)
    identity.set_names(first, last)
    identity.email_enc = crypto.encrypt(email)
    if birth:
        identity.set_birth_date(birth)
    identity.save()
    return subject


def _link(body, kind):
    return re.search(rf"https?://[^\s]+/ucet/{kind}/[^\s/]+/", body).group(0)


def test_email_posle_pozvanku_a_potom_odkaz_pro_prihlaseni(trezor):
    org = trezor
    subject = _identity(org, "FTVS-0001", "Jana", "Nováková", "Jana@Example.cz",
                        date(1998, 3, 12))
    client = Client()
    assert "Poslat odkaz" in client.get("/ucet/odkaz/").content.decode()
    response = client.post("/ucet/odkaz/", {"email": "jana@example.cz"})
    assert "Zkontrolujte e‑mail" in response.content.decode()
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["jana@example.cz"]
    invitation = AccountInvitation.objects.get(subject=subject)
    assert invitation.kind == AccountInvitation.Kind.ATHLETE
    link = _link(mail.outbox[0].body, "pozvanka")
    assert invitation.token in link

    # Účet z pozvánky; napodruhé už přijde odkaz pro přihlášení.
    path = link.split("//", 1)[1].split("/", 1)[1]
    client.post("/" + path, {"email": "jana@example.cz", "password1": HESLO, "password2": HESLO})
    client = Client()
    client.post("/ucet/odkaz/", {"email": "jana@example.cz"})
    assert len(mail.outbox) == 2 and "30 minut" in mail.outbox[1].body
    link = _link(mail.outbox[1].body, "odkaz")
    response = client.get("/" + link.split("//", 1)[1].split("/", 1)[1])
    assert response.status_code == 302 and response.url == "/muj/"
    assert client.get(f"/muj/{subject.pk}/").status_code == 200

    # Po změně hesla starý odkaz neplatí; zfalšovaný taky ne.
    user = User.objects.get(username="jana@example.cz")
    token = accounts.login_link_token(user)
    user.set_password("jine-dlouhe-heslo-123")
    user.save()
    assert Client().get(f"/ucet/odkaz/{token}/").status_code == 410
    assert Client().get("/ucet/odkaz/nesmysl/").status_code == 410


def test_nezletily_dostane_pozvanku_pro_zastupce(trezor):
    subject = _identity(trezor, "FTVS-0002", "Adam", "Malý", "rodic@example.cz",
                        date(2012, 6, 1))
    Client().post("/ucet/odkaz/", {"email": "rodic@example.cz"})
    invitation = AccountInvitation.objects.get(subject=subject)
    assert invitation.kind == AccountInvitation.Kind.GUARDIAN
    assert "zákonný zástupce – Adam Malý" in mail.outbox[0].body


def test_neznamy_email_a_ucet_laboratore_nic_nedostanou(trezor):
    client = Client()
    for email in ("nikdo@example.cz", "lab@ftvs.cz"):
        response = client.post("/ucet/odkaz/", {"email": email})
        assert "Zkontrolujte e‑mail" in response.content.decode()   # stejná odpověď
    assert mail.outbox == []


def test_omezeni_poctu_zadosti_z_jedne_adresy(trezor):
    client = Client()
    for _ in range(5):
        client.post("/ucet/odkaz/", {"email": "nikdo@example.cz"})
    response = client.post("/ucet/odkaz/", {"email": "nikdo@example.cz"}, follow=True)
    assert "Příliš mnoho pokusů" in response.content.decode()


def test_bez_postovniho_serveru_je_cesta_vypnuta(trezor, settings):
    settings.EMAIL_HOST = ""
    _identity(trezor, "FTVS-0001", "Jana", "Nováková", "jana@example.cz")
    client = Client()
    assert "není odesílání e‑mailů zapnuté" in client.get("/ucet/odkaz/").content.decode()
    client.post("/ucet/odkaz/", {"email": "jana@example.cz"})
    assert mail.outbox == [] and not AccountInvitation.objects.exists()


def test_schvaleni_objednavky_posle_pozvanku(lab):  # noqa: F811
    org, offers, slot, team_slot, staff = lab
    Client().post("/objednavka/", jednotlivec(slot, [offers["silova"]]))
    from apps.booking.models import BookingRequest

    booking = BookingRequest.objects.get()
    response = staff.post(f"/objednavky/{booking.pk}/vyridit/", {"akce": "schvalit"}, follow=True)
    assert "Pozvánky k účtu: 1" in response.content.decode()
    subject = Subject.objects.get()
    invitation = AccountInvitation.objects.get(subject=subject)
    assert invitation.kind == AccountInvitation.Kind.ATHLETE
    assert invitation.token in mail.outbox[-1].body and mail.outbox[-1].to == ["jana@example.cz"]
    assert "Jana Nováková" in mail.outbox[-1].body

    # Nezletilý: pozvánka pro zákonného zástupce.
    Client().post("/objednavka/", jednotlivec(team_slot, [offers["wingate"]], jmeno="Adam",
                                              prijmeni="Malý", narozeni="2012-06-01",
                                              email="rodic@example.cz", souhlas_zastupce="on"))
    booking = BookingRequest.objects.latest("pk")
    staff.post(f"/objednavky/{booking.pk}/vyridit/", {"akce": "schvalit"})
    invitation = AccountInvitation.objects.latest("pk")
    assert invitation.kind == AccountInvitation.Kind.GUARDIAN
    assert "zákonný zástupce – Adam Malý" in mail.outbox[-1].body
