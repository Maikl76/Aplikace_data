"""
Import studie TAČR PRODEF (pětidenní simulovaný operační stres) ze sešitu
pro spoluautory.

Data studie do repozitáře ani do veřejného zkušebního provozu nepatří:
sešit se načítá z místa, kde leží (počítač laboratoře), a zaheslovaný se
odšifruje heslem, které se nikam neukládá (proměnná prostředí XLSX_HESLO,
nebo dotaz při spuštění).

Co se načte:

* **probandi** (list Probandi) jako sportovci ``PRODEF-P07`` … – bez jmen,
  jen kód studie, rameno (Stres / Kontrola), blok a přibližný rok narození
  z věku; kdo nenastoupil (zarazen_do_analyzy = NE), se nenačte,
* **testovací dny** 1–5 a v nich **měřicí body** 1–4 jako provedení testů:
  první bod dne (ráno, před zátěží) je hlavní měření dne, další jsou
  opakování dne s pozicí „po zátěžovém bloku N“ – aplikace je porovná
  s prvním proti MDC,
* **pokusy VALD** ForceDecks (CMJ, IMTP, stoj na jedné noze) a HumanTrak
  (box lift) z listů VALD_* – sloupce exportu se na ukazatele převedou
  stejnými profily importu jako běžný export z VALD Hubu. Opravy ze sešitu
  (přeřazení profilu, přepočet vážení) se berou, jak jsou, a u hodnoty
  zůstane kód opravy; pokusy označené v sešitu k ruční kontrole mají
  kvalitu „podezřelá hodnota“ (hodnota se nemění, jako v sešitu),
* **prostředí** dne (teplota a vlhkost v posilovně),
* **ranní dotazník**: hodiny spánku (noční formulář), ospalost KSS,
  únava VAS 0–100 a svalová únava 1–5 do dotazníku „PRODEF – ranní
  připravenost“ s prahy signálu pro semafor připravenosti,
* **výchozí měření** = den 2 (pátek, ráno před první zátěží).

Nic dalšího ze sešitu – vstupní zdravotní dotazník (CIQ), léky, kofein,
strava, střelba, HRV, POMS, STAI – se do aplikace nenačítá.
"""

import io
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path

from django.db import transaction
from django.utils import timezone

CODE_PREFIX = "PRODEF-P"
SOURCE_PREFIX = "prodef:"
SPORT_CODE = "prodef"
SPORT_NAME = "PRODEF – simulovaný operační stres"
ARMS = ("Stres", "Kontrola")
BASELINE_DAY = 2
BASELINE_LABEL = "PRODEF: pátek před zátěží (den 2)"
QUESTIONNAIRE_CODE = "prodef_ranni"
QUESTIONNAIRE_NAME = "PRODEF – ranní připravenost (import)"
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
TRIAL_RE = re.compile(r"(?:(Left|Right)\s*\((\d+)\)|Trial\s*(\d+))", re.IGNORECASE)

# list sešitu → (adaptér, typ testu v exportu) – podle toho se najde profil importu
SHEETS = {
    "VALD_CMJ": ("vald_forcedecks", "Countermovement Jump"),
    "VALD_IMTP": ("vald_forcedecks", "Isometric Mid-Thigh Pull"),
    "VALD_SLS": ("vald_forcedecks", "Single Leg Stand"),
    "VALD_BoxLift": ("vald_humantrak", "Box Lift - Overhead"),
}
# sloupce s označením pokusu k ruční kontrole (hodnota v sešitu zůstává)
CHECK_COLUMNS = ("CMJ_kontrola", "IMTP_kontrola_kategorie", "SLS_kontrola_kategorie")
HUMANTRAK_CONDITIONS = {"Reps": "opakovani", "Box Weight[kg]": "zatez_kg"}

# Ranní dotazník: (kód, znění, druh, jednotka, od, do, kotvy, signál, zdroj, převod)
# zdroj = (nástroj, položka nebo None = jediná položka nástroje, časový bod dne)
KSS_ANCHORS = {"1": "velmi bdělý", "3": "bdělý", "5": "ani bdělý, ani ospalý",
               "7": "ospalý, bez potíží zůstat vzhůru", "9": "velmi ospalý, bojuje se spánkem"}
