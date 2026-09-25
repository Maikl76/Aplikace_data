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
import io
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
from apps.subjects.models import Subject, SubjectExternalId, SubjectIdentity

from .adapters import detect_adapter, get_adapter, registry
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
def stage_file(*, uploaded_file, user, organization, adapter_code="auto",
               protocol=None, device="") -> ImportBatch:
    """Načte soubor, rozparsuje ho a připraví náhled ke kontrole."""
    data = uploaded_file.read()
    content_hash = _hash_content(data)

    if adapter_code in ("", "auto"):
        adapter_code = detect_adapter(io.BytesIO(data))
        if adapter_code is None:
            raise ImportError_(
                f"Formát souboru „{uploaded_file.name}“ se nepodařilo rozpoznat. "
                f"Umím: {', '.join(a.label for a in registry.values())}."
            )

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
                f"jako „{existing.original_name}“. Pokud jste mezitím doplnil profil "
                f"importu, použijte v historii importů „načíst znovu“."
            )
        existing.delete()  # zrušený nebo neúspěšný pokus – jde znovu

    adapter = get_adapter(adapter_code)
    raw_file = RawFile.objects.create(
        file=ContentFile(data, name=uploaded_file.name),
        original_name=uploaded_file.name,
        content_hash=content_hash,
        device=device or adapter.device,
        format=uploaded_file.name.rsplit(".", 1)[-1].lower(),
        size_bytes=len(data),
    )
    batch = ImportBatch.objects.create(
        organization=organization, raw_file=raw_file, adapter=adapter_code,
        protocol=protocol, uploaded_by=user,
    )
    return _parse_into(batch, adapter, data, protocol=protocol)


def restage(raw_file, *, user, organization) -> ImportBatch:
    """
    Znovu načte už uložený soubor – třeba když v profilu importu přibyla
    metrika. Uložení pak doplní chybějící hodnoty a nic nezdvojí.
    """
    batch = raw_file.import_batches.filter(status=ImportBatch.Status.COMMITTED).first()
    if batch is None:
        raise ImportError_("Soubor nebyl uložen, není co načítat znovu.")
    adapter = get_adapter(batch.adapter)
    raw_file.file.open("rb")
    data = raw_file.file.read()
    raw_file.file.close()
    new_batch = ImportBatch.objects.create(
        organization=organization, raw_file=raw_file, adapter=batch.adapter,
        protocol=batch.protocol, uploaded_by=user,
    )
    return _parse_into(new_batch, adapter, data, protocol=batch.protocol)


def _parse_into(batch, adapter, data: bytes, *, protocol=None) -> ImportBatch:
    try:
        rows = list(adapter.parse(io.BytesIO(data)))
    except Exception as exc:  # adaptér může narazit na cokoli
        batch.status = ImportBatch.Status.FAILED
        batch.error = f"{type(exc).__name__}: {exc}"
        batch.save(update_fields=["status", "error"])
        logger.exception("Import %s selhal", batch.pk)
        return batch

    _stage_rows(batch, rows, protocol=protocol)
    batch.status = ImportBatch.Status.PARSED
    batch.summary = {**summarize(batch),
                     "nezmapovane_sloupce": list(adapter.unmapped_columns),
                     "poznamky": list(adapter.notes)}
    batch.save(update_fields=["status", "summary"])
    return batch


# Pořadí, ve kterém se sportovec páruje: od nejspolehlivějšího.
MATCH_ORDER = [
    (SubjectExternalId.System.VALD, "ID ve VALD"),
    (SubjectExternalId.System.NAME_BIRTH, "jméno a datum narození"),
    (SubjectExternalId.System.NAME, "jméno"),
]


