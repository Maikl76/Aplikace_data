"""Startovní oblasti genetiky – zakládá je seed_catalog, dál se spravují v administraci."""

from .models import Domain

DOMAINS = [
    ("vykon", "Výkon a trénink",
     "Silově-rychlostní a vytrvalostní předpoklady, trénovatelnost."),
    ("pohybovy_aparat", "Pohybový aparát", "Pojivové tkáně, zatížení, prevence přetížení."),
    ("regenerace", "Regenerace", "Zánětlivá odpověď na zátěž a zotavení."),
    ("kofein", "Kofein", "Metabolismus kofeinu a individuální odezva."),
    ("laktoza", "Laktóza", "Laktázová persistence a sportovní výživa."),
    ("hmotnost", "Hmotnost a metabolický kontext",
     "Vývoj hmotnosti, stravovací návyky; bez zdravotních závěrů."),
]


def seed_domains() -> int:
    """Doplní chybějící sdílené oblasti; existující nemění. Vrací počet nových."""
    created = 0
    for order, (code, name, description) in enumerate(DOMAINS, start=1):
        _, is_new = Domain.objects.get_or_create(
            organization=None, code=code,
            defaults={"name": name, "description": description, "order": order})
        created += is_new
    return created


def domain_for(name: str):
    """Oblast podle názvu z podkladů („Výkon a trénink“); neznámou založí."""
    wanted = (name or "").strip().lower()
    for code, label, _ in DOMAINS:
        if label.lower() == wanted:
            return Domain.objects.get_or_create(
                organization=None, code=code,
                defaults={"name": label, "order": [c for c, _, _ in DOMAINS].index(code) + 1})[0]
    found = Domain.objects.filter(name__iexact=wanted).first()
    if found:
        return found
    from django.utils.text import slugify

    return Domain.objects.create(organization=None, code=slugify(wanted)[:64] or "ostatni",
                                 name=name.strip() or "Ostatní", order=99)