QUESTIONS = [
    ("spanek_h", "Hodiny spánku tuto noc (noční formulář)", "number", "h", 0, 24, {},
     ("<", 6, "málo spánku"), ("Noční formulář", None, 1)),
    ("kss", "Ospalost ráno – Karolinská škála (KSS 1–9)", "scale", "", 1, 9, KSS_ANCHORS,
     (">=", 7, "ospalost"), ("KSS", None, 1)),
    ("vas_unava", "Únava ráno – VAS 0–100", "number", "", 0, 100, {},
     (">=", 60, "únava"), ("VAS (0–100)", "unava", 1)),
    ("svalova", "Svalová únava ráno (ranní dotazník 1–5)", "scale", "", 1, 5,
     {"1": "žádná", "5": "velmi velká"},
     (">=", 4, "svalová únava"), ("Ranní dotazník (1–5)", "jak_velkou_svalovou", 1)),
]


class ProdefError(Exception):
    """Sešit nejde načíst – zpráva je pro člověka."""


# --- čtení sešitu -------------------------------------------------------------------------

def is_encrypted(data: bytes) -> bool:
    return data[:8] == OLE_MAGIC


def open_workbook(path, *, password: str | None = None):
    """Otevře sešit (zaheslovaný odšifruje v paměti – na disk se nic nezapíše)."""
    import openpyxl

    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise ProdefError(f"Soubor nejde přečíst: {exc}") from exc
    if is_encrypted(data):
        if not password:
            raise ProdefError("Sešit je zaheslovaný. Zadejte heslo (proměnná prostředí "
                              "XLSX_HESLO, nebo se na něj příkaz zeptá), nebo sešit v Excelu "
                              "uložte bez hesla.")
        try:
            import msoffcrypto
        except ImportError as exc:
            raise ProdefError("Na odšifrování chybí balíček msoffcrypto-tool "
                              "(pip install msoffcrypto-tool) – nebo sešit v Excelu uložte "
                              "bez hesla.") from exc
        try:
            office = msoffcrypto.OfficeFile(io.BytesIO(data))
            office.load_key(password=password)
            plain = io.BytesIO()
            office.decrypt(plain)
        except Exception as exc:   # špatné heslo i poškozený soubor
            raise ProdefError("Sešit nejde odšifrovat – heslo nesedí?") from exc
        data = plain.getvalue()
    if data[:2] != b"PK":
        raise ProdefError("Tohle není sešit Excelu (.xlsx).")
    try:
        return openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise ProdefError(f"Sešit nejde otevřít: {exc}") from exc


def sheet_rows(workbook, name: str, *, first: str = "pid") -> list[dict] | None:
    """Řádky listu jako slovníky podle hlavičky (řádek začínající ``first``); bez listu None."""
    if name not in workbook.sheetnames:
        return None
    header, out = None, []
    for i, row in enumerate(workbook[name].iter_rows(values_only=True)):
        if header is None:
            if row and _text(row[0]) == first:
                header = [_text(c) for c in row]
            elif i > 10:
                raise ProdefError(f"List {name}: hlavička se sloupcem „{first}“ není v prvních "
                                  "deseti řádcích.")
            continue
        if not row or row[0] is None or _text(row[0]) == "":
            continue
        out.append({h: v for h, v in zip(header, row, strict=False) if h})
    return out


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _int(value) -> int | None:
    try:
        return int(float(str(value).strip().replace(",", ".")))
    except (TypeError, ValueError):
        return None


def _number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".").replace("−", "-")
    try:
        return float(text) if text else None
    except ValueError:
        return None


def _date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)[:10]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _time(value) -> time | None:
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, time):
        return value
    match = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?", _text(value))
    if not match:
        return None
    return time(int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))


def _side_variant(column: str, side: str) -> str:
    """„Concentric Peak Force [N]“ → „Concentric Peak Force (Left) [N]“ (jako u exportu VALD)."""
    if " [" in column:
        name, unit = column.split(" [", 1)
        return f"{name} ({side}) [{unit}"
    return f"{column} ({side})"


# --- plán importu -------------------------------------------------------------------------

