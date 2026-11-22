"""
Revize karty krok za krokem: jedna fronta úkolů, jeden úkol na obrazovce.

Úkoly se skládají z dat karty, zvlášť se neukládají:
- text se značkou k ověření ([OVĚŘIT …], [DOPLNIT …]) nebo s nepřípustným výrokem,
- nerozhodnutý revizní záznam a rozhodnutý záznam bez odůvodnění,
- chybějící text pro klienta (genotyp, vysvětlení biologické funkce).

Úkol zmizí, když je vyřešený. Každé vyřešení textu se zapíše jako revizní
záznam (původní znění, nové znění, důvod, kdo a kdy) – nic se při revizi
neztratí bez záznamu. Úkoly připravuje laborant nebo metodik, kartu pak
garant schvaluje ze souhrnu (apps/genetics/review_views.py).
"""

import hashlib
import re
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from . import services
from .card_steps import STEPS
from .models import CardRevision, GeneCard, GenotypeText

TEXT, REVISION, MISSING = "text", "revize", "chybi"

CLIENT = "jde do zprávy pro sportovce"
BOTH = "jde do zprávy pro sportovce i pro lékaře"
CLINICIAN = "jen ve zprávě pro lékaře"
EVIDENCE = "řádek důkazů – do zprávy pro sportovce nejde"
INACTIVE = "scénář je vypnutý – do zprávy zatím nejde"

# Rychlá odůvodnění k výběru (obrazovka úkolu je vloží do pole jedním klikem).
REASONS = {
    TEXT: ["Ověřeno ve zdroji karty.", "Upraveno podle zdroje.",
           "Zjednodušeno a zpřesněno pro klienta.",
           "Tvrzení nejde ze zdrojů doložit – vyřazeno."],
    REVISION: ["Návrh odpovídá zdrojům karty.", "Původní znění je přesnější.",
               "Úkol je hotový – karta upravena.", "Nejde doložit – vyřazeno z karty."],
    MISSING: ["Napsáno podle zdrojů karty.", "Převzato z původního znění a zpřesněno."],
}

PART_STEPS = [("Interpretace genotypu", "genotypy"), ("Frekvence", "genotypy"),
              ("Biologická funkce", "gen"), ("Omezení", "gen"), ("Účinek", "gen"),
              ("Doporučení", "doporuceni"), ("Scénář", "kontext"), ("Dotazník", "kontext"),
              ("Důkaz", "zdroje"), ("Zdroj", "zdroje"), ("Literatura", "zdroje")]


@dataclass
class Task:
    key: str
    kind: str
    title: str
    where: str
    blocking: bool
    step: str
    current: str = ""
    problems: list = field(default_factory=list)
    obj: object = None
    field: str = ""
    revision: CardRevision | None = None
    genotype: str = ""
    order: tuple = ()

    @property
    def base(self) -> str:
        """Otisk stavu úkolu – změní se, když někdo text mezitím upraví."""
        raw = self.current
        if self.revision is not None:
            r = self.revision
            raw = "\n".join([raw, r.part, r.original, r.proposal, r.reason, r.decision])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    @property
    def markers(self) -> list[str]:
        return [m.group(0) for m in services.MARKER.finditer(self.current or "")]

    @property
    def verifiable(self) -> bool:
        """Jen značky k ověření (žádné DOPLNIT ani nepřípustný výrok): stačí potvrdit ověření."""
        return (self.kind == TEXT and bool(self.markers)
                and all("OVĚŘIT" in m and "DOPLNIT" not in m for m in self.markers)
                and not any(p.startswith("nepřípustný") for p in self.problems))

    @property
    def is_ab(self) -> bool:
        return bool(self.revision and self.revision.original and self.revision.proposal)


def _step_for_part(part: str) -> str:
    return next((step for prefix, step in PART_STEPS if part.startswith(prefix)), "kontrola")


def _text_task(card, tasks, key, obj, name, title, where, step, *, client: bool, blocking=None):
    text = getattr(obj, name) or ""
    problems = [f"značka k ověření {m.group(0)}" for m in services.MARKER.finditer(text)]
    if client:
        problems += [f"nepřípustný výrok „{hit}“" for hit in services.forbidden_in(card, text)]
    if problems:
        tasks.append(Task(key=key, kind=TEXT, title=title, where=where,
                          blocking=client if blocking is None else blocking, step=step,
                          current=text, problems=problems, obj=obj, field=name))


