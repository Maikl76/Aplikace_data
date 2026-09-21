"""Základ pro adaptéry na formáty přístrojů."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import IO


@dataclass
class ParsedRow:
    """
    Jedna hodnota vytažená ze souboru, ještě nesvázaná s databází.

    ``subject_key`` je hash identifikačních údajů ze zdroje – díky němu
    se opakovaný import téže osoby spáruje, aniž by se kamkoli ukládalo
    jméno. ``subject_hint`` je jen popisek pro náhled před uložením
    a po uložení se maže.
    """

    subject_key: str
    metric_code: str
    value: float
    subject_hint: str = ""
    subject_attrs: dict = field(default_factory=dict)
    protocol_code: str = ""
    session_date: date | None = None
    trial_number: int = 1
    side: str = ""
    mode: str = ""
    speed: float | None = None
    segment: str = ""
    row_number: int = 0
    extra: dict = field(default_factory=dict)


class BaseAdapter:
    """
    Potomek implementuje ``parse``. Adaptér NIKDY nezapisuje do databáze –
    jen vrací řádky, které se uloží do stagingu a projdou kontrolou.
    """

    code: str = ""
    label: str = ""
    device: str = ""
    file_extensions: tuple[str, ...] = ()

    def __init__(self):
        # Sloupce, které adaptér ve zdroji našel, ale neumí je zařadit.
        # Tiše zahozený sloupec je při migraci dat to nejhorší, co se
        # může stát – nikdo si toho nevšimne.
        self.unmapped_columns: list[str] = []

    def parse(self, fileobj: IO[bytes]) -> Iterator[ParsedRow]:
        raise NotImplementedError

    def sniff(self, fileobj: IO[bytes]) -> bool:
        """Vypadá soubor jako formát tohoto adaptéru?"""
        return False


registry: dict[str, type[BaseAdapter]] = {}


def register(adapter_cls: type[BaseAdapter]) -> type[BaseAdapter]:
    registry[adapter_cls.code] = adapter_cls
    return adapter_cls


def get_adapter(code: str) -> BaseAdapter:
    if code not in registry:
        raise KeyError(f"Neznámý adaptér: {code}. Dostupné: {', '.join(sorted(registry))}")
    return registry[code]()