@dataclass
class Proband:
    pid: int
    arm: str
    block: int | None
    block_term: str
    age: int | None


@dataclass
class TrialRow:
    pid: int
    day: int | None
    date: date
    moment: time | None
    point: int
    protocol: str
    number: int
    values: list            # [(kód ukazatele, strana, hodnota)]
    note: str = ""          # kód opravy ze sešitu
    check: str = ""         # označení k ruční kontrole
    conditions: dict = field(default_factory=dict)


@dataclass
class Plan:
    probands: dict = field(default_factory=dict)        # pid → Proband
    excluded: list = field(default_factory=list)        # pid, kdo nenastoupil
    no_data: list = field(default_factory=list)         # pid, kdo nemá v sešitu žádné měření
    trials: list = field(default_factory=list)
    positions: dict = field(default_factory=dict)       # (pid, den, bod) → pozice
    day_names: dict = field(default_factory=dict)       # (pid, datum) → (den, název dne)
    environment: dict = field(default_factory=dict)     # datum → (teplota, vlhkost)
    answers: dict = field(default_factory=dict)         # (pid, datum) → {kód otázky: hodnota}
    protocols: dict = field(default_factory=dict)       # kód protokolu → Protocol z profilu
    notes: list = field(default_factory=list)
    skipped: int = 0

    def runs(self) -> dict:
        """Řádky pokusů po provedeních testu: (pid, datum, protokol, měřicí bod) → řádky."""
        groups = defaultdict(list)
        for t in self.trials:
            groups[(t.pid, t.date, t.protocol, t.point)].append(t)
        return groups

    def summary(self) -> dict:
        days = {(t.pid, t.date) for t in self.trials}
        runs = self.runs()
        per_arm = defaultdict(int)
        for proband in self.probands.values():
            per_arm[proband.arm] += 1
        return {
            "probandu": len(self.probands), "ramena": dict(per_arm),
            "nenastoupili": len(self.excluded),
            "bez_mereni": [subject_code(pid) for pid in self.no_data],
            "testovacich_dnu": len(days),
            # pokusy stejně jako při zápisu (levá a pravá strana s jedním číslem = jeden pokus)
            "provedeni": len(runs),
            "pokusu": sum(len(_place_trials(rows)[0]) for rows in runs.values()),
            "hodnot": sum(len(t.values) for t in self.trials),
            "dotazniku": len([k for k in self.answers if k in days]),
            "preskoceno_radku": self.skipped,
        }


def _place_trials(rows) -> tuple[list[int], list]:
    """
    Čísla pokusů jednoho provedení testu ze sešitu. U stoje na jedné noze má levá
    i pravá „(1)“ a patří do téhož pokusu; kdyby se hodnota (ukazatel a strana)
    v pokusu opakovala, dostane řádek další číslo. Vrátí čísla pokusů a dvojice
    (číslo, řádek).
    """
    used = defaultdict(set)     # číslo pokusu → {(ukazatel, strana)}
    placed = []
    for row in sorted(rows, key=lambda r: (r.number, r.moment or time())):
        number = row.number
        while any((code, side) in used[number] for code, side, _ in row.values):
            number += 1
        for code, side, _ in row.values:
            used[number].add((code, side))
        placed.append((number, row))
    return sorted(used), placed


def _profile(adapter: str, test_type: str, organization=None):
    """Profil importu pro typ testu; vlastní profil pracoviště má přednost před sdíleným."""
    from django.db.models import Q

    from apps.catalog.models import ImportProfile

    scope = Q(organization__isnull=True)
    if organization is not None:
        scope |= Q(organization=organization)
    profiles = list(ImportProfile.objects.filter(scope, device=adapter, test_type=test_type,
                                                 is_active=True)
                    .select_related("protocol").prefetch_related("columns__metric"))
    profiles.sort(key=lambda p: p.organization_id is None)
    return profiles[0] if profiles else None


