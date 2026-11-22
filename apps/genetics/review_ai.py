"""
Návrhy jazykového modelu k úkolům revize karty (apps/genetics/review.py).

Model dostane jen obsah karty: texty, zdroje S1… s abstrakty a hlavními
zjištěními z knihovny článků a kandidátní články z PubMedu k variantě – nový
zdroj smí navrhnout jen z nich a přijde jako článek „navržený, k ověření“.
Každý návrh projde kontrolou (povolené řešení, nepřípustné výroky, značky
k ověření, štítky zdrojů, čísla jen z podkladů); návrh s výhradou nejde
přijmout jedním klikem, jen upravit. Model nic neschvaluje: návrh přijímá
člověk, po jednom, a přijetí se zapíše do revizního záznamu („Návrh AI … přijat“).
Odchází jen obsah karty a literatura – nic o sportovcích.
"""

import json
import logging
import re
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import review, services
from .models import CardRevision, CardSource, ForbiddenStatement, ReviewProposal

logger = logging.getLogger(__name__)

NEW_SOURCE = "[NOVÝ ZDROJ]"
STALLED_MINUTES = 15
CANDIDATES = 6

# Řešení, která model smí navrhnout → akce úkolu (review.act)
TEXT_DECISIONS = {"upravit": "ulozit", "overeno": "overeno", "vyradit": "vyradit"}
AB_DECISIONS = {"upravit_podle_navrhu": "accepted", "ponechat": "rejected", "vyradit": "removed"}
TASK_DECISIONS = {"ponechat": "rejected", "vyradit": "removed"}
CONFIDENCE = {"vysoka": "vysoká", "stredni": "střední", "nizka": "nízká"}
LABELS = {
    "upravit": "upravit text", "overeno": "ověřeno ve zdroji – ponechat text",
    "vyradit": "vyřadit", "upravit_podle_navrhu": "upravit podle návrhu",
    "ponechat": "ponechat", "oduvodnit": "doplnit odůvodnění",
}

PROMPT = """Jsi odborný asistent garantů genetických karet laboratoře funkční diagnostiky \
sportovců. Navrhuješ řešení JEDNOHO úkolu revize karty. Návrh zkontroluje a přijme nebo \
odmítne člověk; ty nic neschvaluješ.

Dostaneš JSON: kartu (texty), zdroje karty (štítky S1… s citací, abstraktem a hlavním \
zjištěním z knihovny), kandidátní články z PubMedu k variantě, nepřípustné výroky a úkol \
s povolenými řešeními.

Pravidla, která nesmíš porušit:
1. Tvrzení jen podle podkladů v datech. Nic si nedomýšlej z vlastní znalosti studií.
2. Když tvrzení podklady nedokládají, navrhni vyřadit větu ("vyradit"), ne ho přeformulovat.
3. Žádné deterministické výroky: genotyp neurčuje výkon, typ svalových vláken, vhodný sport, \
riziko zranění ani účinek doplňků. Žádné dávky, diagnózy ani sliby. Žádný nepřípustný výrok.
4. Čísla jen ta, která jsou v podkladech, přesně jak tam jsou.
5. Odkazuj jen na štítky zdrojů karty v hranatých závorkách, např. [S1]. Článek z kandidátů \
PubMedu označ v textu [NOVÝ ZDROJ] a jeho PMID dej do "novy_zdroj_pmid".
6. V navrženém textu nesmí zůstat značka [OVĚŘIT …] ani [DOPLNIT …].
7. Piš česky, vykej, věcně, ve stylu ostatních textů karty; text nemá být delší než původní.

Odpověz POUZE objektem JSON s klíči:
{"rozhodnuti": jedno z "povolena_rozhodnuti" úkolu,
 "text": nové znění (jen u "upravit"; jinak prázdné),
 "zduvodneni": 1–3 věty, proč, s odkazy na štítky zdrojů,
 "zdroje": ["S1"],
 "novy_zdroj_pmid": PMID z kandidátů nebo null,
 "jistota": "vysoka" | "stredni" | "nizka",
 "overit": co má člověk před přijetím zkontrolovat}

Významy řešení: "upravit" = nové znění textu; "overeno" = zdroj tvrzení dokládá, stačí \
odstranit značku (text se nemění); "vyradit" = věty se značkou (u záznamu položka) z karty \
pryč; "upravit_podle_navrhu" = přijmout navržené znění revizního záznamu; "ponechat" = \
ponechat původní znění / beze změny; "oduvodnit" = jen napsat odůvodnění už rozhodnutého \
záznamu."""


