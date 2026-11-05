"""
Role a skupiny oprávnění na jednom místě.

Role je jedno pole u účtu; skupina Djanga podle ní dává oprávnění
v administraci. Administrace i stránka Kolegové srovnávají skupiny
stejně – odtud.
"""

from django.contrib.auth.models import Group

from .models import Role

ROLE_GROUPS = {
    Role.ADMIN: "Správce",
    Role.LAB: "Diagnostik",
    Role.RESEARCHER: "Výzkumník",
}
# Role, které dostanou i přístup do administrace („Stav týmu“) – pro pokročilé.
STAFF_ROLES = {Role.ADMIN, Role.LAB}
# Role zakládané jako účet kolegy. Sportovec vzniká z pozvánky na své kartě.
COLLEAGUE_ROLES = (Role.ADMIN, Role.LAB, Role.RESEARCHER, Role.COACH)


def sync_groups(user) -> None:
    """Po změně role srovná skupiny: jen ta podle role, žádná jiná z řízených."""
    wanted = ROLE_GROUPS.get(user.role)
    managed = Group.objects.filter(name__in=ROLE_GROUPS.values())
    user.groups.remove(*managed.exclude(name=wanted))
    if wanted:
        group = Group.objects.filter(name=wanted).first()
        if group:
            user.groups.add(group)
