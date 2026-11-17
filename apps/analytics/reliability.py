"""
MDC z vlastních dat.

Typická chyba měření (TE) z opakovaných měření stejných lidí v době, kdy se
neměli změnit – test a retest po pár dnech, kontrolní skupina studie,
opakované měření v klidném období:

* z každého sportovce se vezmou po sobě jdoucí měřené dny v období (nejvýš
  ``max_gap`` dní od sebe) a jejich rozdíl – jeden pár,
* páry se seskupí podle pořadí (1. → 2. den, 2. → 3. den …) a od rozdílů ve
  skupině se odečte její průměrná změna: systematický posun celé skupiny
  (učení, únava) není náhodná chyba měření,
* TE = SD rozdílů / √2, sdružené přes skupiny párů (Hopkins 2000),
* MDC90 = 1,645 · √2 · TE a MDC95 = 1,96 · √2 · TE (Weir 2005),
* SWC = 0,2 × SD mezi osobami z prvního měření každého (nejmenší prakticky
  významná změna jako malý efekt podle Cohena).

Odhad je jen tak dobrý jako výběr dat. Období, kdy se skupina zlepšovala
nebo zhoršovala různě, TE nadhodnotí – nejlepší je kontrolní skupina nebo
opakování v krátkém odstupu. MDC se ukládá v jednotkách ukazatele, jak ho
čte zbytek aplikace; TE v procentech (z logaritmů) je jen pro orientaci.
"""

import math
import statistics
from collections import defaultdict

from apps.measurements.models import Measurement, canonical_side

Z90 = 1.6449
Z95 = 1.9600
MIN_SUBJECTS = 3
MIN_DF = 3
GOOD_SUBJECTS = 15
GOOD_DF = 20
CALM_GAP = 7    # typický odstup měření (dny), nad kterým se upozorní na skutečnou změnu


def chi2_quantile(p: float, df: int) -> float:
    """Kvantil χ² (Wilsonova–Hilfertyho aproximace; pro df ≥ 3 na pár procent přesná)."""
    z = {0.05: -Z90, 0.95: Z90}[p]
    a = 2 / (9 * df)
    return df * (1 - a + z * math.sqrt(a)) ** 3


def _day_values(metric, subjects, date_from, date_to) -> dict:
    """{(sportovec, kombinace): {den: hodnota dne}} – hlavní provedení, platné pokusy."""
    from .queries import _primary_protocols

    primary = _primary_protocols().get(metric.pk, set())
    raw = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    codes = {}
    qs = (Measurement.objects
          .filter(metric=metric, trial__is_valid=True, trial__protocol_run__is_primary=True,
                  trial__protocol_run__session__subject__in=subjects,
                  trial__protocol_run__session__date__gte=date_from,
                  trial__protocol_run__session__date__lte=date_to)
          .order_by("trial__number")
          .values_list("trial__protocol_run__session__subject_id",
                       "trial__protocol_run__session__date",
                       "trial__protocol_run__protocol_id", "trial__protocol_run__protocol__code",
                       "side", "mode", "speed", "segment", "value"))
    for subject_id, day, protocol_id, code, side, mode, speed, segment, value in qs:
        combo = (canonical_side(side), mode or "", float(speed) if speed is not None else None,
                 segment or "")
        raw[(subject_id, combo)][day][protocol_id].append(value)
        codes[protocol_id] = code
    out = {}
    for key, by_day in raw.items():
        out[key] = {}
        for day, by_protocol in by_day.items():
            # jako všude: hodnota dne z testu, kde je ukazatel klíčový
            chosen = min(by_protocol, key=lambda p: (p not in primary, codes[p], p))
            out[key][day] = metric.day_value(by_protocol[chosen])
    return out


def _combo_label(combo) -> str:
    from .charts import qualifier_label

    side, mode, speed, segment = combo
    return qualifier_label({"side": side if side != "B" else "", "mode": mode, "speed": speed,
                            "segment": segment})


def estimate(metric, subjects, date_from, date_to, *, max_gap: int = 14) -> list[dict]:
    """
    Odhad TE, MDC a SWC pro každou kombinaci (strana, režim, rychlost, segment),
    kde je dost dat; hlavní kombinace (oboustranně, nejvíc párů) první.
    """
    values = _day_values(metric, subjects, date_from, date_to)
    by_combo = defaultdict(dict)
    for (subject_id, combo), days in values.items():
        by_combo[combo][subject_id] = sorted(days.items())

    results = []
    for combo, series in by_combo.items():
        result = _estimate_combo(metric, series, max_gap=max_gap)
        result["combo"] = combo
        result["label"] = _combo_label(combo)
        _texts(result, metric)
        results.append(result)
    results.sort(key=lambda r: (r["combo"][0] not in ("B", ""), -r["n_pairs"], r["label"]))
    return results


def _texts(result: dict, metric) -> None:
    """Čísla k zobrazení: o desetinné místo víc než ukazatel, s desetinnou čárkou."""
    from .charts import cz

    d = metric.decimals + 1
    for key in ("te", "mdc90", "mdc95", "swc", "ci_low", "ci_high"):
        result[f"{key}_txt"] = cz(result[key], d) if result.get(key) is not None else ""
    result["te_pct_txt"] = cz(result["te_pct"], 1) if result.get("te_pct") is not None else ""
    mean = result.get("mean")
    result["mdc90_pct_txt"] = (cz(result["mdc90"] / abs(mean) * 100, 1)
                               if result.get("mdc90") is not None and mean else "")


