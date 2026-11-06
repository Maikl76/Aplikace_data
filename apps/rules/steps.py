"""
Kroky pravidel a kontrola jejich zápisu: stav plyne z dat, nic se
neodškrtává ručně. Pravidlo se špatným zápisem se při vyhodnocení
přeskočí – proto se tu hlásí dřív, než ho někdo bude ve zprávě hledat.
"""

from django.db.models import Q

from apps.core.steps import step

from .engine import (
    KINDS,
    RuleError,
    template_fields,
    validate_condition,
    validate_contraindication,
    validate_template,
)

OP_TEXT = {"<": "<", "<=": "≤", ">": ">", ">=": "≥", "==": "=", "!=": "≠"}


def _shared(user):
    return Q(organization__isnull=True) | Q(organization=user.organization)


def _cz(value) -> str:
    if value is None:
        return "?"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    return f"{value:g}".replace(".", ",")


def unit_text(metric) -> str:
    """Jednotka k vypsání; pomlčka u bezrozměrných poměrů se nevypisuje."""
    unit = (metric.unit or "").strip()
    return "" if unit in ("-", "–", "—") else unit


def kinds_in(condition) -> list[str]:
    """Druhy podmínek v pravidle (i ve složených), v pořadí výskytu."""
    out = []
    if not isinstance(condition, dict):
        return out
    for group in ("all", "any"):
        if group in condition and isinstance(condition[group], list):
            for part in condition[group]:
                out.extend(k for k in kinds_in(part) if k not in out)
            return out
    for kind in KINDS:
        if kind in condition:
            out.append(kind)
    return out


def metric_codes(condition) -> list[str]:
    """Kódy ukazatelů, na které se pravidlo odkazuje (bez „*“)."""
    out = []
    if not isinstance(condition, dict):
        return out
    for group in ("all", "any"):
        if group in condition and isinstance(condition[group], list):
            for part in condition[group]:
                out.extend(c for c in metric_codes(part) if c not in out)
            return out
    for kind in KINDS:
        code = condition.get(kind)
        if isinstance(code, str) and code and code != "*" and code not in out:
            out.append(code)
    return out


def describe(condition, metrics: dict) -> str:
    """
    Podmínka slovy: „Poměr IR/ER < 1 (při 210 °/s)“, „asymetrie všech ukazatelů > 10 %“,
    „změna Výška výskoku proti minulému měření < 0 cm (jen nad MDC)“.
    ``metrics`` = kód → MetricDef (pro název a jednotku).
    """
    from apps.measurements.models import Mode, Side

    try:
        if "all" in condition:
            return " a zároveň ".join(describe(p, metrics) for p in condition["all"])
        if "any" in condition:
            return " nebo ".join(describe(p, metrics) for p in condition["any"])
        kind = next(k for k in KINDS if k in condition)
        code = condition[kind]
        metric = metrics.get(code)
        name = "všech ukazatelů" if code == "*" else (metric.name if metric else code)
        unit = f" {unit_text(metric)}" if metric and unit_text(metric) else ""
        op = OP_TEXT.get(condition.get("op"), str(condition.get("op")))
        value = _cz(condition.get("value"))
        if kind == "metric":
            core = f"{name} {op} {value}{unit}"
        elif kind == "asymmetry":
            core = f"asymetrie {name} {op} {value} %"
        elif kind == "change":
            core = f"změna {name} proti minulému měření {op} {value}{unit}"
            if condition.get("require_mdc", True):
                core += " (jen nad MDC)"
        else:
            core = f"z-skóre {name} vůči normě {op} {value}"
        where = condition.get("where") or {}
        bits = []
        if where.get("side"):
            bits.append(dict(Side.choices).get(where["side"], where["side"]).lower())
        if where.get("mode"):
            bits.append(dict(Mode.choices).get(where["mode"], where["mode"]).lower())
        if where.get("speed") is not None:
            bits.append(f"při {_cz(where['speed'])} °/s")
        if where.get("segment"):
            bits.append(f"segment {where['segment']}")
        return core + (f" ({', '.join(bits)})" if bits else "")
    except (StopIteration, AttributeError, TypeError, KeyError):
        return "podmínku nejde přečíst"


def check_rule(rule, metrics: dict, metrics_with_norm: set) -> tuple[list[str], list[str]]:
    """
    Chyby (pravidlo se přeskočí) a upozornění (pravidlo nikdy nesedne).
    ``metrics`` = kód → MetricDef ze sdíleného katalogu a katalogu pracoviště.
    """
    errors, warnings = [], []
    try:
        validate_condition(rule.condition, metrics=set(metrics))
    except RuleError as exc:
        errors.append(f"Podmínka: {exc}")
    try:
        validate_contraindication(rule.contraindication)
    except RuleError as exc:
        errors.append(f"Kontraindikace: {exc}")
    if not (rule.finding_template or "").strip():
        errors.append("Chybí text nálezu.")
    if not errors:
        fields = template_fields(rule.condition)
        for label, template in (("Text nálezu", rule.finding_template),
                                ("Text doporučení", rule.recommendation_template)):
            try:
                validate_template(template, fields)
            except RuleError as exc:
                errors.append(f"{label}: {exc}")
        warnings.extend(_warnings(rule.condition, metrics, metrics_with_norm))
    return errors, warnings


