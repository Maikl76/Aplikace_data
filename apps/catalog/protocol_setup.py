"""
Průvodce „Nový test“: založení a úprava protokolu i s metrikami a zařazením
do baterií – bez administrace a bez psaní ["L", "R"].

Ukládá se jen nastavení. Odebrání metriky z testu ani testu z baterie
nemaže naměřená data – změní jen to, co se bude zadávat příště.
"""

import re
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Max, Q
from django.utils.text import slugify

from .models import (
    BatteryItem,
    Direction,
    MetricDef,
    Protocol,
    ProtocolMetric,
    TestBattery,
)

SIDES = [("B", "celkem / oboustranně"), ("L", "levá"), ("R", "pravá")]
MODES = [("con", "koncentricky"), ("ecc", "excentricky"), ("iso", "izometricky")]
SEGMENTS = ["paze", "noha", "trup"]


class TestSetupError(Exception):
    """Chyba ve vyplnění, kterou má uživatel vidět."""


@dataclass
class MetricRow:
    key: str
    metric: MetricDef | None = None
    new_name: str = ""
    new_unit: str = ""
    new_direction: str = Direction.NEUTRAL
    new_decimals: int = 2
    new_rule: str = MetricDef.TrialRule.MEAN
    new_min: float | None = None
    new_max: float | None = None
    primary: bool = False
    sides: list = field(default_factory=lambda: ["B"])
    modes: list = field(default_factory=list)
    speeds: list = field(default_factory=list)
    segments: list = field(default_factory=list)


def can_edit(user) -> bool:
    """Testy v katalogu nastavuje správce – role Správce nebo oprávnění ke katalogu."""
    from apps.core.models import Role

    return (user.is_superuser or getattr(user, "role", "") == Role.ADMIN
            or user.has_perm("catalog.change_protocol"))


def available_metrics(organization):
    return (MetricDef.objects.filter(is_active=True)
            .filter(Q(organization=organization) | Q(organization__isnull=True))
            .order_by("family", "name"))


