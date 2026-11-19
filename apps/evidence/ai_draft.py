"""
Návrh hlavního zjištění, omezení a populace článku od jazykového modelu.

Model dostane celý text článku (z nahraného nebo uloženého PDF), jinak
abstrakt. Návrh se uloží zvlášť (Article.ai_draft) a do polí článku se
dostane, až ho kurátor zkontroluje a uloží – zprávy do té doby pracují
s tím, co v článku bylo. Čísla, která v textu článku nejsou, se vypíšou
k ověření.

Běží na pozadí (psaní celého článku trvá desítky sekund až minuty).
"""

import json
import logging
import re
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Article, EvidenceLevel

logger = logging.getLogger(__name__)

MAX_PDF_MB = 30

PROMPT = """Jsi kurátor knihovny vědeckých článků laboratoře funkční diagnostiky \
na fakultě tělesné výchovy a sportu. Z textu článku připravíš NÁVRH podkladu, \
který kurátor zkontroluje. Podklad pak dostává jazykový model, který píše \
zprávy z testování sportovců a smí se o článek opřít jen přes tento podklad.

Odpověz POUZE jedním objektem JSON, bez dalšího textu, s klíči:
- "hlavni_zjisteni": 1–3 věty česky – co studie zjistila a co to znamená pro \
testování nebo trénink sportovců. Konkrétně a prakticky; uveď klíčová čísla \
(korelace, rozdíly, procenta).
- "omezeni": 1–3 věty česky – omezení, na která upozorňují autoři, a zjevná \
omezení designu (velikost vzorku, populace, korelační design, způsob měření).
- "uroven_dukazu": jedna z hodnot "meta" (metaanalýza, systematický přehled), \
"rct" (randomizovaná studie), "cohort" (kohortová), "cross" (průřezová), \
"case" (kazuistika), "expert" (stanovisko), nebo "".
- "populace": objekt s klíči "sport" (česky, např. "tenis"), "pohlavi" \
("M" muži, "F" ženy, "B" obě, "" neuvedeno), "vek_od" a "vek_do" (celá čísla \
nebo null), "uroven" (česky, např. "výkonnostní junioři"), "velikost_vzorku" \
(celé číslo nebo null).

Pravidla:
1. Vycházej jen z dodaného textu. Nic nedomýšlej a nepřidávej znalosti odjinud.
2. Čísla uváděj jen ta, která v textu jsou, a přesně jak tam jsou; desetinnou \
tečku převeď na čárku.
3. Věk od a do vyplň, jen když text uvádí rozpětí nebo věkovou kategorii; když \
uvádí jen průměr ± SD, nech null.
4. Doporučení autorů, která jdou nad rámec jejich dat, označ slovy „autoři \
doporučují“.
5. Piš věcně, bez úvodních frází („Tato studie…“)."""

SOURCE_PDF = "celý text článku (PDF)"
SOURCE_ABSTRACT = "abstrakt"


class DraftError(Exception):
    """Návrh nejde připravit – uživatel se musí dozvědět proč."""


# ---------------------------------------------------------------------------
# Zdrojový text
# ---------------------------------------------------------------------------

