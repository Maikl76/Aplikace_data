"""Základ pro adaptéry na formáty přístrojů."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
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
    # Jak sportovce zná zdroj: {"vald": "<uuid>", "hash_jmeno": "<hash>"}.
    # Podle toho se páruje s existujícími sportovci (SubjectExternalId).
    subject_ids: dict = field(default_factory=dict)
    protocol_code: str = ""
    session_date: date | None = None
    # Jedno provedení testu ve zdroji (u VALD sportovec + typ + čas testu).
    # Víc provedení téhož protokolu za den = opakované měření.
    run_key: str = ""
    run_started_at: datetime | None = None
    run_conditions: dict = field(default_factory=dict)
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
        # Upozornění pro náhled („typ testu X nemá profil importu“).
        self.notes: list[str] = []

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
    from apps.catalog.models import DeviceFormat

    if code.startswith(DeviceFormat.PREFIX):
        from .table import DeviceTableAdapter

        device = DeviceFormat.objects.filter(code=code.removeprefix(DeviceFormat.PREFIX)).first()
        if device is None:
            raise KeyError(f"Přístroj „{code}“ v katalogu není.")
        return DeviceTableAdapter(device)
    if code not in registry:
        raise KeyError(f"Neznámý adaptér: {code}. Dostupné: {', '.join(sorted(registry))}")
    return registry[code]()


def detect_adapter(fileobj: IO[bytes], organization=None) -> str | None:
    """Pozná formát podle obsahu souboru, ne podle názvu."""
    for code, adapter_cls in registry.items():
        try:
            fileobj.seek(0)
            if adapter_cls().sniff(fileobj):
                return code
        except Exception:
            continue
        finally:
            fileobj.seek(0)
    return detect_device_format(fileobj, organization)


def detect_device_format(fileobj: IO[bytes], organization=None) -> str | None:
    """Přístroj z průvodce, jehož sloupce soubor má nejvíc (víc shod = jistější)."""
    from django.db.models import Q

    from apps.catalog.models import DeviceFormat, ImportProfile

    from .table import match_score
    from .vald import read_rows

    devices = DeviceFormat.objects.filter(is_active=True)
    if organization is not None:
        devices = devices.filter(Q(organization=organization) | Q(organization__isnull=True))
    if not devices:
        return None
    try:
        fileobj.seek(0)
        rows = read_rows(fileobj)
    except Exception:
        return None
    finally:
        fileobj.seek(0)
    columns: dict[str, list[str]] = {}
    for profile in ImportProfile.objects.filter(
            device__in=[d.adapter_code for d in devices]).prefetch_related("columns"):
        columns[profile.device] = [c.column for c in profile.columns.all()]
    scored = [(match_score(rows, d, columns.get(d.adapter_code, [])), d) for d in devices]
    score, best = max(scored, key=lambda pair: pair[0])
    return best.adapter_code if score > 0 else None
