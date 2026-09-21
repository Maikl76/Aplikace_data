"""
Vyhodnocování pravidel.

První vrstva doporučení: deterministická, auditovatelná, a jediné místo,
kde ve zprávě vznikají čísla. Jazykový model smí výsledek převyprávět,
ale nesmí k němu nic přidat.

Podmínka je JSON, ne Python – pravidlo musí být čitelné a zkontrolovatelné
i pro toho, kdo nekóduje, a musí jít změnit v administraci bez nasazení.

Podporované tvary podmínky
--------------------------
    {"metric": "ir_er_ratio", "op": "<", "value": 1.0, "where": {"speed": 210}}
    {"asymmetry": "*", "op": ">", "value": 10}          # |rozdíl L-P| v %
    {"asymmetry": "grip_strength", "op": ">", "value": 10}
    {"change": "cmj_height", "op": "<", "value": 0, "require_mdc": true}
    {"z": "vo2max", "op": "<", "value": -1.0}           # z-skóre proti normě
    {"all": [...]}  {"any": [...]}

Kontraindikace (pravidlo se potlačí, pokud platí)
-------------------------------------------------
    {"load_restriction": true}     # platné omezení zátěže od lékaře
"""

import logging
import operator
import string

from apps.analytics import queries
from apps.analytics.services import find_norm
from apps.external.models import ExternalExam

from .models import Finding, Severity

logger = logging.getLogger(__name__)

OPERATORS = {
    "<": operator.lt, "<=": operator.le,
    ">": operator.gt, ">=": operator.ge,
    "==": operator.eq, "!=": operator.ne,
}


class RuleError(Exception):
    """Pravidlo je zapsané špatně. Hlásí se, nezamlčuje."""


class SafeFormatter(string.Formatter):
    """
    Formátování textu nálezu bez přístupu k atributům a indexům.

    Šablony píše správce v administraci, ale ``"{0.__class__}"`` by i tak
    otevřelo cestu dovnitř objektů. Povolené jsou jen holé názvy polí.
    """

    def get_field(self, field_name, args, kwargs):
        if "." in field_name or "[" in field_name:
            raise RuleError(f"Nepovolený výraz v šabloně: {{{field_name}}}")
        return kwargs[field_name], field_name

    def format_safe(self, template: str, values: dict) -> str:
        try:
            return self.vformat(template, (), _Missing(values))
        except RuleError:
            raise
        except Exception as exc:
            raise RuleError(f"Šablonu nelze vyplnit: {exc}") from exc


class _Missing(dict):
    """Chybějící pole v šabloně nesmí spadnout – ukáže se jako [?]."""

    def __missing__(self, key):
        logger.warning("Šablona nálezu odkazuje na neznámé pole %r", key)
        return "[?]"


formatter = SafeFormatter()


def evaluate_session(session, *, rules=None, persist: bool = True) -> list[Finding]:
    """
    Projde pravidla proti jednomu testovacímu dni.

    Vrací nálezy. Potlačené kontraindikací se NEZAHAZUJÍ – uloží se
    s příznakem a důvodem, aby bylo doložitelné, že pravidlo sedělo,
    ale doporučení se kvůli zdravotnímu omezení nevydalo.
    """
    from .models import Rule

    if rules is None:
        rules = Rule.objects.filter(is_active=True).prefetch_related("rule_articles")

    context = _build_context(session)
    restriction = ExternalExam.active_restriction_for(session.subject)

    findings = []
    for rule in rules:
        if rule.applies_to_sport_id and rule.applies_to_sport_id != session.subject.sport_id:
            continue
        try:
            matches = _evaluate(rule.condition, context)
        except RuleError as exc:
            logger.error("Pravidlo %s: %s", rule.code, exc)
            continue

        for values in matches:
            suppressed, reason = _check_contraindication(rule, restriction)
            finding = Finding(
                session=session, rule=rule, rule_version=rule.version,
                severity=rule.severity, values=_serializable(values),
                text=formatter.format_safe(rule.finding_template, values),
                suppressed=suppressed, suppressed_reason=reason,
            )
            findings.append(finding)

    if persist:
        Finding.objects.filter(session=session).delete()
        Finding.objects.bulk_create(findings)
        findings = list(Finding.objects.filter(session=session)
                        .select_related("rule").order_by("-severity"))
    return findings