def pdf_text(file) -> str:
    """Text z PDF. Sken bez textové vrstvy vrátí prázdný řetězec."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    # PDF z vydavatelů bývají drobně poškozená; pypdf to zvládne, jen o tom píše do logu.
    logging.getLogger("pypdf").setLevel(logging.ERROR)

    try:
        file.seek(0)
        reader = PdfReader(file)
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except (PdfReadError, ValueError, OSError) as exc:
        raise DraftError("PDF se nepodařilo přečíst – je soubor v pořádku?") from exc
    finally:
        file.seek(0)
    return clean_text(text)


REFERENCES = re.compile(r"\n\s*(References|REFERENCES|Bibliography|Literature cited|Literatura|"
                        r"Seznam literatury)\s*\n")


# Závěrečné části článku, které o výsledcích nic neříkají (hlavně u MDPI,
# Frontiers…): příspěvky autorů, financování, etika, dostupnost dat, střet zájmů.
BACK_MATTER = re.compile(
    r"\n\s*(Author Contributions|Funding|Institutional Review Board Statement|"
    r"Informed Consent Statement|Data Availability Statement|Acknowledge?ments?|"
    r"Conflicts? of Interest|Declaration of Competing Interest|Abbreviations|"
    r"Supplementary Materials|Publisher.s Note)\s*[:.\n]", re.IGNORECASE)


def clean_text(text: str) -> str:
    """Bez seznamu literatury a závěrečných formalit (modelu nic neřeknou)."""
    text = text.replace("\r", "")
    matches = list(REFERENCES.finditer(text))
    if matches and matches[-1].start() > len(text) * 0.4:
        text = text[:matches[-1].start()]
    tail = [m.start() for m in BACK_MATTER.finditer(text) if m.start() > len(text) * 0.6]
    if tail:
        text = text[:min(tail)]
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def check_pdf(upload) -> None:
    if not upload.name.lower().endswith(".pdf"):
        raise DraftError("Nahrajte článek jako PDF.")
    if upload.size > MAX_PDF_MB * 1024 * 1024:
        raise DraftError(f"PDF je větší než {MAX_PDF_MB} MB.")


def source_for(article, uploaded=None, *, abstract_only=False) -> tuple[str, str]:
    """Z čeho bude model vycházet: nahrané PDF → uložené PDF → abstrakt."""
    files = () if abstract_only else (uploaded, article.pdf or None)
    if abstract_only and not article.abstract.strip():
        raise DraftError("Článek nemá abstrakt – vložte ho, nebo nechte model číst PDF.")
    for file in files:
        if file is None:
            continue
        if file is article.pdf:
            file.open("rb")
        try:
            text = pdf_text(file)
        finally:
            if file is article.pdf:
                file.close()
        if len(text) > 500:
            return text, SOURCE_PDF
    if article.abstract.strip():
        return article.abstract.strip(), SOURCE_ABSTRACT
    if uploaded is not None or article.pdf:
        raise DraftError("PDF neobsahuje text (asi je to sken) a článek nemá abstrakt. "
                         "Vložte abstrakt, nebo nahrajte PDF s textem.")
    raise DraftError("Model nemá z čeho vycházet: nahrajte PDF článku, nebo vyplňte abstrakt.")


# ---------------------------------------------------------------------------
# Psaní návrhu
# ---------------------------------------------------------------------------

PART_TOPICS = "temata"   # Article.ai_writing_part: model vybírá ukazatele, testy a pravidla


def _failed(part: str, message: str, model: str) -> dict:
    """Návrh, který se nepovedl – u témat pod klíčem „temata“, ať ho ukáže krok 5."""
    failed = {"chyba": message[:500], "model": model}
    return {PART_TOPICS: failed} if part == PART_TOPICS else failed


def start(article, *, model: str | None, text: str, source: str, part: str = "",
          organization=None) -> None:
    """
    Zahájí psaní návrhu – na pozadí, bez LLM_BACKGROUND (testy) hned. ``part``:
    "" = hlavní zjištění, omezení a populace; PART_TOPICS = ukazatele, testy
    a pravidla z katalogu ``organization`` (krok 5 formuláře).
    """
    from apps.reports import llm
    from apps.reports.ai_models import default_model

    if not llm.is_enabled():
        raise DraftError("Jazykový model není zapnutý (LLM_ENABLED).")
    if article.ai_writing:
        raise DraftError("Model už návrh píše – počkejte, až dopíše.")
    model = model or default_model()
    Article.objects.filter(pk=article.pk).update(
        ai_writing_model=model, ai_writing_started_at=timezone.now(), ai_writing_part=part)
    organization_id = getattr(organization, "pk", None)

    def job():
        if part == PART_TOPICS:
            return write_topics(article.pk, model, text, source, organization_id)
        return write(article.pk, model, text, source)

    if not settings.LLM_BACKGROUND:
        job()
        return
    import threading

    def run():
        from django.db import connection

        try:
            job()
        except Exception as exc:  # nic nesmí nechat článek viset ve stavu „píše“
            logger.exception("Návrh k článku %s selhal", article.pk)
            Article.objects.filter(pk=article.pk).update(
                ai_writing_started_at=None, ai_writing_part="",
                ai_draft=_failed(part, str(exc), model))
        finally:
            connection.close()

    transaction.on_commit(lambda: threading.Thread(target=run, daemon=True).start())


def _header(article) -> str:
    header = f"Název: {article.title}\n"
    if article.authors:
        header += f"Autoři: {article.authors}\n"
    if article.journal or article.year:
        header += f"Časopis: {article.journal} {article.year or ''}\n"
    return header


def write(article_pk: int, model: str, text: str, source: str) -> dict:
    from apps.reports import llm

    article = Article.objects.get(pk=article_pk)
    header = _header(article)
    messages = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": f"{header}\nZdroj: {source}\n\n{text}"},
    ]
    try:
        reply = llm.chat(messages, model=model, temperature=0.2)
        try:
            data = parse_reply(reply.text)
        except DraftError:
            # Menší modely občas přidají text okolo; napodruhé to obvykle opraví.
            messages += [{"role": "assistant", "content": reply.text},
                         {"role": "user", "content": "Odpověz znovu, POUZE platným objektem "
                                                     "JSON se stejnými klíči, bez dalšího textu."}]
            seconds = reply.seconds
            reply = llm.chat(messages, model=model, temperature=0.2)
            reply.seconds += seconds
            data = parse_reply(reply.text)
    except (llm.LLMError, DraftError) as exc:
        draft = {"chyba": str(exc)[:500], "model": model}
    else:
        draft = {**data, "model": reply.model, "zdroj": source,
                 "sekund": round(reply.seconds),
                 "cisla_k_overeni": unsupported_numbers(
                     f"{data['hlavni_zjisteni']}\n{data['omezeni']}", text + "\n" + header),
                 "vytvoreno": timezone.now().isoformat()}
    Article.objects.filter(pk=article_pk).update(ai_draft=draft, ai_writing_started_at=None,
                                                 ai_writing_part="")
    return draft


def _json_value(text: str):
    """JSON z odpovědi modelu – i když ho model obalí do ```json … ```."""
    start_, end = text.find("{"), text.rfind("}")
    if start_ < 0 or end <= start_:
        raise DraftError("Model neodpověděl ve formátu JSON.")
    try:
        return json.loads(text[start_:end + 1])
    except json.JSONDecodeError as exc:
        raise DraftError("Model odpověděl neplatným JSON.") from exc


def parse_reply(text: str) -> dict:
    """Hlavní zjištění, omezení, úroveň evidence a populace z odpovědi modelu."""
    data = _json_value(text)
    if not isinstance(data, dict) or not str(data.get("hlavni_zjisteni") or "").strip():
        raise DraftError("V odpovědi modelu chybí hlavní zjištění.")
    population = data.get("populace") if isinstance(data.get("populace"), dict) else {}
    level = str(data.get("uroven_dukazu") or "").strip().lower()
    sex = str(population.get("pohlavi") or "").strip().upper()[:1]
    return {
        "hlavni_zjisteni": str(data["hlavni_zjisteni"]).strip(),
        "omezeni": str(data.get("omezeni") or "").strip(),
        "uroven_dukazu": level if level in EvidenceLevel.values else "",
        "populace": {
            "sport": str(population.get("sport") or "").strip()[:120],
            "pohlavi": sex if sex in ("M", "F", "B") else "",
            "vek_od": _whole(population.get("vek_od")),
            "vek_do": _whole(population.get("vek_do")),
            "uroven": str(population.get("uroven") or "").strip()[:60],
            "velikost_vzorku": _whole(population.get("velikost_vzorku")),
        },
    }


def _whole(value):
    try:
        number = int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        return None
    return number if 0 < number < 100000 else None


# Články často píší malá čísla slovy („Twelve male players“).
WORDS = {word: i for i, word in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty".split())}
WORDS.update({"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
              "eighty": 80, "ninety": 90, "hundred": 100})


def unsupported_numbers(draft: str, source: str) -> list[str]:
    """Čísla v návrhu, která v textu článku nejsou (ani číslicemi, ani slovy)."""
    from apps.reports.narrative import NUMBER, _numbers_in

    known = set()
    _numbers_in(source, known)
    known.update(float(WORDS[w]) for w in re.findall(r"[a-z]+", source.lower()) if w in WORDS)
    out = []
    for raw in NUMBER.findall(draft):
        value = round(abs(float(raw.replace("−", "-").replace(",", "."))), 4)
        if value not in known and raw not in out:
            out.append(raw)
    return out


def clear_stalled(article) -> bool:
    """Psaní, které se nedokončilo (restart aplikace, model neodpověděl)."""
    from apps.reports.ai_models import timeout_for

    if not article.ai_writing:
        return False
    limit = timedelta(seconds=2 * timeout_for(article.ai_writing_model) + 60)
    if timezone.now() - article.ai_writing_started_at < limit:
        return False
    article.ai_draft = _failed(article.ai_writing_part,
                               "Psaní návrhu se nedokončilo (aplikace se mezitím restartovala "
                               "nebo model neodpověděl).", article.ai_writing_model)
    article.ai_writing_started_at = None
    article.ai_writing_part = ""
    article.save(update_fields=["ai_writing_started_at", "ai_draft", "ai_writing_part"])
    return True


# ---------------------------------------------------------------------------
# Návrh → formulář
# ---------------------------------------------------------------------------

def initial_from(draft: dict, article, organization) -> tuple[dict, list[str]]:
    """Předvyplnění formuláře návrhem a seznam polí, která návrh vyplnil."""
    from django.db.models import Q

    from apps.subjects.models import Sport

    initial, filled = {}, []

    def put(field, value, label):
        if value not in (None, ""):
            initial[field] = value
            filled.append(label)

    put("key_finding", draft.get("hlavni_zjisteni"), "hlavní zjištění")
    put("limitations", draft.get("omezeni"), "omezení")
    put("evidence_level", draft.get("uroven_dukazu"), "úroveň evidence")
    population = draft.get("populace") or {}
    put("population_sex", population.get("pohlavi"), "pohlaví")
    put("population_age_min", population.get("vek_od"), "věk od")
    put("population_age_max", population.get("vek_do"), "věk do")
    put("population_level", population.get("uroven"), "úroveň")
    put("sample_size", population.get("velikost_vzorku"), "velikost vzorku")
    if sport := population.get("sport"):
        found = (Sport.objects.filter(Q(organization=organization) | Q(organization__isnull=True))
                 .filter(name__iexact=sport).first())
        if found:
            current = [s.pk for s in article.sports.all()] if article.pk else []
            initial["sports"] = sorted({*current, found.pk})
        else:
            initial["population_sport"] = sport
        filled.append("sport")
    return initial, filled


# ---------------------------------------------------------------------------
# Kdy se článek použije: ukazatele, testy a pravidla (krok 5 formuláře)
# ---------------------------------------------------------------------------

TOPICS_PROMPT = """Jsi kurátor knihovny vědeckých článků laboratoře funkční diagnostiky \
na fakultě tělesné výchovy a sportu. Podle článku vybereš, u kterých ukazatelů, testů \
a pravidel laboratoře se má článek použít. Jazykový model, který píše zprávy z testování \
sportovců, pak článek dostane u sportovce, kterému se vybraný ukazatel nebo test měřil, \
a cituje ho, když vybrané pravidlo najde nález. Kurátor tvůj výběr zkontroluje.