def available() -> bool:
    from apps.reports import llm

    return llm.is_enabled()


def allowed(task) -> dict:
    if task.kind == review.REVISION:
        if task.revision.decision != CardRevision.Decision.OPEN:
            return {"oduvodnit": "oduvodnit"}
        return AB_DECISIONS if task.is_ab else TASK_DECISIONS
    if task.kind == review.MISSING:
        return {"upravit": "ulozit"}
    return {k: v for k, v in TEXT_DECISIONS.items() if k != "overeno" or task.verifiable}


# --- PubMed ----------------------------------------------------------------------------

def pubmed_candidates(card) -> tuple[list[dict], str]:
    """Články k variantě z PubMedu, které karta ještě nemá; (seznam, proč žádné)."""
    from apps.evidence import lookup

    variant = card.variant
    known = set()
    for source in card.sources.select_related("article"):
        if source.article_id:
            known |= {source.article.pmid, (source.article.doi or "").lower()}
        known |= {d.lower() for d in lookup.DOI.findall(source.citation + " " + source.url)}
    known.discard("")
    term = (f"{variant.rsid}[All Fields] AND (exercise[All Fields] OR athlete*[All Fields] "
            "OR sport*[All Fields] OR training[All Fields] OR performance[All Fields])")
    try:
        ids = [i for i in lookup.search_pubmed(term, retmax=CANDIDATES + 4) if i not in known]
        rows = lookup.fetch_pubmed_many(ids[:CANDIDATES + 2])
    except lookup.LookupError_ as exc:
        return [], str(exc)
    rows = [r for r in rows if (r.get("doi") or "").lower() not in known]
    return rows[:CANDIDATES], "" if rows else "PubMed k variantě nic dalšího nenašel."


# --- podklady pro model ------------------------------------------------------------------

def _sources(card) -> list[dict]:
    out = []
    for s in card.sources.select_related("article").order_by("order", "pk"):
        a = s.article
        out.append({"stitek": s.label, "k_cemu": s.title, "citace": s.citation, "odkaz": s.url,
                    "abstrakt": a.abstract if a else "",
                    "hlavni_zjisteni": a.key_finding if a else "",
                    "omezeni": a.limitations if a else "",
                    "uroven_evidence": a.get_evidence_level_display() if a and a.evidence_level
                    else ""})
    return out


def facts(card, task, candidates: list[dict], original_text: str = "") -> dict:
    variant = card.variant
    forbidden = [f.text for f in (ForbiddenStatement.objects.filter(card=card)
                                  | ForbiddenStatement.objects.filter(card__isnull=True))]
    task_data = {"druh": task.kind, "nazev": task.title, "kde_se_objevi": task.where,
                 "problemy": task.problems, "text": task.current,
                 "puvodni_zneni_z_podkladu": original_text,
                 "povolena_rozhodnuti": list(allowed(task))}
    if task.revision is not None:
        r = task.revision
        task_data["revizni_zaznam"] = {"cast": r.part, "puvodni_zneni": r.original,
                                       "navrh": r.proposal, "duvod_nebo_ukol": r.reason,
                                       "zdroj": r.source,
                                       "rozhodnuto": r.get_decision_display()
                                       if r.decision != CardRevision.Decision.OPEN else ""}
    return {
        "karta": {"gen": variant.gene, "rsid": variant.rsid, "zapis": variant.notation,
                  "oblast": variant.domain.name,
                  "biologie_pro_klienta": card.biology_client,
                  "omezeni_interpretace": card.limitations,
                  "texty_pro_genotypy": {variant.genotype_label(t.genotype): t.client_text
                                         for t in card.genotype_texts.all()}},
        "zdroje_karty": _sources(card),
        "kandidati_pubmed": [{"pmid": c.get("pmid"), "nazev": c.get("title"),
                              "autori": c.get("authors"), "casopis": c.get("journal"),
                              "rok": c.get("year"), "doi": c.get("doi"),
                              "abstrakt": c.get("abstract")} for c in candidates],
        "nepripustne_vyroky": forbidden,
        "ukol": task_data,
    }