def _check_contraindication(rule, restriction) -> tuple[bool, str]:
    contraindication = rule.contraindication or {}
    if contraindication.get("load_restriction") and restriction is not None:
        return True, (
            f"Platné omezení zátěže ({restriction.get_load_restriction_display().lower()}) "
            f"z {restriction.date:%d.%m.%Y}, {restriction.provider}."
        )
    return False, ""


def _build_context(session) -> dict:
    return {
        "session": session,
        "values": queries.session_metric_values(session),
        "previous": queries.previous_session_values(session),
        "asymmetries": queries.session_asymmetries(session),
        "subject": session.subject,
    }


def _evaluate(condition, context) -> list[dict]:
    """Vrací seznam shod; každá shoda je slovník hodnot pro šablonu."""
    if not isinstance(condition, dict) or not condition:
        raise RuleError("Podmínka musí být neprázdný objekt.")

    if "all" in condition:
        return _combine_all(condition["all"], context)
    if "any" in condition:
        matches = []
        for part in condition["any"]:
            matches.extend(_evaluate(part, context))
        return matches

    if "metric" in condition:
        return _eval_metric(condition, context)
    if "asymmetry" in condition:
        return _eval_asymmetry(condition, context)
    if "change" in condition:
        return _eval_change(condition, context)
    if "z" in condition:
        return _eval_z(condition, context)

    raise RuleError(f"Neznámý tvar podmínky: {sorted(condition)}")


def _combine_all(parts, context) -> list[dict]:
    """``all`` platí jen tehdy, když každá část našla aspoň jednu shodu."""
    merged: dict = {}
    for part in parts:
        matches = _evaluate(part, context)
        if not matches:
            return []
        merged.update(matches[0])
    return [merged]


def _op(condition):
    symbol = condition.get("op")
    if symbol not in OPERATORS:
        raise RuleError(f"Neznámý operátor {symbol!r}.")
    return OPERATORS[symbol]


def _matches_where(entry: dict, where: dict) -> bool:
    for key, expected in (where or {}).items():
        actual = entry.get(key)
        if key == "speed" and actual is not None and expected is not None:
            if float(actual) != float(expected):
                return False
        elif actual != expected:
            return False
    return True


def _eval_metric(condition, context) -> list[dict]:
    compare = _op(condition)
    threshold = condition["value"]
    where = condition.get("where", {})

    matches = []
    for entry in context["values"].values():
        if entry["metric"].code != condition["metric"]:
            continue
        if not _matches_where(entry, where):
            continue
        if compare(entry["value"], threshold):
            matches.append(_values_for(entry, threshold=threshold))
    return matches


def _eval_asymmetry(condition, context) -> list[dict]:
    compare = _op(condition)
    threshold = condition["value"]
    wanted = condition["asymmetry"]

    matches = []
    for row in context["asymmetries"]:
        if wanted != "*" and row["metric"].code != wanted:
            continue
        if compare(abs(row["index_pct"]), threshold):
            q = row["qualifiers"]
            matches.append({
                "metric": row["metric"].name,
                "unit": row["metric"].unit,
                "left": round(row["left"], row["metric"].decimals),
                "right": round(row["right"], row["metric"].decimals),
                "index_pct": round(row["index_pct"], 1),
                "threshold": threshold,
                "silnejsi": "levá" if row["index_pct"] > 0 else "pravá",
                "mode": q.get("mode", ""), "speed": q.get("speed"),
                "segment": q.get("segment", ""), "side": "",
                "value": round(abs(row["index_pct"]), 1),
                "value_txt": _cz(abs(row["index_pct"]), 1),
                "index_txt": _cz(abs(row["index_pct"]), 1),
                "speed_txt": "" if q.get("speed") is None else f"{q['speed']:g}",
                "threshold_txt": _cz(threshold, 0),
                "left_txt": _cz(row["left"], row["metric"].decimals),
                "right_txt": _cz(row["right"], row["metric"].decimals),
            })
    return matches


