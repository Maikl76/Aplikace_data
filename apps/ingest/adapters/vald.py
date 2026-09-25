"""
Adaptéry na exporty z VALD Hubu.

**ForceDecks** („ForceDecks Test Results Export“): nad tabulkou je sedm
řádků s popisem exportu, pak hlavička začínající sloupcem „Athlete“.
Jeden řádek = jeden pokus („Trial 1“, u stoje na jedné noze „Left (1)“).
Bilaterální metriky mají vedle souhrnného sloupce i varianty „(Left)“
a „(Right)“ – ty se uloží jako levá a pravá strana.

**HumanTrak**: hlavička hned v prvním řádku, jeden řádek = celý test,
čísla bývají uložená jako text.

Co se z exportu importuje, určují profily importu v katalogu
(ImportProfile) – ne tento kód. Adaptér jen čte.
"""

import csv
import io
import re
import unicodedata
from collections import Counter
from collections.abc import Iterator
from datetime import date, datetime, time
from typing import IO

from django.utils import timezone

from apps.subjects.crypto import search_hash

from .base import BaseAdapter, ParsedRow, register

FORCEDECKS_TITLE = "ForceDecks Test Results Export"
TRIAL_RE = re.compile(r"(?:(Left|Right)\s*\((\d+)\)|Trial\s*(\d+))", re.IGNORECASE)


# --- čtení souboru -----------------------------------------------------------

def read_rows(fileobj: IO[bytes]) -> list[list]:
    """Řádky tabulky z xlsx nebo csv, jako seznamy buněk."""
    fileobj.seek(0)
    head = fileobj.read(4)
    fileobj.seek(0)
    if head.startswith(b"PK"):
        import openpyxl

        workbook = openpyxl.load_workbook(fileobj, read_only=True, data_only=True)
        try:
            return [list(row) for row in workbook.worksheets[0].iter_rows(values_only=True)]
        finally:
            workbook.close()

    raw = fileobj.read()
    for encoding in ("utf-8-sig", "cp1250"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:5000]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


def _cell(value) -> str:
    return "" if value is None else str(value).strip()


def _number(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().replace(",", "."))
    except ValueError:
        return None


def _datetime(value, clock=None) -> datetime | None:
    """Datum a čas testu jako aware datetime v časové zóně aplikace."""
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, date):
        moment = datetime.combine(value, time())
    else:
        text = _cell(value)
        moment = None
        for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d.%m.%Y %H:%M:%S",
                    "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                    "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d"):
            try:
                moment = datetime.strptime(text[:19], fmt)
                break
            except ValueError:
                continue
        if moment is None:
            return None
    if clock is not None:
        if isinstance(clock, time):
            moment = datetime.combine(moment.date(), clock)
        elif (text := _cell(clock)) and re.match(r"^\d{1,2}:\d{2}", text):
            hours, minutes = text.split(":")[:2]
            moment = datetime.combine(moment.date(), time(int(hours), int(minutes[:2])))
    moment = moment.replace(microsecond=0)
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment)
    return moment


def _birth_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _cell(value)
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


# --- identita sportovce ----------------------------------------------------------

def normalize_name(name: str) -> str:
    """„Matěj  Čika“ → „matej cika“: bez diakritiky, malými, jedna mezera."""
    text = unicodedata.normalize("NFD", name or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.lower().split())


def identity_ids(name: str, birth: date | None) -> dict:
    """Hashe pro párování se sportovci – jméno samotné se nikam neukládá."""
    normalized = normalize_name(name)
    ids = {}
    if normalized:
        ids["hash_jmeno"] = search_hash(normalized)
        if birth:
            ids["hash_jmeno_narozeni"] = search_hash(f"{normalized}|{birth.isoformat()}")
    return ids


def split_name(name: str) -> tuple[str, str]:
    """VALD píše „Jméno Příjmení“; víc slov = víc křestních jmen."""
    parts = (name or "").split()
    if len(parts) < 2:
        return "", name.strip()
    return " ".join(parts[:-1]), parts[-1]


def _sex(value) -> str:
    text = _cell(value).lower()
    if text.startswith(("m", "muž")):
        return "M"
    if text.startswith(("f", "ž", "w")):
        return "F"
    return "X"


def _side_variant(column: str, side: str) -> str:
    """„Concentric Peak Force [N]“ → „Concentric Peak Force (Left) [N]“."""
    if " [" in column:
        name, unit = column.split(" [", 1)
        return f"{name} ({side}) [{unit}"
    return f"{column} ({side})"