def read_plan(workbook, organization=None) -> Plan:
    """Projde sešit a sestaví, co se má do aplikace zapsat. Do databáze nezapisuje."""
    plan = Plan()
    probands = sheet_rows(workbook, "Probandi")
    if probands is None:
        raise ProdefError("V sešitu chybí list Probandi – je to sešit PRODEF pro spoluautory?")
    for row in probands:
        pid = _int(row.get("pid"))
        arm = _text(row.get("skupina"))
        if pid is None or arm not in ARMS:
            plan.skipped += 1
            continue
        if _text(row.get("zarazen_do_analyzy")).upper() == "NE":
            plan.excluded.append(pid)
            continue
        plan.probands[pid] = Proband(pid=pid, arm=arm, block=_int(row.get("blok")),
                                     block_term=_text(row.get("blok_termin")),
                                     age=_int(row.get("vek_let")))

    for row in sheet_rows(workbook, "MASTER") or []:
        key = (_int(row.get("pid")), _int(row.get("den")), _int(row.get("mericí_bod")))
        if None not in key and (position := _text(row.get("pozice"))):
            plan.positions[key] = position

    found = False
    for sheet, (adapter, test_type) in SHEETS.items():
        rows = sheet_rows(workbook, sheet)
        if rows is None:
            plan.notes.append(f"List {sheet} v sešitu není – tento test se nenačte.")
            continue
        profile = _profile(adapter, test_type, organization)
        if profile is None:
            plan.notes.append(f"Typ testu „{test_type}“ nemá v katalogu profil importu – "
                              f"list {sheet} se nenačte (Nastavení → Import).")
            continue
        found = True
        plan.protocols[profile.protocol.code] = profile.protocol
        _read_trials(plan, rows, sheet=sheet, protocol=profile.protocol.code,
                     columns=list(profile.columns.all()),
                     humantrak=adapter == "vald_humantrak")
    if not found:
        raise ProdefError("V sešitu nejsou listy VALD_CMJ / VALD_IMTP s pokusy.")
    # Proband bez jediného pokusu by byl v týmech prázdný řádek bez testovacích dnů
    # (dotazníky se načítají jen ke dnům s měřením) – nenačte se, souhrn ho jmenuje.
    measured = {t.pid for t in plan.trials}
    plan.no_data = sorted(pid for pid in plan.probands if pid not in measured)
    for pid in plan.no_data:
        del plan.probands[pid]

    _read_environment(plan, sheet_rows(workbook, "Prostředí", first="blok") or [])
    _read_answers(plan, sheet_rows(workbook, "Dotazníky_skóry") or [])
    return plan


def _read_trials(plan, rows, *, sheet, protocol, columns, humantrak):
    counters = defaultdict(int)     # HumanTrak: řádek = celý test, pokusy se číslují
    for row in rows:
        pid = _int(row.get("pid"))
        day_date = _date(row.get("datum"))
        point = _int(row.get("mericí_bod"))
        if pid not in plan.probands or day_date is None or point is None:
            plan.skipped += 1
            continue
        side, number = "", 1
        if humantrak:
            counters[(pid, day_date, point)] += 1
            number = counters[(pid, day_date, point)]
        elif match := TRIAL_RE.search(_text(row.get("Trial"))):
            if match.group(1):
                side = "L" if match.group(1).lower() == "left" else "R"
                number = int(match.group(2))
            else:
                number = int(match.group(3))
        values = []
        for column in columns:
            if side:
                variants = [(column.column, side)]
            elif column.with_sides and not humantrak:
                variants = [(column.column, "B"), (_side_variant(column.column, "Left"), "L"),
                            (_side_variant(column.column, "Right"), "R")]
            else:
                variants = [(column.column, "B")]
            for source, variant_side in variants:
                value = _number(row.get(source))
                if value is not None:
                    values.append((column.metric.code, variant_side, value * column.factor))
        if not values:
            plan.skipped += 1
            continue
        check = next((_text(row.get(c)) for c in CHECK_COLUMNS if _text(row.get(c))), "")
        conditions = {}
        if humantrak:
            for source, key in HUMANTRAK_CONDITIONS.items():
                if (value := _number(row.get(source))) is not None:
                    conditions[key] = value
        day = _int(row.get("den"))
        plan.trials.append(TrialRow(
            pid=pid, day=day, date=day_date, moment=_time(row.get("cas")), point=point,
            protocol=protocol, number=number, values=values,
            note=_text(row.get("kod_opravy")), check=check, conditions=conditions))
        if day is not None and (name := _text(row.get("den_nazev"))):
            plan.day_names[(pid, day_date)] = (day, name)
        elif day is not None:
            plan.day_names.setdefault((pid, day_date), (day, f"Den {day}"))


