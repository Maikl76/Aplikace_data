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


def compose(session, findings, citations, facts: dict | None = None) -> str:
    """
    Souvislý text ze strukturovaných nálezů a klíčových výsledků – bez
    jazykového modelu. Doporučení v něm nejsou: zpráva je má ve vlastní části.
    """
    if facts is None:
        from . import facts as facts_module
        facts = facts_module.build(session, findings, citations)

    active = [f for f in findings if not f.suppressed]
    suppressed = [f for f in findings if f.suppressed]

    parts = []
    if not active and not suppressed:
        parts.append(
            "Ve výsledcích testování nebyl nalezen žádný stav, který by podle "
            "platných pravidel vyžadoval doporučení."
        )
    elif active:
        parts.append("Zjištěné nálezy:\n" + "\n".join(f"• {f.text}" for f in active))

    # Souhrn vypíše jen skutečné změny; ostatní klíčové ukazatele shrne
    # jménem (bez počtu – číslo, které není ve faktech, by kontrola odmítla).
    klicove = facts.get("klicove_metriky", [])
    skutecne = [m for m in klicove if "přesahující chybu" in m.get("zmena_posouzeni", "")]
    if skutecne:
        parts.append("Změny proti minulému měření, které přesahují chybu měření:\n"
                     + "\n".join(_metric_line(m) for m in skutecne))
    if v_chybe := _names(m for m in klicove if "v pásmu chyby" in m.get("zmena_posouzeni", "")):
        parts.append(f"{'U ostatních' if skutecne else 'U'} klíčových ukazatelů "
                     f"({v_chybe}) je změna v pásmu chyby měření.")
    if bez_mdc := _names(m for m in klicove if "nelze posoudit" in m.get("zmena_posouzeni", "")):
        parts.append(f"Změnu nelze posoudit, protože chybí MDC: {bez_mdc}.")
    if nove := _names(m for m in klicove if "zmena" not in m):
        parts.append(f"Poprvé měřeno: {nove}.")

    if over := [a for a in facts.get("asymetrie", []) if a["nad_prahem"]]:
        prah = over[0]["prah_procent"]
        parts.append(
            f"Stranový rozdíl nad {prah} %:\n" + "\n".join(
                f"• {a['metrika']}{' (' + a['upresneni'] + ')' if a['upresneni'] else ''}: "
                f"{_cz(a['rozdil_procent'])} %, vyšší hodnota {a['vyssi_hodnota']}"
                for a in over)
        )

    if suppressed:
        parts.append(
            "Následující nálezy nevedly k doporučení kvůli zdravotnímu omezení:\n"
            + "\n".join(f"• {f.text} ({f.suppressed_reason})" for f in suppressed)
        )

    parts.append("Úplné výsledky všech testů jsou v tabulkách níže.")

    if recommendations(active):
        parts.append("Doporučení jsou uvedena v samostatné části zprávy.")

    if citations:
        pocet = len(citations)
        parts.append(
            f"Doporučení se opírají o {pocet} "
            f"{plural(pocet, 'citovaný zdroj', 'citované zdroje', 'citovaných zdrojů')} "
            f"{'uvedený' if pocet == 1 else 'uvedené'} v závěru zprávy."
        )
    return "\n\n".join(parts)


def _cz(value) -> str:
    """Číslo z faktů tak, jak tam je – jen s desetinnou čárkou."""
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text.replace(".", ",").replace("-", "−")


def _names(metrics) -> str:
    """Názvy metrik bez opakování (jedna metrika má často víc kombinací)."""
    seen = []
    for m in metrics:
        if m["metrika"] not in seen:
            seen.append(m["metrika"])
    return ", ".join(_lower_first(name) for name in seen)


def _lower_first(name: str) -> str:
    """„Výška výskoku“ → „výška výskoku“, ale „Dynamic Strength Index“ a „RSI“ zůstanou."""
    words = name.split()
    if not words or words[0].isupper() or (len(words) > 1 and words[1][:1].isupper()):
        return name
    return name[0].lower() + name[1:]


def _metric_line(m: dict) -> str:
    unit = f" {m['jednotka']}" if m["jednotka"] and m["jednotka"] != "-" else ""
    name = m["metrika"] + (f" ({m['upresneni']})" if m["upresneni"] else "")
    zmena = m["zmena"]
    sign = "+" if zmena > 0 else ""
    return (f"• {name}: {_cz(m['hodnota'])}{unit}; minule {_cz(m['predchozi_hodnota'])}{unit}, "
            f"změna {sign}{_cz(zmena)}{unit} – {m['zmena_posouzeni']}")


def recommendations(findings) -> list[str]:
    """Doporučení z pravidel, bez opakování a bez potlačených nálezů."""
    from apps.rules.engine import formatter

    out = []
    for finding in findings:
        if finding.suppressed:
            continue
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

9. Pole cmj_ods dělí ukazatele skoku na výsledek, příčinu a strategii. \
Změnu výsledku vysvětluj jen změnami příčin a strategie, které mají posouzení \
„zlepšení“, „zhoršení“ nebo „skutečný posun“; hotové vysvětlení je v poli \
„interpretace“.
10. Vlastní doporučení nevymýšlej. Doporučení z pole doporuceni_z_pravidel \
zpráva uvádí ve zvláštní části; v souhrnu na ně můžeš jen odkázat.

