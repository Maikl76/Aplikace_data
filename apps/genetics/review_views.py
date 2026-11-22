"""
Revize a schválení karet krok za krokem.

Přehled karet s postupem → jeden úkol na obrazovce (co je špatně, kde se text
ve zprávě objeví, zdroje karty, akce s odůvodněním) → souhrn karty: co se
změnilo proti původnímu znění, jak to uvidí sportovec, rozhodnutí revize
a tlačítko pro garanta. Úkoly připravuje laborant nebo metodik, kartu
schvaluje garant oblasti (services.approve).
"""

import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.core.audit import record
from apps.core.models import AuditLog

from . import review, review_ai, services
from .card_steps import TITLES
from .models import CardRevision, GeneCard
from .setup_views import _may_setup
from .views import _catalog, _denied

LABEL = re.compile(r"\bS\d+\b")


def _card(request, pk):
    return get_object_or_404(
        _catalog(GeneCard, request.user).select_related("variant", "variant__domain"), pk=pk)


def _task_url(card, key=None) -> str:
    url = reverse("genetics_review_task", args=[card.pk])
    return f"{url}?ukol={key}" if key else url


def _guarantors(card) -> str:
    return ", ".join(g.get_full_name() or g.get_username()
                     for g in card.variant.domain.guarantors.all()) or "nikdo"


@login_required
def overview(request):
    user = request.user
    if not _may_setup(user):
        return _denied(request, "Revizi karet dělá správce, laborant nebo metodik (garant).")
    cards = list(_catalog(GeneCard, user).filter(status__in=GeneCard.EDITABLE)
                 .select_related("variant", "variant__domain")
                 .order_by("variant__order", "variant__gene", "version"))
    rows = []
    for card in cards:
        tasks = review.tasks_for(card)
        rows.append({"card": card, "progress": review.progress(card, tasks),
                     "next": tasks[0].key if tasks else "",
                     "garant": services.may_approve(user, card),
                     "ai": review_ai.card_state(card, tasks)})
    waiting = [r for r in rows if r["card"].status == GeneCard.Status.REVIEW and r["garant"]]
    last = (CardRevision.objects.filter(decided_by=user, card__in=cards)
            .select_related("card").order_by("-decided_at").first())
    # pokračovat tam, kde je co dělat: naposledy rozpracovaná karta s blokujícími úkoly,
    # jinak první návrh s blokujícími úkoly (karta u garanta ani hotová karta to není)
    todo = [r for r in rows if r["card"].status == GeneCard.Status.DRAFT and r["progress"]["blocking"]]
    resume = next((r for r in todo if last and r["card"].pk == last.card_id), None)
    resume = resume or (todo[0] if todo else None)
    approved = _catalog(GeneCard, user).filter(status=GeneCard.Status.APPROVED).count()
    return render(request, "genetics/review_overview.html", {
        "rows": rows, "waiting": waiting, "resume": resume, "approved": approved,
        "ai_available": review_ai.available(),
    })


def _segments(text: str) -> list[tuple[str, bool]]:
    """Text rozdělený na úseky; značky k ověření zvýrazněné."""
    out, last = [], 0
    for match in services.MARKER.finditer(text or ""):
        out += [(text[last:match.start()], False), (match.group(0), True)]
        last = match.end()
    return out + [((text or "")[last:], False)]


def _sources(card, text: str) -> tuple[list, list]:
    """Zdroje karty: zmíněné v textu úkolu a ostatní (s hlavním zjištěním z knihovny)."""
    labels = set(LABEL.findall(text or ""))
    rows = list(card.sources.select_related("article").order_by("order", "pk"))
    return [s for s in rows if s.label in labels], [s for s in rows if s.label not in labels]


