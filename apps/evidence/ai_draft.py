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


def clean_text(text: str) -> str:
    """Bez seznamu literatury (modelu nic neřekne) a bez zbytečných mezer."""
    text = text.replace("\r", "")
    matches = list(REFERENCES.finditer(text))
    if matches and matches[-1].start() > len(text) * 0.4:
        text = text[:matches[-1].start()]
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def check_pdf(upload) -> None:
    if not upload.name.lower().endswith(".pdf"):
        raise DraftError("Nahrajte článek jako PDF.")
    if upload.size > MAX_PDF_MB * 1024 * 1024:
        raise DraftError(f"PDF je větší než {MAX_PDF_MB} MB.")


def source_for(article, uploaded=None) -> tuple[str, str]:
    """Z čeho bude model vycházet: nahrané PDF → uložené PDF → abstrakt."""
    for file in (uploaded, article.pdf or None):
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

def start(article, *, model: str | None, text: str, source: str) -> None:
    """Zahájí psaní návrhu – na pozadí, bez LLM_BACKGROUND (testy) hned."""
    from apps.reports import llm
    from apps.reports.ai_models import default_model

    if not llm.is_enabled():
        raise DraftError("Jazykový model není zapnutý (LLM_ENABLED).")
    if article.ai_writing:
        raise DraftError("Model už návrh píše – počkejte, až dopíše.")
    model = model or default_model()
    Article.objects.filter(pk=article.pk).update(
        ai_writing_model=model, ai_writing_started_at=timezone.now())
    if not settings.LLM_BACKGROUND:
        write(article.pk, model, text, source)
        return
    import threading

    def run():
        from django.db import connection

        try:
            write(article.pk, model, text, source)
        except Exception as exc:  # nic nesmí nechat článek viset ve stavu „píše“
            logger.exception("Návrh k článku %s selhal", article.pk)
            Article.objects.filter(pk=article.pk).update(
                ai_writing_started_at=None, ai_draft={"chyba": str(exc)[:500]})
        finally:
            connection.close()

    transaction.on_commit(lambda: threading.Thread(target=run, daemon=True).start())


def write(article_pk: int, model: str, text: str, source: str) -> dict:
    from apps.reports import llm

    article = Article.objects.get(pk=article_pk)
    header = f"Název: {article.title}\n"
    if article.authors:
        header += f"Autoři: {article.authors}\n"
    if article.journal or article.year:
        header += f"Časopis: {article.journal} {article.year or ''}\n"
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
    Article.objects.filter(pk=article_pk).update(ai_draft=draft, ai_writing_started_at=None)
    return draft


def parse_reply(text: str) -> dict:
    """JSON z odpovědi modelu – i když ho model obalí do ```json … ```."""
    start_, end = text.find("{"), text.rfind("}")
    if start_ < 0 or end <= start_:
        raise DraftError("Model neodpověděl ve formátu JSON.")
    try:
        data = json.loads(text[start_:end + 1])
    except json.JSONDecodeError as exc:
        raise DraftError("Model odpověděl neplatným JSON.") from exc
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
    article.ai_writing_started_at = None
    article.ai_draft = {"chyba": "Psaní návrhu se nedokončilo (aplikace se mezitím restartovala "
                                 "nebo model neodpověděl).", "model": article.ai_writing_model}
    article.save(update_fields=["ai_writing_started_at", "ai_draft"])
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