Dostaneš katalog laboratoře: ukazatele, testy a pravidla ve tvaru „kód – název“. \
Vybírej JEN z něj.

Odpověz POUZE jedním objektem JSON, bez dalšího textu, s klíči "ukazatele", "testy" \
a "pravidla". Každý je seznam objektů {"kod": "…", "proc": "…"}; "proc" je jedna krátká \
věta česky, proč článek k položce patří (co studie měřila, zkoumala nebo z čeho vyvozuje závěr).

Pravidla:
1. Vyber jen položky, se kterými studie opravdu pracuje. Obecná souvislost s tématem \
nestačí – raději méně položek než nepřesné.
2. Ukazatel vyber, když studie měří nebo vyhodnocuje tuto veličinu (např. výšku výskoku \
z CMJ). Test vyber, když studie používá tento test nebo jeho obdobu se stejným pohybem \
a měřením.
3. Pravidlo vyber jen tehdy, když článek přímo podporuje jeho podmínku nebo doporučení \
(např. hranici asymetrie nebo poměru, se kterou pravidlo pracuje).
4. Když nic nesedí, vrať prázdný seznam.
5. Kódy opiš přesně z katalogu."""

SOURCE_FINDING = "hlavní zjištění"

# klíč v odpovědi modelu, pole formuláře, popisek
TOPICS = (("ukazatele", "metrics", "ukazatele"), ("testy", "protocols", "testy"),
          ("pravidla", "rules", "pravidla"))


def topics_source(article, uploaded=None) -> tuple[str, str]:
    """K výběru témat stačí hlavní zjištění a abstrakt; bez nich celý text z PDF."""
    parts = []
    if article.key_finding.strip():
        parts.append(f"Hlavní zjištění (od kurátora): {article.key_finding.strip()}")
    if article.abstract.strip():
        parts.append(f"Abstrakt:\n{article.abstract.strip()}")
    if parts:
        return "\n\n".join(parts), (SOURCE_ABSTRACT if article.abstract.strip()
                                    else SOURCE_FINDING)
    return source_for(article, uploaded)


def topics_catalog(organization) -> dict:
    """
    Z čeho jde vybírat (stejně jako ve formuláři): aktivní ukazatele a testy
    a pravidla – sdílené z katalogu a vlastní pracoviště. Kód → záznam a text
    katalogu pro model (u ukazatele i testy, ve kterých se měří, u pravidla
    podmínka slovy).
    """
    from django.db.models import Q

    from apps.catalog.models import MetricDef, Protocol
    from apps.rules.models import Rule
    from apps.rules.steps import describe

    mine = Q(organization__isnull=True)
    if organization is not None:
        mine |= Q(organization=organization)
    own_last = lambda item: item.organization_id is not None  # noqa: E731  (vlastní přepíše sdílený)
    metrics = sorted(MetricDef.objects.filter(mine, is_active=True)
                     .prefetch_related("protocol_metrics__protocol"), key=own_last)
    protocols = sorted(Protocol.objects.filter(mine, is_active=True), key=own_last)
    rules = list(Rule.objects.filter(mine).order_by("code", "version"))
    catalog = {"metrics": {m.code.lower(): m for m in metrics},
               "protocols": {p.code.lower(): p for p in protocols},
               "rules": {r.code.lower(): r for r in rules}}   # nejvyšší verze pravidla

    by_code = {m.code: m for m in metrics}

    def metric_line(m):
        tests = sorted({pm.protocol.name for pm in m.protocol_metrics.all()
                        if pm.protocol.is_active})
        unit = f" [{m.unit}]" if m.unit and m.unit != "-" else ""
        return f"{m.code} – {m.name}{unit}" + (f" (testy: {', '.join(tests)})" if tests else "")

    def rule_line(r):
        condition = describe(r.condition, by_code) if r.condition else ""
        return (f"{r.code} – {r.name}" + (f": {condition}" if condition else "")
                + ("" if r.is_active else " (vypnuté)"))

    catalog["text"] = (
        "UKAZATELE\n" + "\n".join(metric_line(m) for m in catalog["metrics"].values())
        + "\n\nTESTY\n" + "\n".join(f"{p.code} – {p.name}" + (f" ({p.device})" if p.device else "")
                                    for p in catalog["protocols"].values())
        + "\n\nPRAVIDLA\n" + ("\n".join(rule_line(r) for r in catalog["rules"].values())
                                or "(žádná)"))
    return catalog


def write_topics(article_pk: int, model: str, text: str, source: str,
                 organization_id: int | None = None) -> dict:
    from apps.core.models import Organization
    from apps.reports import llm

    article = Article.objects.get(pk=article_pk)
    organization = (Organization.objects.filter(pk=organization_id).first()
                    if organization_id else None)
    catalog = topics_catalog(organization)
    messages = [
        {"role": "system", "content": TOPICS_PROMPT},
        {"role": "user", "content": f"{_header(article)}\nZdroj: {source}\n\n{text}\n\n"
                                    f"KATALOG LABORATOŘE – vybírej jen odtud\n\n{catalog['text']}"},
    ]
    try:
        reply = llm.chat(messages, model=model, temperature=0.2)
        try:
            data = parse_topics(reply.text, catalog)
        except DraftError:
            messages += [{"role": "assistant", "content": reply.text},
                         {"role": "user", "content": "Odpověz znovu, POUZE platným objektem "
                                                     "JSON s klíči ukazatele, testy a pravidla, "
                                                     "bez dalšího textu."}]
            seconds = reply.seconds
            reply = llm.chat(messages, model=model, temperature=0.2)
            reply.seconds += seconds
            data = parse_topics(reply.text, catalog)
    except (llm.LLMError, DraftError) as exc:
        topics = {"chyba": str(exc)[:500], "model": model}
    else:
        topics = {**data, "model": reply.model, "zdroj": source,
                  "sekund": round(reply.seconds), "vytvoreno": timezone.now().isoformat()}
    Article.objects.filter(pk=article_pk).update(
        ai_draft={PART_TOPICS: topics}, ai_writing_started_at=None, ai_writing_part="")
    return topics


def parse_topics(text: str, catalog: dict) -> dict:
    """Výběr z odpovědi modelu – jen kódy, které v katalogu jsou; ostatní jmenuje."""
    data = _json_value(text)
    if not isinstance(data, dict) or not any(key in data for key, _, _ in TOPICS):
        raise DraftError("V odpovědi modelu chybí ukazatele, testy i pravidla.")
    out, unknown = {}, []
    for key, field, _ in TOPICS:
        items = data.get(key)
        picked, seen = [], set()
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict):
                code = item.get("kod") or item.get("kód") or item.get("code")
                why = item.get("proc") or item.get("proč") or ""
            else:
                code, why = item, ""
            code = str(code or "").strip()
            found = catalog[field].get(code.lower())
            if found is None:
                if code and code not in unknown:
                    unknown.append(code)
                continue
            if found.pk in seen:
                continue
            seen.add(found.pk)
            picked.append({"pk": found.pk, "kod": found.code, "nazev": found.name,
                           "proc": " ".join(str(why).split())[:300]})
        out[key] = picked
    out["nezname"] = unknown[:20]
    return out


def topics_initial(topics: dict, article) -> tuple[dict, dict, list[str]]:
    """
    Návrh témat → zaškrtnutí ve formuláři: k tomu, co už je vybrané (nic se
    neodškrtne). Vrátí počáteční hodnoty, navržené položky po polích
    ({pk: proč} – pro značku AI) a popis, co návrh vyplnil.
    """
    current = {
        "metrics": set(article.metrics.values_list("pk", flat=True)),
        "protocols": set(article.protocols.values_list("pk", flat=True)),
        "rules": set(article.rule_articles.values_list("rule_id", flat=True)),
    }
    initial, suggested, filled = {}, {}, []
    for key, field, label in TOPICS:
        items = topics.get(key) or []
        suggested[field] = {item["pk"]: item.get("proc") or "navrženo AI" for item in items}
        if items:
            initial[field] = sorted(current[field] | set(suggested[field]))
            filled.append(f"{label} {len(items)}")
    return initial, suggested, filled
