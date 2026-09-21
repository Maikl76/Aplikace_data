"""
Importní pipeline: soubor -> staging -> kontrola -> uložení.

Import nikdy nezapisuje rovnou do provozních tabulek. Nejdřív se všechno
rozparsuje do stagingu a označí příznaky ("neznámý sportovec", "mimo
věrohodný rozsah"), člověk to potvrdí, teprve pak se to uloží.

Zdrojový soubor se archivuje a identifikuje otiskem obsahu – tentýž soubor
podruhé pipeline odmítne. Je to pojistka proti dvojkliku, ne sémantická
deduplikace: dva exporty téhož měření se můžou lišit v bajtech (Excel si
nese čas vytvoření). Duplicitní hodnoty proto hlídá ještě get_or_create
nad kvalifikátory při ukládání.
"""

import hashlib
import logging
from collections import Counter

from django.core.files.base import ContentFile
from django.db import transaction

from apps.catalog.models import MetricDef, Protocol
from apps.measurements.models import (
    Measurement,
    ProtocolRun,
    RawFile,
    TestSession,
    Trial,
)
from apps.subjects.models import Subject

from .adapters import get_adapter
from .models import ImportBatch, StagedMeasurement

logger = logging.getLogger(__name__)


class ImportError_(Exception):
    """Import se nepovedl způsobem, který má uživatel vidět."""