def _number(text):
    text = (text or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise TestSetupError(f"„{text}“ není číslo.") from exc


def read_rows(post, organization) -> list[MetricRow]:
    """Řádky metrik z formuláře (pole m<klíč>_…) v pořadí, v jakém jsou na stránce."""
    metrics = {str(m.pk): m for m in available_metrics(organization)}
    keys = post.getlist("radek")
    rows = []
    for key in keys:
        if not re.fullmatch(r"\w{1,12}", key):
            continue
        prefix = f"m{key}_"
        choice = post.get(prefix + "metric", "")
        if not choice:
            continue
        row = MetricRow(key=key, primary=bool(post.get(prefix + "primary")))
        if choice == "nova":
            row.new_name = post.get(prefix + "new_name", "").strip()
            row.new_unit = post.get(prefix + "new_unit", "").strip()
            row.new_direction = post.get(prefix + "new_dir", "")
            if row.new_direction not in Direction.values:
                row.new_direction = Direction.NEUTRAL
            row.new_rule = post.get(prefix + "new_rule", "")
            if row.new_rule not in MetricDef.TrialRule.values:
                row.new_rule = MetricDef.TrialRule.MEAN
            decimals = _number(post.get(prefix + "new_decimals")) or 0
            row.new_decimals = max(0, min(4, int(decimals)))
            row.new_min = _number(post.get(prefix + "new_min"))
            row.new_max = _number(post.get(prefix + "new_max"))
            if not row.new_name:
                raise TestSetupError("U nové metriky chybí název.")
        else:
            row.metric = metrics.get(choice)
            if row.metric is None:
                continue
        row.sides = [s for s, _ in SIDES if s in post.getlist(prefix + "sides")] or ["B"]
        row.modes = [m for m, _ in MODES if m in post.getlist(prefix + "modes")]
        segments = [s for s in SEGMENTS if s in post.getlist(prefix + "segments")]
        segments += [s.strip().lower() for s in post.get(prefix + "segment_other", "").split(",")
                     if s.strip()]
        row.segments = list(dict.fromkeys(segments))
        speeds = []
        for part in post.get(prefix + "speeds", "").replace(";", ",").split(","):
            if value := _number(part):
                speeds.append(int(value) if value.is_integer() else value)
        row.speeds = speeds
        rows.append(row)
    return rows


def _unique_code(model, name: str, *, sep: str) -> str:
    base = (slugify(name) or "test")[:40].strip("-").replace("-", sep)
    code, n = base, 2
    while model.objects.filter(code=code).exists():
        code, n = f"{base}{sep}{n}", n + 1
    return code


@transaction.atomic
def save_test(protocol: Protocol | None, *, data: dict, rows: list[MetricRow],
              batteries: list[TestBattery], all_batteries, organization) -> dict:
    name = data["name"].strip()
    if not name:
        raise TestSetupError("Napište název testu.")
    if not rows:
        raise TestSetupError("Přidejte do testu aspoň jednu metriku – co se v něm měří.")
    same = Protocol.objects.filter(name__iexact=name)
    if protocol is not None:
        same = same.exclude(pk=protocol.pk)
    if same.exists():
        raise TestSetupError(f"Test s názvem „{name}“ už v katalogu je.")
    used = [r.metric.pk for r in rows if r.metric]
    if len(used) != len(set(used)):
        raise TestSetupError("Stejná metrika je v testu dvakrát – každou přidejte jen jednou "
                             "(strany a části těla nastavíte u ní).")

    created = protocol is None
    if created:
        protocol = Protocol(organization=organization, code=_unique_code(Protocol, name, sep="_"))
    protocol.name = name
    protocol.family = data["family"]
    protocol.device = data.get("device", "").strip()
    protocol.description = data.get("description", "").strip()
    protocol.default_trials = data["trials"]
    protocol.rest_seconds = data.get("rest")
    protocol.rpe_after = bool(data.get("rpe"))
    protocol.is_active = bool(data.get("active", True))
    protocol.save()

    new_metrics = 0
    keep = []
    for order, row in enumerate(rows, start=1):
        metric = row.metric
        if metric is None:
            metric = MetricDef.objects.create(
                organization=organization, code=_unique_code(MetricDef, row.new_name, sep="_"),
                name=row.new_name, family=protocol.family, unit=row.new_unit,
                direction=row.new_direction, decimals=row.new_decimals,
                trial_rule=row.new_rule, plausible_min=row.new_min, plausible_max=row.new_max)
            new_metrics += 1
        ProtocolMetric.objects.update_or_create(
            protocol=protocol, metric=metric,
            defaults={"order": order, "is_primary": row.primary, "sides": row.sides,
                      "modes": row.modes, "speeds": row.speeds, "segments": row.segments})
        keep.append(metric.pk)
    removed = protocol.protocol_metrics.exclude(metric_id__in=keep).delete()[0]

    wanted = {b.pk for b in batteries}
    for battery in all_batteries:
        if battery.pk in wanted:
            last = battery.items.aggregate(m=Max("order"))["m"] or 0
            BatteryItem.objects.get_or_create(battery=battery, protocol=protocol,
                                              defaults={"order": last + 1})
        else:
            BatteryItem.objects.filter(battery=battery, protocol=protocol).delete()

    return {"protocol": protocol, "created": created, "metrik": len(rows),
            "novych_metrik": new_metrics, "odebrano": removed}


def rows_for(protocol: Protocol) -> list[dict]:
    """Uložené metriky testu pro formulář (stejný tvar, jaký posílá prohlížeč)."""
    return [_row_dict(str(i), pm) for i, pm in enumerate(
        protocol.protocol_metrics.select_related("metric").order_by("order", "pk"))]


def _row_dict(key, pm=None) -> dict:
    segments = list(pm.segments) if pm else []
    return {
        "key": key, "metric": str(pm.metric_id) if pm else "",
        "primary": bool(pm and pm.is_primary),
        "sides": [s for s in (pm.sides if pm else ["B"]) if s in dict(SIDES)] or ["B"],
        "modes": list(pm.modes) if pm else [],
        "speeds": ", ".join(f"{s:g}" if isinstance(s, float) else str(s)
                            for s in (pm.speeds if pm else [])),
        "segments": [s for s in segments if s in SEGMENTS],
        "segment_other": ", ".join(s for s in segments if s not in SEGMENTS),
        "new_name": "", "new_unit": "", "new_dir": Direction.NEUTRAL, "new_decimals": 2,
        "new_rule": MetricDef.TrialRule.MEAN, "new_min": "", "new_max": "",
    }


def posted_rows(post) -> list[dict]:
    """Co uživatel vyplnil – aby se po chybě formulář neztratil."""
    out = []
    for key in post.getlist("radek"):
        if not re.fullmatch(r"\w{1,12}", key):
            continue
        p = f"m{key}_"
        out.append({
            "key": key, "metric": post.get(p + "metric", ""), "primary": bool(post.get(p + "primary")),
            "sides": post.getlist(p + "sides"), "modes": post.getlist(p + "modes"),
            "speeds": post.get(p + "speeds", ""), "segments": post.getlist(p + "segments"),
            "segment_other": post.get(p + "segment_other", ""),
            "new_name": post.get(p + "new_name", ""), "new_unit": post.get(p + "new_unit", ""),
            "new_dir": post.get(p + "new_dir", Direction.NEUTRAL),
            "new_decimals": post.get(p + "new_decimals", "2"),
            "new_rule": post.get(p + "new_rule", MetricDef.TrialRule.MEAN),
            "new_min": post.get(p + "new_min", ""), "new_max": post.get(p + "new_max", ""),
        })
    return out
