"""
Které testy umí aplikace načíst z exportu přístroje a z jakého.

Zdrojem pravdy jsou profily importu (přístroj + typ testu → test) a
přístroje přidané průvodcem. Test bez profilu se zadává ručně – a je lepší
to říct u testu předem, než to zjistit až z odmítnutého souboru.
"""

from collections import defaultdict

from django.db.models import Q
from django.urls import reverse

from apps.catalog.models import DeviceFormat, ImportProfile

from .adapters import registry

# Původní Excel je jednorázová migrace staré aplikace, ne denní export přístroje.
HIDDEN_ADAPTERS = {"legacy_excel"}


def device_labels(organization) -> dict[str, str]:
    """Kód adaptéru → název pro lidi (VALD ForceDecks, DEXA z průvodce…)."""
    # bez závorky s názvem exportu: „VALD ForceDecks“, ne „VALD ForceDecks (Test Results Export)“
    labels = {code: a.label.split(" (")[0] for code, a in registry.items()
              if code not in HIDDEN_ADAPTERS}
    devices = DeviceFormat.objects.filter(is_active=True).filter(
        Q(organization=organization) | Q(organization__isnull=True))
    for device in devices:
        labels[device.adapter_code] = device.name
    return labels


def import_sources(protocols, organization) -> dict[int, list[str]]:
    """Pro každý test (podle pk) názvy přístrojů, jejichž export ho vyplní; prázdné = jen ručně."""
    labels = device_labels(organization)
    ids = [p.pk for p in protocols]
    sources: dict[int, list[str]] = defaultdict(list)
    for device, protocol_id in (ImportProfile.objects.filter(protocol_id__in=ids, is_active=True)
                                .values_list("device", "protocol_id").distinct()):
        label = labels.get(device)
        if label and label not in sources[protocol_id]:
            sources[protocol_id].append(label)
    for device in (DeviceFormat.objects.filter(is_active=True, protocol_id__in=ids)
                   .filter(Q(organization=organization) | Q(organization__isnull=True))):
        if device.name not in sources[device.protocol_id]:
            sources[device.protocol_id].append(device.name)
    return dict(sources)


def hint(sources: list[str] | None) -> str:
    """Krátký text k testu: „import: VALD ForceDecks“, nebo „jen ruční zadání“."""
    return f"import: {', '.join(sources)}" if sources else "jen ruční zadání"


def add_device_url() -> str:
    return reverse("device_new")
