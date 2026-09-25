"""
Text zprávy – třetí vrstva doporučení.

Rozdělení rolí:

* **pravidla** (apps.rules) vyrobí nálezy a VŠECHNA čísla
* **evidence** (apps.rules.evidence) k nim přiloží citace
* **tahle vrstva** z toho složí souvislý text

Výchozí implementace skládá text ze šablon nálezů – je deterministická
a nepotřebuje nic vnějšího. Jazykový model se dá připojit na stejné
rozhraní (``compose``), ale platí pro něj tvrdé pravidlo: **nesmí počítat
ani přidat číslo, které nedostal**. Proto je tu ``verify_numbers`` – po
generování se text strojově zkontroluje proti hodnotám z nálezů.

Před připojením modelu ověřte, co smíte posílat ven: sportovci v datech
vystupují pod pseudonymem, ale zdravotní údaje to jsou pořád.
"""

import json
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Čísla v českém i strojovém zápisu: 12, 12,5, 12.5, -3,2, +0,9.
# Číslo nesmí navazovat na písmeno ani na spojovník po písmenu – „FTVS-0007“
# je kód, ne záporná sedmička, a „VO2max“ není dvojka.
NUMBER = re.compile(r"(?<![\w-])[-−+]?\d+(?:[.,]\d+)?")

# Čísla, která smí v textu být vždycky – roky, pořadová čísla, procenta
# prahů se do povolených hodnot doplňují z nálezů.
ALWAYS_ALLOWED = {0, 1, 2, 3, 100}


def plural(count: int, one: str, few: str, many: str) -> str:
    """České skloňování po číslovce: 1 zdroj, 2 zdroje, 5 zdrojů."""
    if count == 1:
        return one
    if 2 <= count <= 4:
        return few
    return many


def compose(session, findings, citations) -> str:
    """Souvislý text ze strukturovaných nálezů."""
    active = [f for f in findings if not f.suppressed]
    suppressed = [f for f in findings if f.suppressed]

    parts = []
    if not active and not suppressed:
        parts.append(
            "Ve výsledcích testování nebyl nalezen žádný stav, který by podle "
            "platných pravidel vyžadoval doporučení."
        )
    else:
        parts.append(_finding_paragraph(active))

    recommendations = _recommendations(active)
    if recommendations:
        parts.append("Doporučení:\n" + "\n".join(f"• {r}" for r in recommendations))

    if suppressed:
        parts.append(
            "Následující nálezy nevedly k doporučení kvůli zdravotnímu omezení:\n"
            + "\n".join(f"• {f.text} ({f.suppressed_reason})" for f in suppressed)
        )

    if citations:
        pocet = len(citations)
        parts.append(
            f"Doporučení se opírají o {pocet} "
            f"{plural(pocet, 'citovaný zdroj', 'citované zdroje', 'citovaných zdrojů')} "
            f"uvedený v závěru zprávy."
            if pocet == 1 else
            f"Doporučení se opírají o {pocet} "
            f"{plural(pocet, 'citovaný zdroj', 'citované zdroje', 'citovaných zdrojů')} "
            f"uvedené v závěru zprávy."
        )
    return "\n\n".join(parts)


def _finding_paragraph(findings) -> str:
    if not findings:
        return "Žádný nález nad prahem."
    return "Zjištěné nálezy:\n" + "\n".join(f"• {f.text}" for f in findings)


def _recommendations(findings) -> list[str]:
    from apps.rules.engine import formatter

    out = []
    for finding in findings:
        template = finding.rule.recommendation_template
        if not template:
            continue
        text = formatter.format_safe(template, finding.values)
        if text not in out:
            out.append(text)
    return out


def _numbers_in(obj, into: set) -> None:
    """Posbírá čísla z libovolně vnořených dat – i z textů v nich."""
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        into.add(round(float(obj), 4))
    elif isinstance(obj, str):
        for raw in NUMBER.findall(obj):
            into.add(round(abs(float(raw.replace("−", "-").replace(",", "."))), 4))
    elif isinstance(obj, dict):
        for value in obj.values():
            _numbers_in(value, into)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            _numbers_in(value, into)


def allowed_numbers(findings, facts: dict | None = None) -> set:
    """Čísla, která smí text obsahovat: všechno, co vyrobila pravidla a analytika."""
    allowed = set(ALWAYS_ALLOWED)
    for finding in findings:
        _numbers_in(finding.values, allowed)
        _numbers_in(finding.text, allowed)
    if facts is not None:
        _numbers_in(facts, allowed)
    return allowed


