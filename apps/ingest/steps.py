"""Kroky importu: přístroje, nahrát, zkontrolovat a uložit, kam se zapsalo."""

from django.db.models import Q
from django.urls import reverse

from apps.core.steps import step

from .models import ImportBatch


def import_list_steps(user, batches) -> list[dict]:
    from apps.catalog.models import DeviceFormat

    from .device_views import can_edit

    batches = list(batches)
    parsed = [b for b in batches if b.status == ImportBatch.Status.PARSED]
    committed = [b for b in batches if b.status == ImportBatch.Status.COMMITTED]
    devices = DeviceFormat.objects.filter(
        Q(organization__isnull=True) | Q(organization=user.organization), is_active=True).count()
    return [
        step(1, "Přístroje", devices > 0,
             ("Exporty z VALD aplikace pozná sama; "
              + (f"{devices} vlastních přístrojů s profilem." if devices else
                 "další přístroj (DEXA, InBody…) přidáte průvodcem.")),
             url=reverse("device_new"), button="Přidat přístroj", optional=True,
             admin_only=not can_edit(user)),
        step(2, "Nahrát export", bool(batches),
             (f"{len(batches)} importů, poslední {batches[0].created_at:%d.%m.%Y}."
              if batches else "Přetáhněte soubory z přístroje; formát se rozpozná sám."),
             url="#nahrat", button="Nahrát"),
        step(3, "Zkontrolovat a uložit", not parsed,
             (f"{len(parsed)} souborů čeká na kontrolu – do databáze se nic nezapsalo."
              if parsed else "Nic nečeká na kontrolu."),
             url=reverse("import_detail", args=[parsed[0].pk]) if parsed else "#historie",
             button="Zkontrolovat", count=len(parsed) or None),
        step(4, "Výsledky v testovacích dnech", bool(committed),
             (f"Poslední uložený import {committed[0].created_at:%d.%m.%Y}; hodnoty jsou "
              "v testovacích dnech sportovců." if committed else "Po uložení importu."),
             url=reverse("session_list"), button="Měření", optional=True),
    ]


def import_detail_steps(batch, sportovci, problems) -> list[dict]:
    committed = batch.status == ImportBatch.Status.COMMITTED
    unmatched = [s for s in sportovci if s.get("selected") is None]
    return [
        step(1, "Nahráno", True, f"Soubor načten {batch.created_at:%d.%m.%Y %H:%M}; nic se "
                                  "ještě nezapsalo." if not committed else
             f"Soubor načten {batch.created_at:%d.%m.%Y}.", url="#nahled"),
        step(2, "Sportovci rozpoznáni", not unmatched,
             (f"{len(unmatched)} nepoznaných – vyberte, komu výsledky patří; příště je aplikace "
              "pozná sama." if unmatched else "Všichni sportovci ze souboru jsou přiřazení."),
             url="#sportovci", button="Přiřadit" if unmatched and not committed else "",
             count=len(unmatched) or None),
        step(3, "Vyžaduje pozornost", not problems,
             (f"{len(problems)} hodnot mimo rozsah nebo neznámých ukazatelů – zkontrolujte, "
              "uložit jde i tak." if problems else "Nic podezřelého."),
             url="#pozornost", button="Prohlédnout" if problems else "",
             count=len(problems) or None),
        step(4, "Uložit do databáze", committed,
             (f"Uloženo {batch.updated_at:%d.%m.%Y %H:%M}." if committed else
              "Zapíše hodnoty do testovacích dnů; opakovaný import nic nezdvojí."),
             url="#ulozit", button="" if committed else "Uložit"),
        step(5, "Kam se zapsalo", committed,
             ("Hodnoty jsou v testovacích dnech sportovců; zprávy vytvoříte tam." if committed
              else "Po uložení."),
             url=reverse("session_list"), button="Testovací dny" if committed else "",
             optional=True),
    ]
