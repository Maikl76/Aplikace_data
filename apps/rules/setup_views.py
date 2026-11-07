"""
Pravidla v aplikaci: přehled s kroky (co chybí), formulář pravidla v pěti
částech (název a kdy platí, podmínka ze stavitele, texty nálezu
a doporučení, kontraindikace, zdroje) a zkouška na posledních testovacích
dnech – u každého dne je vidět, jestli pravidlo sedlo, a když ne, proč.

Podmínka se skládá z řádků (druh, ukazatel, operátor, práh, kde platí)
a ukládá se do stejného JSON, jaký čte vyhodnocování (apps/rules/engine.py).
Složené vnořené podmínky (any uvnitř all) stavitel neumí – ty se upravují
jako JSON.
"""

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from apps.catalog import protocol_setup as setup
from apps.catalog.models import MetricDef
from apps.catalog.norm_views import article_choices
from apps.core.audit import record
from apps.core.models import AuditLog
from apps.evidence.models import Article
from apps.measurements.models import Mode, Side, TestSession
from apps.subjects.models import Sport

from . import engine
from .engine import KINDS, OPERATORS, RuleError, validate_condition, validate_template
from .models import Rule, RuleArticle, Severity
from .steps import (
    _cz,
    _shared,
    describe,
    kinds_in,
    metric_codes,
    rule_status,
    rule_steps,
    unit_text,
)

KIND_LABELS = [
    ("metric", "Hodnota ukazatele", "naměřená hodnota proti prahu, např. poměr IR/ER < 1"),
    ("asymmetry", "Asymetrie stran", "rozdíl levé a pravé v % proti prahu; „všechny ukazatele“ "
                                      "= každý ukazatel měřený oboustranně"),
    ("change", "Změna proti minulému měření", "rozdíl proti poslednímu dřívějšímu měření téhož "
                                              "ukazatele; bez MDC se o změně nic netvrdí"),
    ("z", "Z-skóre vůči normě", "o kolik SD se hodnota liší od normy, která sportovci sedí"),
]
MODES = [c for c in Mode.choices if c[0]]
ROW_FIELDS = ("kind", "metric", "op", "value", "side", "mode", "speed", "segment")
EMPTY_ROW = {"kind": "metric", "metric": "", "op": "<", "value": "", "side": "", "mode": "",
             "speed": "", "segment": "", "mdc": True}
MAX_ROWS = 12

# Pole šablon slovy – nabídka pod textem nálezu. Pořadí = pořadí v nabídce.
FIELD_HELP = {
    "metric": "název ukazatele", "metric_code": "kód ukazatele", "unit": "jednotka",
    "value": "hodnota (číslo)", "value_txt": "hodnota s desetinnou čárkou",
    "threshold": "práh (číslo)", "threshold_txt": "práh s čárkou",
    "side": "strana", "mode": "režim", "speed": "rychlost (číslo)", "speed_txt": "rychlost (text)",
    "segment": "segment", "mdc": "MDC (číslo)", "mdc_txt": "MDC s čárkou",
    "delta": "změna (číslo)", "delta_txt": "změna se znaménkem", "predchozi": "minulá hodnota",
    "z": "z-skóre", "norma": "průměr normy", "citace": "citace normy",
    "left": "levá (číslo)", "right": "pravá (číslo)", "left_txt": "levá s čárkou",
    "right_txt": "pravá s čárkou", "index_pct": "rozdíl stran v % (číslo)",
    "index_txt": "rozdíl stran v % s čárkou", "silnejsi": "silnější strana (levá / pravá)",
}
PREFERRED = ("value_txt", "threshold_txt", "unit", "metric", "speed_txt", "side", "mode",
             "delta_txt", "predchozi", "mdc_txt", "z", "norma", "citace", "index_txt", "left_txt",
             "right_txt", "silnejsi")


def palette() -> list[dict]:
    """Nabídka polí pro šablony po druzích podmínky (nejužitečnější první)."""
    out = []
    for kind, label, _ in KIND_LABELS:
        fields = engine.TEMPLATE_FIELDS[kind]
        ordered = [f for f in PREFERRED if f in fields] + sorted(f for f in fields
                                                                 if f not in PREFERRED)
        out.append({"kind": kind, "label": label,
                    "fields": [(f, FIELD_HELP.get(f, "")) for f in ordered]})
    return out


