"""
Hlídání rolí v samotné aplikaci.

Administrace Djanga si oprávnění hlídá sama; obrazovky aplikace dřív
rozhodovaly jen o tom, kdo vidí jména. Role Trenér a Sportovec mají mít
vlastní omezený pohled (jen můj tým, jen moje výsledky), který ještě není
– takový účet by viděl všechny sportovce pracoviště. Dokud pohled není,
aplikace mu přihlášení odmítne. Výzkumník má „jen čtení“: každý pokus
něco uložit se odmítne tady, na jednom místě, ne v každém pohledu zvlášť.
"""

import re

from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect, render

from .models import Role

NOT_READY = ()          # role, jejichž pohled ještě není hotový (dnes žádná)
READ_ONLY = (Role.RESEARCHER,)
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
# Odhlášení musí jít vždy; administrace si oprávnění hlídá sama.
WRITE_ALLOWED_PREFIXES = ("/ucet/", "/admin/")
# Portálové role se pohybují jen ve svém portálu; obrazovky laboratoře
# jsou pro ně neviditelné (jinak by scoping ukázal celé pracoviště).
PORTAL_HOME = {Role.ATHLETE: "portal_home", Role.COACH: "coach_home"}
PORTAL_PREFIXES = {
    Role.ATHLETE: ("/muj/", "/ucet/", "/d/", "/objednavka/", "/o-aplikaci/", "/zdravi/",
                   "/pripominky/nova/"),
    Role.COACH: ("/trener/", "/muj/ucet/", "/ucet/", "/objednavka/", "/o-aplikaci/", "/zdravi/",
                 "/pripominky/nova/"),
}

NOT_READY_MESSAGE = ("Tento typ účtu zatím není v provozu. Přihlaste se účtem laboranta, "
                     "nebo požádejte správce.")

# Celé sekce a zapisující akce podle přístupu účtu (apps.core.access): vzor
# adresy, metody (None = všechny, WRITE = jen zapisující) a klíč oprávnění.
# První shoda rozhoduje; správce projde vždy.
WRITE = ("POST", "PUT", "PATCH", "DELETE")
SECTION_RULES = [
    # genové karty (znalostní báze) vidí každý v laboratoři; data sportovců jen s genetikou
    (r"^/genetika/sportovec/", None, "genetics"),
    (r"^/objednavky/", None, "bookings"),
    (r"^/import/", None, "measure"),
    (r"^/kolegove/", None, "manage"),
    (r"^/nastaveni/pracoviste/", None, "manage"),
    (r"^/zpravy/ai/", None, "manage"),
    # nastavení testování: číst může každý v laboratoři, měnit jen s oprávněním
    (r"^/nastaveni/(mdc|import|popisy)/", WRITE, "settings_tests"),
    (r"^/nastaveni/(normy|pravidla|dotazniky|reference)/", WRITE, "settings_sports"),
    (r"^/sporty/testy/", WRITE, "settings_tests"),
    (r"^/sporty/", WRITE, "settings_sports"),
    (r"^/sportovci/\d+/vysetreni/", None, "exams"),
    (r"^/sportovci/\d+/dnes/", WRITE, "measure"),
    (r"^/sportovci/", WRITE, "subjects_edit"),
    (r"^/mereni/\d+/doporuceni-minule/", WRITE, "reports_draft"),
    (r"^/mereni/", WRITE, "measure"),
    (r"^/testovani/", WRITE, "measure"),
    (r"^/zpravy/\d+/(vydat|predat|upozornit|nova-verze)/", WRITE, "reports_release"),
    (r"^/zpravy/", WRITE, "reports_draft"),
    (r"^/clanky/", WRITE, "articles"),
]
_COMPILED = [(re.compile(pattern), methods, key) for pattern, methods, key in SECTION_RULES]


def section_rule(path: str, method: str) -> str | None:
    """Klíč oprávnění, které adresa vyžaduje; None = nic zvláštního."""
    for pattern, methods, key in _COMPILED:
        if pattern.match(path) and (methods is None or method in methods):
            return key
    return None


class RoleAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not user.is_superuser:
            if user.role in NOT_READY:
                logout(request)
                messages.warning(request, NOT_READY_MESSAGE)
                return redirect("login")
            if (user.role in READ_ONLY and request.method not in SAFE_METHODS
                    and not request.path.startswith(WRITE_ALLOWED_PREFIXES)):
                return render(request, "core/jen_cteni.html", status=403)
            if (user.role in PORTAL_HOME and not request.path.startswith("/static/")
                    and not request.path.startswith(PORTAL_PREFIXES[user.role])):
                return redirect(PORTAL_HOME[user.role])
            if user.role != Role.ADMIN and user.role not in PORTAL_HOME:
                from . import access

                key = section_rule(request.path, request.method)
                if key is not None and not access.can(user, key):
                    return render(request, "core/odepreno.html", {"duvod": access.reason(key)},
                                  status=403)
        return self.get_response(request)
