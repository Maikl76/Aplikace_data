"""
Hlídání rolí v samotné aplikaci.

Administrace Djanga si oprávnění hlídá sama; obrazovky aplikace dřív
rozhodovaly jen o tom, kdo vidí jména. Role Trenér a Sportovec mají mít
vlastní omezený pohled (jen můj tým, jen moje výsledky), který ještě není
– takový účet by viděl všechny sportovce pracoviště. Dokud pohled není,
aplikace mu přihlášení odmítne. Výzkumník má „jen čtení“: každý pokus
něco uložit se odmítne tady, na jednom místě, ne v každém pohledu zvlášť.
"""

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
    Role.ATHLETE: ("/muj/", "/ucet/", "/d/", "/objednavka/", "/o-aplikaci/", "/zdravi/"),
    Role.COACH: ("/trener/", "/muj/ucet/", "/ucet/", "/objednavka/", "/o-aplikaci/", "/zdravi/"),
}

NOT_READY_MESSAGE = ("Tento typ účtu zatím není v provozu. Přihlaste se účtem laboranta, "
                     "nebo požádejte správce.")


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
        return self.get_response(request)