def _denied(request, reason):
    return render(request, "core/odepreno.html", {"duvod": reason}, status=403)


def _num(text):
    """„1,5“ i „1.5“ → číslo (celé zůstane celé); prázdné → None; nesmysl → ValueError."""
    text = (text or "").strip().replace(",", ".").replace(" ", "")
    if not text:
        return None
    value = float(text)
    return int(value) if value.is_integer() and "." not in text else value


def _num_txt(value) -> str:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return "" if value is None else str(value)
    return f"{value:g}".replace(".", ",")


# --- přehled ---------------------------------------------------------------------------------

@login_required
def rule_list(request):
    user = request.user
    status = rule_status(user)
    return render(request, "rules/list.html", {
        "rules": status["rules"], "steps": rule_steps(user, status),
        "can_edit": setup.can_edit_sports(user), "active": len(status["active"]),
    })


# --- formulář ---------------------------------------------------------------------------------

FIELDS = ("name", "code", "sport", "severity", "finding_template", "recommendation_template")


def _row(part) -> dict | None:
    """Jedna jednoduchá podmínka jako řádek stavitele; None = nejde (vnořená skupina)."""
    if not isinstance(part, dict):
        return None
    kind = next((k for k in KINDS if k in part), None)
    if kind is None:
        return None
    where = part.get("where") if isinstance(part.get("where"), dict) else {}
    return {"kind": kind, "metric": str(part.get(kind) or ""), "op": str(part.get("op") or "<"),
            "value": _num_txt(part.get("value")), "side": str(where.get("side") or ""),
            "mode": str(where.get("mode") or ""), "speed": _num_txt(where.get("speed")),
            "segment": str(where.get("segment") or ""),
            "mdc": bool(part.get("require_mdc", True))}


def rows_from_condition(condition) -> tuple[list[dict], str] | None:
    """Řádky stavitele a skupina (all / any); None, když je podmínka vnořená."""
    if not isinstance(condition, dict):
        return None
    group = "all" if "all" in condition else "any" if "any" in condition else ""
    parts = condition.get(group) if group else [condition]
    if not isinstance(parts, list):
        return None
    rows = [_row(p) for p in parts]
    if any(r is None for r in rows):
        return None
    return rows, group or "all"


def condition_from_rows(rows: list[dict], group: str) -> tuple[dict, list[str]]:
    """Řádky stavitele → JSON podmínky; chyby zápisu čísel se hlásí po řádcích."""
    parts, errors = [], []
    for i, row in enumerate(rows, start=1):
        kind = row["kind"] if row["kind"] in KINDS else "metric"
        metric = row["metric"].strip()
        if not metric:
            errors.append(f"Podmínka {i}: vyberte ukazatel.")
        elif metric == "*" and kind != "asymmetry":
            errors.append(f"Podmínka {i}: „všechny ukazatele“ jde jen u asymetrie stran.")
        part = {kind: metric, "op": row["op"] if row["op"] in OPERATORS else "<"}
        try:
            value = _num(row["value"])
        except ValueError:
            value = None
            errors.append(f"Podmínka {i}: práh musí být číslo.")
        if value is None and not any(e.startswith(f"Podmínka {i}: práh") for e in errors):
            errors.append(f"Podmínka {i}: doplňte práh.")
        part["value"] = value if value is not None else 0
        where = {}
        for key in ("side", "mode", "segment"):
            if row[key].strip():
                where[key] = row[key].strip()
        try:
            speed = _num(row["speed"])
        except ValueError:
            speed = None
            errors.append(f"Podmínka {i}: rychlost musí být číslo (°/s).")
        if speed is not None:
            where["speed"] = speed
        if where:
            part["where"] = where
        if kind == "change":
            part["require_mdc"] = bool(row["mdc"])
        parts.append(part)
    if not parts:
        errors.append("Přidejte aspoň jednu podmínku.")
        return {}, errors
    return (parts[0] if len(parts) == 1 else {group if group in ("all", "any") else "all": parts},
            errors)


