"""
Na které sportovce má účet nárok.

Laboratoř (správce, laborant) a výzkumník vidí celé pracoviště, výzkumník
jen pod kódy. Sportovec vidí sebe a děti, které zastupuje; trenér jen
sportovce s aktivním sdílením. Všechno ostatní je pro ně neviditelné –
ne „jen pod kódem“, ale vůbec. Tahle pravidla jsou na jednom místě
a používá je scoping dotazů, dešifrování jmen i portál.
"""

from apps.core.models import Role

PORTAL_ROLES = (Role.ATHLETE, Role.COACH)


def subject_ids_for(user) -> set[int] | None:
    """Kódy sportovců, které účet smí vidět; None = bez omezení (laboratoř)."""
    role = getattr(user, "role", "")
    if getattr(user, "is_superuser", False) or role not in PORTAL_ROLES:
        return None
    from .models import Guardian, Sharing, SubjectIdentity

    if role == Role.ATHLETE:
        own = SubjectIdentity.objects.filter(user=user).values_list("subject_id", flat=True)
        kids = Guardian.objects.filter(user=user).values_list("identity__subject_id", flat=True)
        return set(own) | set(kids)
    return set(Sharing.objects.filter(coach=user, status=Sharing.Status.ACTIVE,
                                      subject__is_active=True)
               .values_list("subject_id", flat=True))


def subjects_for(user):
    """Queryset sportovců pro portál sportovce a trenéra."""
    from .models import Subject

    ids = subject_ids_for(user)
    qs = Subject.objects.select_related("sport", "team")
    return qs if ids is None else qs.filter(pk__in=ids)


def may_see_name(user, subject) -> bool:
    """Jméno vidí laboratoř, sportovec u sebe a dětí, trenér u sdílených."""
    if getattr(user, "sees_identity", False) or getattr(user, "is_superuser", False):
        return True
    ids = subject_ids_for(user)
    return bool(ids) and subject.pk in ids