def _match_subjects(organization, subjects_in_file: dict) -> dict:
    """
    Najde sportovce z aplikace ke každé osobě v souboru.

    Vrací {subject_key: (Subject | None, jak se našel, upozornění)}. Shoda
    jen podle jména platí, jen když je jednoznačná – dva Novákové znamenají
    raději nového sportovce ke kontrole než data u cizího člověka.
    """
    wanted = {(system, info["ids"][system])
              for info in subjects_in_file.values()
              for system, _ in MATCH_ORDER if info["ids"].get(system)}
    values = {value for _, value in wanted}
    owners: dict[tuple, set] = {}
    for ext in (SubjectExternalId.objects
                .filter(subject__organization=organization, value__in=values)
                .select_related("subject")):
        owners.setdefault((ext.system, ext.value), set()).add(ext.subject)

    legacy = {s.source_key: s for s in Subject.objects.filter(
        organization=organization, source_key__in=list(subjects_in_file))}

    result = {}
    for key, info in subjects_in_file.items():
        found, how, warning = None, "", ""
        for system, label in MATCH_ORDER:
            candidates = owners.get((system, info["ids"].get(system)), set())
            if len(candidates) == 1:
                found, how = next(iter(candidates)), label
                break
            if len(candidates) > 1:
                warning = (f"Podle {label} odpovídá víc sportovcům "
                           f"({', '.join(sorted(s.code for s in candidates))}).")
        if found is None and key in legacy:
            found, how = legacy[key], "dřívější import"
        result[key] = (found, how, warning)
    return result


def _stage_rows(batch, rows, *, protocol=None):
    """Uloží rozparsované řádky a přiřadí jim příznaky kontroly."""
    metrics = {m.code: m for m in MetricDef.objects.filter(is_active=True)}
    protocols = {p.code: p for p in Protocol.objects.filter(is_active=True)}

    subjects_in_file: dict[str, dict] = {}
    runs: dict[str, dict] = {}
    for row in rows:
        info = subjects_in_file.setdefault(
            row.subject_key, {"hint": row.subject_hint, "ids": {}, "attrs": {}, "runs": set()})
        info["ids"].update({k: v for k, v in row.subject_ids.items() if v})
        info["attrs"].update({k: v for k, v in row.subject_attrs.items() if v not in (None, "")})
        if row.run_key:
            info["runs"].add(row.run_key)
            runs.setdefault(row.run_key, {"conditions": row.run_conditions})

    matches = _match_subjects(batch.organization, subjects_in_file)
    existing_runs = set(
        ProtocolRun.objects.filter(session__organization=batch.organization,
                                   external_ref__in=list(runs))
        .values_list("external_ref", flat=True)
    ) if runs else set()

    staged = []
    for row in rows:
        metric = metrics.get(row.metric_code)
        subject = matches[row.subject_key][0]
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
        if row.run_key in existing_runs:
            problems.append((StagedMeasurement.Flag.DUPLICATE,
                             "Test už je v aplikaci – při uložení se hodnoty aktualizují."))
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
            run_key=row.run_key,
            run_started_at=row.run_started_at,
            metric_code=row.metric_code,
            metric=metric,
            trial_number=row.trial_number,
            side=row.side,
            mode=row.mode,
            speed=row.speed,
            segment=row.segment,
            value=row.value,
            flag=flag,
            message=message[:255],
        ))

    StagedMeasurement.objects.bulk_create(staged, batch_size=1000)

    # Údaje o osobách (jméno pro založení identity, identifikátory) se drží
    # v souhrnu jen do uložení nebo zrušení importu – pak se mažou.
    batch.summary = {
        "subjects": {
            key: {"hint": info["hint"], "ids": info["ids"], "attrs": info["attrs"],
                  "testu": len(info["runs"]),
                  "kod": matches[key][0].code if matches[key][0] else None,
                  "shoda": matches[key][1], "upozorneni": matches[key][2]}
            for key, info in subjects_in_file.items()
        },
        "runs": runs,
        "existujici_testy": len(existing_runs),
    }


def summarize(batch) -> dict:
    """Souhrn pro náhled: co se našlo a na co se má člověk podívat."""
    staged = batch.staged.all()
    previous = batch.summary or {}
    subjects = previous.get("subjects", {})
    flags = Counter(staged.values_list("flag", flat=True))
    dates = [d for d in staged.values_list("session_date", flat=True).distinct() if d]
    keys = set(staged.values_list("subject_key", flat=True).distinct())
    matched = set(staged.filter(subject__isnull=False)
                  .values_list("subject_key", flat=True).distinct())
    runs = previous.get("runs", {})
    return {
        "hodnot": staged.count(),
        "sportovcu": len(keys),
        "novych_sportovcu": len(keys - matched),
        "testu": len(runs) or staged.values("protocol_code", "subject_key",
                                            "session_date").distinct().count(),
        "existujici_testy": previous.get("existujici_testy", 0),
        "metrik": staged.filter(metric__isnull=False).values("metric_code").distinct().count(),
        "protokolu": staged.filter(protocol__isnull=False)
        .values("protocol_code").distinct().count(),
        "mimo_rozsah": flags.get(StagedMeasurement.Flag.OUT_OF_RANGE, 0),
        "novych_hodnot_bez_data": staged.filter(session_date__isnull=True).count(),
        "nezname_metriky": sorted(set(staged.filter(
            flag=StagedMeasurement.Flag.UNKNOWN_METRIC).values_list("metric_code", flat=True))),
        "datum_od": min(dates).isoformat() if dates else None,
        "datum_do": max(dates).isoformat() if dates else None,
        "subjects": subjects,
        "runs": runs,
        "subject_attrs": previous.get("subject_attrs", {}),
    }