def _pooled_sd(groups: dict) -> tuple[float | None, int, int]:
    """SD rozdílů po odečtení průměru každé skupiny párů; (SD, df, počet párů)."""
    squares, df, pairs = 0.0, 0, 0
    for diffs in groups.values():
        if len(diffs) < 2:
            continue
        mean = statistics.fmean(diffs)
        squares += sum((x - mean) ** 2 for x in diffs)
        df += len(diffs) - 1
        pairs += len(diffs)
    if df < 1:
        return None, df, pairs
    return math.sqrt(squares / df), df, pairs


def _estimate_combo(metric, series: dict, *, max_gap: int) -> dict:
    groups, log_groups = defaultdict(list), defaultdict(list)
    used_subjects, all_values, first_values, mean_changes, gaps = set(), [], [], {}, []
    positive = True
    for subject_id, points in series.items():
        first_values.append(points[0][1])
        for order, ((day_a, a), (day_b, b)) in enumerate(zip(points, points[1:], strict=False)):
            if (day_b - day_a).days > max_gap:
                continue
            gaps.append((day_b - day_a).days)
            groups[order].append(b - a)
            if a > 0 and b > 0:
                log_groups[order].append(math.log(b) - math.log(a))
            else:
                positive = False
            used_subjects.add(subject_id)
            all_values += [a, b]

    sd, df, pairs = _pooled_sd(groups)
    out = {"n_subjects": len(used_subjects), "n_pairs": pairs, "df": df, "ok": False,
           "warnings": [], "te": None, "te_pct": None, "mdc90": None, "mdc95": None,
           "swc": None, "ci_low": None, "ci_high": None, "mean": None, "groups": 0,
           "median_gap": statistics.median(gaps) if gaps else None}
    if sd is None or len(used_subjects) < MIN_SUBJECTS or df < MIN_DF:
        out["warnings"].append(
            f"Málo dat: potřeba aspoň {MIN_SUBJECTS} sportovci s opakovaným měřením "
            f"v odstupu nejvýš {max_gap} dní (teď {len(used_subjects)} sportovců, "
            f"{pairs} párů).")
        return out
    te = sd / math.sqrt(2)
    out.update({
        "ok": True, "te": te, "mdc90": Z90 * math.sqrt(2) * te, "mdc95": Z95 * math.sqrt(2) * te,
        "ci_low": te * math.sqrt(df / chi2_quantile(0.95, df)),
        "ci_high": te * math.sqrt(df / chi2_quantile(0.05, df)),
        "mean": statistics.fmean(all_values),
        "groups": sum(1 for diffs in groups.values() if len(diffs) >= 2),
    })
    for order, diffs in sorted(groups.items()):
        if len(diffs) >= 2:
            mean_changes[order] = statistics.fmean(diffs)
    out["mean_changes"] = mean_changes
    if positive:
        log_sd, _, _ = _pooled_sd(log_groups)
        if log_sd is not None:
            out["te_pct"] = 100 * (math.exp(log_sd / math.sqrt(2)) - 1)
    if len(first_values) >= MIN_SUBJECTS:
        out["swc"] = 0.2 * statistics.stdev(first_values)
    if len(used_subjects) < GOOD_SUBJECTS or df < GOOD_DF:
        out["warnings"].append(
            f"Odhad je hrubý ({len(used_subjects)} sportovců, {df} stupňů volnosti) – "
            "interval spolehlivosti je široký. Pro přesný odhad se doporučuje kolem 50 osob "
            "a aspoň tři měření (Hopkins 2000).")
    if out["median_gap"] is not None and out["median_gap"] > CALM_GAP:
        out["warnings"].append(
            f"Měření jsou od sebe typicky {out['median_gap']:g} dní – mezi nimi se sportovci "
            "mohli skutečně zlepšit nebo zhoršit a TE pak zahrnuje i tuto změnu. Spolehlivější "
            "je opakování po pár dnech nebo kontrolní skupina.")
    big_shift = [o for o, m in mean_changes.items() if abs(m) >= out["mdc90"] / 2]
    if big_shift:
        out["warnings"].append(
            "Skupina se mezi některými měřeními posunula jako celek (např. učení nebo únava) – "
            "posun se do chyby měření nepočítá, ale ověřte, že období bylo opravdu klidné.")
    return out


def source_text(result: dict, *, level: int, group: str, date_from, date_to, metric) -> str:
    """Zdroj MDC do pole „zdroj“: odkud, kolik osob a párů, jak spočítáno."""
    from .charts import cz

    d = metric.decimals + 1
    unit = f" {metric.unit}" if metric.unit and metric.unit != "-" else ""
    te_pct = f" ({cz(result['te_pct'], 1)} %)" if result.get("te_pct") is not None else ""
    text = (f"Vlastní data: {group}, {date_from:%d. %m. %Y}–{date_to:%d. %m. %Y}, "
            f"{result['n_subjects']} osob, {result['n_pairs']} párů; TE {cz(result['te'], d)}"
            f"{unit}{te_pct}, MDC{level} = {'1,645' if level == 90 else '1,96'}·√2·TE "
            f"(Hopkins 2000; Weir 2005)")
    return text[:300]
