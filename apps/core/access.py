"""
Přístup účtů laboratoře: kdo na co vidí a co smí.

Jediné místo, kde se rozhoduje. Role (správce, laborant, metodik,
výzkumník) je šablona výchozích hodnot; správce položky upraví u účtu
v Kolegové → Přístup. Dvě nezávislé věci:

* rozsah dat – sporty (všechny, nebo vybrané; volitelně jen týmy),
  jména sportovců, genetika, externí vyšetření, objednávky;
* oprávnění – měření, sportovci, koncepty zpráv, vydávání zpráv,
  nastavení sportů, nastavení testů (po metodikách = rodinách testů),
  exporty, úpravy knihovny článků.

Správce má vždy vše. Portálové role (sportovec, trenér) sem nepatří –
jejich rozsah určuje účet a sdílení (apps.subjects.access). Dotazy
filtruje OrgScopedQuerySet.for_user přes scope_queryset, celé sekce
hlídá middleware, klíčové akce pohledy přes can() nebo require().
"""

from dataclasses import dataclass
from functools import wraps

from django.db.models import Q
from django.shortcuts import render

from .models import Access, Role

PORTAL_ROLES = (Role.ATHLETE, Role.COACH)
LAB_ROLES = (Role.ADMIN, Role.LAB, Role.METHODOLOGIST, Role.RESEARCHER)
# role zakládané jako účet kolegy s vlastním přístupem (správce má vše)
SCOPED_ROLES = (Role.LAB, Role.METHODOLOGIST, Role.RESEARCHER)

# skupiny položek pro editor: (nadpis, [(klíč, popisek, vysvětlení)])
GROUPS = [
    ("Na co vidí", [
        ("names", "Jména sportovců",
         "Jinak jen kódy. Jména jsou šifrovaná a bez tohoto oprávnění se nedešifrují."),
        ("genetics", "Genetika",
         "Genové karty, vzorky, genotypy a genetické zprávy sportovců v rozsahu."),
        ("exams", "Externí vyšetření",
         "Lékařská vyšetření a omezení zátěže na kartě sportovce."),
        ("bookings", "Objednávky",
         "Žádosti klientů o testování včetně kontaktů a zdravotních údajů."),
    ]),
    ("Co smí", [
        ("measure", "Zadávat a importovat měření",
         "Testovací dny, hodnoty, režim u přístroje, import exportů z přístroje."),
        ("subjects_edit", "Sportovci",
         "Zakládat a upravovat sportovce, souhlasy, pozvánky do portálu, sdílení, plán a cíle."),
        ("reports_draft", "Koncepty zpráv",
         "Vytvářet a upravovat koncepty, posuzovat plnění doporučení."),
        ("reports_release", "Vydávat a předávat zprávy",
         "Vydání, upozornění, předání lékaři, nová verze. Vydává správce nebo metodik sportu."),
    ]),
    ("Nastavení", [
        ("settings_sports", "Sporty a baterie, normy, pravidla, dotazníky, interní reference",
         "Pro sporty v rozsahu účtu."),
        ("settings_tests", "Testy, ukazatele, MDC, popisy, přístroje",
         "Pro metodiky měření (rodiny testů) v rozsahu účtu."),
        ("exports", "Exporty dat", "CSV týmového přehledu, výzkumný export."),
        ("articles", "Úpravy knihovny článků", "Zařazovat a upravovat články; číst může každý."),
    ]),
]
FLAGS = tuple(key for _, items in GROUPS for key, _, _ in items)
LABELS = {key: label for _, items in GROUPS for key, label, _ in items}
SHORT = {"names": "jména", "genetics": "genetika", "exams": "vyšetření", "bookings": "objednávky",
         "measure": "měření", "subjects_edit": "sportovci", "reports_draft": "koncepty",
         "reports_release": "vydávání zpráv", "settings_sports": "nastavení sportů",
         "settings_tests": "nastavení testů", "exports": "exporty", "articles": "články"}