Struktura: celkové zhodnocení (3–5 vět: co se měřilo, jak si sportovec \
stojí, co se proti minulému měření skutečně změnilo), pak „Hlavní zjištění:“ \
s odrážkami – nálezy, skutečné změny a stranové rozdíly nad prahem. \
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

    facts = facts_module.build(session, findings, citations)
    fallback = compose(session, findings, citations, facts)
    if not llm.is_enabled():
        return Composition(text=fallback, source="šablona", facts=facts)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content":
            "Fakta z testování:\n\n" + json.dumps(facts, ensure_ascii=False, indent=2)},
    ]

    seconds = 0.0
    for attempt in (1, 2):
        try:
            reply = llm.chat(messages)
        except llm.LLMError as exc:
            logger.warning("Model se pro %s nepoužil: %s", session.subject.code, exc)
            return Composition(text=fallback, source="šablona", facts=facts,
                               note=f"Jazykový model se nepoužil: {exc}")
        seconds += reply.seconds

        problems = verify_numbers(reply.text, findings, facts)
        if not problems:
            return Composition(
                text=reply.text, source=reply.model, facts=facts,
                note=(f"Text sestavil model {reply.model} za {seconds:.0f} s"
                      + (" (na druhý pokus)." if attempt == 2 else ".")),
            )

        reason = f"obsahoval čísla, která v datech nejsou ({', '.join(problems[:5])})"
        logger.warning("Model %s %s (pokus %s).", reply.model, reason, attempt)
        # Jedna oprava: model dostane vlastní text a výčet čísel navíc.
        # Malé modely občas něco dopočítají; napodruhé to obvykle opraví.
        messages = messages + [
            {"role": "assistant", "content": reply.text},
            {"role": "user", "content":
                f"Text obsahuje čísla, která ve faktech nejsou: {', '.join(problems)}. "
                "Napiš ho znovu a použij jen čísla, která jsou ve faktech, "
                "přesně jak tam jsou. Nic nepočítej."},
        ]

    return Composition(
        text=fallback, source="šablona", facts=facts,
        note=f"Text od modelu {reply.model} byl odmítnut: {reason}. Použita šablona.",
    )


# ---------------------------------------------------------------------------
# Návrh doporučení pro diagnostika
# ---------------------------------------------------------------------------

RECOMMENDATION_PROMPT = """Jsi odborný asistent laboratoře funkční diagnostiky \
na fakultě tělesné výchovy a sportu. Připravuješ NÁVRH doporučení, který \
diagnostik před vydáním zprávy zkontroluje a upraví.

Dostaneš fakta ve formátu JSON: výsledky, změny proti minulému měření, \
stranové rozdíly, nálezy a doporučení z pravidel laboratoře.

Pravidla:
1. Doporučení z pole doporuceni_z_pravidel převezmi a můžeš je rozvést; \
nic v nich neměň ve smyslu ani neoslabuj.
2. Další doporučení navrhuj jen tam, kde k tomu fakta dávají důvod \
(nález, skutečná změna, stranový rozdíl nad prahem). U každého uveď, na který \
výsledek reaguje.
3. Změnu „v pásmu chyby měření“ nevykládej jako zlepšení ani zhoršení.
4. Nestanovuj diagnózy a nedoporučuj léčbu. Kde by šlo o zdravotní otázku, \
doporuč konzultaci s lékařem nebo fyzioterapeutem.
5. Neuváděj studie ani zdroje kromě těch v poli „citace“.
6. Konkrétní dávkování (počty týdnů, sérií, opakování) navrhuj jen \
střídmě; diagnostik ho bude ověřovat.
7. Piš česky, věcně, v odrážkách „•“, nejvýš 8 odrážek. Bez úvodu a závěru."""


@dataclass
class RecommendationDraft:
    text: str
    model: str
    seconds: float
    unverified_numbers: list[str]


def draft_recommendations(report) -> RecommendationDraft:
    """
    Návrh doporučení od modelu. Není to text zprávy: jde do komentáře
    diagnostika a zpráva se nevydá, dokud ho člověk neprojde a neuloží.

    Čísla se tu neodmítají – dávkování (3× týdně, 6 týdnů) v datech být
    nemůže. Místo toho se vypíšou, aby je diagnostik ověřil.
    """
    from apps.rules import evidence

    from . import facts as facts_module
    from . import llm

    session = report.session
    findings = list(session.findings.select_related("rule")) if session else []
    citations = evidence.articles_for(findings)
    facts = facts_module.build(session, findings, citations)

    reply = llm.chat([
        {"role": "system", "content": RECOMMENDATION_PROMPT},
        {"role": "user", "content":
            "Fakta z testování:\n\n" + json.dumps(facts, ensure_ascii=False, indent=2)},
    ])
    return RecommendationDraft(
        text=reply.text.strip(), model=reply.model, seconds=reply.seconds,
        unverified_numbers=verify_numbers(reply.text, findings, facts),
    )


def unsupported_numbers(report, text: str) -> list[str]:
    """Čísla v textu, která nejsou ve výsledcích – pro upozornění, ne zákaz."""
    from apps.rules import evidence

    from . import facts as facts_module

    session = report.session
    if session is None:
        return []
    findings = list(session.findings.select_related("rule"))
    facts = facts_module.build(session, findings, evidence.articles_for(findings))
    return verify_numbers(text, findings, facts)