def _read_environment(plan, rows):
    """Teplota a vlhkost dne; přednost má posilovna, kde se měřilo VALD."""
    best = {}
    for row in rows:
        day_date = _date(row.get("datum"))
        temperature = _number(row.get("teplota_C"))
        humidity = _number(row.get("vlhkost_pct"))
        if day_date is None or (temperature is None and humidity is None):
            continue
        rank = 0 if _text(row.get("misto")).lower().startswith("posilovn") else 1
        if day_date not in best or rank < best[day_date][0]:
            best[day_date] = (rank, temperature, humidity)
    plan.environment = {d: (t, h) for d, (_, t, h) in best.items()}


def _read_answers(plan, rows):
    sources = {}
    for code, *_, source in QUESTIONS:
        sources[(source[0], source[1], source[2])] = code
    for row in rows:
        pid = _int(row.get("pid"))
        day_date = _date(row.get("datum"))
        if pid not in plan.probands or day_date is None:
            continue
        instrument, item = _text(row.get("nastroj")), _text(row.get("polozka"))
        point = _int(row.get("casovy_bod"))
        code = sources.get((instrument, item, point)) or sources.get((instrument, None, point))
        value = _number(row.get("hodnota"))
        if code is None or value is None:
            continue
        plan.answers.setdefault((pid, day_date), {})[code] = value


# --- zápis do aplikace --------------------------------------------------------------------

def subject_code(pid: int) -> str:
    return f"{CODE_PREFIX}{pid:02d}"


def _questionnaire(organization):
    """Dotazník „PRODEF – ranní připravenost“ pracoviště; neaktivní – v testovacím dni se nenabízí."""
    from apps.catalog.models import Question, Questionnaire

    questionnaire, _ = Questionnaire.objects.get_or_create(
        organization=organization, code=QUESTIONNAIRE_CODE,
        defaults={"name": QUESTIONNAIRE_NAME, "is_active": False,
                  "description": "Načteno ze sešitu studie PRODEF – ranní odpovědi probandů. "
                                 "Prahy signálu odpovídají analýze studie."})
    questions = {}
    for order, (code, text, kind, unit, low, high, anchors, signal, _source) in enumerate(QUESTIONS):
        op, threshold, label = signal
        question, _ = Question.objects.get_or_create(
            questionnaire=questionnaire, code=code,
            defaults={"text": text, "order": order, "kind": kind, "unit": unit,
                      "scale_min": low if kind == "scale" else 0,
                      "scale_max": high if kind == "scale" else 10, "anchors": anchors,
                      "required": False, "signal_op": op, "signal_value": threshold,
                      "signal_label": label})
        questions[code] = question
    return questionnaire, questions


def _setup(organization, protocols):
    """Sport, ramena studie jako týmy a baterie testů pro týmový přehled."""
    from apps.catalog.models import BatteryItem, TestBattery
    from apps.subjects.models import Sport, Team

    sport, _ = Sport.objects.get_or_create(organization=organization, code=SPORT_CODE,
                                           defaults={"name": SPORT_NAME})
    teams, batteries = {}, {}
    order = ["cmj", "imtp", "sls", "box_lift"]
    used = sorted(protocols.items(),
                  key=lambda kv: (order.index(kv[0]) if kv[0] in order else 99, kv[0]))
    for arm in ARMS:
        teams[arm], _ = Team.objects.get_or_create(organization=organization, sport=sport,
                                                   name=f"PRODEF {arm}")
        battery, _ = TestBattery.objects.get_or_create(
            organization=organization, sport=sport, category=arm,
            defaults={"name": f"PRODEF {arm}",
                      "note": "Baterie studie PRODEF (import ze sešitu)."})
        for position, (_code, protocol) in enumerate(used, start=1):
            BatteryItem.objects.get_or_create(battery=battery, protocol=protocol,
                                              defaults={"order": position})
        batteries[arm] = battery
    return sport, teams, batteries


