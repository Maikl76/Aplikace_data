"""
Semafor připravenosti.

Jednoduché „jak je na tom dnes“ z toho, co se ten den změřilo a vyplnilo:

* **subjektivní signály** – odpovědi dotazníků dne za prahem nastaveným
  u otázky (ranní dotazník: spánek pod 6 h, ospalost KSS 7 a víc, únava,
  bolest svalů; práh je v Nastavení → Dotazníky u otázky),
* **výkonové signály** – klíčový ukazatel testu se proti výchozímu měření
  (když ho sportovec nemá, proti minulému) zhoršil víc, než je MDC. Ukazatele
  bez žádoucího směru (hmotnost) se neberou – o připravenosti nic neříkají.

Počet signálů dá barvu: 0–1 zelená, 2–3 oranžová, 4 a víc červená. Ukazatel
bez MDC nebo bez žádoucího směru a otázka bez odpovědi se nepočítají – nedá
se o nich nic říct, a proto se ani nevydávají za „v pořádku“. Semafor
nehodnotí jedno číslo, ale shodu víc nezávislých signálů: jeden signál je
běžný šum dne, čtyři najednou už ne.

Je to pomůcka pro rozhodnutí trenéra, ne diagnóza. Prahy barev jsou
vyzkoušené na pilotních datech pětidenní zátěže (stresová skupina proti
kontrolní); jiné prostředí je může potřebovat jinak.
"""

from collections import defaultdict

from apps.catalog.models import Direction

GREEN_MAX = 1   # 0–1 signál
AMBER_MAX = 3   # 2–3 signály, 4 a víc = červená
# Semafor se ukáže, až když se dá posoudit aspoň tolik ukazatelů, kolik je
# potřeba na červenou – z jednoho výskoku by „zelená“ nic neříkala.
MIN_EVALUATED = AMBER_MAX + 1

LEVELS = {
    "zelena": {"label": "připraven", "css": "badge-good", "range": "0–1 signál",
               "color": "zelená", "tone": "good"},
    "oranzova": {"label": "pozor", "css": "badge-warn", "range": "2–3 signály",
                 "color": "oranžová", "tone": "warn"},
    "cervena": {"label": "snížená připravenost", "css": "badge-bad", "range": "4 a víc signálů",
                "color": "červená", "tone": "bad"},
}


def level_for(count: int) -> str:
    if count <= GREEN_MAX:
        return "zelena"
    return "oranzova" if count <= AMBER_MAX else "cervena"


def _subjective(session) -> list[dict]:
    """Odpovědi dotazníků dne u otázek se signálem: hodnota, práh, je-li to signál."""
    from apps.measurements.models import Answer

    out = []
    answers = (Answer.objects.filter(response__session=session)
               .select_related("question", "response__questionnaire")
               .order_by("response__questionnaire__name", "question__order"))
    for answer in answers:
        question = answer.question
        if not question.has_signal:
            continue
        evaluated = answer.is_answered and answer.value is not None
        out.append({
            "kind": "dotaznik",
            "label": question.signal_label or question.text,
            "question": question,
            "questionnaire": answer.response.questionnaire.code,
            "value": answer.value,
            "value_txt": answer.display() if evaluated else answer.get_state_display().lower(),
            "threshold_txt": question.signal_text(),
            "evaluated": evaluated,
            "signal": evaluated and question.is_signal(answer.value),
        })
    return out


def _main_keys(values: dict, primary: dict) -> dict:
    """
    Klíčové ukazatele dne seskupené po ukazateli: z kombinací se berou
    oboustranné (celek), a když žádná není, obě strany. Jeden ukazatel je
    jeden signál, ať má kombinací kolik chce – izokinetika s osmi kombinacemi
    by jinak semafor přehlasovala.
    """
    by_metric = defaultdict(list)
    for key, entry in values.items():
        metric = entry["metric"]
        if metric.pk in primary:
            by_metric[metric.code].append(key)
    out = {}
    for code, keys in by_metric.items():
        both = [k for k in keys if k[1] in ("B", "")]
        out[code] = both or keys
    return out