# Výchozí šablony podle role. Laborant měří a tvoří koncepty, nevydává;
# metodik vydává pro své sporty a nastavuje, ale bez jmen; výzkumník jen čte.
PRESETS = {
    Role.ADMIN: dict.fromkeys(FLAGS, True),
    Role.LAB: {"names": True, "genetics": False, "exams": True, "bookings": True,
               "measure": True, "subjects_edit": True, "reports_draft": True,
               "reports_release": False, "settings_sports": False, "settings_tests": False,
               "exports": False, "articles": False},
    Role.METHODOLOGIST: {"names": False, "genetics": False, "exams": False, "bookings": False,
                         "measure": False, "subjects_edit": False, "reports_draft": True,
                         "reports_release": True, "settings_sports": True, "settings_tests": True,
                         "exports": True, "articles": True},
    Role.RESEARCHER: dict.fromkeys(FLAGS, False),
}

REASONS = {
    "manage": "Tohle nastavuje správce.",
    "names": "Jména sportovců vidí jen účet s tímto oprávněním.",
    "genetics": "Genetiku vidí jen účet s přístupem ke genetice.",
    "exams": "Externí vyšetření vidí a zapisuje jen účet s tímto oprávněním.",
    "bookings": "Objednávky vyřizuje jen účet s tímto oprávněním.",
    "measure": "Zadávat a importovat měření smí jen účet s oprávněním k měření.",
    "subjects_edit": "Údaje sportovců upravuje jen účet s tímto oprávněním.",
    "reports_draft": "Koncepty zpráv tvoří jen účet s tímto oprávněním.",
    "reports_release": "Zprávy vydává správce nebo metodik sportu.",
    "settings_sports": "Sporty, baterie, normy, pravidla a dotazníky nastavuje správce nebo "
                       "metodik sportu.",
    "settings_tests": "Testy, ukazatele, MDC a přístroje nastavuje správce nebo metodik měření.",
    "exports": "Exporty dat smí jen účet s tímto oprávněním.",
    "articles": "Knihovnu článků upravuje správce nebo metodik.",
}
HINT = " Přístup nastavuje správce v Kolegové → Přístup."


def reason(key: str) -> str:
    return REASONS.get(key, "Na tohle účet nemá oprávnění.") + HINT


def preset(role: str) -> dict:
    return dict(PRESETS.get(role, PRESETS[Role.RESEARCHER]))


def manage(user) -> bool:
    """Správa pracoviště: kolegové a přístupy, pracoviště, provoz, klíče a model."""
    return bool(user is not None and getattr(user, "is_authenticated", False)
                and (user.is_superuser or getattr(user, "role", "") == Role.ADMIN))


def is_lab(user) -> bool:
    return bool(user is not None and getattr(user, "is_authenticated", False)
                and (user.is_superuser or getattr(user, "role", "") in LAB_ROLES))


def profile(user):
    """Záznam přístupu účtu (vznikne ze šablony role, když chybí); None mimo laboratoř."""
    if not is_lab(user) or getattr(user, "role", "") in PORTAL_ROLES:
        return None
    cached = getattr(user, "_access_profile", None)
    if cached is None:
        cached, _ = Access.objects.get_or_create(user=user, defaults=preset(user.role))
        user._access_profile = cached
    return cached


def forget(user) -> None:
    """Po změně přístupu zahodit, co si účet pamatuje (v testech a editoru)."""
    for name in ("_access_profile", "_access_scope"):
        if hasattr(user, name):
            delattr(user, name)


def can(user, key: str) -> bool:
    """Smí účet danou věc? Správce vše, portálové role nic z laboratoře."""
    if key == "manage":
        return manage(user)
    if not is_lab(user):
        return False
    if user.is_superuser or user.role == Role.ADMIN:
        return True
    access = profile(user)
    return bool(access is not None and getattr(access, key, False))


def flags(user) -> dict:
    """Všechny položky najednou – pro menu a šablony."""
    out = {key: can(user, key) for key in FLAGS}
    out["manage"] = manage(user)
    out["restricted"] = scope(user) is not None
    return out


