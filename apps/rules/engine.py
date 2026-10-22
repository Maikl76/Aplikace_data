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
from apps.analytics.services import NormIndex, find_norm
from apps.external.models import ExternalExam
from apps.measurements.models import canonical_side

from .models import Finding, Severity

logger = logging.getLogger(__name__)

OPERATORS = {
    "<": operator.lt, "<=": operator.le,
    ">": operator.gt, ">=": operator.ge,
    "==": operator.eq, "!=": operator.ne,
}


class RuleError(Exception):
    """Pravidlo je zapsané špatně. Hlásí se, nezamlčuje."""


# --- kontrola tvaru pravidla při ukládání -----------------------------------
#
# Špatně zapsané pravidlo dřív prošlo uložením a při vyhodnocení se buď
# tiše přeskočilo, nebo – hůř – sedělo na víc, než mělo: {"speed": 210}
# mimo "where" se ignorovalo a pravidlo pro 210 °/s našlo nález při každé
# rychlosti. Tady se tvar zkontroluje dřív, než se pravidlo uloží.

KINDS = ("metric", "asymmetry", "change", "z")
WHERE_KEYS = ("side", "mode", "speed", "segment")

_BASE_FIELDS = {"metric", "metric_code", "unit", "value", "side", "mode", "speed", "segment",
                "mdc", "threshold", "value_txt", "threshold_txt", "mdc_txt", "speed_txt"}
TEMPLATE_FIELDS = {
    "metric": _BASE_FIELDS,
    "change": _BASE_FIELDS | {"delta", "predchozi", "delta_txt"},
    "z": _BASE_FIELDS | {"z", "norma", "citace"},
    "asymmetry": {"metric", "unit", "left", "right", "index_pct", "threshold", "silnejsi",
                  "mode", "speed", "segment", "side", "value", "value_txt", "index_txt",
                  "speed_txt", "threshold_txt", "left_txt", "right_txt"},
}


def validate_condition(condition, *, metrics=None) -> None:
    """
    Zkontroluje tvar podmínky. Chybu hlásí česky a s nápovědou, jak to má být.

    ``metrics`` = množina kódů ukazatelů, které existují; když je dána,
    odhalí i překlep v kódu (pravidlo s překlepem by jinak nikdy nesedělo).
    """
    if not isinstance(condition, dict) or not condition:
        raise RuleError('Podmínka musí být neprázdný objekt JSON, např. '
                        '{"metric": "ir_er_ratio", "op": "<", "value": 1.0}.')
    for group in ("all", "any"):
        if group in condition:
            if extra := sorted(set(condition) - {group}):
                raise RuleError(f"U „{group}“ nesmí být další klíče ({', '.join(extra)}).")
            parts = condition[group]
            if not isinstance(parts, list) or not parts:
                raise RuleError(f"„{group}“ musí být neprázdný seznam podmínek.")
            for part in parts:
                validate_condition(part, metrics=metrics)
            return

    kinds = [k for k in KINDS if k in condition]
    if len(kinds) != 1:
        raise RuleError("Podmínka musí mít právě jeden z klíčů "
                        f"{', '.join(KINDS)}, all, any (má: {', '.join(kinds) or 'žádný'}).")
    kind = kinds[0]
    code = condition[kind]
    if not isinstance(code, str) or not code:
        raise RuleError(f"„{kind}“ musí být kód ukazatele"
                        + (" nebo „*“ (všechny ukazatele)" if kind == "asymmetry" else "")
                        + ".")
    if metrics is not None and code not in metrics and not (kind == "asymmetry" and code == "*"):
        raise RuleError(f"Ukazatel s kódem „{code}“ v katalogu není.")
    if condition.get("op") not in OPERATORS:
        raise RuleError(f"Neznámý operátor {condition.get('op')!r}; povolené: "
                        f"{', '.join(OPERATORS)}.")
    value = condition.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuleError("„value“ (práh) musí být číslo.")

    allowed = {kind, "op", "value", "where"} | ({"require_mdc"} if kind == "change" else set())
    if unknown := sorted(set(condition) - allowed):
        hint = ""
        if misplaced := [k for k in unknown if k in WHERE_KEYS]:
            example = ", ".join(f'"{k}": {_json(condition[k])}' for k in misplaced)
            hint = (f" Strana, režim, rychlost a segment patří do „where“: "
                    f'{{"where": {{{example}}}}} – mimo něj se ignorují a pravidlo by sedělo '
                    f"při každé rychlosti.")
        raise RuleError(f"Neznámé klíče v podmínce: {', '.join(unknown)}.{hint}")
    where = condition.get("where", {})
    if not isinstance(where, dict):
        raise RuleError('„where“ musí být objekt, např. {"speed": 210}.')
    if bad := sorted(set(where) - set(WHERE_KEYS)):
        raise RuleError(f"„where“ smí obsahovat jen {', '.join(WHERE_KEYS)}; "
                        f"ne {', '.join(bad)}.")
    if "speed" in where and (isinstance(where["speed"], bool)
                             or not isinstance(where["speed"], (int, float))):
        raise RuleError("„speed“ ve „where“ musí být číslo (°/s).")
    for key in ("side", "mode", "segment"):
        if key in where and not isinstance(where[key], str):
            raise RuleError(f"„{key}“ ve „where“ musí být text.")
    if "require_mdc" in condition and not isinstance(condition["require_mdc"], bool):
        raise RuleError("„require_mdc“ musí být true nebo false.")