def tasks_for(card) -> list[Task]:
    """Otevřené úkoly karty v pořadí: blokující první, pak podle kroků průvodce."""
    variant = card.variant
    tasks: list[Task] = []
    _text_task(card, tasks, "text:karta:biology_client", card, "biology_client",
               "Vysvětlení biologické funkce pro klienta", CLIENT, "gen", client=True)
    _text_task(card, tasks, "text:karta:limitations", card, "limitations",
               "Omezení interpretace", BOTH, "gen", client=True)
    _text_task(card, tasks, "text:karta:biology_expert", card, "biology_expert",
               "Biologická funkce – odborně", CLINICIAN, "gen", client=False)
    _text_task(card, tasks, "text:karta:effect", card, "effect", "Účinek varianty",
               CLINICIAN, "gen", client=False)
    if not card.biology_client.strip():
        tasks.append(Task(key="chybi:biology_client", kind=MISSING, blocking=True, step="gen",
                          title="Vysvětlení biologické funkce pro klienta", where=CLIENT,
                          problems=["text chybí"], obj=card, field="biology_client"))
    texts = {t.genotype: t for t in card.genotype_texts.all()}
    for genotype in variant.genotypes:
        label = variant.genotype_label(genotype)
        text = texts.get(genotype)
        if text is None or not text.client_text.strip():
            tasks.append(Task(key=f"chybi:genotyp:{genotype}", kind=MISSING, blocking=True,
                              step="genotypy", title=f"Text pro genotyp {label}", where=CLIENT,
                              problems=["text chybí"], obj=text, field="client_text",
                              genotype=genotype))
            continue
        _text_task(card, tasks, f"text:genotyp:{text.pk}:client_text", text, "client_text",
                   f"Text pro genotyp {label}", CLIENT, "genotypy", client=True)
        _text_task(card, tasks, f"text:genotyp:{text.pk}:expert_text", text, "expert_text",
                   f"Odborný text pro genotyp {label}", CLINICIAN, "genotypy", client=False)
    for rec in card.recommendations.all():
        who = f"genotyp {variant.genotype_label(rec.genotype)}" if rec.genotype else "všechny genotypy"
        _text_task(card, tasks, f"text:doporuceni:{rec.pk}:text", rec, "text",
                   f"Doporučení – {rec.get_kind_display().lower()} ({who})", CLIENT,
                   "doporuceni", client=True)
    for scenario in card.scenarios.prefetch_related("texts"):
        for text in scenario.texts.all():
            _text_task(card, tasks, f"text:scenar:{text.pk}:text", text, "text",
                       f"Text scénáře „{scenario.statement[:50]}“ pro {text.genotype}",
                       CLIENT if scenario.is_active else INACTIVE, "kontext",
                       client=scenario.is_active)
    for row in card.evidence.all():
        name = row.code or row.trait[:30]
        _text_task(card, tasks, f"text:dukaz:{row.pk}:basis_text", row, "basis_text",
                   f"Řádek důkazů {name} – podklad a omezení", EVIDENCE, "zdroje", client=False)
        _text_task(card, tasks, f"text:dukaz:{row.pk}:usage", row, "usage",
                   f"Řádek důkazů {name} – použití ve zprávě", EVIDENCE, "zdroje", client=False)
    for revision in card.revisions.all():
        if revision.decision == CardRevision.Decision.OPEN:
            problem = "čeká na rozhodnutí"
        elif not revision.decision_note.strip():
            problem = "rozhodnuto bez odůvodnění"
        else:
            continue
        tasks.append(Task(key=f"revize:{revision.pk}", kind=REVISION, blocking=True,
                          step=_step_for_part(revision.part), title=revision.part,
                          where="revizní záznam", problems=[problem], revision=revision,
                          current=_target_text(card, revision)))
    for index, task in enumerate(tasks):
        task.order = (0 if task.blocking else 1, STEPS.index(task.step), index)
    return sorted(tasks, key=lambda t: t.order)


def original_text(task: Task, original) -> str:
    """Stejné místo v původním znění (v1 z podkladů, jinak předchozí verze)."""
    if original is None or task.kind == REVISION:
        return ""
    if task.field in ("client_text", "expert_text"):
        genotype = task.genotype or getattr(task.obj, "genotype", "")
        row = original.genotype_texts.filter(genotype=genotype).first()
        return getattr(row, task.field, "") if row else ""
    if isinstance(task.obj, GeneCard):
        return getattr(original, task.field, "") or ""
    return ""


def find(tasks: list[Task], key: str) -> Task | None:
    return next((t for t in tasks if t.key == key), None)