# --- kontrola návrhu ---------------------------------------------------------------------

def _labels_in(text: str) -> set:
    return {label for inside in re.findall(r"\[([^\]]*)\]", text or "")
            for label in re.findall(r"\bS\d+\b", inside)}


def check(card, task, proposal, candidates: list[dict], source_text: str) -> list[str]:
    from apps.evidence.ai_draft import unsupported_numbers

    issues = []
    if proposal.decision not in allowed(task):
        issues.append(f"Řešení „{proposal.decision}“ u tohoto úkolu nejde – zvolte ho ručně.")
    if not proposal.justification.strip():
        issues.append("Návrh nemá zdůvodnění.")
    if proposal.new_source and proposal.new_source.get("pmid") not in {
            c.get("pmid") for c in candidates}:
        issues.append("Nový zdroj není mezi články nalezenými v PubMedu.")
    if proposal.decision != "upravit":
        return issues
    text = proposal.text.strip()
    if not text:
        issues.append("Návrh nemá text.")
    if services.MARKER.search(text):
        issues.append("V navrženém textu zůstala značka k ověření.")
    if task.blocking and (hits := services.forbidden_in(card, text)):
        issues.append(f"Návrh obsahuje nepřípustný výrok „{hits[0]}“.")
    known = {s.label for s in card.sources.all() if s.label}
    if unknown := sorted(_labels_in(text) - known):
        issues.append("Návrh odkazuje na zdroj, který karta nemá: " + ", ".join(unknown) + ".")
    if NEW_SOURCE in text and not proposal.new_source:
        issues.append("Návrh odkazuje na nový zdroj, ale článek z PubMedu neuvedl.")
    if proposal.new_source and NEW_SOURCE not in text:
        issues.append("Nový zdroj je navržený, ale text na něj neodkazuje.")
    plain = re.sub(r"\[[^\]]*\]", "", text)
    if numbers := unsupported_numbers(plain, source_text):
        issues.append("Čísla, která v podkladech nejsou: " + ", ".join(numbers[:5]) + ".")
    return issues


# --- generování ----------------------------------------------------------------------------

def _stalled(proposal) -> bool:
    return (proposal.status == ReviewProposal.Status.PENDING
            and proposal.updated_at < timezone.now() - timedelta(minutes=STALLED_MINUTES))


def card_state(card, tasks) -> dict:
    """Stav návrhů karty pro obrazovky: kolik je připraveno, zda se právě připravují."""
    rows = {p.task_key: p for p in card.review_proposals.all()}
    current = [rows.get(t.key) for t in tasks]
    pending = [p for p in current if p and p.status == ReviewProposal.Status.PENDING
               and not _stalled(p)]
    ready = [p for p, t in zip(current, tasks, strict=True)
             if p and p.status == ReviewProposal.Status.READY and p.base == t.base]
    return {"available": available(), "pending": len(pending), "ready": len(ready),
            "open": len(tasks), "running": bool(pending)}


def proposal_for(card, task):
    proposal = card.review_proposals.filter(task_key=task.key).first()
    if proposal is None:
        return None
    proposal.fresh = proposal.base == task.base
    proposal.stalled = _stalled(proposal)
    proposal.label = LABELS.get(proposal.decision, proposal.decision)
    proposal.confidence_label = CONFIDENCE.get(proposal.confidence, proposal.confidence)
    return proposal


def _skip(proposal, task, *, explicit: bool) -> bool:
    """Platný návrh se znovu nepřipravuje; odmítnutý jen na výslovné přání."""
    status = ReviewProposal.Status
    if proposal is None:
        return False
    if proposal.status == status.PENDING and not _stalled(proposal):
        return True
    if proposal.base != task.base or proposal.status == status.FAILED:
        return False
    return not explicit