def _subject(organization, proband, *, sport, team, first_date):
    from apps.subjects.models import Subject

    note = (f"Studie PRODEF, rameno {proband.arm}, blok {proband.block or '?'}"
            + (f" ({proband.block_term})" if proband.block_term else "")
            + ". Načteno ze sešitu pro spoluautory.")
    birth_year = first_date.year - proband.age if proband.age and first_date else None
    subject, created = Subject.objects.get_or_create(
        organization=organization, code=subject_code(proband.pid),
        defaults={"sport": sport, "team": team, "category": proband.arm,
                  "birth_year": birth_year, "note": note,
                  "source_key": f"{SOURCE_PREFIX}{proband.pid}"})
    if not created:
        changed = {"sport": sport, "team": team, "category": proband.arm, "note": note,
                   "source_key": f"{SOURCE_PREFIX}{proband.pid}"}
        if birth_year:
            changed["birth_year"] = birth_year
        for name, value in changed.items():
            setattr(subject, name, value)
        subject.save()
    return subject, created


def apply_plan(plan: Plan, organization) -> dict:
    """
    Zapíše plán do aplikace. Opakovaný import nic nezdvojí: sportovec se
    pozná podle kódu, provedení testu podle odkazu do sešitu a jeho pokusy
    se nahradí aktuálními hodnotami ze sešitu.
    """
    from apps.analytics import baseline
    from apps.catalog.models import MetricDef
    from apps.measurements import questionnaires
    from apps.measurements.models import (
        Measurement,
        ProtocolRun,
        QuestionnaireResponse,
        TestSession,
        Trial,
    )

    counts = defaultdict(int)
    with transaction.atomic():
        sport, teams, _batteries = _setup(organization, plan.protocols)
        questionnaire, questions = _questionnaire(organization)
        metrics = {}
        for t in plan.trials:
            for code, _, _ in t.values:
                metrics[code] = None
        for metric in MetricDef.objects.filter(code__in=list(metrics)).order_by("organization_id"):
            # sdílený katalog, vlastní ukazatel pracoviště téhož kódu má přednost
            if metrics.get(metric.code) is None or metric.organization_id == organization.pk:
                metrics[metric.code] = metric

        first_dates = defaultdict(lambda: None)
        for t in plan.trials:
            if first_dates[t.pid] is None or t.date < first_dates[t.pid]:
                first_dates[t.pid] = t.date
        subjects = {}
        for pid, proband in sorted(plan.probands.items()):
            subject, created = _subject(organization, proband, sport=sport,
                                        team=teams[proband.arm], first_date=first_dates[pid])
            subjects[pid] = subject
            counts["novych_sportovcu" if created else "aktualizovanych_sportovcu"] += 1

        # testovací dny – jen dny s měřením; dotazník ze dne bez měření (čtvrtek
        # nástupu) by založil prázdný den, který by se tvářil jako naplánovaný
        sessions = {}
        day_keys = {(t.pid, t.date) for t in plan.trials}
        for pid, day_date in sorted(day_keys):
            subject = subjects[pid]
            day, name = plan.day_names.get((pid, day_date), (None, ""))
            session, created = TestSession.objects.get_or_create(
                organization=organization, subject=subject, date=day_date,
                defaults={"location": f"PRODEF, {name}"[:120] if name else "PRODEF"})
            counts["novych_dnu" if created else "existujicich_dnu"] += 1
            temperature, humidity = plan.environment.get(day_date, (None, None))
            if (temperature, humidity) != (None, None) and (
                    session.temperature_c, session.humidity_pct) != (temperature, humidity):
                session.temperature_c, session.humidity_pct = temperature, humidity
                session.save(update_fields=["temperature_c", "humidity_pct", "updated_at"])
            sessions[(pid, day_date)] = session

        # provedení testů: první bod dne je hlavní měření dne
        groups = plan.runs()
        first_point = defaultdict(lambda: 99)
        for pid, day_date, protocol, point in groups:
            key = (pid, day_date, protocol)
            first_point[key] = min(first_point[key], point)
        wanted_refs = set()
        for (pid, day_date, protocol, point), rows in sorted(groups.items()):
            session = sessions[(pid, day_date)]
            ref = f"{SOURCE_PREFIX}{pid}:{day_date.isoformat()}:{protocol}:{point}"
            wanted_refs.add(ref)
            moments = sorted(r.moment for r in rows if r.moment)
            started = (timezone.make_aware(datetime.combine(day_date, moments[0]))
                       if moments else None)
            day = rows[0].day
            conditions = dict(rows[0].conditions)
            position = plan.positions.get((pid, day, point))
            conditions["pozice"] = position or f"měřicí bod {point}"
            run, created = ProtocolRun.objects.get_or_create(
                session=session, external_ref=ref,
                defaults={"protocol": plan.protocols[protocol], "started_at": started,
                          "is_primary": point == first_point[(pid, day_date, protocol)],
                          "conditions": conditions})
            if not created:
                run.started_at = started
                run.is_primary = point == first_point[(pid, day_date, protocol)]
                run.conditions = conditions
                run.save(update_fields=["started_at", "is_primary", "conditions", "updated_at"])
                run.trials.all().delete()
            counts["provedeni"] += 1
            numbers, placed = _place_trials(rows)
            trials = {t.number: t for t in Trial.objects.bulk_create(
                [Trial(protocol_run=run, number=n) for n in numbers])}
            counts["pokusu"] += len(trials)
            items = []
            for number, row in placed:
                note = f"oprava v sešitu: {row.note}" if row.note else ""
                check = f"k ruční kontrole: {row.check}" if row.check else ""
                for code, side, value in row.values:
                    metric = metrics.get(code)
                    if metric is None:
                        continue
                    items.append(Measurement(
                        trial=trials[number], metric=metric, side=side, value=value,
                        quality=(Measurement.Quality.SUSPECT if row.check
                                 else Measurement.Quality.OK),
                        note="; ".join(x for x in (note, check) if x)[:255]))
            Measurement.objects.bulk_create(items)
            counts["hodnot"] += len(items)
        # provedení z dřívějšího importu, která už v sešitu nejsou
        stale = ProtocolRun.objects.filter(session__subject__in=subjects.values(),
                                           external_ref__startswith=SOURCE_PREFIX).exclude(
            external_ref__in=wanted_refs)
        counts["odebranych_provedeni"] = stale.count()
        stale.delete()

        # ranní dotazník
        for (pid, day_date), values in sorted(plan.answers.items()):
            session = sessions.get((pid, day_date))
            if session is None:
                counts["dotazniku_bez_mereni"] += 1
                continue
            questionnaires.save(session, questionnaire,
                                {questions[c]: v for c, v in values.items() if c in questions},
                                source=QuestionnaireResponse.Source.SUBJECT)
            counts["dotazniku"] += 1

        # výchozí měření: pátek (den 2) – ruční změnu u sportovce import nepřepíše
        for pid, subject in subjects.items():
            days = {d for (p, d), (day, _) in plan.day_names.items() if p == pid and day == BASELINE_DAY}
            measured = set(baseline.measured_days(subject))
            target = next((d for d in sorted(days) if d in measured), None)
            if target is None and measured:
                target = min(measured)
            if target is None:
                continue
            if subject.baseline_date is None or subject.baseline_label.startswith("PRODEF"):
                label = BASELINE_LABEL if target in days else "PRODEF: první měřený den"
                if (subject.baseline_date, subject.baseline_label) != (target, label):
                    baseline.set_baseline(subject, target, label)
                    counts["vychozich_mereni"] += 1
    return dict(counts)


