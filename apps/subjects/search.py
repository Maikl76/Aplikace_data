"""
Hledání sportovce podle kódu nebo jména.

Jména jsou šifrovaná, takže je databáze neumí prohledat. Pro laboratoř
se stovkami sportovců stačí jména dešifrovat v paměti a porovnat – je to
otázka milisekund. Jména vidí jen role, které na ně mají nárok; ostatní
hledají jen podle kódu.
"""

import unicodedata

from django.conf import settings
from django.db.models import Count, F, Max

from .models import Subject


def plain(text: str) -> str:
    """Text bez diakritiky malými písmeny – „Nováková“ → „novakova“ (pro hledání)."""
    text = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn").lower()


_plain = plain


def _visible_identities(subjects, user):
    """Identity sportovců, jejichž jména smí uživatel vidět (prázdné bez klíče)."""
    from .models import SubjectIdentity

    if not settings.IDENTITY_ENCRYPTION_KEY:
        return SubjectIdentity.objects.none()
    from .access import subject_ids_for

    qs = SubjectIdentity.objects.filter(subject__in=subjects)
    if not user.sees_identity and not user.is_superuser:
        allowed = subject_ids_for(user)
        if not allowed:
            return SubjectIdentity.objects.none()
        qs = qs.filter(subject_id__in=allowed)
    return qs


def names_for(subjects, user) -> dict[int, str]:
    """
    Jména sportovců, která smí uživatel vidět: {pk: „Jméno Příjmení“}.
    Laboratoř všechna, sportovec svoje a dětí, trenér sdílených, výzkumník žádné.
    """
    names = {}
    for identity in _visible_identities(subjects, user):
        try:
            names[identity.subject_id] = identity.full_name
        except Exception:  # jiný klíč, poškozený záznam – radši kód než pád
            continue
    return names


def name_parts_for(subjects, user) -> dict[int, tuple[str, str]]:
    """{pk: (jméno, příjmení)} – pro hledání a řazení podle příjmení; stejná práva jako names_for."""
    parts = {}
    for identity in _visible_identities(subjects, user):
        try:
            parts[identity.subject_id] = (identity.first_name, identity.last_name)
        except Exception:  # jiný klíč, poškozený záznam – radši kód než pád
            continue
    return parts


def annotate(subjects, user, *, limit: int | None = None, recent: bool = False) -> list:
    """
    Doplní ke sportovcům jméno k zobrazení, počet měření a poslední datum.
    ``subjects`` je queryset (ještě neoříznutý), ``recent`` řadí od
    naposledy měřených.
    """
    # Identita kvůli věku z přesného data narození – jedním dotazem, ne po řádcích.
    qs = subjects.select_related("identity").annotate(
        pocet_mereni=Count("sessions", distinct=True), posledni_mereni=Max("sessions__date"))
    if recent:
        qs = qs.order_by(F("posledni_mereni").desc(nulls_last=True), "code")
    rows = list(qs[:limit] if limit else qs)
    names = names_for(rows, user)
    for s in rows:
        s.jmeno = names.get(s.pk, "")
        s.zobrazeni = s.jmeno or s.code
    return rows


def search(user, query: str, *, limit: int | None = 8, base=None) -> list:
    """Sportovci, jejichž kód nebo jméno obsahuje dotaz (bez ohledu na diakritiku)."""
    qs = (base if base is not None else Subject.objects.for_user(user)).select_related("sport")
    query = (query or "").strip()
    if not query:
        return annotate(qs.filter(is_active=True), user, limit=limit, recent=True)

    needle = _plain(query)
    by_code = set(qs.filter(code__icontains=query).values_list("pk", flat=True))
    by_name = {pk for pk, name in names_for(qs, user).items() if needle in _plain(name)}
    found = qs.filter(pk__in=by_code | by_name).order_by("code")
    return annotate(found, user, limit=limit)


def label(items, user, subject=lambda item: item.subject) -> list:
    """
    Doplní k záznamům (testovací den, zpráva…) jméno sportovce k zobrazení:
    ``item.jmeno`` je jméno, nebo kód, pokud jméno uživatel nevidí.
    """
    items = list(items)
    names = names_for([subject(i) for i in items], user)
    for item in items:
        s = subject(item)
        item.jmeno = names.get(s.pk) or s.code
    return items