def _warnings(condition, metrics, metrics_with_norm) -> list[str]:
    out = []
    for group in ("all", "any"):
        if group in condition:
            for part in condition[group]:
                out.extend(w for w in _warnings(part, metrics, metrics_with_norm) if w not in out)
            return out
    kind = next(k for k in KINDS if k in condition)
    metric = metrics.get(condition[kind])
    if metric is None:
        return out
    if kind == "change" and condition.get("require_mdc", True) and metric.mdc is None:
        out.append(f"Ukazatel {metric.name} nemá MDC – změna se bez něj nehodnotí a pravidlo "
                   "nikdy nesedne. Doplňte MDC v Nastavení, nebo MDC u podmínky nevyžadujte.")
    if kind == "z" and metric.pk not in metrics_with_norm:
        out.append(f"Ukazatel {metric.name} nemá žádnou normu – z-skóre se nespočítá a pravidlo "
                   "nikdy nesedne. Založte normu v Nastavení → Normy.")
    return out


def rule_status(user) -> dict:
    """Pravidla pracoviště i sdílená, každé s chybami a upozorněními; čísla pro kroky."""
    from django.db.models import Count

    from apps.catalog.models import MetricDef, Norm

    from .models import Finding, Rule

    shared = _shared(user)
    metrics = {m.code: m for m in MetricDef.objects.filter(shared)}
    with_norm = set(Norm.objects.filter(shared).values_list("metric_id", flat=True))
    rules = list(Rule.objects.filter(shared).select_related("applies_to_sport")
                 .prefetch_related("rule_articles__article")
                 .annotate(nalezu=Count("findings", distinct=True,
                                        filter=Q(findings__session__organization=user.organization)))
                 .order_by("-is_active", "name"))
    for rule in rules:
        rule.errors, rule.warnings = check_rule(rule, metrics, with_norm)
        rule.condition_text = describe(rule.condition, metrics)
        rule.article_count = len(rule.rule_articles.all())
    active = [r for r in rules if r.is_active]
    return {
        "rules": rules, "active": active,
        "invalid": [r for r in rules if r.errors],
        "no_source": [r for r in active if not r.article_count],
        "findings": Finding.objects.filter(session__organization=user.organization,
                                           rule__in=active).count() if active else 0,
    }


def rule_steps(user, status: dict | None = None) -> list[dict]:
    """Kroky pravidel: aktivní pravidla, správný zápis, zdroje, zkouška na datech."""
    from django.urls import reverse

    s = status or rule_status(user)
    rules, active, invalid, no_source = s["rules"], s["active"], s["invalid"], s["no_source"]
    return [
        step(1, "Aktivní pravidla", bool(active),
             (f"{len(active)} z {len(rules)} pravidel je aktivních; nálezy a doporučení dávají "
              "jen aktivní." if active else
              f"{len(rules)} pravidel, žádné aktivní. Vzorová pravidla zůstávají vypnutá, "
              "dokud práh neověří ten, kdo za něj ručí – otevřete je, doplňte zdroj a zapněte."
              if rules else "Zatím žádné pravidlo. Pravidlo dává zprávě nález a doporučení."),
             url="#pravidla" if rules else reverse("rule_new"),
             button="K pravidlům" if rules else "Nové pravidlo"),
        step(2, "Zápis", not invalid,
             (f"{len(invalid)} pravidel se špatným zápisem – podmínka nebo text nálezu neprojde "
              "kontrolou, takové pravidlo se při vyhodnocení přeskočí." if invalid
              else "Každé pravidlo má správně zapsanou podmínku i texty." if rules
              else "Zatím žádné pravidlo."),
             url="#pravidla", button="K pravidlům", count=len(invalid) or None),
        step(3, "Zdroje", not no_source,
             (f"{len(no_source)} aktivních pravidel bez připojeného článku – zpráva nález vydá, "
              "ale necituje k němu zdroj." if no_source
              else "Každé aktivní pravidlo má připojený článek." if active
              else "Článek z knihovny se připojuje u pravidla; zpráva ho pak cituje u nálezu."),
             url="#pravidla", button="K pravidlům", count=len(no_source) or None),
        step(4, "Zkouška na datech", s["findings"] > 0,
             (f"{s['findings']} nálezů aktivních pravidel v testovacích dnech pracoviště."
              if s["findings"] else
              "Aktivní pravidla zatím nedala žádný nález – vyzkoušejte je na posledních "
              "testovacích dnech, uvidíte, kde sedí a proč ne."),
             url=reverse("rules_test"), button="Vyzkoušet", optional=True, admin_only=True),
    ]
