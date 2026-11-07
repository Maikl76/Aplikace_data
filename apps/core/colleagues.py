"""
Účty kolegů: správce založí účet s rolí a dostane jednorázový odkaz, kterým
si kolega nastaví heslo. E‑mail není potřeba – odkaz předá správce sám.
Odkaz nese kousek otisku hesla, takže po nastavení hesla přestane platit;
stejný odkaz slouží i jako „zapomenuté heslo“ bez poštovního serveru.
"""

import re
import unicodedata

from django.core import signing
from django.db import transaction

from . import access
from .models import Role, User
from .roles import COLLEAGUE_ROLES, STAFF_ROLES, sync_groups

LINK_SALT = "nastaveni-hesla"
LINK_DAYS = 7
LINK_MAX_AGE = LINK_DAYS * 24 * 60 * 60
USERNAME = re.compile(r"[a-z0-9][a-z0-9._@-]{2,149}")


class ColleagueError(Exception):
    """Srozumitelná chyba pro uživatele."""


def suggest_username(first_name: str, last_name: str) -> str:
    """jmeno.prijmeni bez diakritiky; při kolizi s číslem na konci."""
    raw = ".".join(part for part in (first_name, last_name) if part.strip())
    base = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode().lower()
    base = re.sub(r"[^a-z0-9.]+", "", base).strip(".") or "kolega"
    name, n = base, 2
    while User.objects.filter(username__iexact=name).exists():
        name, n = f"{base}{n}", n + 1
    return name


@transaction.atomic
def create_colleague(organization, *, role: str, first_name: str, last_name: str,
                     username: str = "", email: str = "") -> User:
    """Nový účet bez hesla; heslo si kolega nastaví z odkazu."""
    if role not in COLLEAGUE_ROLES:
        raise ColleagueError("Tahle role se jako účet kolegy nezakládá.")
    if organization is None:
        raise ColleagueError("Účet potřebuje pracoviště – nejdřív ho založte.")
    first_name, last_name = first_name.strip(), last_name.strip()
    if not first_name or not last_name:
        raise ColleagueError("Vyplňte jméno a příjmení.")
    username = username.strip().lower() or suggest_username(first_name, last_name)
    if not USERNAME.fullmatch(username):
        raise ColleagueError("Uživatelské jméno: malá písmena bez diakritiky, číslice, tečka, "
                             "pomlčka nebo podtržítko; aspoň 3 znaky.")
    if User.objects.filter(username__iexact=username).exists():
        raise ColleagueError(f"Uživatelské jméno „{username}“ už někdo má.")
    user = User(username=username, first_name=first_name[:150], last_name=last_name[:150],
                email=email.strip().lower()[:254], organization=organization, role=role,
                is_staff=role in STAFF_ROLES)
    user.set_unusable_password()
    user.save()
    sync_groups(user)
    if role != Role.COACH:
        access.initial_for(user)   # šablona podle role, zatím bez sportů – nastaví správce
    return user


def password_link_token(user) -> str:
    """Podepsaný odkaz; nastavení hesla ho zneplatní (nese kousek otisku hesla)."""
    return signing.dumps({"u": user.pk, "h": user.password[-12:]}, salt=LINK_SALT)


def user_from_password_link(token: str):
    """Účet, kterému odkaz patří; None po vypršení, po nastavení hesla nebo u vypnutého účtu."""
    try:
        data = signing.loads(token, salt=LINK_SALT, max_age=LINK_MAX_AGE)
    except signing.BadSignature:
        return None
    user = (User.objects.filter(pk=data.get("u"), is_active=True)
            .exclude(role=Role.ATHLETE).first())
    if user is None or user.password[-12:] != data.get("h"):
        return None
    return user


def set_password(user, password: str) -> None:
    user.set_password(password)
    user.save(update_fields=["password"])