def start(card, *, model: str | None = None, keys: list[str] | None = None) -> int:
    """
    Připraví návrhy k otevřeným úkolům karty (nebo jen k ``keys``), které ještě
    platný návrh nemají. Na pozadí, bez LLM_BACKGROUND (testy) hned. Vrací počet.
    """
    from apps.reports.ai_models import default_model

    if not available():
        raise review.ActionError("Jazykový model není zapnutý – návrhy AI zapne správce "
                                 "v Nastavení → Klíče a model.")
    model = model or default_model()
    tasks = [t for t in review.tasks_for(card) if keys is None or t.key in keys]
    queued = 0
    for task in tasks:
        if _skip(card.review_proposals.filter(task_key=task.key).first(), task,
                 explicit=keys is not None):
            continue
        ReviewProposal.objects.update_or_create(
            card=card, task_key=task.key,
            defaults={"base": task.base, "status": ReviewProposal.Status.PENDING,
                      "decision": "", "text": "", "justification": "", "labels": [],
                      "new_source": {}, "confidence": "", "verify": "", "issues": [],
                      "model": model, "error": "", "accepted_by": None, "accepted_at": None})
        queued += 1
    if not queued:
        return 0
    if not settings.LLM_BACKGROUND:
        generate(card.pk, model)
        return queued
    import threading

    def run():
        from django.db import connection

        try:
            generate(card.pk, model)
        except Exception as exc:  # nic nesmí nechat návrhy viset ve stavu „připravuje se“
            logger.exception("Návrhy AI ke kartě %s selhaly", card.pk)
            ReviewProposal.objects.filter(card_id=card.pk,
                                          status=ReviewProposal.Status.PENDING).update(
                status=ReviewProposal.Status.FAILED, error=f"Návrh selhal: {exc}"[:500])
        finally:
            connection.close()

    transaction.on_commit(lambda: threading.Thread(target=run, daemon=True).start())
    return queued


def generate(card_pk: int, model: str) -> None:
    from .card_wizard import _original
    from .models import GeneCard as Card

    card = Card.objects.select_related("variant", "variant__domain").get(pk=card_pk)
    candidates, note = pubmed_candidates(card)
    original, _ = _original(card)
    for proposal in list(card.review_proposals.filter(status=ReviewProposal.Status.PENDING)):
        card.refresh_from_db()
        task = review.find(review.tasks_for(card), proposal.task_key)
        if task is None:
            proposal.delete()
            continue
        _propose(card, task, proposal, candidates, note, model, original)


def _propose(card, task, proposal, candidates, note, model, original) -> None:
    from apps.evidence.ai_draft import DraftError, _json_value
    from apps.reports import llm

    data_in = facts(card, task, candidates, review.original_text(task, original))
    content = json.dumps(data_in, ensure_ascii=False, indent=1)
    messages = [{"role": "system", "content": PROMPT}, {"role": "user", "content": content}]
    try:
        reply = llm.chat(messages, model=model, temperature=0.2)
        try:
            data = _json_value(reply.text)
        except DraftError:
            messages += [{"role": "assistant", "content": reply.text},
                         {"role": "user", "content": "Odpověz znovu, POUZE platným objektem "
                                                     "JSON se stejnými klíči, bez dalšího textu."}]
            reply = llm.chat(messages, model=model, temperature=0.2)
            data = _json_value(reply.text)
    except (llm.LLMError, DraftError) as exc:
        proposal.status, proposal.error = ReviewProposal.Status.FAILED, str(exc)[:500]
        proposal.save()
        return
    pmid = str(data.get("novy_zdroj_pmid") or "").strip()
    chosen = next((c for c in candidates if c.get("pmid") == pmid), None) if pmid else None
    proposal.decision = str(data.get("rozhodnuti") or "").strip()
    proposal.text = str(data.get("text") or "").strip()
    proposal.justification = str(data.get("zduvodneni") or "").strip()
    proposal.labels = [str(x) for x in data.get("zdroje") or [] if x][:10]
    proposal.new_source = chosen or ({"pmid": pmid} if pmid else {})
    proposal.confidence = str(data.get("jistota") or "")[:12]
    proposal.verify = str(data.get("overit") or "").strip()
    if note and not candidates:
        proposal.verify = (proposal.verify + f" (PubMed: {note})").strip()
    proposal.model = reply.model
    proposal.issues = check(card, task, proposal, candidates, content)
    proposal.status = ReviewProposal.Status.READY
    proposal.base = task.base
    proposal.save()


