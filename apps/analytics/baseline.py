"""
Výchozí měření sportovce.

Den, ke kterému se vztahují další měření: začátek studie, den před
soustředěním, první měření po návratu ze zranění. Změna proti němu se
posuzuje stejně jako změna proti minule – proti MDC ukazatele. Bez MDC se
o zlepšení ani zhoršení nemluví.

Hodnota výchozího měření je hodnota dne z hlavního provedení testu: když se
ten den měřilo víckrát (před a po zátěži), platí první měření – stejně jako
všude jinde v aplikaci.

Výchozí měření je vlastnost sportovce, ne skupiny: ve studii s víc bloky
má každý blok jiná data, a tak se pro skupinu nastavuje „první měřený den
od data“ – každý dostane svůj.
"""

from datetime import date

from django.db.models import Exists, OuterRef

from apps.measurements.models import Measurement, TestSession


def _measured(qs):
    """Jen testovací dny, kdy se v hlavním provedení něco naměřilo."""
    values = Measurement.objects.filter(trial__protocol_run__session=OuterRef("pk"),
                                        trial__protocol_run__is_primary=True)
    return qs.filter(Exists(values))


def measured_days(subject) -> list[date]:
    """Dny s hodnotami, od nejnovějšího – nabídka pro volbu výchozího měření."""
    return list(_measured(TestSession.objects.filter(subject=subject))
                .order_by("-date").values_list("date", flat=True))


def baseline_session(subject):
    """Testovací den výchozího měření, nebo None (nenastaveno, den smazán)."""
    if subject.baseline_date is None:
        return None
    return TestSession.objects.filter(subject=subject, date=subject.baseline_date).first()


def describe(subject, *, case: str = "1") -> str:
    """
    „výchozí měření 10. 7. 2026 (začátek studie)“; s ``case="3"`` ve třetím
    pádě („proti výchozímu měření …“). Bez výchozího měření prázdné.
    """
    if subject.baseline_date is None:
        return ""
    day = subject.baseline_date
    words = "výchozímu měření" if case == "3" else "výchozí měření"
    text = f"{words} {day.day}. {day.month}. {day.year}"
    return f"{text} ({subject.baseline_label})" if subject.baseline_label else text


def values_for(session) -> dict:
    """
    Hodnoty výchozího měření ke srovnání s testovacím dnem ``session`` – klíče
    stejné jako ``queries.session_metric_values``. Prázdné, když výchozí měření
    není nastavené, nebo není starší než tento den (den sám výchozí je).
    """
    from . import queries

    subject = session.subject
    if subject.baseline_date is None or subject.baseline_date >= session.date:
        return {}
    base = baseline_session(subject)
    if base is None:
        return {}
    values = queries.session_metric_values(base)
    for entry in values.values():
        entry["date"] = base.date
    return values


def set_baseline(subject, day, label: str = "") -> None:
    """Nastaví (nebo s ``day=None`` zruší) výchozí měření sportovce."""
    subject.baseline_date = day
    subject.baseline_label = (label or "").strip()[:80] if day else ""
    subject.save(update_fields=["baseline_date", "baseline_label", "updated_at"])


def set_for_group(subjects, since: date, label: str = "") -> dict:
    """
    Výchozí měření celé skupině: každému jeho první měřený testovací den
    od data ``since``. Kdo od toho dne nic naměřeného nemá, zůstane beze změny.
    """
    changed, unchanged, missing = [], [], []
    for subject in subjects:
        first = (_measured(TestSession.objects.filter(subject=subject, date__gte=since))
                 .order_by("date").values_list("date", flat=True).first())
        if first is None:
            missing.append(subject)
            continue
        label = (label or "").strip()[:80]
        if (subject.baseline_date, subject.baseline_label) == (first, label):
            unchanged.append(subject)
            continue
        set_baseline(subject, first, label)
        changed.append(subject)
    return {"changed": changed, "unchanged": unchanged, "missing": missing}


def clear_for_group(subjects) -> int:
    """Zruší výchozí měření celé skupině; vrátí, kolika sportovcům."""
    count = 0
    for subject in subjects:
        if subject.baseline_date is not None:
            set_baseline(subject, None)
            count += 1
    return count
