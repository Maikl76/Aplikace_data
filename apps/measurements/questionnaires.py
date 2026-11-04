"""
Dotazníky: RPE k testovacímu dni a samostatné dotazníky ke sportovci
(dotazník ke genetickému vyšetření).

Jeden vyplněný dotazník k testovacímu dni = jeden den a případně jeden test
(„RPE po Wingate“); když se vyplní znovu, přepíše se – sportovec se mohl
překliknout. Samostatný dotazník se ukládá vždy znovu (zůstává historie,
použije se nejnovější).

Odpověď „nevím“ nebo „netýká se“ je stav bez hodnoty a nikdy se nepřekládá
na „ne“.
"""

from django.db import transaction
from django.db.models import Q

from apps.catalog.models import Question, Questionnaire

from .models import Answer, QuestionnaireResponse

RPE = "rpe"
STATES = {"unknown": Answer.State.UNKNOWN, "na": Answer.State.NA}
TEXT_MAX = 2000


def questionnaire(code: str, organization=None):
    """Dotazník podle kódu: vlastní verze pracoviště má přednost před sdílenou."""
    scope = Q(organization__isnull=True)
    if organization is not None:
        scope |= Q(organization=organization)
    found = {q.organization_id: q for q in Questionnaire.objects.filter(scope, code=code,
                                                                          is_active=True)
             .prefetch_related("questions")}
    return found.get(getattr(organization, "pk", None)) or found.get(None)


def _fields(answer) -> dict:
    """Odpověď jako pole záznamu; prosté číslo (škála) je zkratka pro hodnotu."""
    if isinstance(answer, dict):
        return {"value": answer.get("value"), "text": answer.get("text", "") or "",
                "choices": list(answer.get("choices") or []),
                "state": answer.get("state") or Answer.State.ANSWERED}
    return {"value": answer, "text": "", "choices": [], "state": Answer.State.ANSWERED}


@transaction.atomic
def save(session, questionnaire, values: dict, *, run=None, source) -> QuestionnaireResponse:
    """Uloží odpovědi {question: hodnota nebo dict}. Existující vyplnění téhož přepíše."""
    response, _ = QuestionnaireResponse.objects.update_or_create(
        session=session, protocol_run=run, questionnaire=questionnaire,
        defaults={"source": source, "subject": session.subject})
    for question, answer in values.items():
        Answer.objects.update_or_create(response=response, question=question,
                                        defaults=_fields(answer))
    return response


@transaction.atomic
def save_standalone(subject, questionnaire, values: dict, *, source) -> QuestionnaireResponse:
    """Samostatný dotazník ke sportovci – vždy nový záznam, historie zůstává."""
    response = QuestionnaireResponse.objects.create(subject=subject, questionnaire=questionnaire,
                                                    source=source)
    for question in questionnaire.questions.all():
        fields = _fields(values[question]) if question in values else {
            "value": None, "text": "", "choices": [], "state": Answer.State.MISSING}
        Answer.objects.create(response=response, question=question, **fields)
    return response


def latest(subject, code: str):
    """Nejnovější samostatné vyplnění dotazníku daného kódu, nebo None."""
    return (QuestionnaireResponse.objects.filter(subject=subject, session__isnull=True,
                                                 questionnaire__code=code)
            .select_related("questionnaire").order_by("-created_at", "-pk").first())


def parse_answers(questionnaire, data) -> dict:
    """
    Odpovědi z formuláře (pole „q_<kód>“, stav „q_<kód>__stav“) jako
    {question: dict}. Neplatné nebo prázdné odpovědi se vynechají; u otázek
    se stavem „nevím“ / „netýká se“ se hodnota nebere.
    """
    values = {}
    for question in questionnaire.questions.all():
        name = f"q_{question.code}"
        state = STATES.get(str(data.get(f"{name}__stav", "")).strip())
        if state and (state == Answer.State.UNKNOWN and question.allow_unknown
                      or state == Answer.State.NA and question.allow_na):
            values[question] = {"state": state}
            continue
        parsed = _parse(question, data, name)
        if parsed is not None:
            values[question] = parsed
    return values