def clear_personal_data(batch):
    """Po uložení nebo zrušení: pryč se jmény a identifikátory ze souhrnu."""
    summary = dict(batch.summary or {})
    subjects = summary.pop("subjects", {})
    summary.pop("subject_attrs", None)
    summary.pop("runs", None)
    summary["sportovci_kody"] = sorted({i.get("kod") for i in subjects.values() if i.get("kod")})
    batch.summary = summary


@transaction.atomic
def commit_batch(batch, *, user, default_date=None, skip_out_of_range=False) -> dict:
    """
    Uloží zkontrolovaný staging do provozních tabulek.

    Hodnoty mimo věrohodný rozsah se ve výchozím stavu ULOŽÍ, jen se
    označí ``quality=OUT_OF_RANGE``. Mlčky zahazovat naměřená data je
    horší než je mít označená – chyba přístroje je taky informace.

    Test, který už v aplikaci je (stejná identifikace ve zdroji), se
    nezdvojí: chybějící hodnoty se doplní, změněné (VALD test přepočítal)
    se aktualizují.
    """
    if batch.status != ImportBatch.Status.PARSED:
        raise ImportError_("Import není ve stavu ke kontrole.")

    summary = batch.summary or {}
    subjects_info = summary.get("subjects", {})
    legacy_attrs = summary.get("subject_attrs", {})
    runs_info = summary.get("runs", {})
    result = {"sportovci": 0, "session": 0, "testy": 0, "hodnoty": 0,
              "aktualizovano": 0, "preskoceno": 0, "jmena_neulozena": 0}

    rows = list(batch.staged.select_related("metric", "protocol", "subject"))

    # 1) sportovci – existující doplnit o nové identifikátory, chybějící založit
    subjects: dict[str, Subject] = {}
    for row in rows:
        if row.subject_key in subjects:
            continue
        info = subjects_info.get(row.subject_key, {})
        if row.subject is not None:
            subject = row.subject
        else:
            subject = _create_subject(batch, row, info, legacy_attrs, result)
            result["sportovci"] += 1
        _learn_ids(subject, info.get("ids", {}))
        subjects[row.subject_key] = subject

    # 2) testovací dny, provedení, pokusy
    sessions: dict[tuple, TestSession] = {}
    runs: dict[str, ProtocolRun] = {}
    run_is_existing: dict[str, bool] = {}
    existing_refs = {
        r.external_ref: r for r in ProtocolRun.objects.filter(
            session__organization=batch.organization,
            external_ref__in=[k for k in runs_info])
    } if runs_info else {}
    trials: dict[tuple, Trial] = {}
    touched: set[tuple] = set()

    def session_for(subject, day):
        key = (subject.pk, day)
        if key not in sessions:
            sessions[key], created = TestSession.objects.get_or_create(
                organization=batch.organization, subject=subject, date=day,
                defaults={"operator": user,
                          "note": f"Import: {batch.raw_file.original_name}"},
            )
            result["session"] += int(created)
        return sessions[key]

    new_measurements = []
    pending_updates = []
    for row in rows:
        if row.metric_id is None or row.protocol_id is None:
            result["preskoceno"] += 1
            continue
        if skip_out_of_range and row.flag == StagedMeasurement.Flag.OUT_OF_RANGE:
            result["preskoceno"] += 1
            continue
        day = row.session_date or default_date
        if day is None:
            result["preskoceno"] += 1
            continue
        subject = subjects[row.subject_key]

        run_key = row.run_key or f"bez-id:{subject.pk}:{day}:{row.protocol_id}"
        if run_key not in runs:
            if row.run_key and row.run_key in existing_refs:
                run, is_existing = existing_refs[row.run_key], True
            elif row.run_key:
                run = ProtocolRun.objects.create(
                    session=session_for(subject, day), protocol=row.protocol,
                    started_at=row.run_started_at, external_ref=row.run_key,
                    conditions=runs_info.get(row.run_key, {}).get("conditions", {}),
                )
                is_existing = False
                result["testy"] += 1
            else:
                run, created = ProtocolRun.objects.get_or_create(
                    session=session_for(subject, day), protocol=row.protocol)
                is_existing = not created
                result["testy"] += int(created)
            runs[run_key], run_is_existing[run_key] = run, is_existing
            touched.add((run.session_id, run.protocol_id))
            if is_existing:
                for trial in run.trials.all():
                    trials[(run.pk, trial.number)] = trial

        run = runs[run_key]
        trial = trials.get((run.pk, row.trial_number))
        if trial is None:
            trial = Trial.objects.create(protocol_run=run, number=row.trial_number)
            trials[(run.pk, row.trial_number)] = trial

        quality = (Measurement.Quality.OUT_OF_RANGE
                   if row.flag == StagedMeasurement.Flag.OUT_OF_RANGE
                   else Measurement.Quality.OK)
        values = {"trial": trial, "metric_id": row.metric_id, "side": row.side,
                  "mode": row.mode, "speed": row.speed, "segment": row.segment}
        if run_is_existing[run_key]:
            pending_updates.append((values, row.value, quality))
        else:
            new_measurements.append(Measurement(**values, value=row.value, quality=quality))

    Measurement.objects.bulk_create(new_measurements, batch_size=1000)
    result["hodnoty"] += len(new_measurements)

    existing = {}
    if pending_updates:
        trial_ids = {values["trial"].pk for values, _, _ in pending_updates}
        for m in Measurement.objects.filter(trial_id__in=trial_ids):
            existing[(m.trial_id, m.metric_id, m.side, m.mode, m.speed, m.segment)] = m
    for values, value, quality in pending_updates:
        current = existing.get((values["trial"].pk, values["metric_id"], values["side"],
                                values["mode"], values["speed"], values["segment"]))
        if current is None:
            Measurement.objects.create(**values, value=value, quality=quality)
            result["hodnoty"] += 1
        elif current.value != value:
            current.value, current.quality = value, quality
            current.save(update_fields=["value", "quality"])
            result["aktualizovano"] += 1

    _mark_primary_runs(touched)

    batch.status = ImportBatch.Status.COMMITTED
    batch.summary = {**summary, "vysledek": result}
    clear_personal_data(batch)
    batch.save(update_fields=["status", "summary"])
    batch.purge_staging()
    return result