@login_required
def task_view(request, pk):
    user = request.user
    if not _may_setup(user):
        return _denied(request, "Úkoly revize připravuje správce, laborant nebo metodik.")
    card = _card(request, pk)
    if not card.is_editable:
        messages.info(request, "Karta není návrh ani v revizi – úkoly jdou jen číst v souhrnu.")
        return redirect("genetics_review_summary", pk=card.pk)
    tasks = review.tasks_for(card)
    if request.method == "POST":
        key = request.POST.get("ukol", "")
        action = request.POST.get("akce", "")
        if action in ("ai_karta", "ai_ukol"):
            return _start_ai(request, card, key, single=action == "ai_ukol")
        task = review.find(tasks, key)
        if task is None:
            messages.info(request, "Úkol už je vyřešený.")
            return redirect(_task_url(card))
        if request.POST.get("base") != task.base:
            messages.error(request, "Text úkolu se mezitím změnil – zkontrolujte aktuální znění.")
            return redirect(_task_url(card, key))
        if action == "navrh_odmitnout":
            review_ai.dismiss(card, task)
            messages.info(request, "Návrh AI je odmítnutý – úkol vyřešte sami.")
            return redirect(_task_url(card, key))
        try:
            if action == "navrh":
                proposal = review_ai.proposal_for(card, task)
                if proposal is None:
                    raise review.ActionError("K úkolu není návrh AI.")
                message = review_ai.accept(card, task, proposal, user=user)
            else:
                message = _act_manually(card, task, action, user, request.POST)
        except review.ActionError as exc:
            messages.error(request, str(exc))
            return redirect(_task_url(card, key))
        record(request, AuditLog.Action.UPDATE, card, karta=str(card), ukol=key, akce=action,
               navrh_ai=action == "navrh")
        messages.success(request, message)
        remaining = review.tasks_for(card)
        following = review.next_after(remaining, key)
        if not remaining or not any(t.blocking for t in remaining) and task.blocking:
            return redirect("genetics_review_summary", pk=card.pk)
        return redirect(_task_url(card, following.key if following else None))
    if not tasks:
        return redirect("genetics_review_summary", pk=card.pk)
    task = review.find(tasks, request.GET.get("ukol", "")) or tasks[0]
    from .card_wizard import _original

    original, original_label = _original(card)
    mentioned, other_sources = _sources(card, task.current + (
        task.revision.reason + task.revision.proposal if task.revision else ""))
    following = review.next_after(tasks, task.key)
    proposal = review_ai.proposal_for(card, task)
    ai = review_ai.card_state(card, tasks)
    return render(request, "genetics/review_task.html", {
        "proposal": proposal, "ai": ai,
        # s platným návrhem AI je hlavní cestou návrh; ruční řešení se schová
        "ai_first": bool(ai["available"] and proposal and proposal.fresh
                         and proposal.status == proposal.Status.READY),
        "proposal_preview": _proposal_preview(card, task, proposal),
        "card": card, "variant": card.variant, "task": task, "tasks": tasks,
        "index": tasks.index(task) + 1, "progress": review.progress(card, tasks),
        "segments": _segments(task.current), "reasons": review.REASONS[task.kind],
        "preview_verified": review.strip_markers(task.current) if task.verifiable else "",
        "preview_removed": (review.without_flagged(card, task.current, client=task.blocking)
                            if task.kind == review.TEXT else ""),
        "original_text": review.original_text(task, original), "original_label": original_label,
        "mentioned": mentioned, "other_sources": other_sources,
        "next": following, "step_title": TITLES.get(task.step, ""),
        "step_url": reverse("genetics_card_step", args=[card.pk, task.step]),
    })


@transaction.atomic
def _act_manually(card, task, action, user, post) -> str:
    """Akce úkolu; upravený návrh AI s novým zdrojem z PubMedu ten zdroj přidá ke kartě."""
    text, source = post.get("text", ""), ""
    if action == "ulozit" and review_ai.NEW_SOURCE in text:
        proposal = review_ai.proposal_for(card, task)
        if proposal is None or not proposal.new_source.get("title"):
            raise review.ActionError(f"Text odkazuje na {review_ai.NEW_SOURCE}, ale k úkolu není "
                                     "návrh AI s novým zdrojem – odkaz nahraďte štítkem zdroje.")
        added = review_ai._add_source(card, proposal.new_source)
        text, source = text.replace(review_ai.NEW_SOURCE, f"[{added.label}]"), added.citation
    return review.act(card, task, action, user=user, text=text, note=post.get("duvod", ""),
                      source=source)


def _proposal_preview(card, task, proposal) -> str:
    """Jak bude text vypadat po přijetí návrhu."""
    if proposal is None or proposal.status != proposal.Status.READY:
        return ""
    if proposal.decision == "overeno":
        return review.strip_markers(task.current)
    if proposal.decision == "vyradit" and task.kind == review.TEXT:
        return review.without_flagged(card, task.current, client=task.blocking)
    if task.kind == review.REVISION and task.is_ab:
        return {"upravit_podle_navrhu": task.revision.proposal,
                "ponechat": task.revision.original,
                "vyradit": "(text se z karty odstraní)"}.get(proposal.decision, "")
    return proposal.text


def _start_ai(request, card, key, *, single: bool):
    try:
        count = review_ai.start(card, keys=[key] if single and key else None)
    except review.ActionError as exc:
        messages.error(request, str(exc))
    else:
        messages.info(request, f"AI připravuje {count} návrhů – stránka se sama obnoví."
                      if count else "Všechny úkoly už platný návrh mají.")
    return redirect(_task_url(card, key or None))


