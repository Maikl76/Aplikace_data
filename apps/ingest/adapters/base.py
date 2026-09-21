"""Základ pro adaptéry na formáty přístrojů."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import IO


@dataclass
class ParsedRow:
    """Jedna hodnota vytažená ze souboru, ještě nesvázaná s databází."""

    subject_hint: str
    metric_code: str
    value: float
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

    def parse(self, fileobj: IO[bytes]) -> Iterator[ParsedRow]:
        raise NotImplementedError

    def sniff(self, fileobj: IO[bytes]) -> bool:
        """Vypadá soubor jako formát tohoto adaptéru?"""
        return False


registry: dict[str, type[BaseAdapter]] = {}


def register(adapter_cls: type[BaseAdapter]) -> type[BaseAdapter]:
    registry[adapter_cls.code] = adapter_cls
    return adapter_cls
