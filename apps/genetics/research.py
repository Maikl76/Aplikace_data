"""
Výzkumné použití genetiky: anonymizovaný export a vlastní frekvence genotypů.

Jen sportovci s platným souhlasem s výzkumem (sekundární použití,
anonymizovaně) a zároveň s genetickými daty. Export nenese kód ani jméno:
osoba má náhodně vypadající stálý identifikátor odvozený tajným klíčem
instance, věk je v pásmech, data měření jen po měsících, z dotazníku jdou
jen volby a čísla (žádný volný text). Pod pět osob se export nevydá –
s pár řádky by šel člověk poznat i bez jména.
"""

import csv
import hashlib
import io
import zipfile
from collections import Counter

from django.conf import settings
from django.utils import timezone

from apps.analytics import queries
from apps.catalog.models import Question
from apps.measurements import questionnaires
from apps.measurements.models import TestSession
from apps.subjects.models import Consent, Subject

from .models import GeneticSample, GeneVariant
from .seed import QUESTIONNAIRE_CODE

MIN_SUBJECTS = 5
AGE_BANDS = ((18, 24), (25, 34), (35, 44), (45, 54), (55, 64), (65, 200))


def research_id(subject) -> str:
    """Stálý identifikátor bez vazby na kód: hash čísla řádku a tajného klíče instance."""
    raw = f"{settings.SECRET_KEY}|vyzkum|{subject.pk}".encode()
    return hashlib.sha256(raw).hexdigest()[:12]


def age_band(age) -> str:
    if age is None:
        return ""
    for low, high in AGE_BANDS:
        if low <= age <= high:
            return f"{low}–{high}" if high < 200 else f"{low}+"
    return "do 17"


def _valid_consent(subject, scope) -> bool:
    return any(c.is_valid for c in subject.consents.all() if c.scope == scope)


def eligible_subjects(organization) -> list:
    """Sportovci s ověřeným vzorkem a platným souhlasem s výzkumem i genetikou."""
    rows = (Subject.objects.filter(organization=organization, genetic_samples__status=GeneticSample.Status.VERIFIED)
            .distinct().select_related("sport").prefetch_related("consents").order_by("pk"))
    return [s for s in rows if _valid_consent(s, Consent.Scope.RESEARCH)
            and _valid_consent(s, Consent.Scope.GENETICS)]


def latest_sample(subject):
    return (subject.genetic_samples.filter(status=GeneticSample.Status.VERIFIED)
            .prefetch_related("genotypes__variant").order_by("-reported_on", "-created_at").first())


def genotype_rows(subjects) -> list[dict]:
    rows = []
    for subject in subjects:
        sample = latest_sample(subject)
        if sample is None:
            continue
        rid = research_id(subject)
        for genotype in sample.genotypes.all():
            if not genotype.variant.is_active:
                continue
            rows.append({"id": rid, "gen": genotype.variant.gene, "rsid": genotype.variant.rsid,
                         "genotyp": genotype.value, "kvalita": genotype.quality})
    return rows


def subject_rows(subjects) -> list[dict]:
    return [{"id": research_id(s), "pohlavi": s.sex, "vek_pasmo": age_band(s.age),
             "sport": s.sport.name if s.sport_id else "", "uroven": s.level}
            for s in subjects]


def measurement_rows(subjects) -> list[dict]:
    rows = []
    for subject in subjects:
        rid = research_id(subject)
        for session in TestSession.objects.filter(subject=subject).order_by("date"):
            month = session.date.strftime("%Y-%m")
            if session.fatigue_rating:
                rows.append({"id": rid, "mesic": month, "ukazatel": "subjektivni_unava",
                             "upresneni": "", "hodnota": session.fatigue_rating, "jednotka": "1-10"})
            for entry in queries.session_metric_values(session).values():
                metric = entry["metric"]
                rows.append({"id": rid, "mesic": month, "ukazatel": metric.code,
                             "upresneni": _qualifiers(entry),
                             "hodnota": round(entry["value"], metric.decimals),
                             "jednotka": metric.unit})
    return rows


def _qualifiers(entry: dict) -> str:
    parts = [str(entry[k]) for k in ("side", "mode", "speed", "segment") if entry.get(k)]
    return " ".join(parts)