def _form_data(rule, post=None) -> dict:
    if post is not None:
        data = {f: post.get(f, "").strip() for f in FIELDS}
        data.update({
            "is_active": bool(post.get("is_active")),
            "load_restriction": bool(post.get("load_restriction")),
            "group": post.get("group", "all"), "json_mode": bool(post.get("json_mode")),
            "condition_json": post.get("condition_json", "").strip(),
            "rows": [], "new_articles": [],
        })
        try:
            count = min(int(post.get("row_count") or 0), MAX_ROWS)
        except ValueError:
            count = 0
        for i in range(count):
            row = {f: post.get(f"r{i}_{f}", "").strip() for f in ROW_FIELDS}
            row["mdc"] = bool(post.get(f"r{i}_mdc"))
            if row["metric"] or row["value"]:
                data["rows"].append(row)
        try:
            count = min(int(post.get("nra_count") or 0), 10)
        except ValueError:
            count = 0
        for i in range(count):
            article = post.get(f"nra{i}_article", "").strip()
            if article:
                data["new_articles"].append({"article": article,
                                             "note": post.get(f"nra{i}_note", "").strip()[:500]})
        return data
    if rule is None:
        return {**dict.fromkeys(FIELDS, ""), "severity": Severity.MEDIUM, "is_active": False,
                "load_restriction": True, "group": "all", "json_mode": False,
                "condition_json": "", "rows": [], "new_articles": []}
    parsed = rows_from_condition(rule.condition)
    data = {
        "name": rule.name, "code": rule.code, "sport": str(rule.applies_to_sport_id or ""),
        "severity": rule.severity, "finding_template": rule.finding_template,
        "recommendation_template": rule.recommendation_template, "is_active": rule.is_active,
        "load_restriction": bool((rule.contraindication or {}).get("load_restriction")),
        "group": parsed[1] if parsed else "all", "json_mode": parsed is None,
        "condition_json": json.dumps(rule.condition, ensure_ascii=False, indent=1),
        "rows": parsed[0] if parsed else [], "new_articles": [],
    }
    return data


def _parse(data: dict, rule, metrics: dict, sports, user) -> tuple[dict, list[str]]:
    errors = []
    name = data["name"][:200]
    if len(name) < 3:
        errors.append("Doplňte název pravidla – tak se ukáže v přehledu.")
    if rule is None:
        code = slugify((data["code"] or name).replace("/", " "))[:64].replace("-", "_")
        if not code:
            errors.append("Kód pravidla nejde odvodit – napište ho (např. pomer_ir_er).")
        elif Rule.objects.filter(_shared(user), code=code).exists():
            errors.append(f"Pravidlo s kódem „{code}“ už existuje – zvolte jiný kód.")
    else:
        code = rule.code
    sport = next((s for s in sports if str(s.pk) == data["sport"]), None)
    severity = data["severity"] if data["severity"] in Severity.values else Severity.MEDIUM

    if data["json_mode"]:
        try:
            condition = json.loads(data["condition_json"] or "{}")
        except ValueError as exc:
            condition, errors = {}, errors + [f"Podmínka není platný JSON: {exc}."]
    else:
        condition, row_errors = condition_from_rows(data["rows"], data["group"])
        errors.extend(row_errors)
    if condition and not any(e.startswith("Podmínka") for e in errors):
        try:
            validate_condition(condition, metrics=set(metrics))
        except RuleError as exc:
            errors.append(f"Podmínka: {exc}")
    finding = data["finding_template"][:2000]
    recommendation = data["recommendation_template"][:2000]
    if not finding:
        errors.append("Doplňte text nálezu – věta, která se objeví ve zprávě.")
    if condition and not any(e.startswith("Podmínka") for e in errors):
        fields = engine.template_fields(condition)
        for label, template in (("Text nálezu", finding), ("Text doporučení", recommendation)):
            try:
                validate_template(template, fields)
            except RuleError as exc:
                errors.append(f"{label}: {exc}")
    values = {
        "name": name, "code": code, "applies_to_sport": sport, "severity": severity,
        "condition": condition,
        "contraindication": {"load_restriction": True} if data["load_restriction"] else {},
        "finding_template": finding, "recommendation_template": recommendation,
        "is_active": data["is_active"],
    }
    return values, errors


