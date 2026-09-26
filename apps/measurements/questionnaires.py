"""
Dotazníky k testovacímu dni (zatím RPE).

Jeden vyplněný dotazník = jeden testovací den a případně jeden test
(„RPE po Wingate“). Když se vyplní znovu, přepíše se – sportovec se
mohl překliknout a opraví to.
"""

from django.db import transaction
from django.db.models import Q

from apps.catalog.models import Questionnaire

from .models import Answer, QuestionnaireResponse

RPE = "rpe"


def questionnaire(code: str, organization=None):
    """Dotazník podle kódu: vlastní verze pracoviště má přednost před sdílenou."""
    scope = Q(organization__isnull=True)
    if organization is not None:
        scope |= Q(organization=organization)
    found = {q.organization_id: q for q in Questionnaire.objects.filter(scope, code=code,
                                                                          is_active=True)
             .prefetch_related("questions")}
    return found.get(getattr(organization, "pk", None)) or found.get(None)


@transaction.atomic
def save(session, questionnaire, values: dict, *, run=None, source) -> QuestionnaireResponse:
    """Uloží odpovědi {question: hodnota}. Existující vyplnění téhož přepíše."""
    response, _ = QuestionnaireResponse.objects.update_or_create(
        session=session, protocol_run=run, questionnaire=questionnaire,
        defaults={"source": source})
    for question, value in values.items():
        Answer.objects.update_or_create(response=response, question=question,
                                        defaults={"value": value})
    return response


def parse_answers(questionnaire, data) -> dict:
    """Odpovědi z formuláře (pole „q_<kód otázky>“). Hodnoty mimo škálu se zahodí."""
    values = {}
    for question in questionnaire.questions.all():
        raw = str(data.get(f"q_{question.code}", "")).strip()
        try:
            value = int(raw)
        except ValueError:
            continue
        if question.scale_min <= value <= question.scale_max:
            values[question] = value
    return values


def summary(session) -> list[dict]:
    """Vyplněné dotazníky dne k zobrazení: po jakém testu, kdo, odpovědi slovy."""
    out = []
    for response in (session.responses.select_related("questionnaire", "protocol_run__protocol")
                     .prefetch_related("answers__question")):
        answers = [{"question": a.question, "value": a.value,
                    "value_txt": f"{a.value:g}", "label": a.question.label(a.value),
                    "max": a.question.scale_max}
                   for a in sorted(response.answers.all(), key=lambda a: a.question.order)
                   if a.value is not None]
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