def _parse(question, data, name):
    Kind = Question.Kind
    kind = question.kind
    if kind == Kind.MULTI:
        getlist = getattr(data, "getlist", None)
        raw = getlist(name) if getlist else data.get(name, [])
        if isinstance(raw, str):
            raw = [raw]
        allowed = question.option_codes()
        chosen = [c for c in raw if c in allowed]
        return {"choices": chosen} if chosen else None
    raw = str(data.get(name, "")).strip()
    if not raw:
        return None
    if kind == Kind.SCALE:
        try:
            value = int(raw)
        except ValueError:
            return None
        return {"value": value} if question.scale_min <= value <= question.scale_max else None
    if kind == Kind.NUMBER:
        try:
            return {"value": float(raw.replace(",", ".").replace(" ", ""))}
        except ValueError:
            return None
    if kind == Kind.YESNO:
        return {"value": 1.0} if raw in ("1", "ano", "true") else (
            {"value": 0.0} if raw in ("0", "ne", "false") else None)
    if kind == Kind.CHOICE:
        return {"choices": [raw]} if raw in question.option_codes() else None
    return {"text": raw[:TEXT_MAX]}


def missing_required(questionnaire, values: dict) -> list:
    """Povinné otázky bez odpovědi (ani „nevím“ / „netýká se“)."""
    return [q for q in questionnaire.questions.all() if q.required and q not in values]


def sections(questionnaire, response=None) -> list[dict]:
    """Otázky po oddílech s případnou dřívější odpovědí – pro formulář i výpis."""
    answers = response.answers_by_code() if response is not None else {}
    out: list[dict] = []
    for question in questionnaire.questions.all():
        if not out or out[-1]["name"] != question.section:
            out.append({"name": question.section, "questions": []})
        out[-1]["questions"].append({"question": question, "answer": answers.get(question.code)})
    return out


def summary(session) -> list[dict]:
    """Vyplněné dotazníky dne k zobrazení: po jakém testu, kdo, odpovědi slovy."""
    out = []
    for response in (session.responses.select_related("questionnaire", "protocol_run__protocol")
                     .prefetch_related("answers__question")):
        answers = [{"question": a.question, "value": a.value,
                    "value_txt": f"{a.value:g}" if a.value is not None else a.display(),
                    "label": a.question.label(a.value) if a.value is not None else "",
                    "display": a.display(), "max": a.question.scale_max}
                   for a in sorted(response.answers.all(), key=lambda a: a.question.order)
                   if a.value is not None or not a.is_answered or a.text or a.choices]
        out.append({"response": response, "questionnaire": response.questionnaire,
                    "run": response.protocol_run, "answers": answers,
                    "after": (response.protocol_run.protocol.name
                              if response.protocol_run else "")})
    return out


def rpe_for_run(run):
    """Hodnota RPE po daném testu (nebo None)."""
    answer = (Answer.objects.filter(response__protocol_run=run,
                                    response__questionnaire__code=RPE)
              .select_related("question").first())
    return answer


# --- odkaz pro sportovce ------------------------------------------------
# Sportovec vyplní dotazník na svém telefonu bez přihlášení. Odkaz je
# podepsaný (nejde podvrhnout jiný testovací den) a platí jen omezenou
# dobu. Stránka neukazuje jméno ani žádné výsledky – jen otázku.

TOKEN_SALT = "dotaznik-sportovce"
TOKEN_MAX_AGE = 12 * 3600


def make_token(session, questionnaire, run=None) -> str:
    from django.core import signing

    return signing.dumps({"s": session.pk, "q": questionnaire.pk,
                          "r": run.pk if run else None}, salt=TOKEN_SALT, compress=True)


def read_token(token: str) -> dict | None:
    from django.core import signing

    try:
        return signing.loads(token, salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE)
    except signing.BadSignature:  # včetně prošlé platnosti
        return None


def qr_svg(text: str) -> str:
    """QR kód jako SVG do stránky. Vždy černá na bílé – tak ho přečte každý telefon."""
    import re

    import segno

    svg = segno.make(text, error="m").svg_inline(scale=5, border=2, dark="#000", light="#fff")
    # viewBox, aby kód šel zvětšit/zmenšit stylem bez oříznutí
    return re.sub(r'^<svg width="(\d+)" height="(\d+)"',
                  r'<svg viewBox="0 0 \1 \2" width="\1" height="\2" role="img" '
                  r'aria-label="QR kód"', svg)


def reachable_from_phone(request) -> bool:
    """Adresa 127.0.0.1 / localhost z telefonu nefunguje – stojí za upozornění."""
    host = request.get_host().split(":")[0]
    return host not in ("127.0.0.1", "localhost", "::1", "[::1]")
