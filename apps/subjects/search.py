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


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn").lower()


def names_for(subjects, user) -> dict[int, str]:
    """Jména sportovců, která smí uživatel vidět: {pk: „Jméno Příjmení“}."""
    if not user.sees_identity or not settings.IDENTITY_ENCRYPTION_KEY:
        return {}
    from .models import SubjectIdentity

    names = {}
    for identity in SubjectIdentity.objects.filter(subject__in=subjects):
        try:
            names[identity.subject_id] = identity.full_name
        except Exception:  # jiný klíč, poškozený záznam – radši kód než pád
            continue
    return names


def annotate(subjects, user, *, limit: int | None = None, recent: bool = False) -> list:
    """
    Doplní ke sportovcům jméno k zobrazení, počet měření a poslední datum.
    ``subjects`` je queryset (ještě neoříznutý), ``recent`` řadí od
    naposledy měřených.
    """
    qs = subjects.annotate(pocet_mereni=Count("sessions", distinct=True),
                           posledni_mereni=Max("sessions__date"))
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
