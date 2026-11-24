"""
Vyplněnost testu: kolik ukazatelů zadávací mřížky má hodnotu (z platného
pokusu) a kolik ještě zbývá.

Test s jednou hodnotou ještě není hotový. Hotový je, až má hodnotu každý
ukazatel, který se do mřížky zadává (vypočtené ukazatele – W/kg z W a
hmotnosti – se nepočítají, přepočítají se samy). Hodnota z neplatného
pokusu se nepočítá, do výsledků nejde.

Řádky se párují jako v analytice a ve zprávě: oboustranná hodnota uložená
bez strany je totéž co „B“ (tak ji ukládají některé importy). Hodnota
ukazatele testu, která do žádného řádku nepatří (starý formát bez strany
u testu s levou a pravou stranou), se nepočítá, jen se v bublině zmíní.
"""

from collections import defaultdict

from .models import Measurement, canonical_side

EMPTY, PARTIAL, DONE = "prazdny", "rozpracovany", "hotovy"
MISSING_SHOWN = 8


def _key(metric_id, side, mode, speed, segment) -> tuple:
    """Klíč řádku: oboustranně bez strany = „B“, prázdné kvalifikátory jednotně."""
    return (metric_id, canonical_side(side or ""), mode or "",
            float(speed) if speed is not None else None, segment or "")


def _slots(protocol) -> list[tuple]:
    """Řádky zadávací mřížky protokolu: (klíč řádku, název pro bublinu)."""
    from apps.analytics.derived import DERIVED_METRICS

    from .forms import _combo_label

    out = []
    for pm in protocol.protocol_metrics.select_related("metric").all():
        if pm.metric.code in DERIVED_METRICS:
            continue
        for combo in pm.qualifier_combinations():
            label = _combo_label(combo)
            out.append((_key(pm.metric_id, combo["side"], combo["mode"], combo["speed"],
                             combo["segment"]),
                        pm.metric.name + (f" ({label})" if label else "")))
    return out


def annotate(runs) -> list:
    """
    Doplní ke každému provedení ``ukazatelu`` (kolik řádků mřížka má),
    ``vyplneno``, ``zbyva``, ``chybi`` (názvy prvních chybějících), ``mimo``
    (hodnoty ukazatelů testu mimo řádky mřížky) a ``stav`` (prázdný /
    rozpracovaný / hotový). Vrací seznam provedení.
    """
    runs = list(runs)
    if not runs:
        return runs
    filled = defaultdict(set)
    for row in (Measurement.objects.filter(trial__protocol_run__in=runs, trial__is_valid=True)
                .values_list("trial__protocol_run_id", "metric_id", "side", "mode", "speed",
                             "segment").order_by().distinct()):
        filled[row[0]].add(_key(*row[1:]))
    slots_by_protocol: dict = {}
    for run in runs:
        if run.protocol_id not in slots_by_protocol:
            slots_by_protocol[run.protocol_id] = _slots(run.protocol)
        slots = slots_by_protocol[run.protocol_id]
        keys = {key for key, _ in slots}
        metrics = {key[0] for key in keys}
        have = filled[run.pk]
        missing = [label for key, label in slots if key not in have]
        run.ukazatelu = len(slots)
        run.vyplneno = len(slots) - len(missing)
        run.zbyva = len(missing)
        run.chybi = missing[:MISSING_SHOWN]
        run.chybi_dalsi = max(0, len(missing) - MISSING_SHOWN)
        run.mimo = sum(1 for key in have if key[0] in metrics and key not in keys)
        if have and not missing:
            run.stav = DONE      # i test, kde se nic nezadává a hodnoty jsou vypočtené
        elif run.vyplneno or run.mimo:
            run.stav = PARTIAL
        else:
            run.stav = EMPTY
        run.chybi_text = missing_title(run)
    return runs


def missing_title(run) -> str:
    """Text do bubliny: co ještě chybí (a co se do vyplněnosti nepočítá)."""
    from apps.reports.narrative import plural

    parts = []
    if getattr(run, "chybi", None):
        more = f" a dalších {run.chybi_dalsi}" if run.chybi_dalsi else ""
        parts.append("Chybí: " + ", ".join(run.chybi) + more)
    if getattr(run, "mimo", 0):
        n = run.mimo
        parts.append(f"{n} {plural(n, 'hodnota je', 'hodnoty jsou', 'hodnot je')} mimo řádky "
                     "tabulky (např. bez rozlišení strany) a "
                     f"{plural(n, 'nepočítá', 'nepočítají', 'nepočítá')} se")
    return ". ".join(parts)


def annotate_sessions(sessions, *, exclude_derived: bool = False) -> list:
    """
    U testovacích dnů doplní ``testu`` (počet testů), ``zmereno`` (kolik je
    vyplněných celých) a ``s_hodnotami`` (kolik má aspoň jednu hodnotu).
    """
    from .models import ProtocolRun
    from .planning import DERIVED_PROTOCOLS

    sessions = list(sessions)
    runs = ProtocolRun.objects.filter(session__in=sessions).select_related("protocol")
    if exclude_derived:
        runs = runs.exclude(protocol__code__in=DERIVED_PROTOCOLS)
    by_session: dict = defaultdict(list)
    for run in annotate(runs):
        by_session[run.session_id].append(run)
    for session in sessions:
        rows = by_session.get(session.pk, [])
        session.testu = len(rows)
        session.zmereno = sum(1 for r in rows if r.stav == DONE)
        session.s_hodnotami = sum(1 for r in rows if r.stav != EMPTY)
    return sessions
