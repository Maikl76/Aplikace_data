"""
Registr adaptérů na formáty přístrojů.

Každý přístroj exportuje jinak (ForceDecks, Cosmed, Biodex, HUMAC...).
Adaptér je malá třída, která z jednoho formátu udělá kanonické hodnoty.
Přidat podporu nového přístroje = přidat sem jeden soubor.
"""

from .base import BaseAdapter, ParsedRow, registry  # noqa: F401

# Až budou adaptéry hotové, naimportují se tady, aby se zaregistrovaly:
# from . import forcedecks, biodex, cosmed, generic_excel  # noqa: F401
