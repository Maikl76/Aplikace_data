"""
Dotazníky v aplikaci místo administrace: přehled s kroky (co chybí),
dotazník (název, pokyn pro sportovce, aktivní, pořadí otázek a náhled,
jak ho sportovec uvidí) a otázka (znění, druh odpovědi, možnosti nebo
škála s popisky, povinnost a stavy „nevím“ / „netýká se“).

Kódy dotazníků a otázek jsou klíče, přes které se k nim dostávají odpovědi
a scénáře genových karet – u uložené otázky se proto nemění. Otázku
s odpověďmi nebo se scénářem nejde smazat.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from apps.core.audit import record
from apps.core.models import AuditLog
from apps.measurements import questionnaires

from . import protocol_setup as setup
from .models import Question, Questionnaire
from .steps import question_problems, questionnaire_status, questionnaire_steps

Kind = Question.Kind
KIND_HELP = [
    (Kind.SCALE, "Škála", "celá čísla od–do, body mohou mít popisky (RPE: 0 klid … 10 maximální)"),
    (Kind.NUMBER, "Číslo", "volná hodnota, případně s jednotkou (hodin týdně, kg)"),
    (Kind.YESNO, "Ano / ne", "dvě odpovědi; „nevím“ a „netýká se“ se nabízejí zvlášť"),
    (Kind.CHOICE, "Jedna možnost", "sportovec vybere jednu z nabídky"),
    (Kind.MULTI, "Více možností", "může zaškrtnout víc najednou"),
    (Kind.TEXT, "Text", "volná odpověď"),
]
MAX_POINTS = 31


def _shared(user):
    return Q(organization__isnull=True) | Q(organization=user.organization)


def _denied(request, reason):
    return render(request, "core/odepreno.html", {"duvod": reason}, status=403)


def _code(text: str, length: int = 64) -> str:
    return slugify(text.replace("/", " "))[:length].replace("-", "_").strip("_")


def where_used(questionnaire) -> str:
    """Kde se dotazník v aplikaci nabízí – ať je jasné, k čemu který je."""
    if questionnaire.code == questionnaires.RPE:
        return "po každém testu v testovacím dni (zapíše operátor, nebo sportovec přes QR kód)"
    if questionnaire.code in questionnaires.STANDALONE:
        return "u sportovce v Genetice, před genetickou zprávou (laboratoř i portál)"
    if not questionnaire.is_active:
        return "vypnutý – nikde se nenabízí"
    return "v testovacím dni pod Další dotazníky (operátor, nebo sportovec přes QR kód)"


# --- přehled ---------------------------------------------------------------------------------

@login_required
def questionnaire_list(request):
    user = request.user
    status = questionnaire_status(user)
    for q in status["questionnaires"]:
        q.used = where_used(q)
    return render(request, "catalog/questionnaires.html", {
        "questionnaires": status["questionnaires"], "steps": questionnaire_steps(user, status),
        "can_edit": setup.can_edit(user), "active": len(status["active"]),
    })


# --- dotazník --------------------------------------------------------------------------------

def _questionnaire(user, pk):
    return get_object_or_404(
        Questionnaire.objects.filter(_shared(user)).annotate(
            vyplneni=Count("responses", distinct=True,
                           filter=Q(responses__subject__organization=user.organization))),
        pk=pk)


def _questions(questionnaire) -> list:
    rows = list(questionnaire.questions.annotate(
        odpovedi=Count("answers", distinct=True),
        scenaru=Count("gene_scenarios", distinct=True)).order_by("order", "pk"))
    for q in rows:
        q.problems = question_problems(q)
    return rows


@login_required
def questionnaire_edit(request, pk=None):
    user = request.user
    if not setup.can_edit(user):
        return _denied(request, "Dotazníky upravuje správce.")
    questionnaire = _questionnaire(user, pk) if pk else None
    questions = _questions(questionnaire) if questionnaire else []
    if request.method == "POST":
        data = {f: request.POST.get(f, "").strip() for f in ("name", "code", "description")}
        data["is_active"] = bool(request.POST.get("is_active"))
        errors = []
        if len(data["name"]) < 3:
            errors.append("Doplňte název dotazníku.")
        if questionnaire is None:
            code = _code(data["code"] or data["name"])
            if not code:
                errors.append("Kód dotazníku nejde odvodit – napište ho (např. unava).")
            elif Questionnaire.objects.filter(_shared(user), code=code).exists():
                errors.append(f"Dotazník s kódem „{code}“ už existuje – zvolte jiný kód.")
        else:
            code = questionnaire.code
        orders = {}
        for q in questions:
            try:
                orders[q.pk] = int(request.POST.get(f"q{q.pk}_order", q.order))
            except ValueError:
                errors.append(f"Pořadí u otázky „{q.text}“ musí být celé číslo.")
        if not errors:
            created = questionnaire is None
            if created:
                questionnaire = Questionnaire(organization=user.organization, code=code)
            questionnaire.name = data["name"][:200]
            questionnaire.description = data["description"][:2000]
            questionnaire.is_active = data["is_active"]
            questionnaire.save()
            for q in questions:
                if orders[q.pk] != q.order:
                    q.order = orders[q.pk]
                    q.save(update_fields=["order"])
            record(request, AuditLog.Action.CREATE if created else AuditLog.Action.UPDATE,
                   questionnaire, dotaznik=questionnaire.code)
            if created:
                messages.success(request, f"Dotazník {questionnaire.name} je založený – teď "
                                          "přidejte otázky.")
                return redirect("question_new", pk=questionnaire.pk)
            messages.success(request, f"Dotazník {questionnaire.name} je uložený.")
            return redirect("questionnaire_edit", pk=questionnaire.pk)
        for error in errors:
            messages.error(request, error)
    elif questionnaire is None:
        data = {"name": "", "code": "", "description": "", "is_active": True}
    else:
        data = {"name": questionnaire.name, "code": questionnaire.code,
                "description": questionnaire.description, "is_active": questionnaire.is_active}
    return render(request, "catalog/questionnaire_form.html", {
        "questionnaire": questionnaire, "data": data, "questions": questions,
        "protected": bool(questionnaire) and questionnaire.code in (
            questionnaires.RPE, *questionnaires.STANDALONE),
        "used": where_used(questionnaire) if questionnaire else "",
        "sections": questionnaires.sections(questionnaire) if questionnaire else [],
        "responses": questionnaire.vyplneni if questionnaire else 0,
    })


@login_required
@require_POST
def questionnaire_delete(request, pk):
    user = request.user
    if not setup.can_edit(user):
        return _denied(request, "Dotazníky maže správce.")
    questionnaire = _questionnaire(user, pk)
    if questionnaire.code in (questionnaires.RPE, *questionnaires.STANDALONE):
        messages.error(request, f"Dotazník {questionnaire.name} aplikace potřebuje (RPE a genetika); "
                                "nejde smazat, jen vypnout.")
        return redirect("questionnaire_edit", pk=pk)
    if questionnaire.responses.exists():
        messages.error(request, f"Dotazník {questionnaire.name} má vyplnění, proto nejde smazat. "
                                "Vypněte ho – odpovědi zůstanou dohledatelné.")
        return redirect("questionnaire_edit", pk=pk)
    record(request, AuditLog.Action.DELETE, questionnaire, dotaznik=questionnaire.code)
    label = questionnaire.name
    questionnaire.delete()
    messages.info(request, f"Dotazník {label} je smazaný.")
    return redirect("questionnaires_settings")


# --- otázka ----------------------------------------------------------------------------------

QFIELDS = ("code", "text", "help_text", "section", "kind", "unit", "scale_min", "scale_max",
           "anchors", "options")
FLAGS = ("required", "allow_unknown", "allow_na")


def _lines(text: str) -> list[tuple[str, str]]:
    """Řádky „klíč = hodnota“ (nebo jen hodnota) z textového pole."""
    out = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        key, sep, value = line.partition("=")
        out.append((key.strip(), value.strip()) if sep else ("", line))
    return out


def _question_data(question, post=None) -> dict:
    if post is not None:
        data = {f: post.get(f, "").strip() for f in QFIELDS}
        data.update({f: bool(post.get(f)) for f in FLAGS})
        return data
    if question is None:
        return {**dict.fromkeys(QFIELDS, ""), "kind": Kind.SCALE, "scale_min": "0",
                "scale_max": "10", "required": True, "allow_unknown": False, "allow_na": False}
    anchors = sorted(((int(k), v) for k, v in (question.anchors or {}).items()
                      if str(k).lstrip("-").isdigit()), key=lambda kv: kv[0])
    return {
        "code": question.code, "text": question.text, "help_text": question.help_text,
        "section": question.section, "kind": question.kind, "unit": question.unit,
        "scale_min": str(question.scale_min), "scale_max": str(question.scale_max),
        "anchors": "\n".join(f"{k} = {v}" for k, v in anchors),
        "options": "\n".join(f"{o.get('code', '')} = {o.get('label', '')}"
                             for o in (question.options or [])),
        "required": question.required, "allow_unknown": question.allow_unknown,
        "allow_na": question.allow_na,
    }


def _parse_question(data: dict, questionnaire, question) -> tuple[dict, list[str]]:
    errors = []
    text = data["text"][:300]
    if len(text) < 3:
        errors.append("Doplňte znění otázky.")
    kind = data["kind"] if data["kind"] in Kind.values else Kind.SCALE
    if question is None:
        base = _code(data["code"] or text) or "otazka"
        code, n = base, 1
        while questionnaire.questions.filter(code=code).exists():
            n += 1
            code = f"{base[:60]}_{n}"
    else:
        code = question.code
    scale_min, scale_max = 0, 10
    anchors, options = {}, []
    if kind == Kind.SCALE:
        try:
            scale_min, scale_max = int(data["scale_min"] or 0), int(data["scale_max"] or 10)
        except ValueError:
            errors.append("Škála od a do musí být celá čísla.")
        if scale_min >= scale_max:
            errors.append("Škála: „od“ musí být menší než „do“.")
        elif scale_max - scale_min + 1 > MAX_POINTS:
            errors.append(f"Škála má nejvýš {MAX_POINTS} bodů.")
        for key, label in _lines(data["anchors"]):
            if not key.lstrip("-").isdigit():
                errors.append(f"Popisky bodů: řádek „{key or label}“ musí být „číslo = popisek“.")
                continue
            if not scale_min <= int(key) <= scale_max:
                errors.append(f"Popisek bodu {key} je mimo škálu {scale_min}–{scale_max}.")
                continue
            anchors[str(int(key))] = label[:120]
    if kind in (Kind.CHOICE, Kind.MULTI):
        seen = set()
        for key, label in _lines(data["options"]):
            option_code = _code(key or label, 32)
            if not option_code or not label:
                errors.append(f"Možnosti: řádek „{key or label}“ – napište „kod = Popisek“ nebo jen "
                              "popisek.")
                continue
            if option_code in seen:
                errors.append(f"Možnosti: kód „{option_code}“ je dvakrát.")
                continue
            seen.add(option_code)
            options.append({"code": option_code, "label": label[:200]})
        if len(options) < 2:
            errors.append("Jedna nebo více možností: napište aspoň dvě možnosti, každou na řádek.")
        if question is not None and question.gene_scenarios.exists():
            if question.kind != kind:
                errors.append("Otázku používají scénáře genových karet – druh odpovědi se nemění.")
            for scenario in question.gene_scenarios.all():
                for used in (scenario.answer_match or {}).get("choices", []):
                    if used not in seen:
                        errors.append(f"Možnost „{used}“ používá scénář genové karty "
                                      f"({scenario.card}); nejde ji odebrat ani přejmenovat.")
    elif question is not None and question.gene_scenarios.exists() and question.kind != kind:
        errors.append("Otázku používají scénáře genových karet – druh odpovědi se nemění.")
    values = {
        "code": code, "text": text, "help_text": data["help_text"][:300],
        "section": data["section"][:120], "kind": kind,
        "unit": data["unit"][:20] if kind == Kind.NUMBER else "",
        "scale_min": scale_min, "scale_max": scale_max, "anchors": anchors, "options": options,
        "required": data["required"], "allow_unknown": data["allow_unknown"],
        "allow_na": data["allow_na"],
    }
    return values, errors


def _preview(question, values: dict | None, questionnaire):
    """Otázka pro náhled – uložená, nebo poskládaná z formuláře (neukládá se)."""
    if values is None:
        return question
    preview = Question(questionnaire=questionnaire, **values)
    if not preview.text:
        preview.text = "(znění otázky)"
    return preview


@login_required
def question_edit(request, pk, qpk=None):
    user = request.user
    if not setup.can_edit(user):
        return _denied(request, "Otázky dotazníků upravuje správce.")
    questionnaire = _questionnaire(user, pk)
    question = get_object_or_404(questionnaire.questions, pk=qpk) if qpk else None
    values = None
    if request.method == "POST":
        data = _question_data(None, request.POST)
        values, errors = _parse_question(data, questionnaire, question)
        if not errors:
            created = question is None
            if created:
                question = Question(questionnaire=questionnaire,
                                    order=(questionnaire.questions.count() + 1))
            for name, value in values.items():
                setattr(question, name, value)
            question.save()
            record(request, AuditLog.Action.CREATE if created else AuditLog.Action.UPDATE,
                   questionnaire, dotaznik=questionnaire.code, otazka=question.code)
            messages.success(request, f"Otázka „{question.text}“ je uložená.")
            if request.POST.get("action") == "dalsi":
                return redirect("question_new", pk=questionnaire.pk)
            return redirect(reverse("questionnaire_edit", args=[questionnaire.pk]) + "#otazky")
        for error in errors:
            messages.error(request, error)
    else:
        data = _question_data(question)
    sections = sorted({q.section for q in questionnaire.questions.all() if q.section})
    answers = question.answers.count() if question else 0
    scenarios = question.gene_scenarios.count() if question else 0
    return render(request, "catalog/question_form.html", {
        "questionnaire": questionnaire, "question": question, "data": data, "kinds": KIND_HELP,
        "sections": sections, "answers": answers, "scenarios": scenarios,
        "preview": {"question": _preview(question, values, questionnaire), "answer": None},
    })


@login_required
@require_POST
def question_delete(request, pk, qpk):
    user = request.user
    if not setup.can_edit(user):
        return _denied(request, "Otázky dotazníků maže správce.")
    questionnaire = _questionnaire(user, pk)
    question = get_object_or_404(questionnaire.questions, pk=qpk)
    if question.answers.exists() or question.gene_scenarios.exists():
        messages.error(request, f"Otázku „{question.text}“ používají odpovědi nebo scénáře genových "
                                "karet, proto nejde smazat. Zrušte u ní povinnost, nebo ji nechte.")
        return redirect("question_edit", pk=pk, qpk=qpk)
    record(request, AuditLog.Action.DELETE, questionnaire, dotaznik=questionnaire.code,
           otazka=question.code)
    label = question.text
    question.delete()
    messages.info(request, f"Otázka „{label}“ je smazaná.")
    return redirect(reverse("questionnaire_edit", args=[pk]) + "#otazky")