def _profiles(device: str) -> dict:
    from apps.catalog.models import ImportProfile

    return {
        p.test_type: p
        for p in ImportProfile.objects.filter(device=device, is_active=True)
        .select_related("protocol").prefetch_related("columns__metric")
    }


# --- ForceDecks --------------------------------------------------------------------

@register
class ForceDecksAdapter(BaseAdapter):
    code = "vald_forcedecks"
    label = "VALD ForceDecks (Test Results Export)"
    device = "VALD ForceDecks"
    file_extensions = (".xlsx", ".csv")

    def sniff(self, fileobj: IO[bytes]) -> bool:
        try:
            rows = read_rows(fileobj)
        except Exception:
            return False
        return bool(rows) and _cell(rows[0][0] if rows[0] else "") == FORCEDECKS_TITLE

    def parse(self, fileobj: IO[bytes]) -> Iterator[ParsedRow]:
        rows = read_rows(fileobj)
        header_at = next((i for i, row in enumerate(rows[:30])
                          if row and _cell(row[0]) == "Athlete"), None)
        if header_at is None:
            raise ValueError("V souboru chybí hlavička tabulky (řádek začínající „Athlete“).")

        header = [_cell(c) for c in rows[header_at]]
        index = {name: i for i, name in enumerate(header) if name}
        for needed in ("Athlete", "Athlete Id", "Test Type", "Test Date", "Trial"):
            if needed not in index:
                raise ValueError(f"V hlavičce chybí sloupec „{needed}“.")

        def get(row, name):
            i = index.get(name)
            return row[i] if i is not None and i < len(row) else None

        profiles = _profiles(self.code)
        used_columns: set[str] = set()
        missing: set[str] = set()
        skipped_types: Counter = Counter()

        for row_number, row in enumerate(rows[header_at + 1:], start=header_at + 2):
            name = _cell(get(row, "Athlete"))
            if not name:
                continue
            test_type = _cell(get(row, "Test Type"))
            profile = profiles.get(test_type)
            if profile is None:
                skipped_types[test_type] += 1
                continue

            started = _datetime(get(row, "Test Date"))
            athlete_id = _cell(get(row, "Athlete Id"))
            birth = _birth_date(get(row, "Date of Birth"))
            first, last = split_name(name)
            ids = {"vald": athlete_id} if athlete_id else {}
            if ext := _cell(get(row, "ExtId")):
                ids["extid"] = ext
            ids.update(identity_ids(name, birth))
            subject_key = f"vald:{athlete_id}" if athlete_id else f"jmeno:{ids['hash_jmeno']}"

            conditions = {}
            if params := _cell(get(row, "Test Parameters")):
                conditions["parametry"] = params
            if tags := _cell(get(row, "Test Tags")):
                conditions["stitky"] = tags

            trial_side, trial_number = "", 1
            if match := TRIAL_RE.search(_cell(get(row, "Trial"))):
                if match.group(1):
                    trial_side = "L" if match.group(1).lower() == "left" else "R"
                    trial_number = int(match.group(2))
                else:
                    trial_number = int(match.group(3))

            common = {
                "subject_key": subject_key,
                "subject_hint": name,
                "subject_ids": ids,
                "subject_attrs": {
                    "first_name": first, "last_name": last,
                    "birth_year": birth.year if birth else None,
                    "sex": _sex(get(row, "Gender")),
                },
                "protocol_code": profile.protocol.code,
                "session_date": started.date() if started else None,
                "run_key": (f"vald:{athlete_id or ids['hash_jmeno']}:{test_type}:"
                            f"{started.isoformat() if started else row_number}"),
                "run_started_at": started,
                "run_conditions": conditions,
                "trial_number": trial_number,
                "row_number": row_number,
            }

            for column in profile.columns.all():
                # U stoje na jedné noze nese stranu pokus, ne sloupec.
                if trial_side:
                    variants = [(column.column, trial_side)]
                elif column.with_sides:
                    variants = [(column.column, "B"),
                                (_side_variant(column.column, "Left"), "L"),
                                (_side_variant(column.column, "Right"), "R")]
                else:
                    variants = [(column.column, "B")]
                found = False
                for source, side in variants:
                    if source not in index:
                        continue
                    found = True
                    used_columns.add(source)
                    value = _number(get(row, source))
                    if value is None:
                        continue
                    yield ParsedRow(
                        metric_code=column.metric.code, value=value * column.factor,
                        side=side, extra={"source_column": source}, **common,
                    )
                if not found:
                    missing.add(column.column)

        ignored = [c for c in header[header.index("Trial") + 1:] if c and c not in used_columns]
        if ignored:
            count = len(ignored)
            word = ("další sloupec, který se neimportuje" if count == 1 else
                    f"další {count} sloupce, které se neimportují" if count < 5 else
                    f"dalších {count} sloupců, které se neimportují")
            self.notes.append(
                f"Soubor obsahuje {word}. Chcete-li některý sledovat, přidejte ho "
                f"v Katalogu → Profily importu a soubor načtěte znovu.")
        if missing:
            self.notes.append("V souboru chybí sloupce, které profil importu očekává: "
                              + ", ".join(f"„{c}“" for c in sorted(missing))
                              + ". Jiný profil exportu ve VALD Hubu?")
        for test_type, count in skipped_types.items():
            self.notes.append(
                f"Typ testu „{test_type}“ nemá profil importu – {count} řádků se přeskočilo. "
                f"Založte ho v Katalogu → Profily importu.")