def _save_articles(rule, post, new_articles) -> None:
    for link in rule.rule_articles.all():
        if post.get(f"ra{link.pk}_delete"):
            link.delete()
            continue
        note = post.get(f"ra{link.pk}_note", "").strip()[:500]
        if note != link.relevance_note:
            link.relevance_note = note
            link.save(update_fields=["relevance_note"])
    for item in new_articles:
        article = Article.objects.filter(pk=item["article"], status=Article.Status.APPROVED).first()
        if article is not None:
            RuleArticle.objects.get_or_create(rule=rule, article=article,
                                              defaults={"relevance_note": item["note"]})


def _bump_version(rule, values) -> bool:
    """Změna podmínky, textů, závažnosti nebo kontraindikace = nová verze pravidla."""
    changed = any(getattr(rule, f) != values[f] for f in
                  ("condition", "finding_template", "recommendation_template", "severity",
                   "contraindication"))
    if not changed:
        return False
    version = rule.version + 1
    while Rule.objects.filter(organization=rule.organization, code=rule.code,
                              version=version).exclude(pk=rule.pk).exists():
        version += 1
    rule.version = version
    return True


@login_required
def rule_edit(request, pk=None):
    user = request.user
    if not setup.can_edit_sports(user):
        return _denied(request, "Pravidla zapisuje správce nebo metodik sportu.")
    rule = get_object_or_404(Rule.objects.filter(_shared(user)), pk=pk) if pk else None
    metrics = {m.code: m for m in MetricDef.objects.filter(_shared(user)).order_by("family", "name")}
    sports = list(Sport.objects.for_user(user).order_by("name"))
    if request.method == "POST":
        data = _form_data(None, request.POST)
        values, errors = _parse(data, rule, metrics, sports, user)
        if not errors:
            created = rule is None
            if created:
                rule = Rule(organization=user.organization)
                bumped = False
            else:
                bumped = _bump_version(rule, values)
            for name, value in values.items():
                setattr(rule, name, value)
            rule.save()
            _save_articles(rule, request.POST, data["new_articles"])
            record(request, AuditLog.Action.CREATE if created else AuditLog.Action.UPDATE, rule,
                   pravidlo=rule.code, verze=rule.version)
            messages.success(request, f"Pravidlo {rule.name} je uložené"
                             + (f" jako verze {rule.version}; starší nálezy ve zprávách si "
                                "pamatují svou verzi." if bumped else ".")
                             + ("" if rule.is_active else " Je vypnuté – nálezy dává až aktivní."))
            status = rule_status(user)
            saved = next((r for r in status["rules"] if r.pk == rule.pk), None)
            for warning in (saved.warnings if saved else []):
                messages.warning(request, warning)
            return redirect(reverse("rules_settings") + f"#pravidlo-{rule.pk}")
        for error in errors:
            messages.error(request, error)
    else:
        data = _form_data(rule)
    if not data["rows"] and not data["json_mode"]:
        data["rows"] = [dict(EMPTY_ROW)]
    links = list(rule.rule_articles.select_related("article")) if rule else []
    return render(request, "rules/form.html", {
        "rule": rule, "data": data, "links": links,
        "metrics": [m for m in metrics.values() if m.is_active], "sports": sports,
        "severities": Severity.choices, "kinds": KIND_LABELS, "operators": list(OPERATORS),
        "sides": Side.choices, "modes": MODES, "palette": palette(),
        "articles": article_choices(), "max_rows": MAX_ROWS,
        "findings": rule.findings.count() if rule else 0,
        "condition_text": describe(rule.condition, metrics) if rule else "",
        "empty_row": dict(EMPTY_ROW),
    })


@login_required
@require_POST
def rule_delete(request, pk):
    if not setup.can_edit_sports(request.user):
        return _denied(request, "Pravidla maže správce nebo metodik sportu.")
    rule = get_object_or_404(Rule.objects.filter(_shared(request.user)), pk=pk)
    findings = rule.findings.count()
    if findings:
        messages.error(request, f"Pravidlo {rule.name} má {findings} nálezů ve zprávách, proto "
                                "nejde smazat. Vypněte ho – nálezy zůstanou dohledatelné.")
        return redirect("rule_edit", pk=pk)
    record(request, AuditLog.Action.DELETE, rule, pravidlo=rule.code)
    label = rule.name
    rule.delete()
    messages.info(request, f"Pravidlo {label} je smazané.")
    return redirect("rules_settings")