def _hash_content(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _next_subject_code(organization) -> str:
    existing = (
        Subject.objects.filter(organization=organization, code__startswith="FTVS-")
        .values_list("code", flat=True)
    )
    numbers = [int(c.rsplit("-", 1)[1]) for c in existing if c.rsplit("-", 1)[1].isdigit()]
    return f"FTVS-{max(numbers, default=0) + 1:04d}"


@transaction.atomic
def stage_file(*, uploaded_file, user, organization, adapter_code,
               protocol=None, device="") -> ImportBatch:
    """Načte soubor, rozparsuje ho a připraví náhled ke kontrole."""
    data = uploaded_file.read()
    content_hash = _hash_content(data)

    if existing := RawFile.objects.filter(content_hash=content_hash).first():
        # Nedokončený import téhož souboru není chyba – jen se vrátíme
        # k jeho náhledu. Chyba je až opakování něčeho, co už je uložené.
        pending = existing.import_batches.filter(
            status=ImportBatch.Status.PARSED, organization=organization,
        ).first()
        if pending:
            return pending
        if existing.import_batches.filter(status=ImportBatch.Status.COMMITTED).exists():
            raise ImportError_(
                f"Tento soubor už byl importován {existing.created_at:%d.%m.%Y %H:%M} "
                f"jako „{existing.original_name}“."
            )
        existing.delete()  # zrušený nebo neúspěšný pokus – jde znovu

    raw_file = RawFile.objects.create(
        file=ContentFile(data, name=uploaded_file.name),
        original_name=uploaded_file.name,
        content_hash=content_hash,
        device=device,
        format=uploaded_file.name.rsplit(".", 1)[-1].lower(),
        size_bytes=len(data),
    )

    batch = ImportBatch.objects.create(
        organization=organization,
        raw_file=raw_file,
        adapter=adapter_code,
        protocol=protocol,
        uploaded_by=user,
    )

    try:
        adapter = get_adapter(adapter_code)
        raw_file.file.seek(0)
        rows = list(adapter.parse(raw_file.file))
        unmapped = list(getattr(adapter, "unmapped_columns", []))
    except Exception as exc:  # adaptér může narazit na cokoli
        batch.status = ImportBatch.Status.FAILED
        batch.error = f"{type(exc).__name__}: {exc}"
        batch.save(update_fields=["status", "error"])
        logger.exception("Import %s selhal", batch.pk)
        return batch

    _stage_rows(batch, rows, protocol=protocol)
    batch.status = ImportBatch.Status.PARSED
    batch.summary = {**summarize(batch), "nezmapovane_sloupce": unmapped}
    batch.save(update_fields=["status", "summary"])
    return batch


def _stage_rows(batch, rows, *, protocol=None):
    """Uloží rozparsované řádky a přiřadí jim příznaky kontroly."""
    metrics = {m.code: m for m in MetricDef.objects.filter(is_active=True)}
    protocols = {p.code: p for p in Protocol.objects.filter(is_active=True)}
    subjects = {
        s.source_key: s
        for s in Subject.objects.filter(organization=batch.organization)
        .exclude(source_key="")
    }

    staged = []
    for row in rows:
        metric = metrics.get(row.metric_code)
        subject = subjects.get(row.subject_key)
        row_protocol = protocols.get(row.protocol_code) or protocol

        # Příznaky se vyhodnocují nezávisle a vybere se ten nejzávažnější.
        # Dřív to byla jedna větev if/elif a "nový sportovec" tím přebil
        # "mimo rozsah" – nesmyslná hodnota u nově zakládané osoby prošla
        # bez povšimnutí.
        problems: list[tuple[str, str]] = []
        if metric is None:
            problems.append((StagedMeasurement.Flag.UNKNOWN_METRIC,
                             f"Metrika „{row.metric_code}“ není v katalogu."))
        elif not metric.is_plausible(row.value):
            problems.append((StagedMeasurement.Flag.OUT_OF_RANGE,
                             f"Hodnota mimo věrohodný rozsah "
                             f"{metric.plausible_min:g}–{metric.plausible_max:g} "
                             f"{metric.unit}."))
        if subject is None:
            problems.append((StagedMeasurement.Flag.UNKNOWN_SUBJECT,
                             "Sportovec zatím neexistuje – při uložení se založí nový."))

        flag = problems[0][0] if problems else StagedMeasurement.Flag.OK
        message = " ".join(text for _, text in problems)

        staged.append(StagedMeasurement(
            batch=batch,
            row_number=row.row_number,
            subject_hint=row.subject_hint,
            subject_key=row.subject_key,
            subject=subject,
            protocol_code=row.protocol_code,
            protocol=row_protocol,
            session_date=row.session_date,
            metric_code=row.metric_code,
            metric=metric,
            trial_number=row.trial_number,
            side=row.side,
            mode=row.mode,
            speed=row.speed,
            segment=row.segment,
            value=row.value,
            flag=flag,
            message=message,
        ))

    StagedMeasurement.objects.bulk_create(staged, batch_size=500)

    # Atributy sportovců si necháme pro chvíli zakládání při uložení.
    # Atributy sportovce (rok narození, pohlaví) si necháme stranou pro
    # chvíli, kdy se při uložení zakládají noví sportovci.
    batch.summary = {"subject_attrs": {
        row.subject_key: row.subject_attrs for row in rows if row.subject_attrs
    }}


def summarize(batch) -> dict:
    """Souhrn pro náhled: co se našlo a na co se má člověk podívat."""
    staged = batch.staged.all()
    flags = Counter(staged.values_list("flag", flat=True))
    dates = [d for d in staged.values_list("session_date", flat=True).distinct() if d]
    return {
        "hodnot": staged.count(),
        "sportovcu": len({s.subject_key for s in staged}),
        "novych_sportovcu": len({s.subject_key for s in staged if s.subject_id is None}),
        "metrik": len({s.metric_code for s in staged if s.metric_id}),
        "protokolu": len({s.protocol_code for s in staged if s.protocol_id}),
        "mimo_rozsah": flags.get(StagedMeasurement.Flag.OUT_OF_RANGE, 0),
        "novych_hodnot_bez_data": staged.filter(session_date__isnull=True).count(),
        "nezname_metriky": sorted({s.metric_code for s in staged
                                   if s.flag == StagedMeasurement.Flag.UNKNOWN_METRIC}),
        "datum_od": min(dates).isoformat() if dates else None,
        "datum_do": max(dates).isoformat() if dates else None,
        "subject_attrs": (batch.summary or {}).get("subject_attrs", {}),
    }


@transaction.atomic
def commit_batch(batch, *, user, default_date=None, skip_out_of_range=False) -> dict:
    """
    Uloží zkontrolovaný staging do provozních tabulek.

    Hodnoty mimo věrohodný rozsah se ve výchozím stavu ULOŽÍ, jen se
    označí ``quality=OUT_OF_RANGE``. Mlčky zahazovat naměřená data je
    horší než je mít označená – chyba přístroje je taky informace.
    """
    if batch.status != ImportBatch.Status.PARSED:
        raise ImportError_("Import není ve stavu ke kontrole.")

    attrs_by_key = (batch.summary or {}).get("subject_attrs", {})
    created = {"sportovci": 0, "session": 0, "hodnoty": 0, "preskoceno": 0}
    subject_cache: dict[str, Subject] = {}

    staged_rows = batch.staged.select_related("metric", "protocol", "subject")
    for row in staged_rows:
        if row.flag == StagedMeasurement.Flag.UNKNOWN_METRIC or row.metric_id is None:
            created["preskoceno"] += 1
            continue
        if skip_out_of_range and row.flag == StagedMeasurement.Flag.OUT_OF_RANGE:
            created["preskoceno"] += 1
            continue
        if row.protocol_id is None:
            created["preskoceno"] += 1
            continue

        subject = row.subject or subject_cache.get(row.subject_key)
        if subject is None:
            subject = _create_subject(batch, row, attrs_by_key)
            created["sportovci"] += 1
        subject_cache[row.subject_key] = subject

        session_date = row.session_date or default_date
        if session_date is None:
            created["preskoceno"] += 1
            continue

        session, is_new = TestSession.objects.get_or_create(
            organization=batch.organization, subject=subject, date=session_date,
            defaults={"operator": user, "note": f"Import: {batch.raw_file.original_name}"},
        )
        created["session"] += int(is_new)

        run, _ = ProtocolRun.objects.get_or_create(session=session, protocol=row.protocol)
        trial, _ = Trial.objects.get_or_create(protocol_run=run, number=row.trial_number)

        quality = (Measurement.Quality.OUT_OF_RANGE
                   if row.flag == StagedMeasurement.Flag.OUT_OF_RANGE
                   else Measurement.Quality.OK)
        _, made = Measurement.objects.get_or_create(
            trial=trial, metric=row.metric, side=row.side, mode=row.mode,
            speed=row.speed, segment=row.segment,
            defaults={"value": row.value, "quality": quality, "note": row.message[:255]},
        )
        created["hodnoty"] += int(made)

    batch.status = ImportBatch.Status.COMMITTED
    batch.summary = {**(batch.summary or {}), "vysledek": created}
    batch.summary.pop("subject_attrs", None)
    batch.save(update_fields=["status", "summary"])
    batch.purge_staging()
    return created


def _create_subject(batch, row, attrs_by_key) -> Subject:
    """
    Nový sportovec dostane pseudonymní kód. Jméno ze zdrojového souboru
    se NEUKLÁDÁ – zůstane jen hash v ``source_key``, aby se příští import
    téže osoby spároval s toutéž osobou.
    """
    attrs = attrs_by_key.get(row.subject_key, {})
    return Subject.objects.create(
        organization=batch.organization,
        code=_next_subject_code(batch.organization),
        source_key=row.subject_key,
        birth_year=attrs.get("birth_year"),
        sex=attrs.get("sex", "X"),
        note=f"Založeno importem {batch.raw_file.original_name}",
    )
