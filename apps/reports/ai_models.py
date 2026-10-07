"""
Který jazykový model psát a jak dlouho na něj čekat.

Výchozí model a čekání se nastavují v aplikaci (AI zprávy → Modely).
Dokud tam nic není, platí LLM_MODEL a LLM_TIMEOUT z .env – instalace
bez úprav tedy funguje jako dřív.
"""

from django.conf import settings
from django.db import DatabaseError


def _rows():
    from .models import AiModel

    try:
        return list(AiModel.objects.all())
    except DatabaseError:  # tabulka ještě není (před migrací)
        return []


def default_model() -> str:
    for row in _rows():
        if row.is_default:
            return row.name
    return settings.LLM_MODEL


def timeout_for(name: str | None) -> int:
    name = name or default_model()
    for row in _rows():
        if row.name == name:
            return row.timeout
    return settings.LLM_TIMEOUT


def label_for(name: str) -> str:
    for row in _rows():
        if row.name == name and row.label:
            return row.label
    return name


def choices() -> list[tuple[str, str]]:
    """Modely k výběru u zprávy: výchozí první, pak ostatní nabízené."""
    default = default_model()
    out = [(default, label_for(default) + " (výchozí)")]
    for row in _rows():
        if row.is_active and row.name != default:
            out.append((row.name, row.display))
    return out


def is_offered(name: str) -> bool:
    return any(value == name for value, _ in choices())