def _json(value) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def validate_contraindication(contraindication) -> None:
    """Kontraindikace: zatím jen platné omezení zátěže od lékaře."""
    if contraindication in (None, {}, ""):
        return
    if not isinstance(contraindication, dict):
        raise RuleError('Kontraindikace musí být objekt JSON: {"load_restriction": true}.')
    if unknown := sorted(set(contraindication) - {"load_restriction"}):
        raise RuleError(f"Neznámé klíče v kontraindikaci: {', '.join(unknown)}. "
                        'Podporované je jen {"load_restriction": true} '
                        "(pravidlo se potlačí, když má sportovec platné omezení zátěže).")
    if not isinstance(contraindication["load_restriction"], bool):
        raise RuleError("„load_restriction“ musí být true nebo false.")


def template_fields(condition) -> set[str]:
    """Pole, která může šablona nálezu u této podmínky použít."""
    if "all" in condition:
        return set().union(*(template_fields(p) for p in condition["all"]))
    if "any" in condition:
        # Shoda přijde vždy jen z jedné části – jisté je jen to, co mají všechny.
        return set.intersection(*(template_fields(p) for p in condition["any"]))
    kind = next(k for k in KINDS if k in condition)
    return set(TEMPLATE_FIELDS[kind])


def validate_template(template: str, fields: set[str]) -> None:
    """Šablona smí používat jen pole, která pravidlo při shodě nabídne."""
    try:
        parsed = list(string.Formatter().parse(template or ""))
    except ValueError as exc:
        raise RuleError(f"Šablona má špatné složené závorky: {exc}.") from exc
    used = {name for _, name, _, _ in parsed if name}
    if bad := sorted(n for n in used if "." in n or "[" in n or not n.strip()):
        raise RuleError(f"Nepovolený výraz v šabloně: {', '.join('{' + n + '}' for n in bad)}.")
    if unknown := sorted(used - fields):
        raise RuleError(f"Šablona používá pole, která pravidlo nenabízí: "
                        f"{', '.join('{' + n + '}' for n in unknown)}. "
                        f"K dispozici: {', '.join(sorted(fields))}.")


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
        "norms": NormIndex(),
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
        elif key == "side":
            if canonical_side(actual or "") != canonical_side(expected or ""):
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
    where = condition.get("where", {})

    matches = []
    for row in context["asymmetries"]:
        if wanted != "*" and row["metric"].code != wanted:
            continue
        if not _matches_where({"side": "", **row["qualifiers"]}, where):
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
                         mode=entry["mode"], speed=entry["speed"],
                         day=context["session"].date, norms=context.get("norms"))
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
