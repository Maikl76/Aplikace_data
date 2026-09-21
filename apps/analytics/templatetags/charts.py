"""Předání figury do šablony jako JSON."""

import json

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def figure_json(value) -> str:
    """
    Figura jako JSON pro plotly.js.

    Používá se uvnitř <script type="application/json">, kde HTML entity
    neplatí – uzavírací značku proto escapujeme ručně, ať obsah nemůže
    skript předčasně ukončit.
    """
    payload = json.dumps(value, ensure_ascii=False, default=str)
    return mark_safe(payload.replace("<", "\\u003c").replace(">", "\\u003e"))
