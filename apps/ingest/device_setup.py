"""
Průvodce „Nový přístroj“: přečtení ukázkového souboru, návrhy přiřazení
a uložení nastavení.

Návrhy jsou jen předvyplnění – člověk je v průvodci vidí a může změnit.
Proto stačí jednoduchá pravidla (podobnost názvů, slovníček anglických
slov z exportů), žádná chytristika, která by se tvářila jistě.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Q
from django.utils.text import slugify

from apps.catalog.models import (
    DeviceFormat,
    Direction,
    ImportColumn,
    ImportProfile,
    MetricDef,
    ProtocolMetric,
)

from .adapters.table import guess_header_row
from .adapters.vald import _cell, _number, read_rows

SAMPLE_ROWS = 3


# --- ukázkový soubor --------------------------------------------------------------

@dataclass
class Sample:
    header_row: int                     # 1 = první řádek souboru
    header: list[str]
    rows: list[list[str]] = field(default_factory=list)   # pár řádků pro náhled

    def values(self, column: str) -> list[str]:
        i = self.header.index(column) if column in self.header else None
        if i is None:
            return []
        return [r[i] for r in self.rows if i < len(r) and r[i]]


def read_sample(fileobj) -> Sample:
    rows = read_rows(fileobj)
    if not rows:
        raise ValueError("Soubor je prázdný.")
    at = guess_header_row(rows)
    header = [_cell(c) for c in rows[at]]
    # Prázdné názvy na konci řádku (Excel) pryč; uprostřed se nechají kvůli indexům.
    while header and not header[-1]:
        header.pop()
    if sum(1 for h in header if h) < 2:
        raise ValueError("V souboru jsem nenašel řádek s názvy sloupců.")
    data = [[_display(c) for c in row[:len(header)]]
            for row in rows[at + 1:] if any(_cell(c) for c in row)]
    return Sample(header_row=at + 1, header=header, rows=data[:SAMPLE_ROWS])


def _display(value) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%d.%m.%Y %H:%M" if getattr(value, "hour", 0) else "%d.%m.%Y")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return _cell(value)


# --- návrhy ----------------------------------------------------------------------------

def normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn").lower()
    text = text.replace("%", " pct ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


IDENTITY_HINTS = {
    "first_name_column": ["first name", "firstname", "given name", "jmeno", "krestni jmeno"],
    "last_name_column": ["last name", "lastname", "surname", "family name", "prijmeni"],
    "name_column": ["name", "jmeno a prijmeni", "athlete", "patient name", "full name",
                    "sportovec", "klient", "patient"],
    "id_column": ["patient id", "id", "athlete id", "subject id", "external id", "pid",
                  "id pacienta"],
    "birth_column": ["birth date", "date of birth", "dob", "birthdate", "datum narozeni",
                     "narozen", "birthday"],
    "sex_column": ["sex", "gender", "pohlavi"],
    "date_column": ["scan date", "test date", "date", "measurement date", "datum mereni",
                    "datum", "exam date", "visit date"],
    "time_column": ["time", "scan time", "test time", "cas", "cas mereni"],
}
# Jen u těchto polí stačí, když název sloupce nápovědu obsahuje („Patient Name“).
# U data a času by „Time to Peak“ nebo „Birth Date“ zmátly návrh.
SUBSTRING_OK = {"name_column", "birth_column"}


def suggest_identity(sample: Sample) -> dict[str, str]:
    """Který sloupec je jméno, datum… – podle názvu sloupce."""
    taken: set[str] = set()
    out: dict[str, str] = {}
    norm = {h: normalize(h) for h in sample.header if h}
    for fld, hints in IDENTITY_HINTS.items():
        # Křestní jméno a příjmení zvlášť → celé jméno se nehledá.
        if fld == "name_column" and out.get("first_name_column") and out.get("last_name_column"):
            continue
        best, best_rank = "", None
        for column, text in norm.items():
            if column in taken:
                continue
            for rank, hint in enumerate(hints):
                hit = text == hint or (fld in SUBSTRING_OK and len(hint) > 3 and hint in text)
                if hit and (best_rank is None or rank < best_rank):
                    best, best_rank = column, rank
        if best:
            out[fld] = best
            taken.add(best)
    if not (out.get("first_name_column") and out.get("last_name_column")):
        # Jen jedna z dvojice nedává smysl – „Jméno“ samotné je asi celé jméno.
        lone = out.pop("first_name_column", "") or out.pop("last_name_column", "")
        if lone and not out.get("name_column"):
            out["name_column"] = lone
        out.pop("first_name_column", None)
        out.pop("last_name_column", None)
    return out


# Slova z anglických exportů → slova z názvů metrik v katalogu.
SYNONYMS = {
    "fat": "tuk", "lean": "beztukova", "mass": "hmotnost", "weight": "hmotnost",
    "height": "vyska", "total": "celkova", "body": "telesna", "tissue": "",
    "arm": "paze", "arms": "paze", "leg": "noha", "legs": "noha", "trunk": "trup",
    "left": "", "right": "", "bone": "kostni", "bmd": "kostni hustota", "bmc": "kostni",
    "percent": "pct", "power": "vykon", "peak": "maximalni", "force": "sila",
    "time": "cas", "speed": "rychlost", "velocity": "rychlost", "jump": "vyskok",
    "torque": "moment", "heart": "srdecni", "rate": "frekvence", "hr": "srdecni frekvence",
}
SIDES = {"L": ("left", "leva", "levy", "lt", "l"), "R": ("right", "prava", "pravy", "rt", "r")}
SEGMENTS = {"paze": ("arm", "arms", "paze", "ruka"), "noha": ("leg", "legs", "noha", "nohy"),
            "trup": ("trunk", "trup")}
UNIT_RE = re.compile(r"[\[(]\s*([^\])]+?)\s*[\])]\s*$")
FACTORS = {("g", "kg"): 0.001, ("kg", "g"): 1000.0, ("ms", "s"): 0.001, ("s", "ms"): 1000.0,
           ("mm", "cm"): 0.1, ("cm", "mm"): 10.0, ("m", "cm"): 100.0, ("cm", "m"): 0.01}


def column_unit(column: str) -> str:
    match = UNIT_RE.search(column or "")
    return match.group(1).strip() if match else ("%" if "%" in (column or "") else "")


@dataclass
class ColumnSuggestion:
    metric: MetricDef | None = None
    side: str = ""
    segment: str = ""
    factor: float = 1.0
    why: str = ""


def _words(column: str) -> list[str]:
    return normalize(UNIT_RE.sub("", column)).split()


def _same_word(a: str, b: str) -> bool:
    """„tuk“ ~ „tuku“, „telesna“ ~ „telesneho“; „tuk“ ≁ „beztukova“."""
    short, long_ = sorted((a, b), key=len)
    if len(short) >= 3 and long_.startswith(short):
        return True
    prefix = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        prefix += 1
    return prefix >= 4


def _units_fit(column_unit: str, metric_unit: str) -> float:
    a, b = column_unit.lower(), (metric_unit or "").lower()
    if not a or not b:
        return 0.0
    return 0.2 if a == b or (a, b) in FACTORS else -0.5


def suggest_columns(header: list[str], protocol, metrics: list[MetricDef],
                    skip: set[str]) -> dict[str, ColumnSuggestion]:
    """
    Návrh metriky pro každý sloupec. Nejdřív to, co už je někde přiřazené
    (stejný název sloupce u jiného přístroje), pak shoda slov a jednotek.
    """
    known = {c.column: c for c in ImportColumn.objects.select_related("metric")}
    in_protocol = set(protocol.protocol_metrics.values_list("metric_id", flat=True))
    names = {m.pk: normalize(m.name).split() for m in metrics}
    qualifier_words = {w for hints in (*SIDES.values(), *SEGMENTS.values()) for w in hints}
    out = {}
    for column in header:
        if not column or column in skip:
            continue
        words = _words(column)
        unit = column_unit(column)
        suggestion = ColumnSuggestion()
        suggestion.side = next((s for s, hints in SIDES.items() if set(hints) & set(words)), "")
        suggestion.segment = next((s for s, hints in SEGMENTS.items()
                                   if set(hints) & set(words)), "")
        if column in known:
            suggestion.metric = known[column].metric
            suggestion.factor = known[column].factor
            suggestion.why = "stejný sloupec už má jiný přístroj"
            out[column] = suggestion
            continue

        tokens = [t for w in words if w not in qualifier_words
                  for t in SYNONYMS.get(w, w).split()]
        if unit == "%":
            tokens.append("podil")
        best, best_score = None, 0.0
        for metric in metrics if tokens else ():
            metric_words = names[metric.pk]
            hits_col = sum(1 for t in tokens if any(_same_word(t, m) for m in metric_words))
            if not hits_col:
                continue
            hits_metric = sum(1 for m in metric_words if any(_same_word(t, m) for t in tokens))
            score = 0.5 * hits_col / len(tokens) + 0.5 * hits_metric / len(metric_words)
            score += _units_fit(unit, metric.unit)
            if metric.pk in in_protocol:
                score += 0.1
            is_segment = metric.code.startswith("segment_")
            if suggestion.segment:
                score += 0.25 if is_segment else -0.25
            elif is_segment:
                score -= 0.25
            if score > best_score:
                best, best_score = metric, score
        if best is not None and best_score >= 0.8:
            suggestion.metric = best
            suggestion.why = "podle názvu"
            suggestion.factor = FACTORS.get((unit.lower(), best.unit.lower()), 1.0)
        out[column] = suggestion
    return out


def metric_choices(protocol, organization) -> tuple[list[MetricDef], list[MetricDef]]:
    """Metriky testu (nabízí se nahoře) a všechny ostatní."""
    metrics = list(MetricDef.objects.filter(is_active=True).filter(
        Q(organization=organization) | Q(organization__isnull=True)).order_by("name"))
    own = set(protocol.protocol_metrics.values_list("metric_id", flat=True))
    return [m for m in metrics if m.pk in own], [m for m in metrics if m.pk not in own]


# --- uložení ----------------------------------------------------------------------------

def unique_code(model, base: str, *, max_length=40, sep="-") -> str:
    base = (slugify(base) or "pristroj")[:max_length - 4].strip("-").replace("-", sep)
    code, n = base, 2
    while model.objects.filter(code=code).exists():
        code = f"{base}{sep}{n}"
        n += 1
    return code


def create_device(*, name: str, protocol, organization, sample: Sample) -> DeviceFormat:
    device = DeviceFormat.objects.create(
        organization=organization, name=name.strip(),
        code=unique_code(DeviceFormat, name), protocol=protocol,
        header_row=sample.header_row, columns_seen=sample.header,
        **suggest_identity(sample))
    return device


def update_sample(device: DeviceFormat, sample: Sample) -> list[str]:
    """Nový ukázkový soubor (výrobce změnil export). Vrací sloupce, které zmizely."""
    gone = [c for c in device.columns_seen if c and c not in sample.header]
    device.header_row = sample.header_row
    device.columns_seen = sample.header
    device.save(update_fields=["header_row", "columns_seen", "updated_at"])
    return gone


@dataclass
class Mapping:
    column: str
    metric: MetricDef | None = None
    new_name: str = ""
    new_unit: str = ""
    new_direction: str = Direction.NEUTRAL
    side: str = ""
    segment: str = ""
    factor: float = 1.0


@transaction.atomic
def save_device(device: DeviceFormat, *, identity: dict, mappings: list[Mapping],
                organization) -> dict:
    """
    Uloží, kde je jméno a datum, a přiřazení sloupců. Nové metriky založí
    a přidá k testu, aby se ve výsledcích a zprávě objevily. Nic nemaže –
    sloupec, který se přestal importovat, nechá dřív uložená data být.
    """
    for fld in DeviceFormat.IDENTITY_FIELDS:
        setattr(device, fld, identity.get(fld, ""))
    device.is_active = True
    device.save()

    profile, _ = ImportProfile.objects.update_or_create(
        organization=device.organization, device=device.adapter_code, test_type="",
        defaults={"protocol": device.protocol, "is_active": True})

    created_metrics = []
    keep = set()
    for item in mappings:
        metric = item.metric
        if metric is None and item.new_name:
            metric = MetricDef.objects.create(
                organization=organization, name=item.new_name.strip(),
                code=unique_code(MetricDef, item.new_name, max_length=64, sep="_"),
                family=device.protocol.family, unit=item.new_unit.strip(),
                direction=item.new_direction, decimals=2)
            created_metrics.append(metric)
        if metric is None:
            continue
        ImportColumn.objects.update_or_create(
            profile=profile, column=item.column,
            defaults={"metric": metric, "factor": item.factor or 1.0, "side": item.side,
                      "segment": item.segment.strip(), "with_sides": False})
        keep.add(item.column)
        _add_to_protocol(device.protocol, metric, item.side or "B", item.segment.strip())

    profile.columns.exclude(column__in=keep).delete()
    return {"sloupcu": len(keep), "novych_metrik": len(created_metrics)}


def _add_to_protocol(protocol, metric, side: str, segment: str):
    pm, created = ProtocolMetric.objects.get_or_create(
        protocol=protocol, metric=metric,
        defaults={"order": protocol.protocol_metrics.count() + 1, "sides": [side],
                  "segments": [segment] if segment else []})
    if created:
        return
    changed = False
    if side not in (pm.sides or []):
        pm.sides = [*(pm.sides or []), side]
        changed = True
    if segment and segment not in (pm.segments or []):
        pm.segments = [*(pm.segments or []), segment]
        changed = True
    if changed:
        pm.save(update_fields=["sides", "segments"])


def is_number(text) -> bool:
    return _number(text) is not None


def parse_factor(text) -> float:
    value = _number(text)
    return value if value not in (None, 0) else 1.0


# --- ukázka ------------------------------------------------------------------------------

DEMO_EXPORT = "demo/ukazkovy-export-dexa.csv"


def create_demo_device(organization):
    """
    Ukázkový přístroj DEXA pro veřejnou ukázku, kde se soubory nenahrávají –
    ať je průvodce vidět. Přiřazení je to, co by průvodce sám navrhl.
    """
    from pathlib import Path

    from django.conf import settings

    from apps.catalog.models import Protocol

    protocol = Protocol.objects.filter(code="bodycomp").first()
    if protocol is None or DeviceFormat.objects.filter(code="dexa").exists():
        return None
    with open(Path(settings.BASE_DIR) / DEMO_EXPORT, "rb") as handle:
        sample = read_sample(handle)
    device = create_device(name="DEXA", protocol=protocol, organization=organization,
                           sample=sample)
    metrics = [m for group in metric_choices(protocol, organization) for m in group]
    suggestions = suggest_columns(sample.header, protocol, metrics, skip=device.identity_columns)
    mappings = [Mapping(column=c, metric=s.metric, side=s.side, segment=s.segment,
                        factor=s.factor) for c, s in suggestions.items() if s.metric]
    identity = {f: getattr(device, f) for f in DeviceFormat.IDENTITY_FIELDS}
    save_device(device, identity=identity, mappings=mappings, organization=organization)
    return device
