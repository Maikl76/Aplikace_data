"""
Popisy ukazatelů a testů pro klienta – návrh jazykovým modelem.

Ukazatele mají odborný název a jednotku, ale ne větu pro laika. Model
navrhne jednu větu „co to znamená“ pro sportovce a jednu pro trenéra
(u testu, jak probíhá); laboratoř návrh zkontroluje a uloží – do té doby
se v portálu ani ve zprávě nic neukazuje. Model nedostává žádná data
sportovců, jen katalog.
"""

import json

from apps.reports import llm

PROMPT = """Jsi diagnostik laboratoře funkční diagnostiky na fakultě tělesné výchovy \
a sportu. Píšeš krátké popisy ukazatelů a testů pro klienty laboratoře. Dostaneš \
seznam ukazatelů a testů z katalogu.

Pro každý ukazatel napiš:
- "sportovec": jedna věta (nejvýš 25 slov) česky, laicky, vykání – co ukazatel \
vyjadřuje a proč na něm záleží.
- "trener": jedna věta pro trenéra – co ukazatel vyjadřuje a k čemu v tréninku \
slouží; odborné pojmy mohou zůstat.
Pro každý test napiš:
- "sportovec": jedna až dvě věty, co sportovec při testu dělá a co se měří.

Odpověz POUZE jedním objektem JSON, bez dalšího textu:
{"ukazatele": {"kod": {"sportovec": "…", "trener": "…"}}, "testy": {"kod": {"sportovec": "…"}}}

Pravidla:
1. Žádná čísla, normy, hodnocení ani sliby o výkonu; žádná diagnóza a lékařské pojmy.
2. Nezačínej větu názvem ukazatele – název je vedle textu.
3. Vycházej jen z dodaného názvu, jednotky, směru a popisu; nic nedomýšlej.
4. Klíče použij přesně tak, jak jsou v zadání (kod)."""

CHUNK = 12
MAX_LENGTH = 300


class SuggestError(Exception):
    pass


def _describe_metric(m, tests: list[str]) -> str:
    bits = [f"kod: {m.code}", f"název: {m.name}"]
    if m.unit and m.unit != "-":
        bits.append(f"jednotka: {m.unit}")
    bits.append(f"žádoucí směr: {m.get_direction_display().lower()}")
    bits.append(f"rodina testů: {m.get_family_display().lower()}")
    if m.description:
        bits.append(f"popis: {m.description[:200]}")
    if tests:
        bits.append(f"testy: {', '.join(tests)}")
    return "- " + "; ".join(bits)


def _describe_protocol(p) -> str:
    bits = [f"kod: {p.code}", f"název: {p.name}"]
    if p.device:
        bits.append(f"přístroj: {p.device}")
    if p.description:
        bits.append(f"popis procedury: {p.description[:300]}")
    names = [pm.metric.name for pm in p.protocol_metrics.all()]
    if names:
        bits.append(f"ukazatele: {', '.join(names[:8])}")
    return "- " + "; ".join(bits)


def parse_reply(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise SuggestError("Model neodpověděl ve formátu JSON.")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise SuggestError("Model odpověděl neplatným JSON.") from exc
    if not isinstance(data, dict):
        raise SuggestError("Model neodpověděl objektem JSON.")
    return data


def _clean(value) -> str:
    text = " ".join(str(value or "").split())
    return text[:MAX_LENGTH]


def _ask(items: list, *, model) -> dict:
    """Jedna dávka: ukazatele i testy dohromady, nejvýš CHUNK položek."""
    metrics = [(m, tests) for kind, m, tests in items if kind == "ukazatel"]
    protocols = [p for kind, p, _ in items if kind == "test"]
    parts = []
    if metrics:
        parts.append("Ukazatele:\n" + "\n".join(_describe_metric(m, t) for m, t in metrics))
    if protocols:
        parts.append("Testy:\n" + "\n".join(_describe_protocol(p) for p in protocols))
    messages = [{"role": "system", "content": PROMPT},
                {"role": "user", "content": "\n\n".join(parts)}]
    try:
        reply = llm.chat(messages, model=model, temperature=0.3)
        try:
            data = parse_reply(reply.text)
        except SuggestError:
            messages += [{"role": "assistant", "content": reply.text},
                         {"role": "user", "content": "Odpověz znovu, POUZE platným objektem "
                                                     "JSON se stejnými klíči, bez dalšího textu."}]
            reply = llm.chat(messages, model=model, temperature=0.3)
            data = parse_reply(reply.text)
    except llm.LLMError as exc:
        raise SuggestError(str(exc)) from exc
    out = {"ukazatele": {}, "testy": {}, "model": reply.model}
    for m, _ in metrics:
        row = (data.get("ukazatele") or {}).get(m.code) or {}
        if isinstance(row, dict) and (row.get("sportovec") or row.get("trener")):
            out["ukazatele"][m.code] = {"sportovec": _clean(row.get("sportovec")),
                                       "trener": _clean(row.get("trener"))}
    for p in protocols:
        row = (data.get("testy") or {}).get(p.code) or {}
        if isinstance(row, dict) and row.get("sportovec"):
            out["testy"][p.code] = {"sportovec": _clean(row.get("sportovec"))}
    return out


def suggest(metrics, protocols, *, model: str | None = None) -> dict:
    """
    Návrhy pro dané ukazatele (seznam (metrika, [názvy testů])) a testy.
    Vrací {"ukazatele": {kod: {"sportovec", "trener"}}, "testy": {kod: {"sportovec"}}, "model"}.
    """
    if reason := llm.blocked_reason():
        raise SuggestError(reason)
    items = ([("ukazatel", m, tests) for m, tests in metrics]
             + [("test", p, None) for p in protocols])
    out = {"ukazatele": {}, "testy": {}, "model": ""}
    for i in range(0, len(items), CHUNK):
        part = _ask(items[i:i + CHUNK], model=model)
        out["ukazatele"].update(part["ukazatele"])
        out["testy"].update(part["testy"])
        out["model"] = part["model"]
    return out