# --- přijetí ------------------------------------------------------------------------------

def _citation(data: dict) -> str:
    authors = data.get("authors") or ""
    parts = [p.strip() for p in authors.split(",") if p.strip()]
    who = (parts[0] + " et al.") if len(parts) > 2 else ", ".join(parts)
    year = f" ({data['year']})" if data.get("year") else ""
    doi = f" https://doi.org/{data['doi']}" if data.get("doi") else ""
    return f"{who}{year}. {data.get('title', '').rstrip('.')}. {data.get('journal', '')}." \
           f"{doi} PMID {data.get('pmid', '')}.".strip()


def _add_source(card, data: dict) -> CardSource:
    from apps.evidence.models import Article

    article = None
    if data.get("pmid"):
        article = Article.objects.filter(pmid=data["pmid"]).first()
    if article is None and data.get("doi"):
        article = Article.objects.filter(doi__iexact=data["doi"]).first()
    if article is not None and (same := card.sources.filter(article=article).first()):
        return same                       # článek už karta má – stejný štítek
    numbers = [int(m.group(1)) for s in card.sources.all()
               if (m := re.fullmatch(r"S(\d+)", s.label or ""))]
    label = f"S{max(numbers, default=0) + 1}"
    if article is None:
        article = Article.objects.create(
            title=data.get("title") or f"PMID {data.get('pmid')}", authors=data.get("authors", ""),
            journal=(data.get("journal") or "")[:300], year=data.get("year"),
            doi=(data.get("doi") or "")[:120], pmid=(data.get("pmid") or "")[:20],
            abstract=data.get("abstract", ""), url=(data.get("url") or "")[:500],
            evidence_level=data.get("evidence_level", ""),
            tags=["genetika", card.variant.gene, card.variant.rsid],
            curator_note="Navrženo jazykovým modelem při revizi karty – ověřit.")
    url = f"https://doi.org/{data['doi']}" if data.get("doi") else data.get("url", "")
    return CardSource.objects.create(
        card=card, label=label, title="Nový zdroj z PubMedu (návrh AI) – k ověření",
        citation=_citation(data), url=url[:500], article=article, order=card.sources.count())


@transaction.atomic
def accept(card, task, proposal, *, user) -> str:
    """Přijetí návrhu člověkem – jeden úkol, s odůvodněním z návrhu."""
    if proposal.status != ReviewProposal.Status.READY or proposal.base != task.base:
        raise review.ActionError("Návrh je ke staršímu znění úkolu – připravte ho znovu.")
    if proposal.issues:
        raise review.ActionError("Návrh má výhrady kontroly – upravte ho ručně.")
    action = allowed(task)[proposal.decision]
    note = f"Návrh AI ({proposal.model}) přijat: {proposal.justification}".strip()
    text, source = proposal.text, ""
    if proposal.new_source and NEW_SOURCE in text:
        added = _add_source(card, proposal.new_source)
        text, source = text.replace(NEW_SOURCE, f"[{added.label}]"), added.citation
    message = review.act(card, task, action, user=user, text=text, note=note, source=source)
    proposal.status = ReviewProposal.Status.USED
    proposal.accepted_by, proposal.accepted_at = user, timezone.now()
    proposal.save(update_fields=["status", "accepted_by", "accepted_at", "updated_at"])
    return message


def dismiss(card, task) -> None:
    card.review_proposals.filter(task_key=task.key).update(
        status=ReviewProposal.Status.DISMISSED, updated_at=timezone.now())