def questionnaire_rows(subjects) -> list[dict]:
    """Odpovědi dotazníku genetiky bez volného textu (ten může nést identifikaci)."""
    rows = []
    for subject in subjects:
        response = questionnaires.latest(subject, QUESTIONNAIRE_CODE)
        if response is None:
            continue
        rid = research_id(subject)
        for answer in response.answers.select_related("question"):
            question = answer.question
            if question.kind == Question.Kind.TEXT or answer.state == "missing":
                continue
            if answer.state != "answered":
                value = answer.state
            elif question.kind in (Question.Kind.CHOICE, Question.Kind.MULTI):
                value = "|".join(answer.choices or [])
            else:
                value = "" if answer.value is None else f"{answer.value:g}"
            rows.append({"id": rid, "otazka": question.code, "odpoved": value})
    return rows


README = """Anonymizovaný výzkumný export genetiky a měření – {org}, {date}

Zahrnuti jsou jen sportovci s platným souhlasem se sekundárním použitím pro výzkum
a se zpracováním genetických dat, s ověřeným výsledkem genotypizace. Počet osob: {n}.

Identifikátor „id“ je stálý hash bez vazby na kód sportovce; vazbu nelze obnovit bez
tajného klíče instance aplikace. Věk je v pásmech, měření jen po měsících, z dotazníku
jen volby a čísla (volný text se neexportuje).

sportovci.csv  id, pohlavi (F/M/X), vek_pasmo, sport, uroven (rec/trained/national/intl)
genotypy.csv   id, gen, rsid, genotyp (kanonický zápis), kvalita (ok/unclear/missing/failed)
mereni.csv     id, mesic (RRRR-MM), ukazatel (kód z katalogu), upresneni (strana, režim…),
               hodnota dne, jednotka; subjektivni_unava = únava v testovacím dni 1–10
dotaznik.csv   id, otazka (kód), odpoved (kód volby, více voleb odděleno |, číslo,
               nebo stav unknown = nevím / na = netýká se); nezodpovězené otázky chybí

Genotyp je dílčí informace; populační asociace neříkají, jak se varianta projeví
u konkrétní osoby. Data slouží výzkumu, ne hodnocení jednotlivce.
"""


def build_export(organization) -> tuple[bytes, int]:
    """ZIP se čtyřmi CSV a README. Vrací (obsah, počet osob); pod minimum vyhodí ValueError."""
    subjects = eligible_subjects(organization)
    if len(subjects) < MIN_SUBJECTS:
        raise ValueError(f"Export se vydá až od {MIN_SUBJECTS} sportovců s platným souhlasem "
                         f"s výzkumem i genetikou a ověřeným vzorkem (teď {len(subjects)}).")
    tables = {
        "sportovci.csv": subject_rows(subjects),
        "genotypy.csv": genotype_rows(subjects),
        "mereni.csv": measurement_rows(subjects),
        "dotaznik.csv": questionnaire_rows(subjects),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", README.format(
            org=organization.name, date=timezone.localdate().strftime("%d.%m.%Y"),
            n=len(subjects)))
        for name, rows in tables.items():
            archive.writestr(name, _csv(rows))
    return buffer.getvalue(), len(subjects)


def _csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]), delimiter=";", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def frequencies(organization) -> list[dict]:
    """
    Vlastní frekvence genotypů v populaci laboratoře – jen z osob se souhlasem
    s výzkumem, jen pro varianty s aspoň MIN_SUBJECTS výsledky. Frekvence
    není mírou výhodnosti genotypu.
    """
    subjects = eligible_subjects(organization)
    counts: dict[int, Counter] = {}
    for row in genotype_rows(subjects):
        if row["kvalita"] != "ok" or not row["genotyp"]:
            continue
        counts.setdefault(row["rsid"], Counter())[row["genotyp"]] += 1
    out = []
    for variant in GeneVariant.objects.filter(is_active=True).order_by("order", "gene"):
        counter = counts.get(variant.rsid, Counter())
        total = sum(counter.values())
        out.append({
            "variant": variant, "n": total, "enough": total >= MIN_SUBJECTS,
            "genotypes": [{"genotyp": variant.genotype_label(g), "pocet": counter.get(g, 0),
                           "procent": round(100 * counter.get(g, 0) / total) if total else 0}
                          for g in variant.genotypes],
        })
    return out