def next_after(tasks: list[Task], key: str) -> Task | None:
    """Další úkol za zadaným (podle pořadí), jinak první otevřený."""
    keys = [t.key for t in tasks]
    if key in keys:
        later = tasks[keys.index(key) + 1:]
        if later:
            return later[0]
    return next((t for t in tasks if t.key != key), None)


def progress(card, tasks=None) -> dict:
    tasks = tasks_for(card) if tasks is None else tasks
    blocking = sum(1 for t in tasks if t.blocking)
    done = card.revisions.exclude(decision=CardRevision.Decision.OPEN).exclude(
        decision_note="").count()
    total = done + len(tasks)
    return {"blocking": blocking, "optional": len(tasks) - blocking, "done": done,
            "total": total, "open": len(tasks),
            "percent": round(100 * done / total) if total else 100}


# --- úpravy textu ------------------------------------------------------------------

SENTENCE = re.compile(r"(?<=[.!?…])\s+")
# Po zkratce věta nekončí („např. konsenzus“, „Ma et al. 2013“).
ABBREVIATIONS = {"např", "tj", "tzv", "resp", "č", "s", "obr", "min", "max", "cca", "aj", "mj",
                 "př", "vs", "al", "tab", "str", "vyd", "roč", "sv"}


def sentences(paragraph: str) -> list[str]:
    """Věty odstavce; značky [OVĚŘIT …] zůstanou celé, i když obsahují tečku."""
    markers = []

    def hide(match):
        markers.append(match.group(0))
        return f"\x00{len(markers) - 1}\x00"

    text = services.MARKER.sub(hide, paragraph or "")
    out, start = [], 0
    for match in SENTENCE.finditer(text):
        word = re.search(r"(\w+)\.$", text[start:match.start()])
        if word and word.group(1).lower() in ABBREVIATIONS:
            continue
        out.append(text[start:match.start()])
        start = match.end()
    out.append(text[start:])
    return [re.sub(r"\x00(\d+)\x00", lambda m: markers[int(m.group(1))], s) for s in out]


def strip_markers(text: str) -> str:
    """„[S3, OVĚŘIT]“ → „[S3]“, „[OVĚŘIT …]“ pryč – štítky zdrojů zůstanou."""
    def keep_labels(match):
        labels = [p.strip() for p in match.group(0)[1:-1].split(",")
                  if re.fullmatch(r"\s*S\d+\s*", p)]
        return f"[{', '.join(labels)}]" if labels else ""

    out = services.MARKER.sub(keep_labels, text or "")
    return re.sub(r"[ \t]+([.,;:!?])", r"\1", re.sub(r"[ \t]{2,}", " ", out)).strip()


def without_flagged(card, text: str, *, client: bool) -> str:
    """Text bez vět se značkou k ověření (a u textů pro klienta bez nepřípustných výroků)."""
    kept = []
    for paragraph in (text or "").split("\n"):
        kept.append(" ".join(s for s in sentences(paragraph)
                             if s.strip() and not services.MARKER.search(s)
                             and not (client and services.forbidden_in(card, s))))
    return "\n".join(p for p in kept if p.strip()).strip()


# --- revizní záznamy -----------------------------------------------------------------

def revision_target(card, part: str):
    """Pole karty, kterého se revizní záznam týká – jen tam, kde je to jednoznačné."""
    if part.startswith("Interpretace genotypu "):
        row = card.genotype_texts.filter(
            genotype=part.removeprefix("Interpretace genotypu ").strip()).first()
        return (row, "client_text") if row else None
    if part == "Biologická funkce – pro klienta":
        return card, "biology_client"
    if part in ("Biologická funkce – odborně", "Biologická funkce – odborný popis"):
        return card, "biology_expert"
    return None


def _target_text(card, revision) -> str:
    target = revision_target(card, revision.part)
    return (getattr(target[0], target[1]) or "") if target else ""


def apply_revision(card, revision) -> str:
    """
    Rozhodnutí se u interpretace a vysvětlení propíše do textu karty:
    ponechat = původní znění, upravit = návrh, vyřadit = text pryč. Jen když
    text karty je jedno z obou znění – ručně upravený text se nepřepisuje.
    """
    target = revision_target(card, revision.part)
    if target is None or not card.is_editable:
        return ""
    obj, name = target
    current = (getattr(obj, name) or "").strip()
    original, proposal = revision.original.strip(), revision.proposal.strip()
    decision = CardRevision.Decision
    new = None
    if revision.decision == decision.ACCEPTED and proposal and current == original:
        new = proposal
    elif revision.decision == decision.REJECTED and original and current == proposal:
        new = original
    elif revision.decision == decision.REMOVED and current and current in (original, proposal):
        new = ""
    if new is None or new == current:
        return ""
    setattr(obj, name, new)
    obj.save(update_fields=[name, "updated_at"] if obj is card else [name])
    return (f"{revision.part}: text karty upraven podle rozhodnutí "
            f"„{revision.get_decision_display().lower()}“.")


