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
# Do administrace Djanga smí jen správce: administrace neumí rozsah dat po
# sportech, laborant s omezeným rozsahem by v ní viděl celé pracoviště.
STAFF_ROLES = {Role.ADMIN}
# Role zakládané jako účet kolegy. Sportovec vzniká z pozvánky na své kartě.
COLLEAGUE_ROLES = (Role.ADMIN, Role.LAB, Role.METHODOLOGIST, Role.RESEARCHER, Role.COACH)


def sync_groups(user) -> None:
    """Po změně role srovná skupiny: jen ta podle role, žádná jiná z řízených."""
    wanted = ROLE_GROUPS.get(user.role)
    managed = Group.objects.filter(name__in=ROLE_GROUPS.values())
    user.groups.remove(*managed.exclude(name=wanted))
    if wanted:
        group = Group.objects.filter(name=wanted).first()
        if group:
            user.groups.add(group)