def initial_for(user) -> Access:
    """
    Přístup nového účtu kolegy: šablona podle role a – mimo správce – zatím
    žádný sport. Bez přidělených sportů kolega nevidí žádného sportovce;
    správce rozsah nastaví hned po založení účtu.
    """
    forget(user)
    access, _ = Access.objects.update_or_create(
        user=user, defaults={**preset(user.role), "all_sports": user.role == Role.ADMIN,
                             "configured": False})
    return access


def grant(user, **values) -> Access | None:
    """Nastaví položky přístupu účtu přímo (skripty, testy); vrací záznam."""
    access = profile(user)
    if access is None:
        return None
    for key, value in values.items():
        setattr(access, key, value)
    access.save()
    forget(user)
    return access


def apply_preset(access: Access, role: str) -> None:
    """Vrátí oprávnění na šablonu role; rozsah sportů a týmů nechá."""
    for key, value in preset(role).items():
        setattr(access, key, value)


# --- rozsah dat ---------------------------------------------------------------

@dataclass(frozen=True)
class Scope:
    sports: frozenset | None     # None = všechny sporty
    teams: frozenset             # prázdné = všechny týmy sportů


def scope(user) -> Scope | None:
    """Rozsah dat účtu; None = bez omezení (správce, nebo účet se všemi sporty)."""
    if not is_lab(user) or user.is_superuser or user.role == Role.ADMIN:
        return None
    if hasattr(user, "_access_scope"):
        return user._access_scope
    access = profile(user)
    result = None
    if access is not None:
        sports = None if access.all_sports else frozenset(
            access.sports.values_list("pk", flat=True))
        teams = frozenset(access.teams.values_list("pk", flat=True))
        if sports is not None or teams:
            result = Scope(sports, teams)
    user._access_scope = result
    return result


def families(user) -> set | None:
    """Metodiky měření (rodiny testů), které účet nastavuje; None = všechny."""
    if not is_lab(user) or user.is_superuser or user.role == Role.ADMIN:
        return None
    access = profile(user)
    if access is None or access.all_families:
        return None
    return set(access.families or [])


def family_allowed(user, family: str) -> bool:
    """Smí účet nastavovat test (ukazatel, profil) této rodiny testů?"""
    allowed = families(user)
    return allowed is None or family in allowed


def sport_allowed(user, sport_id) -> bool:
    """
    Smí účet nastavovat normu, pravidlo nebo baterii tohoto sportu? Záznam
    napříč sporty (bez sportu) jen účet bez omezení rozsahu.
    """
    sc = scope(user)
    if sc is None:
        return True
    if sport_id is None:
        return False
    return sc.sports is None or sport_id in sc.sports


def may_add_sport(user) -> bool:
    """Nový sport zakládá jen účet se všemi sporty – jinak by ho sám neviděl."""
    return can(user, "settings_sports") and scope(user) is None


def scope_text(user) -> str:
    """„Florbal, Hokej · jen Ženy A“ pro účet s omezeným rozsahem; jinak prázdné."""
    sc = scope(user)
    if sc is None:
        return ""
    from apps.subjects.models import Sport, Team

    parts = []
    if sc.sports is not None:
        names = list(Sport.objects.filter(pk__in=sc.sports).order_by("name")
                     .values_list("name", flat=True))
        parts.append(", ".join(names) if names else "žádný sport")
    else:
        parts.append("všechny sporty")
    if sc.teams:
        parts.append("jen " + ", ".join(Team.objects.filter(pk__in=sc.teams).order_by("name")
                                        .values_list("name", flat=True)))
    return " · ".join(parts)


