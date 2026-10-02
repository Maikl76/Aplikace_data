"""
Přístroje přidané průvodcem „Nový přístroj“ (DeviceFormat).

Export je obyčejná tabulka (CSV nebo Excel): řádek s názvy sloupců,
pod ním jeden řádek na jedno měření jednoho člověka. Kde je jméno, datum
a které sloupce jsou které metriky, říká DeviceFormat a jeho profil
importu – tento kód nic o konkrétním přístroji neví.

Víc řádků téhož člověka se stejným datem (a časem) = víc pokusů jednoho
testu, stejně jako u VALD.
"""

from collections import Counter
from collections.abc import Iterator
from typing import IO

from .base import BaseAdapter, ParsedRow
from .vald import (
    _birth_date,
    _cell,
    _datetime,
    _number,
    _sex,
    identity_ids,
    read_rows,
    split_name,
)


def guess_header_row(rows: list[list]) -> int:
    """
    Index řádku s názvy sloupců: nad tabulkou bývá popis exportu (název
    přístroje, datum exportu). Vyhrává první řádek s nejvíc textovými
    buňkami mezi prvními třiceti.
    """
    best, best_count = 0, 0
    for i, row in enumerate(rows[:30]):
        count = sum(1 for c in row if _cell(c) and _number(c) is None)
        if count > best_count:
            best, best_count = i, count
    return best


def header_at(rows: list[list], device) -> int | None:
    """Kde je hlavička tohoto přístroje: na uloženém řádku, jinak kdekoli nahoře."""
    needed = device.identity_columns
    candidates = [device.header_row - 1] + [i for i in range(min(30, len(rows)))
                                             if i != device.header_row - 1]
    for i in candidates:
        if 0 <= i < len(rows) and needed <= {_cell(c) for c in rows[i]}:
            return i
    return None


def match_score(rows: list[list], device, columns: list[str]) -> int:
    """Kolik sloupců profilu soubor má (0 = soubor tomuto přístroji nepatří)."""
    at = header_at(rows, device)
    if at is None:
        return 0
    header = {_cell(c) for c in rows[at]}
    return sum(1 for c in columns if c in header)


class DeviceTableAdapter(BaseAdapter):
    file_extensions = (".xlsx", ".csv")

    def __init__(self, device):
        super().__init__()
        self.device_format = device
        self.code = device.adapter_code
        self.label = device.name
        self.device = device.name

    def sniff(self, fileobj: IO[bytes]) -> bool:
        profile = self.device_format.profile()
        columns = [c.column for c in profile.columns.all()] if profile else []
        return match_score(read_rows(fileobj), self.device_format, columns) > 0

    def parse(self, fileobj: IO[bytes]) -> Iterator[ParsedRow]:
        device = self.device_format
        profile = device.profile()
        if profile is None or not device.is_active:
            raise ValueError(f"Přístroj „{device.name}“ ještě nemá přiřazené sloupce – "
                             f"dokončete ho v Importu → Přístroje.")
        rows = read_rows(fileobj)
        at = header_at(rows, device)
        if at is None:
            missing = ", ".join(f"„{c}“" for c in sorted(device.identity_columns))
            raise ValueError(f"V souboru chybí sloupce, podle kterých se pozná sportovec "
                             f"a datum ({missing}). Je to opravdu export z „{device.name}“?")

        header = [_cell(c) for c in rows[at]]
        index = {name: i for i, name in enumerate(header) if name}

        def get(row, name):
            i = index.get(name) if name else None
            return row[i] if i is not None and i < len(row) else None

        columns = list(profile.columns.all())
        missing = sorted({c.column for c in columns if c.column not in index})
        trials: Counter = Counter()

        for row_number, row in enumerate(rows[at + 1:], start=at + 2):
            if device.name_column:
                name = _cell(get(row, device.name_column))
            else:
                name = " ".join(filter(None, (_cell(get(row, device.first_name_column)),
                                              _cell(get(row, device.last_name_column)))))
            device_id = _cell(get(row, device.id_column))
            if not name and not device_id:
                continue  # prázdný řádek nebo součet pod tabulkou

            birth = _birth_date(get(row, device.birth_column))
            ids = identity_ids(name, birth)
            if device_id:
                ids["pristroj"] = f"{device.code}:{device_id}"
            person = f"{device.code}:{device_id}" if device_id else f"jmeno:{ids['hash_jmeno']}"
            if device.first_name_column and device.last_name_column:
                first = _cell(get(row, device.first_name_column))
                last = _cell(get(row, device.last_name_column))
            else:
                first, last = split_name(name)

            started = _datetime(get(row, device.date_column),
                                get(row, device.time_column) if device.time_column else None)
            run_key = f"{device.code}:{person}:{started.isoformat() if started else 'bez-data'}"
            trials[run_key] += 1

            common = {
                "subject_key": person,
                "subject_hint": name or f"ID {device_id}",
                "subject_ids": ids,
                "subject_attrs": {
                    "first_name": first, "last_name": last,
                    "birth_year": birth.year if birth else None,
                    "birth_date": birth.isoformat() if birth else None,
                    "sex": _sex(get(row, device.sex_column)) if device.sex_column else "",
                },
                "protocol_code": profile.protocol.code,
                "session_date": started.date() if started else None,
                "run_key": run_key,
                "run_started_at": started,
                "trial_number": trials[run_key],
                "row_number": row_number,
            }
            for column in columns:
                value = _number(get(row, column.column))
                if value is None:
                    continue
                yield ParsedRow(metric_code=column.metric.code, value=value * column.factor,
                                side=column.side or "B", segment=column.segment,
                                extra={"source_column": column.column}, **common)

        used = device.identity_columns | {c.column for c in columns}
        if ignored := [c for c in header if c and c not in used]:
            count = len(ignored)
            word = ("další sloupec, který se neimportuje" if count == 1 else
                    f"další {count} sloupce, které se neimportují" if count < 5 else
                    f"dalších {count} sloupců, které se neimportují")
            self.notes.append(f"Soubor obsahuje {word}. Chcete-li některý sledovat, přiřaďte "
                              f"ho v Importu → Přístroje → {device.name}.")
        if missing:
            self.notes.append("V souboru chybí sloupce, které má přístroj nastavené: "
                              + ", ".join(f"„{c}“" for c in missing)
                              + ". Změnil výrobce export? Nahrajte nový ukázkový soubor "
                                "v Importu → Přístroje.")
