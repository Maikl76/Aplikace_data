"""
Registr adaptérů na formáty přístrojů.

Každý přístroj exportuje jinak (ForceDecks, Cosmed, Biodex, HUMAC...).
Adaptér je malá třída, která z jednoho formátu udělá kanonické hodnoty.
Přidat podporu nového přístroje = přidat sem jeden soubor a naimportovat ho.
"""

from . import (
    legacy_excel,  # noqa: F401
    vald,  # noqa: F401  (import registruje adaptéry; pořadí = pořadí rozpoznávání)
)
from .base import BaseAdapter, ParsedRow, detect_adapter, get_adapter, register, registry

__all__ = ["BaseAdapter", "ParsedRow", "detect_adapter", "get_adapter", "register", "registry"]

# Připravené k doplnění: tanita, performlab (VO2max PDF), biodex, humac