# --- HumanTrak -----------------------------------------------------------------------

HUMANTRAK_IDENTITY = {"Name", "ExternalId", "Date", "Time", "Device", "Test"}
HUMANTRAK_CONDITIONS = {"Reps": "opakovani", "Box Weight[kg]": "zatez_kg"}


@register
class HumanTrakAdapter(BaseAdapter):
    code = "vald_humantrak"
    label = "VALD HumanTrak"
    device = "VALD HumanTrak"
    file_extensions = (".xlsx", ".csv")

    def sniff(self, fileobj: IO[bytes]) -> bool:
        try:
            rows = read_rows(fileobj)
        except Exception:
            return False
        header = {_cell(c) for c in (rows[0] if rows else [])}
        return {"Name", "ExternalId", "Date", "Test"} <= header

    def parse(self, fileobj: IO[bytes]) -> Iterator[ParsedRow]:
        rows = read_rows(fileobj)
        header = [_cell(c) for c in rows[0]]
        index = {name: i for i, name in enumerate(header) if name}

        def get(row, name):
            i = index.get(name)
            return row[i] if i is not None and i < len(row) else None

        profiles = _profiles(self.code)
        used = set(HUMANTRAK_IDENTITY) | set(HUMANTRAK_CONDITIONS)
        skipped_types: Counter = Counter()
        missing: set[str] = set()

        for row_number, row in enumerate(rows[1:], start=2):
            name = _cell(get(row, "Name"))
            if not name:
                continue
            test_type = _cell(get(row, "Test"))
            profile = profiles.get(test_type)
            if profile is None:
                skipped_types[test_type] += 1
                continue

            started = _datetime(get(row, "Date"), get(row, "Time"))
            ids = identity_ids(name, None)
            if ext := _cell(get(row, "ExternalId")):
                ids["extid"] = ext
            first, last = split_name(name)
            conditions = {key: _number(get(row, column)) for column, key
                          in HUMANTRAK_CONDITIONS.items() if _number(get(row, column)) is not None}

            common = {
                "subject_key": f"jmeno:{ids['hash_jmeno']}",
                "subject_hint": name,
                "subject_ids": ids,
                "subject_attrs": {"first_name": first, "last_name": last},
                "protocol_code": profile.protocol.code,
                "session_date": started.date() if started else None,
                "run_key": (f"humantrak:{ids['hash_jmeno']}:{test_type}:"
                            f"{started.isoformat() if started else row_number}"),
                "run_started_at": started,
                "run_conditions": conditions,
                "trial_number": 1,
                "row_number": row_number,
            }
            for column in profile.columns.all():
                if column.column not in index:
                    missing.add(column.column)
                    continue
                used.add(column.column)
                value = _number(get(row, column.column))
                if value is None:
                    continue
                yield ParsedRow(metric_code=column.metric.code, value=value * column.factor,
                                side="B", extra={"source_column": column.column}, **common)

        if ignored := [c for c in header if c and c not in used]:
            self.notes.append(f"Neimportované sloupce: {', '.join(ignored)}.")
        if missing:
            self.notes.append("V souboru chybí sloupce, které profil importu očekává: "
                              + ", ".join(f"„{c}“" for c in sorted(missing))
                              + ". Jiný profil exportu ve VALD Hubu?")
        for test_type, count in skipped_types.items():
            self.notes.append(
                f"Typ testu „{test_type}“ nemá profil importu – {count} řádků se přeskočilo.")