def imported_subjects(organization):
    from apps.subjects.models import Subject

    return Subject.objects.filter(organization=organization, code__startswith=CODE_PREFIX,
                                  source_key__startswith=SOURCE_PREFIX)


def delete_imported(organization) -> dict:
    """
    Smaže všechno, co import PRODEF založil: probandy s jejich testovacími
    dny, hodnotami, dotazníky, nálezy a zprávami, a potom sport, týmy,
    baterie a dotazník studie, když je už nic jiného nepoužívá.
    """
    from apps.catalog.models import Questionnaire, TestBattery
    from apps.measurements.models import TestSession
    from apps.reports.models import Report, ReportDelivery
    from apps.subjects.models import Sport, Subject, Team

    subjects = list(imported_subjects(organization))
    counts = {"sportovcu": len(subjects)}
    with transaction.atomic():
        reports = Report.objects.filter(subject__in=subjects)
        ReportDelivery.objects.filter(report__in=reports).delete()
        counts["zprav"] = reports.count()
        reports.delete()
        sessions = TestSession.objects.filter(subject__in=subjects)
        counts["testovacich_dnu"] = sessions.count()
        sessions.delete()
        Subject.objects.filter(pk__in=[s.pk for s in subjects]).delete()
        sport = Sport.objects.filter(organization=organization, code=SPORT_CODE).first()
        if sport is not None and not sport.subjects.exists():
            TestBattery.objects.filter(organization=organization, sport=sport).delete()
            Team.objects.filter(organization=organization, sport=sport).delete()
            sport.delete()
            counts["sport"] = 1
        questionnaire = Questionnaire.objects.filter(organization=organization,
                                                     code=QUESTIONNAIRE_CODE).first()
        if questionnaire is not None and not questionnaire.responses.exists():
            questionnaire.delete()
            counts["dotaznik"] = 1
    return counts


