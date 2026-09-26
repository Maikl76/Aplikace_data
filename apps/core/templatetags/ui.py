"""
Drobnosti pro vzhled: ikony a iniciály.

Ikony jsou jednoduché čárové SVG přímo v kódu – žádná knihovna z internetu
(fakultní server nemusí mít přístup ven) a barvu přebírají z textu.
"""

import hashlib
import os
from functools import lru_cache

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

_PATHS = {
    "home": '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.8-3.6 3.4-5.5 6.5-5.5s5.7 1.9 6.5 5.5"/>'
             '<path d="M16 4.6a3.5 3.5 0 0 1 0 6.8"/><path d="M18 14.8c1.9.7 3.1 2.4 3.5 5.2"/>',
    "activity": '<path d="M3 12h4l3-7 4 14 3-7h4"/>',
    "file": '<path d="M14 3H6v18h12V7z"/><path d="M14 3v4h4"/><path d="M9 12h6M9 16h6"/>',
    "upload": '<path d="M12 16V4"/><path d="M7 9l5-5 5 5"/><path d="M4 16v4h16v-4"/>',
    "settings": '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/>'
                '<circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/>'
                '<circle cx="18" cy="18" r="2"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4'
           'M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    "logout": '<path d="M15 4h4v16h-4"/><path d="M10 8l-4 4 4 4"/><path d="M6 12h10"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "arrow-up": '<path d="M12 19V5M6 11l6-6 6 6"/>',
    "arrow-down": '<path d="M12 5v14M6 13l6 6 6-6"/>',
    "minus": '<path d="M5 12h14"/>',
    "alert": '<path d="M12 3l10 18H2z"/><path d="M12 10v4M12 17.5v.5"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "chevron-right": '<path d="M9 5l7 7-7 7"/>',
}


@register.simple_tag
def icon(name: str, css: str = "") -> str:
    paths = _PATHS.get(name, "")
    return mark_safe(
        f'<svg class="{css}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true">{paths}</svg>'
    )


@register.filter
def initials(name: str) -> str:
    """„Petr Novák“ → „PN“, „FTVS-0012“ → „12“."""
    parts = [p for p in str(name or "").replace("-", " ").split() if p]
    if not parts:
        return "?"
    if parts[0].upper() == "FTVS" and len(parts) > 1:
        return parts[-1].lstrip("0")[-2:] or "0"
    return "".join(p[0] for p in parts[:2]).upper()


@register.simple_tag(takes_context=True)
def nav_link(context, url_name: str, label: str, icon_name: str, prefix: str = ""):
    """Položka menu; aktivní podle začátku cesty."""
    from django.urls import reverse

    request = context.get("request")
    url = reverse(url_name) if not url_name.startswith("/") else url_name
    path = request.path if request else ""
    active = path == url if url == "/" else path.startswith(prefix or url)
    return format_html('<a href="{}" class="nav-link{}">{}<span>{}</span></a>',
                       url, " active" if active else "", mark_safe(icon(icon_name)), label)


@register.simple_tag
def static_v(path: str) -> str:
    """
    Adresa statického souboru s otiskem obsahu (?v=…).

    Prohlížeč si styly a skripty pamatuje. Po aktualizaci aplikace by pak
    ukazoval novou stránku se starými styly – rozsypaný vzhled. Otisk se
    změní s obsahem souboru, takže prohlížeč pozná, že má stáhnout nový.
    """
    from django.contrib.staticfiles import finders
    from django.templatetags.static import static

    url = static(path)
    if "?" in url or len(url.rsplit("/", 1)[-1].split(".")) > 2:
        return url  # už má otisk v názvu (produkční manifest)
    found = finders.find(path)
    if not found:
        return url
    return f"{url}?v={_digest(found, os.path.getmtime(found))}"


@lru_cache(maxsize=64)
def _digest(file_path: str, mtime: float) -> str:
    """Otisk obsahu; počítá se znovu jen po změně souboru (mtime je v klíči)."""
    with open(file_path, "rb") as fh:
        return hashlib.md5(fh.read(), usedforsecurity=False).hexdigest()[:10]