class Responsibility:
    """Kdo (metodik) odpovídá za který sport a metodiku – pro stránky Sporty a Testy."""

    def __init__(self, organization):
        from .models import User

        self.by_sport: dict = {}
        self.all_sports: list[str] = []
        self.by_family: dict = {}
        self.all_families: list[str] = []
        users = (User.objects.filter(organization=organization, role=Role.METHODOLOGIST,
                                     is_active=True)
                 .select_related("access").prefetch_related("access__sports")
                 .order_by("last_name", "first_name", "username"))
        for user in users:
            access = getattr(user, "access", None)
            name = user.get_full_name() or user.get_username()
            if access is None or access.all_sports:
                self.all_sports.append(name)
            else:
                for sport in access.sports.all():
                    self.by_sport.setdefault(sport.pk, []).append(name)
            if access is None or access.all_families:
                self.all_families.append(name)
            else:
                for family in access.families or []:
                    self.by_family.setdefault(family, []).append(name)

    def for_sport(self, sport_id) -> list[str]:
        return self.all_sports + self.by_sport.get(sport_id, [])

    def for_family(self, family: str) -> list[str]:
        return self.all_families + self.by_family.get(family, [])


def scope_queryset(model, qs, user):
    """
    Omezí dotaz na rozsah účtu. Sportovec podle sportu a týmu, tabulky se
    sportovcem přes něj, sport a tým samy, tabulky se sportem podle sportu.
    Náhled importu nese jména ze souboru, proto účet s rozsahem vidí jen
    importy, které nahrál sám.
    """
    sc = scope(user)
    if sc is None:
        return qs
    name = model._meta.model_name
    fields = {f.name for f in model._meta.fields}

    def subject_q(prefix: str = "") -> Q:
        q = Q()
        if sc.sports is not None:
            q &= Q(**{f"{prefix}sport_id__in": sc.sports})
        if sc.teams:
            q &= Q(**{f"{prefix}team_id__in": sc.teams})
        return q

    if name == "subject":
        return qs.filter(subject_q())
    if "subject" in fields:
        return qs.filter(subject_q("subject__"))
    if name == "sport":
        return qs.filter(pk__in=sc.sports) if sc.sports is not None else qs
    if name == "team":
        q = Q(pk__in=sc.teams) if sc.teams else Q()
        if sc.sports is not None:
            q &= Q(sport_id__in=sc.sports)
        return qs.filter(q)
    if "sport" in fields:
        return qs.filter(sport_id__in=sc.sports) if sc.sports is not None else qs
    if name == "importbatch":
        return qs.filter(uploaded_by=user)
    return qs


def sees_subject(user, subject) -> bool:
    """Je sportovec v rozsahu účtu? (Portálové role řeší apps.subjects.access.)"""
    sc = scope(user)
    if sc is None:
        return True
    if sc.sports is not None and subject.sport_id not in sc.sports:
        return False
    return not sc.teams or subject.team_id in sc.teams


# --- popis pro stránky --------------------------------------------------------

def summary(user) -> str:
    """Jedna řádka do seznamu kolegů: rozsah, jména a hlavní oprávnění."""
    if manage(user):
        return "vše (správce)"
    access = profile(user)
    if access is None:
        return ""
    parts = []
    if access.all_sports:
        parts.append("všechny sporty")
    else:
        names = list(access.sports.values_list("name", flat=True))
        parts.append(", ".join(names) if names else "žádný sport")
    teams = list(access.teams.values_list("name", flat=True))
    if teams:
        parts.append("jen " + ", ".join(teams))
    parts.append("jména" if access.names else "bez jmen")
    rights = [SHORT[key] for key in FLAGS if key != "names" and getattr(access, key)]
    parts.append(", ".join(rights) if rights else "jen čtení")
    return " · ".join(parts)


def unconfigured(organization) -> list:
    """Aktivní účty kolegů, jejichž přístup správce ještě nepotvrdil."""
    from .models import User

    users = (User.objects.filter(organization=organization, is_active=True,
                                 role__in=SCOPED_ROLES, is_superuser=False)
             .select_related("access").order_by("last_name", "username"))
    return [u for u in users if not getattr(getattr(u, "access", None), "configured", False)]


def require(key: str):
    """Dekorátor pohledu: bez oprávnění stránka „odepřeno“ (403)."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not can(request.user, key):
                return render(request, "core/odepreno.html", {"duvod": reason(key)}, status=403)
            return view(request, *args, **kwargs)
        return wrapper
    return decorator
