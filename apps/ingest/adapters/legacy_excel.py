"""
Adaptér na původní Excel ze Streamlit aplikace.

Formát: jeden široký list, jeden řádek = jeden proband, každá měřená
veličina vlastní sloupec s režimem a rychlostí v názvu. Historická
databáze má navíc sloupec ``DatumMereni`` a víc řádků na probanda.

Převod na kanonické metriky řeší ``LEGACY_COLUMN_MAP`` v catalog/seed_data.py.
"""

from collections.abc import Iterator
from datetime import date, datetime
from typing import IO

from apps.catalog.seed_data import (
    LEGACY_COLUMN_MAP,
    LEGACY_IDENTITY_COLUMNS,
    LEGACY_META_COLUMNS,
)
from apps.subjects.crypto import search_hash

from .base import BaseAdapter, ParsedRow, register


def _parse_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%d.%m.%Y", "%d. %m. %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _birth_year(value) -> int | None:
    parsed = _parse_date(value)
    if parsed:
        return parsed.year
    try:
        number = int(str(value).strip()[:4])
    except (ValueError, TypeError):
        return None
    return number if 1900 < number < 2100 else None


@register
class LegacyExcelAdapter(BaseAdapter):
    code = "legacy_excel"
    label = "Původní Excel (Streamlit aplikace)"
    device = ""
    file_extensions = (".xlsx",)

    def parse(self, fileobj: IO[bytes]) -> Iterator[ParsedRow]:
        import pandas as pd

        excel = pd.ExcelFile(fileobj)
        sheet = "data" if "data" in excel.sheet_names else excel.sheet_names[0]
        df = pd.read_excel(excel, sheet_name=sheet)
        df.columns = [str(c).strip() for c in df.columns]

        known = set(LEGACY_COLUMN_MAP) | set(LEGACY_IDENTITY_COLUMNS) | set(LEGACY_META_COLUMNS)
        self.unmapped_columns = sorted(c for c in df.columns if c not in known)

        for row_number, (_, row) in enumerate(df.iterrows(), start=2):
            identity_parts = [str(row.get(col, "")).strip() for col in LEGACY_IDENTITY_COLUMNS]
            subject_key = search_hash("|".join(identity_parts))
            subject_hint = " ".join(p for p in identity_parts[:2] if p) or f"řádek {row_number}"

            subject_attrs = {}
            if (year := _birth_year(row.get("Narozen"))) is not None:
                subject_attrs["birth_year"] = year
            if (sex := str(row.get("Pohlavi", "")).strip().upper()[:1]) in ("F", "M", "Z"):
                subject_attrs["sex"] = "F" if sex == "Z" else sex

            session_date = _parse_date(row.get("DatumMereni"))

            for column, mapping in LEGACY_COLUMN_MAP.items():
                if column not in df.columns:
                    continue
                raw = row[column]
                if raw is None or (isinstance(raw, float) and raw != raw):  # NaN
                    continue
                try:
                    value = float(str(raw).replace(",", "."))
                except (TypeError, ValueError):
                    continue

                protocol_code, metric_code, side, mode, speed, segment = mapping
                yield ParsedRow(
                    subject_key=subject_key,
                    subject_hint=subject_hint,
                    subject_attrs=subject_attrs,
                    metric_code=metric_code,
                    protocol_code=protocol_code,
                    session_date=session_date,
                    value=value,
                    side=side,
                    mode=mode,
                    speed=speed,
                    segment=segment,
                    row_number=row_number,
                    extra={"source_column": column},
                )

    def sniff(self, fileobj: IO[bytes]) -> bool:
        import pandas as pd

        try:
            excel = pd.ExcelFile(fileobj)
            sheet = "data" if "data" in excel.sheet_names else excel.sheet_names[0]
            columns = {str(c).strip() for c in pd.read_excel(excel, sheet_name=sheet, nrows=0).columns}
        except Exception:
            return False
        return bool(columns & set(LEGACY_COLUMN_MAP)) and "Jmeno" in columns
