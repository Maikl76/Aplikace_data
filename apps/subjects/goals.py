"""
Cíle klíčových ukazatelů.

Diagnostik s trenérem nastaví cílovou hodnotu ukazatele a dokdy. Karta
sportovce, portál i zpráva pak ukážou postup k cíli: kolik zbývá a zda je
rozdíl nad chybou měření (MDC). Cíl se vyhodnocuje nad hodnotou dne téže
řady, jakou mají dlaždice a grafy (celek / obě strany).
"""

from dataclasses import dataclass, field
from datetime import date

from django.utils import timezone

from apps.catalog.models import Direction, MetricDef

from .models import Goal


def metric_choices(subject):
    """Klíčové ukazatele: napřed z baterie sportovce, pak ostatní klíčové v katalogu."""
    from apps.measurements.planning import battery_for

    shared = MetricDef.objects.filter(protocol_metrics__is_primary=True, is_active=True)
    if subject.organization_id:
        from django.db.models import Q

        shared = shared.filter(Q(organization__isnull=True) | Q(organization=subject.organization))
    battery = battery_for(subject)
    first = []
    if battery is not None:
        for protocol in battery.protocols():
            first += [pm.metric for pm in protocol.protocol_metrics.all() if pm.is_primary]
    seen = {m.pk for m in first}
    rest = [m for m in shared.distinct().order_by("name") if m.pk not in seen]
    return first + rest


def series_for(subject, metric, *, until=None) -> list:
    """Řada hodnot dne (datum, hodnota) – přednostně celek / obě strany."""
    from apps.analytics.queries import primary_metric_series

    fallback = []
    for s in primary_metric_series(subject, limit_metrics=200, until=until):
        if s["metric"].pk != metric.pk:
            continue
        if s["qualifiers"]["side"] in ("B", ""):
            return s["points"]
        fallback = fallback or s["points"]
    return fallback


def meets(metric, value: float, target: float) -> bool:
    if metric.direction == Direction.HIGHER:
        return value >= target
    if metric.direction == Direction.LOWER:
        return value <= target
    return abs(value - target) <= (metric.mdc or 0)


def remaining(metric, value: float, target: float) -> float:
    """Kolik ještě chybí ve směru cíle (záporné = cíl překonaný)."""
    if metric.direction == Direction.LOWER:
        return value - target
    if metric.direction == Direction.HIGHER:
        return target - value
    return abs(target - value)


@dataclass
class Progress:
    goal: Goal
    points: list = field(default_factory=list)
    today: date | None = None

    def __post_init__(self):
        self.today = self.today or timezone.localdate()
        self.metric = self.goal.metric
        self.target = self.goal.target_value
        self.current = self.points[-1][1] if self.points else None
        self.current_date = self.points[-1][0] if self.points else None
        self.reached_on = next(
            (day for day, value in self.points
             if (self.goal.start_date is None or day >= self.goal.start_date)
             and meets(self.metric, value, self.target)), None)
        self.remaining = (remaining(self.metric, self.current, self.target)
                          if self.current is not None else None)
        self.reached = self.current is not None and meets(self.metric, self.current, self.target)
        self.near = (not self.reached and self.remaining is not None
                     and self.metric.mdc is not None and self.remaining <= self.metric.mdc)
        self.overdue = (not self.reached and self.goal.due_date is not None
                        and self.goal.due_date < self.today)
        self.percent = None
        start = self.goal.start_value
        if self.current is not None and start is not None and self.target != start:
            self.percent = max(0, min(100, round((self.current - start) / (self.target - start) * 100)))
        if self.reached:
            self.percent = 100
        self.status = ("nodata" if self.current is None else "reached" if self.reached
                       else "near" if self.near else "overdue" if self.overdue else "open")

    # --- texty -------------------------------------------------------------

    @property
    def unit(self) -> str:
        return "" if self.metric.unit in ("", "-") else self.metric.unit

    def _num(self, value) -> str:
        from apps.analytics.charts import cz

        return cz(value, self.metric.decimals) + (f" {self.unit}" if self.unit else "")

    @property
    def target_txt(self) -> str:
        return self._num(self.target)

    @property
    def current_txt(self) -> str:
        return self._num(self.current) if self.current is not None else ""

    @property
    def remaining_shown(self):
        """Zbývá jako rozdíl zobrazených čísel (40,0 − 37,9 = 2,1), aby seděl při kontrole."""
        if self.current is None:
            return None
        d = self.metric.decimals
        return round(abs(round(self.target, d) - round(self.current, d)), d)

    @property
    def remaining_txt(self) -> str:
        return self._num(self.remaining_shown) if self.current is not None else ""

    def verdict(self) -> str:
        """Posouzení pro zprávu a portál – stejná slova jako u změny proti minule."""
        if self.status == "nodata":
            return "zatím bez měření"
        if self.status == "reached":
            return "splněno"
        if self.status == "near":
            return "zbývá méně než chyba měření – cíl je prakticky splněn"
        if self.metric.mdc is None:
            return "zbývá; bez MDC nelze říct, zda je rozdíl nad chybou měření"
        return "zbývá více než chyba měření"

    def text(self) -> str:
        due = f", do {self.goal.due_date:%d.%m.%Y}" if self.goal.due_date else ""
        if self.status == "nodata":
            return f"Cíl {self.target_txt}{due}; ukazatel zatím nebyl změřen."
        if self.status == "reached":
            when = f" {self.reached_on:%d.%m.%Y}" if self.reached_on else ""
            return f"Splněno{when}: {self.current_txt} (cíl {self.target_txt})."
        base = (f"Zbývá {self.remaining_txt}: aktuálně {self.current_txt} "
                f"({self.current_date:%d.%m.%Y}), cíl {self.target_txt}{due}.")
        if self.status == "near":
            return base + " Rozdíl je menší než chyba měření – cíl je prakticky splněn."
        if self.status == "overdue":
            return base.replace("Zbývá", "Termín prošel, zbývá", 1)
        if self.reached_on:
            return base + f" Splněno už {self.reached_on:%d.%m.%Y}, poslední měření je pod cílem."
        return base

    def badge(self) -> tuple[str, str]:
        return {
            "reached": ("badge-good", "splněno"),
            "near": ("badge-accent", "v dosahu"),
            "overdue": ("badge-warn", "po termínu"),
            "open": ("", f"zbývá {self.remaining_txt}"),
            "nodata": ("", "bez měření"),
        }[self.status]


def goals_for(subject, *, until=None, today=None) -> list[Progress]:
    """Platné cíle sportovce s postupem (``until`` omezí měření – pro zprávu)."""
    goals = list(Goal.objects.filter(subject=subject, is_active=True).select_related("metric"))
    return [Progress(g, series_for(subject, g.metric, until=until), today=today) for g in goals]


def by_metric(progress) -> dict:
    out = {}
    for p in progress:
        out.setdefault(p.metric.pk, p)
    return out


def create(subject, metric, target: float, *, due_date=None, note: str = "", user=None) -> Goal:
    """Založí cíl; výchozí bod je poslední naměřená hodnota dne."""
    points = series_for(subject, metric)
    start_date, start_value = points[-1] if points else (None, None)
    return Goal.objects.create(
        subject=subject, metric=metric, target_value=target, due_date=due_date,
        note=note[:200], start_value=start_value, start_date=start_date, set_by=user)
