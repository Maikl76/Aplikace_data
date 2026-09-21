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

import re

# Čísla v českém i strojovém zápisu: 12, 12,5, 12.5, -3,2, +0,9
NUMBER = re.compile(r"[-−+]?\d+(?:[.,]\d+)?")

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


def allowed_numbers(findings) -> set:
    """Čísla, která smí text obsahovat: všechno, co vyrobila pravidla."""
    allowed = set(ALWAYS_ALLOWED)
    for finding in findings:
        for value in finding.values.values():
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                allowed.add(round(float(value), 4))
    return allowed


def verify_numbers(text: str, findings) -> list[str]:
    """
    Zkontroluje, že text neobsahuje čísla, která nepocházejí z nálezů.

    Pojistka pro případ, že text píše jazykový model. Vrací seznam
    nepodložených čísel – prázdný seznam znamená, že je text v pořádku.
    """
    allowed = allowed_numbers(findings)
    problems = []
    for raw in NUMBER.findall(text):
        value = float(raw.replace("−", "-").replace(",", "."))
        if round(value, 4) in allowed or round(abs(value), 4) in allowed:
            continue
        problems.append(raw)
    return problems
