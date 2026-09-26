"""
Analytická vrstva: srovnání s normou, změna v čase, asymetrie.

Všechno pracuje obecně nad MetricDef a kvalifikátory – proto tu není
nic specifického pro force plate nebo izokinetiku. Přidáním nového
protokolu do katalogu tyhle funkce začnou fungovat i pro něj.
"""

from dataclasses import dataclass

from apps.catalog.models import Direction, Norm
from apps.measurements.models import Measurement, Side


@dataclass
class ChangeResult:
    """Výsledek srovnání dvou měření téže metriky."""

    delta: float
    is_real: bool          # přesahuje MDC (chybu měření)?
    is_worthwhile: bool    # přesahuje SWC (praktickou významnost)?
    is_improvement: bool | None
    text: str


def compare_to_previous(metric, current: float, previous: float) -> ChangeResult:
    """
    Nahrazuje interpretuj_graf() z původní aplikace. Rozdíl: bez MDC
    neřekne "zlepšení", ale "v pásmu chyby měření" – což je poctivější.
    """
    delta = current - previous
    is_real = metric.change_is_real(delta)
    is_worthwhile = metric.change_is_worthwhile(delta)

    if metric.direction == Direction.HIGHER:
        improvement = delta > 0
    elif metric.direction == Direction.LOWER:
        improvement = delta < 0
    else:
        improvement = None

    if metric.mdc is None:
        text = (f"{metric.name}: změna {delta:+.{metric.decimals}f} {metric.unit}. "
                f"Pro metriku není stanovena MDC, změnu nelze odlišit od chyby měření.")
    elif not is_real:
        text = (f"{metric.name}: změna {delta:+.{metric.decimals}f} {metric.unit} "
                f"nepřesahuje nejmenší detekovatelnou změnu (MDC {metric.mdc:g}) – "
                f"bez prokazatelného posunu.")
    else:
        smer = "zlepšení" if improvement else "zhoršení" if improvement is False else "posun"
        text = (f"{metric.name}: {smer} o {abs(delta):.{metric.decimals}f} {metric.unit} "
                f"(přesahuje MDC {metric.mdc:g}).")

    return ChangeResult(delta, is_real, is_worthwhile, improvement, text)


def find_norm(metric, subject, *, side="", mode="", speed=None):
    """Nejspecifičtější norma, která na sportovce sedí."""
    qs = Norm.objects.filter(metric=metric)
    candidates = []
    for norm in qs:
        if norm.sport_id and norm.sport_id != subject.sport_id:
            continue
        if norm.sex and norm.sex != subject.sex:
            continue
        age = subject.age
        if age is not None:
            if norm.age_min and age < norm.age_min:
                continue
            if norm.age_max and age > norm.age_max:
                continue
        if norm.mode and mode and norm.mode != mode:
            continue
        if norm.speed is not None and speed is not None and norm.speed != speed:
            continue
        # skóre specifičnosti – čím víc kritérií norma určuje, tím lépe sedí
        score = sum(bool(x) for x in [norm.sport_id, norm.sex, norm.age_min,
                                      norm.level, norm.mode, norm.speed])
        candidates.append((score, norm))
    if not candidates:
        return None
    return max(candidates, key=lambda pair: pair[0])[1]


def asymmetry_index(left: float, right: float) -> float:
    """
    Rozdíl stran v procentech vztažený k silnější straně.

    Tohle je ta funkce, kvůli které jsou kvalifikátory poli a ne součástí
    názvu metriky: jedno pravidlo "rozdíl > 10 %" pak platí pro force
    plate, izokinetiku, sílu úchopu i segmentální složení těla.
    """
    stronger = max(abs(left), abs(right))
    if stronger == 0:
        return 0.0
    return (left - right) / stronger * 100.0


def asymmetries_for_run(protocol_run, *, threshold_pct: float = 10.0) -> list[dict]:
    """Projde všechny metriky provedení a spáruje levou a pravou stranu."""
    measurements = (
        Measurement.objects
        .filter(trial__protocol_run=protocol_run, trial__is_valid=True)
        .select_related("metric").order_by("trial__number")
    )

    by_key: dict[tuple, dict[str, list[float]]] = {}
    for m in measurements:
        if m.side not in (Side.LEFT, Side.RIGHT):
            continue
        by_key.setdefault(m.qualifier_key, {}).setdefault(m.side, []).append(m.value)

    results = []
    for key, sides in by_key.items():
        if Side.LEFT not in sides or Side.RIGHT not in sides:
            continue
        metric = next(m.metric for m in measurements if m.qualifier_key == key)
        left, right = metric.day_value(sides[Side.LEFT]), metric.day_value(sides[Side.RIGHT])
        index = asymmetry_index(left, right)
        results.append({
            "metric": metric,
            "qualifiers": {"mode": key[1], "speed": key[2], "segment": key[3]},
            "left": left,
            "right": right,
            "index_pct": index,
            "exceeds_threshold": abs(index) > threshold_pct,
        })
    return sorted(results, key=lambda r: abs(r["index_pct"]), reverse=True)