class ActionError(Exception):
    """Akci nejde provést – uživatel se musí dozvědět proč."""


def _record(card, task, *, old: str, new: str, decision, note: str, user, source="") -> None:
    CardRevision.objects.create(
        card=card, part=task.title, original=old, proposal=new,
        reason="Vyřešeno v revizi krok za krokem: " + "; ".join(task.problems),
        source=source, decision=decision, decision_note=note, decided_by=user,
        decided_at=timezone.now(), created_by=user)


def _save_field(card, task, value: str):
    obj = task.obj
    if obj is None and task.kind == MISSING and task.genotype:
        obj, _ = GenotypeText.objects.get_or_create(card=card, genotype=task.genotype)
    setattr(obj, task.field, value)
    if isinstance(obj, GeneCard):
        obj.save(update_fields=[task.field, "updated_at"])
    else:
        obj.save(update_fields=[task.field])


@transaction.atomic
def act(card, task: Task, action: str, *, user, text: str = "", note: str = "",
        source: str = "") -> str:
    """Provede akci úkolu a vrátí zprávu pro uživatele. Každé vyřešení má odůvodnění."""
    if not card.is_editable:
        raise ActionError("Karta už není návrh ani v revizi – úkoly jdou jen číst.")
    note = (note or "").strip()[:5000]
    if task.kind == REVISION:
        return _act_revision(card, task, action, user=user, note=note)
    old = task.current
    if action == "overeno":
        if not task.verifiable:
            raise ActionError("Potvrdit ověření jde jen u textu se značkou [OVĚŘIT …].")
        new = strip_markers(old)
        note = note or "Ověřeno ve zdroji karty."
        decision = CardRevision.Decision.ACCEPTED
    elif action == "vyradit":
        new = without_flagged(card, old, client=task.blocking)
        note = note or "Tvrzení nejde ze zdrojů doložit – věta vyřazena."
        decision = CardRevision.Decision.REMOVED
    elif action == "ulozit":
        new = (text or "").strip()
        if not new and task.kind == MISSING:
            raise ActionError("Napište text – prázdný text úkol nevyřeší.")
        if not note:
            raise ActionError("Připište odůvodnění (např. podle kterého zdroje).")
        decision = CardRevision.Decision.ACCEPTED
    else:
        raise ActionError("Neznámá akce.")
    if new == old.strip():
        raise ActionError("Text se nezměnil.")
    _save_field(card, task, new)
    _record(card, task, old=old, new=new, decision=decision, note=note, user=user, source=source)
    left = [p for p in tasks_for(card) if p.key == task.key]
    if left:
        return f"{task.title}: uloženo, ale text ještě obsahuje {left[0].problems[0]}."
    return f"{task.title}: vyřešeno."


def _act_revision(card, task, action, *, user, note) -> str:
    revision = task.revision
    if action == "oduvodnit":
        if not note:
            raise ActionError("Připište odůvodnění rozhodnutí.")
        revision.decision_note = note
        revision.save(update_fields=["decision_note", "updated_at"])
        return f"{revision.part}: odůvodnění doplněno."
    if action not in (CardRevision.Decision.ACCEPTED, CardRevision.Decision.REJECTED,
                      CardRevision.Decision.REMOVED):
        raise ActionError("Neznámé rozhodnutí.")
    if not note:
        raise ActionError("Každé rozhodnutí potřebuje odůvodnění – vyberte nebo napište důvod.")
    revision.decision = action
    revision.decision_note = note
    revision.decided_by = user
    revision.decided_at = timezone.now()
    revision.save(update_fields=["decision", "decision_note", "decided_by", "decided_at",
                                 "updated_at"])
    applied = apply_revision(card, revision)
    return applied or f"{revision.part}: {revision.get_decision_display().lower()}."


def add_remark(card, *, user, text: str) -> CardRevision:
    """Připomínka garanta při vrácení karty – připravujícímu se objeví jako úkol."""
    return CardRevision.objects.create(card=card, part="Připomínka garanta", reason=text,
                                       source=user.get_full_name() or user.get_username(),
                                       created_by=user)