def verify_numbers(text: str, findings, facts: dict | None = None) -> list[str]:
    """
    Zkontroluje, že text neobsahuje čísla, která nepocházejí z dat.

    Pojistka pro text, který píše jazykový model. Vrací seznam nepodložených
    čísel – prázdný seznam znamená, že je text v pořádku.
    """
    allowed = allowed_numbers(findings, facts)
    problems = []
    for raw in NUMBER.findall(text):
        value = float(raw.replace("−", "-").replace(",", "."))
        if round(value, 4) in allowed or round(abs(value), 4) in allowed:
            continue
        problems.append(raw)
    return problems


# ---------------------------------------------------------------------------
# Jazykový model
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Jsi odborný asistent laboratoře funkční diagnostiky na fakultě \
tělesné výchovy a sportu. Píšeš souhrn zprávy z testování sportovce.

Dostaneš fakta ve formátu JSON. Všechna čísla i všechna hodnocení v nich už \
spočítala a posoudila pravidla laboratoře. Tvým úkolem je z nich napsat \
souvislý, věcný text v češtině – ne je znovu hodnotit.

Pravidla, která nesmíš porušit:
1. Používej výhradně čísla, která jsou ve faktech, přesně jak tam jsou. \
Nic nepočítej, nezaokrouhluj jinak, nepřidávej odhady ani rozsahy.
2. Nepiš data, věky ani počty, které ve faktech nejsou.
3. Nestanovuj diagnózy a nepoužívej lékařskou terminologii nad rámec faktů.
4. Neuváděj žádné zdroje ani studie kromě těch v poli „citace“; odkazuj na \
ně jejich číslem v hranatých závorkách, např. [1].
5. Když je u změny uvedeno, že je „v pásmu chyby měření“, nepiš o ní jako \
o zlepšení ani zhoršení.
6. Nálezy bez doporučení (kvůli zdravotnímu omezení) zmiň, ale nic k nim \
nedoporučuj.
7. Nepoužívej číslované seznamy; na výčet používej odrážky „•“.
8. Nepiš úvodní ani závěrečné fráze o sobě, nepiš doložku o lékaři – \
tu zpráva obsahuje zvlášť.

Struktura: krátké celkové zhodnocení (2–4 věty), pak „Zjištění:“ s odrážkami, \
pak „Doporučení:“ s odrážkami převzatými z pole doporuceni_z_pravidel. \
Rozsah nejvýš 250 slov."""


@dataclass
class Composition:
    text: str
    source: str                # název modelu, nebo "šablona"
    note: str = ""             # proč se model nepoužil, pokud se nepoužil
    facts: dict | None = None  # co model dostal – stejná data platí pro kontrolu čísel


def compose_report(session, findings, citations) -> Composition:
    """
    Text zprávy. Když je model zapnutý, napíše ho model; když selže nebo
    napíše číslo, které nemá oporu v datech, použije se šablona a do
    poznámky se zapíše proč. Zpráva tedy vznikne vždycky – a nikdy
    s číslem, které si model vymyslel.
    """
    from . import facts as facts_module
    from . import llm

    fallback = compose(session, findings, citations)
    if not llm.is_enabled():
        return Composition(text=fallback, source="šablona")

    facts = facts_module.build(session, findings, citations)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content":
            "Fakta z testování:\n\n" + json.dumps(facts, ensure_ascii=False, indent=2)},
    ]

    try:
        reply = llm.chat(messages)
    except llm.LLMError as exc:
        logger.warning("Model se pro %s nepoužil: %s", session.subject.code, exc)
        return Composition(text=fallback, source="šablona",
                           note=f"Jazykový model se nepoužil: {exc}")

    if problems := verify_numbers(reply.text, findings, facts):
        logger.warning("Model %s napsal nepodložená čísla %s – použita šablona.",
                       reply.model, problems)
        return Composition(
            text=fallback, source="šablona", facts=facts,
            note=(f"Text od modelu {reply.model} byl odmítnut: obsahoval čísla, "
                  f"která v datech nejsou ({', '.join(problems[:5])}). "
                  f"Použita šablona."),
        )

    return Composition(text=reply.text, source=reply.model, facts=facts,
                       note=f"Text sestavil model {reply.model} za {reply.seconds:.0f} s.")