def _performance(session, values: dict, reference: dict, against: str) -> list[dict]:
    """Klíčové ukazatele: změna proti výchozímu (minulému) měření a je-li to zhoršení nad MDC."""
    from apps.reports.results import change_verdict, signed

    from .charts import cz
    from .queries import _primary_protocols

    out = []
    for _code, keys in sorted(_main_keys(values, _primary_protocols()).items(),
                             key=lambda kv: values[kv[1][0]]["metric"].name):
        metric = values[keys[0]]["metric"]
        if metric.direction not in (Direction.HIGHER, Direction.LOWER):
            continue   # hmotnost a jiné ukazatele bez „lépe–hůře“ připravenost neříkají
        item = {"kind": "vykon", "label": metric.name, "metric": metric, "evaluated": False,
                "signal": False, "value_txt": "", "delta_txt": "", "pct_txt": "",
                "verdict": "", "against": against, "date": None}
        comparable = [(k, reference[k]) for k in keys if k in reference]
        if not comparable:
            item["verdict"] = "není s čím srovnat"
            out.append(item)
            continue
        if metric.mdc is None:
            item["verdict"] = "nelze posoudit (chybí MDC)"
            out.append(item)
            continue
        # nejhorší z kombinací (u stran ta horší strana)
        sign = 1 if metric.direction == Direction.HIGHER else -1
        key, before = min(comparable, key=lambda kb: sign * (values[kb[0]]["value"]
                                                             - kb[1]["value"]))
        value, base = values[key]["value"], before["value"]
        delta = value - base
        text, kind = change_verdict(metric, delta)
        d = metric.decimals
        shown = round(value, d) - round(base, d)
        pct = round(shown / abs(round(base, d)) * 100) if round(base, d) else None
        unit = f" {metric.unit}" if metric.unit and metric.unit != "-" else ""
        side = {"L": "levá", "R": "pravá"}.get(key[1], "")
        item.update({
            "evaluated": True, "signal": kind == "worse",
            "value_txt": cz(value, d) + unit,
            "delta_txt": signed(shown, d) + unit,
            "pct_txt": (signed(pct, 0) + " %") if pct else "",
            "verdict": text + (f" ({side})" if side else ""),
            "date": before.get("date"),
        })
        out.append(item)
    return out


def for_session(session, *, values=None, previous=None, baseline_values=None) -> dict | None:
    """
    Semafor jednoho testovacího dne; None, když je k posouzení méně než
    MIN_EVALUATED ukazatelů (odpovědí s prahem a klíčových ukazatelů s MDC
    a s čím srovnat) – typicky den bez ranního dotazníku.
    """
    from . import baseline, queries

    if values is None:
        values = queries.session_metric_values(session)
    if baseline_values is None:
        baseline_values = baseline.values_for(session)
    if baseline_values:
        reference, against = baseline_values, "výchozímu měření"
    else:
        if previous is None:
            previous = queries.previous_session_values(session)
        reference, against = previous, "minulému měření"

    subjective = _subjective(session)
    performance = _performance(session, values, reference, against) if values else []
    evaluated = [i for i in subjective + performance if i["evaluated"]]
    if len(evaluated) < MIN_EVALUATED:
        return None
    signals = [i for i in evaluated if i["signal"]]
    level = level_for(len(signals))
    return {
        "level": level, **LEVELS[level], "date": session.date, "session": session,
        "count": len(signals), "evaluated": len(evaluated),
        "signals": signals, "subjective": subjective, "performance": performance,
        "against": against,
        "against_text": (baseline.describe(session.subject, case="3") if baseline_values
                         else "minulému měření"),
        "signals_txt": ", ".join(s["label"].lower() if s["kind"] == "dotaznik" else s["label"]
                                 for s in signals),
    }


def latest_for(subjects) -> dict:
    """
    Semafor posledního testovacího dne každého sportovce (do týmového přehledu):
    {pk sportovce: semafor, nebo None}. Starší den se nehledá – včerejší
    připravenost dnes neplatí, a proto se ukazuje i s datem.
    """
    from apps.measurements.models import TestSession

    out = {}
    for subject in subjects:
        session = (TestSession.objects.filter(subject=subject)
                   .filter(_has_content()).order_by("-date").first())
        out[subject.pk] = for_session(session) if session is not None else None
    return out


def _has_content():
    from django.db.models import Exists, OuterRef, Q

    from apps.measurements.models import Answer, Measurement

    measured = Measurement.objects.filter(trial__protocol_run__session=OuterRef("pk"),
                                          trial__protocol_run__is_primary=True)
    answered = Answer.objects.filter(response__session=OuterRef("pk"))
    return Q(Exists(measured)) | Q(Exists(answered))