def _changes(card, original) -> list[dict]:
    """Co se změnilo proti původnímu znění – jen změněné části."""
    if original is None:
        return []
    rows = []
    for name, label in (("biology_client", "Vysvětlení pro klienta"),
                        ("limitations", "Omezení interpretace")):
        old, new = (getattr(original, name) or "").strip(), (getattr(card, name) or "").strip()
        if old != new:
            rows.append({"cast": label, "puvodne": old, "nyni": new})
    old_texts = {t.genotype: t.client_text.strip() for t in original.genotype_texts.all()}
    for text in card.genotype_texts.all():
        old, new = old_texts.get(text.genotype, ""), text.client_text.strip()
        if old != new:
            rows.append({"cast": f"Text pro genotyp {card.variant.genotype_label(text.genotype)}",
                         "puvodne": old, "nyni": new})
    old_recs = {r.text.strip() for r in original.recommendations.all()}
    new_recs = {r.text.strip() for r in card.recommendations.all()}
    if old_recs != new_recs:
        rows.append({"cast": "Doporučení",
                     "puvodne": f"{len(old_recs)} doporučení, z toho {len(old_recs - new_recs)} "
                                "už v kartě není",
                     "nyni": f"{len(new_recs)} doporučení, z toho {len(new_recs - old_recs)} nových"})
    old_src = {s.citation.strip() for s in original.sources.all()}
    new_src = {s.citation.strip() for s in card.sources.all()}
    if old_src != new_src:
        rows.append({"cast": "Zdroje", "puvodne": f"{len(old_src)} zdrojů",
                     "nyni": f"{len(new_src)} zdrojů, z toho {len(new_src - old_src)} nových"})
    return rows


@login_required
def summary(request, pk):
    user = request.user
    if not _may_setup(user):
        return _denied(request, "Revizi karet dělá správce, laborant nebo metodik (garant).")
    card = _card(request, pk)
    if request.method == "POST":
        return _summary_action(request, card)
    from .card_wizard import _original

    original, original_label = _original(card)
    tasks = review.tasks_for(card) if card.is_editable else []
    variant = card.variant
    texts = {t.genotype: t for t in card.genotype_texts.all()}
    decided = list(card.revisions.exclude(decision=CardRevision.Decision.OPEN)
                   .select_related("decided_by").order_by("decided_at", "pk"))
    preparers = sorted({(r.decided_by.get_full_name() or r.decided_by.get_username())
                        for r in decided if r.decided_by_id})
    return render(request, "genetics/review_summary.html", {
        "card": card, "variant": variant, "tasks": tasks,
        "progress": review.progress(card, tasks) if card.is_editable else None,
        "checklist": services.checklist(card) if card.is_editable else None,
        "changes": _changes(card, original), "original_label": original_label,
        "genotypes": [{"label": variant.genotype_label(g), "text": texts.get(g)}
                      for g in variant.genotypes],
        "recommendations": list(card.recommendations.select_related("protocol")),
        "decided": decided, "preparers": preparers,
        "may_approve": services.may_approve(user, card), "guarantors": _guarantors(card),
        "same_person": (services.may_approve(user, card)
                        and (user.get_full_name() or user.get_username()) in preparers),
    })


def _summary_action(request, card):
    action = request.POST.get("akce", "")
    user = request.user
    try:
        if action == "k_revizi":
            if any(t.blocking for t in review.tasks_for(card)):
                raise ValueError("Garantovi jde poslat až karta bez blokujících úkolů.")
            services.submit_for_review(card)
            messages.success(request, f"Karta {card} čeká na garanta oblasti "
                                      f"„{card.variant.domain}“ ({_guarantors(card)}).")
        elif action == "schvalit":
            services.approve(card, by=user)
            record(request, AuditLog.Action.UPDATE, card, karta=str(card), akce="schvalit")
            messages.success(request, f"Karta {card} je schválená – od teď je to jediné znění, "
                                      "které smí do zpráv.")
            return redirect("genetics_review")
        elif action == "vratit":
            if not services.may_approve(user, card):
                raise PermissionError("Kartu k úpravě vrací garant oblasti.")
            remark = request.POST.get("pripominka", "").strip()
            if not remark:
                raise ValueError("Napište, co upravit – připomínka se připravujícímu objeví "
                                 "jako úkol.")
            services.return_to_draft(card)
            review.add_remark(card, user=user, text=remark[:5000])
            messages.info(request, f"Karta {card} je vrácená k úpravě s připomínkou.")
        else:
            raise ValueError("Neznámá akce.")
    except PermissionError as exc:
        return _denied(request, str(exc))
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("genetics_review_summary", pk=card.pk)
    record(request, AuditLog.Action.UPDATE, card, karta=str(card), akce=action)
    return redirect("genetics_review_summary", pk=card.pk)