def _mark_primary_runs(pairs: set[tuple]):
    """
    Když se protokol ten den měřil víckrát, hodnotou dne je první měření.
    Další (třeba po zátěži) zůstávají jako opakovaná měření.
    """
    for session_id, protocol_id in pairs:
        same_day = list(ProtocolRun.objects.filter(session_id=session_id,
                                                   protocol_id=protocol_id)
                        .order_by("started_at", "created_at", "pk"))
        for index, run in enumerate(same_day):
            should = index == 0
            if run.is_primary != should:
                run.is_primary = should
                run.save(update_fields=["is_primary"])


def _learn_ids(subject, ids: dict):
    """Zapamatuje si, jak sportovce zná zdroj – příště ho pozná sám."""
    for system, value in ids.items():
        if value and system in SubjectExternalId.System.values:
            SubjectExternalId.objects.get_or_create(subject=subject, system=system,
                                                    value=str(value)[:128])


def _create_subject(batch, row, info: dict, legacy_attrs: dict, result: dict) -> Subject:
    """
    Nový sportovec dostane pseudonymní kód. Jméno se uloží jen do šifrované
    identity (a jen když je nastavený šifrovací klíč); provozní tabulky
    nesou jen kód.
    """
    from django.conf import settings

    attrs = {**legacy_attrs.get(row.subject_key, {}), **info.get("attrs", {})}
    subject = Subject.objects.create(
        organization=batch.organization,
        code=_next_subject_code(batch.organization),
        source_key="" if info.get("ids") else row.subject_key,
        birth_year=attrs.get("birth_year"),
        sex=attrs.get("sex") or "X",
        note=f"Založeno importem {batch.raw_file.original_name}",
    )
    if attrs.get("last_name"):
        if settings.IDENTITY_ENCRYPTION_KEY:
            identity = SubjectIdentity(subject=subject)
            identity.set_names(attrs.get("first_name", ""), attrs["last_name"])
            identity.save()
        else:
            result["jmena_neulozena"] += 1
    return subject