def _eval_change(condition, context) -> list[dict]:
    """Změna proti předchozímu měření. Bez MDC se o ní nic netvrdí."""
    compare = _op(condition)
    threshold = condition["value"]
    require_mdc = condition.get("require_mdc", True)

    matches = []
    for key, entry in context["values"].items():
        if entry["metric"].code != condition["change"]:
            continue
        before = context["previous"].get(key)
        if before is None:
            continue
        delta = entry["value"] - before["value"]
        metric = entry["metric"]
        if require_mdc and not metric.change_is_real(delta):
            continue
        if compare(delta, threshold):
            matches.append(_values_for(entry, threshold=threshold, delta=delta,
                                       predchozi=round(before["value"], metric.decimals),
                                       mdc=metric.mdc))
    return matches


def _eval_z(condition, context) -> list[dict]:
    compare = _op(condition)
    threshold = condition["value"]

    matches = []
    for entry in context["values"].values():
        metric = entry["metric"]
        if metric.code != condition["z"]:
            continue
        norm = find_norm(metric, context["subject"], side=entry["side"],
                         mode=entry["mode"], speed=entry["speed"])
        if norm is None:
            continue
        z = norm.z_score(entry["value"])
        if z is None:
            continue
        if compare(z, threshold):
            matches.append(_values_for(entry, threshold=threshold, z=round(z, 2),
                                       norma=round(norm.mean, metric.decimals),
                                       citace=norm.source_citation))
    return matches


def _cz(value, decimals: int = 2) -> str:
    """Číslo s desetinnou čárkou pro text nálezu."""
    if value is None:
        return "—"
    return f"{float(value):.{decimals}f}".replace(".", ",")


def _precision_for(value, threshold, decimals: int) -> int:
    """
    Kolik desetinných míst, aby věta nezněla jako protimluv.

    Při hodnotě 0,9996 a prahu 1,0 by obě čísla zaokrouhlila na „1,00“
    a nález by tvrdil, že 1,00 je pod 1,00. V takovém případě se přidá
    jedno desetinné místo, dokud se čísla neliší.
    """
    if value is None or threshold is None:
        return decimals
    for extra in range(0, 4):
        if round(float(value), decimals + extra) != round(float(threshold), decimals + extra):
            return decimals + extra
    return decimals


def _values_for(entry, **extra) -> dict:
    metric = entry["metric"]
    raw = entry["value"]
    threshold = extra.get("threshold")

    # Přesnost se počítá z NEZAOKROUHLENÉ hodnoty. Kdyby se zaokrouhlilo
    # dřív, porovnávala by se už dvě stejná čísla a věta by zůstala
    # v podobě „1,00 je pod 1,00“.
    decimals = _precision_for(raw, threshold, metric.decimals)

    values = {
        "metric": metric.name,
        "metric_code": metric.code,
        "unit": metric.unit,
        "value": round(raw, decimals),
        "side": entry["side"],
        "mode": entry["mode"],
        "speed": entry["speed"],
        "segment": entry["segment"],
        "mdc": metric.mdc,
    }
    values.update(extra)

    # Předformátované varianty pro šablony – aby text nálezu psal 1,05
    # a ne 1.05, a autor pravidla nemusel řešit formátování.
    values["value_txt"] = _cz(raw, decimals)
    if threshold is not None:
        values["threshold_txt"] = _cz(threshold, decimals)
    if "delta" in values:
        delta = values["delta"]
        values["delta_txt"] = f"{'+' if delta > 0 else '−'}{_cz(abs(delta), metric.decimals)}"
    if values.get("mdc") is not None:
        values["mdc_txt"] = _cz(values["mdc"], metric.decimals)
    values["speed_txt"] = "" if entry["speed"] is None else f"{entry['speed']:g}"
    return values


def _serializable(values: dict) -> dict:
    """Do JSONField patří jen to, co se z něj dá zase přečíst."""
    return {k: (v if isinstance(v, (int, float, str, bool, type(None))) else str(v))
            for k, v in values.items()}


def severity_order(finding) -> int:
    order = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2, Severity.INFO: 3}
    return order.get(finding.severity, 9)