# --- zkouška na datech -------------------------------------------------------------------------

SESSIONS = 20


def _qualifiers(entry) -> str:
    bits = []
    if entry["side"] and entry["side"] != Side.BILATERAL:
        bits.append(dict(Side.choices).get(entry["side"], entry["side"]).lower())
    if entry["mode"]:
        bits.append(dict(Mode.choices).get(entry["mode"], entry["mode"]).lower())
    if entry["speed"] is not None:
        bits.append(f"{_cz(entry['speed'])} °/s")
    if entry["segment"]:
        bits.append(entry["segment"])
    return f" ({', '.join(bits)})" if bits else ""


def why_not(rule, session, metrics: dict) -> str:
    """Proč pravidlo ten den nesedlo: neměřilo se, chybí minulé měření či norma, nebo hodnoty."""
    from apps.analytics.services import find_norm

    if rule.applies_to_sport_id and rule.applies_to_sport_id != session.subject.sport_id:
        return f"pravidlo platí jen pro sport {rule.applies_to_sport.name}"
    context = engine.build_context(session)
    codes, kinds = metric_codes(rule.condition), kinds_in(rule.condition)
    measured = {}
    for key, entry in context["values"].items():
        if entry["metric"].code in codes:
            measured.setdefault(entry["metric"].code, []).append((key, entry))
    if "asymmetry" in kinds and not context["asymmetries"]:
        return "ten den nebyl žádný ukazatel měřený na obou stranách, asymetrie se nepočítá"
    if missing := [metrics[c].name if c in metrics else c for c in codes if c not in measured]:
        return "ten den se neměřil ukazatel " + ", ".join(missing)
    values = []
    for entries in measured.values():
        for _key, entry in entries:
            metric = entry["metric"]
            unit = unit_text(metric)
            values.append(f"{metric.name} {_cz(round(entry['value'], metric.decimals))}"
                          f"{' ' + unit if unit else ''}{_qualifiers(entry)}")
    if "change" in kinds and not any(key in context["previous"]
                                     for entries in measured.values() for key, _ in entries):
        return "bez dřívějšího měření téhož ukazatele se změna nepočítá; naměřeno: " + "; ".join(values)
    if "z" in kinds and not any(
            find_norm(entry["metric"], session.subject, side=entry["side"], mode=entry["mode"],
                      speed=entry["speed"], day=session.date, norms=context["norms"]) is not None
            for entries in measured.values() for _, entry in entries):
        return "na sportovce nesedí žádná norma ukazatele; naměřeno: " + "; ".join(values)
    return "hodnoty podmínku nesplnily: " + "; ".join(values)


@login_required
def rule_test(request, pk=None):
    user = request.user
    if not setup.can_edit_sports(user):
        return _denied(request, "Zkoušku pravidel spouští správce nebo metodik sportu.")
    status = rule_status(user)
    rule = None
    if pk:
        rule = next((r for r in status["rules"] if r.pk == int(pk)), None)
        if rule is None:
            return _denied(request, "Takové pravidlo tu není.")
        rules = [] if rule.errors else [rule]
    else:
        rules = [r for r in status["active"] if not r.errors]
    metrics = {m.code: m for m in MetricDef.objects.filter(_shared(user))}
    sessions = list(TestSession.objects.for_user(user).select_related("subject", "subject__sport")
                    .order_by("-date", "-pk")[:SESSIONS])
    rows, hits = [], 0
    if rule is not None and rule.errors:
        messages.error(request, "Pravidlo má špatný zápis, zkouška neproběhne: "
                       + " ".join(rule.errors))
    else:
        for session in sessions:
            findings = engine.evaluate_session(session, rules=rules, persist=False)
            hits += bool(findings)
            rows.append({"session": session, "subject": session.subject.display_for(user),
                         "findings": findings,
                         "why": why_not(rule, session, metrics) if rule and not findings else ""})
    return render(request, "rules/test.html", {
        "rule": rule, "rules": rules, "rows": rows, "hits": hits, "limit": SESSIONS,
        "sessions": len(sessions),
    })