def imtp_rule_note(organization=None) -> str:
    """
    Upozornění, když se vrcholová síla IMTP v aplikaci počítá z pokusů jinak než
    v sešitu (list MASTER bere nejlepší pokus, katalog průměr). Prázdné, když už
    je nastavený nejlepší pokus.
    """
    from django.db.models import Q

    from apps.catalog.models import MetricDef

    scope = Q(organization__isnull=True)
    if organization is not None:
        scope |= Q(organization=organization)
    rules = set(MetricDef.objects.filter(scope, code="imtp_peak_force")
                .values_list("trial_rule", flat=True))
    if not rules or rules == {MetricDef.TrialRule.BEST}:
        return ""
    return ("Pozor: v sešitu (list MASTER) je u vrcholové síly IMTP nejlepší pokus, v aplikaci "
            "průměr pokusů. Pro stejné hodnoty jako MASTER: Administrace → Metriky → Vrcholová "
            "síla (IMTP) → Hodnota dne z pokusů: Nejlepší pokus. Platí pro všechny sportovce "
            "pracoviště a hned i zpětně (hodnota dne se z pokusů počítá při zobrazení).")


# --- MDC z kontrolní skupiny ----------------------------------------------------------------

KEY_METRICS = ("cmj_height", "imtp_peak_force", "sls_cop_area")


def control_mdc(organization, *, save: bool = False, max_gap: int = 1) -> list[dict]:
    """
    TE a MDC90 klíčových ukazatelů z kontrolního ramene (měření den po dni).
    S ``save`` je uloží k ukazatelům i se zdrojem – stejně jako „spočítat
    z dat“ v Nastavení → MDC.
    """
    from apps.analytics import reliability
    from apps.catalog.models import MetricDef

    control = imported_subjects(organization).filter(category="Kontrola")
    dates = list(control.values_list("sessions__date", flat=True))
    dates = [d for d in dates if d]
    if not dates:
        return []
    out = []
    for code in KEY_METRICS:
        metric = MetricDef.objects.filter(code=code, organization__isnull=True).first()
        if metric is None:
            continue
        results = [r for r in reliability.estimate(metric, control, min(dates), max(dates),
                                                   max_gap=max_gap) if r["ok"]]
        if not results:
            continue
        result = results[0]
        item = {"metric": metric, "result": result, "saved": False,
                "puvodne": {"te": metric.typical_error, "mdc": metric.mdc}}
        if save:
            d = metric.decimals + 1
            metric.typical_error = round(result["te"], d)
            metric.mdc = round(result["mdc90"], d)
            metric.mdc_source = reliability.source_text(
                result, level=90, group="PRODEF, kontrolní skupina", date_from=min(dates),
                date_to=max(dates), metric=metric)
            metric.save(update_fields=["typical_error", "mdc", "mdc_source", "updated_at"])
            item["saved"] = True
        out.append(item)
    return out
