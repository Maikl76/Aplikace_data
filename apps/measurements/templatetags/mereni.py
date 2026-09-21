"""Filtry pro zobrazení kvalifikátorů tam, kde nejsou navázané na model."""

from django import template

from apps.measurements.models import Mode, Side

register = template.Library()


@register.filter
def strana(code: str) -> str:
    """"L" -> "levá". Staging drží holý kód, ne odkaz na model."""
    if not code:
        return "—"
    try:
        return Side(code).label.lower()
    except ValueError:
        return code


@register.filter
def rezim(code: str) -> str:
    """"con" -> "koncentricky"."""
    if not code:
        return "—"
    try:
        return Mode(code).label.lower()
    except ValueError:
        return code
