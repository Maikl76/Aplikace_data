"""Knihovna článků v aplikaci (Katalog → Články): přehled, přidání podle DOI/PMID, schválení."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.catalog.protocol_setup import can_edit as can_edit_catalog
from apps.core.audit import record
from apps.core.models import AuditLog

from . import lookup
from .forms import ArticleForm
from .models import Article


def can_edit(user) -> bool:
    """Knihovnu spravuje správce – co se do ní zařadí, cituje se ve zprávách."""
    return can_edit_catalog(user) or user.has_perm("evidence.change_article")


@login_required
def article_list(request):
    status = request.GET.get("stav", "")
    query = request.GET.get("q", "").strip()
    articles = (Article.objects.annotate(pocet_pravidel=Count("rule_articles", distinct=True))
                .prefetch_related("metrics", "protocols"))
    if status in Article.Status.values:
        articles = articles.filter(status=status)
    if query:
        articles = articles.filter(Q(title__icontains=query) | Q(authors__icontains=query)
                                   | Q(doi__icontains=query) | Q(pmid=query)
                                   | Q(key_finding__icontains=query))
    counts = dict(Article.objects.values_list("status").annotate(n=Count("pk")))
    return render(request, "evidence/articles.html", {
        "articles": articles.order_by("status", "-year", "title"),
        "status": status, "q": query, "can_edit": can_edit(request.user),
        "statuses": [(value, label, counts.get(value, 0))
                     for value, label in Article.Status.choices],
    })


def _form_page(request, form, article=None, found=None):
    return render(request, "evidence/article_form.html", {
        "form": form, "article": article, "found": found,
        "evidence_levels": form.fields["evidence_level"].choices,
    })


@login_required
def article_new(request):
    if not can_edit(request.user):
        messages.error(request, "Články do knihovny přidává správce.")
        return redirect("article_list")
    organization = request.user.organization
    if request.method == "POST":
        form = ArticleForm(request.POST, organization=organization)
        if form.is_valid():
            article = form.save()
            record(request, AuditLog.Action.CREATE, article)
            messages.success(request, f"Článek uložen ({article.get_status_display().lower()}).")
            return redirect("article_list")
        return _form_page(request, form)

    initial, found = {}, None
    if identifier := request.GET.get("hledat", "").strip():
        try:
            found = lookup.lookup(identifier)
        except lookup.LookupError_ as exc:
            messages.error(request, str(exc))
        else:
            same = Q(pk__in=[])
            if found["doi"]:
                same |= Q(doi__iexact=found["doi"])
            if found["pmid"]:
                same |= Q(pmid=found["pmid"])
            if existing := Article.objects.filter(same).first():
                messages.info(request, "Tento článek už v knihovně je.")
                return redirect("article_edit", existing.pk)
            initial = {k: v for k, v in found.items() if k != "source" and v}
            messages.success(request, f"Údaje doplněny z {found['source']}u. Zkontrolujte je "
                                      f"a doplňte hlavní zjištění pro praxi.")
    return _form_page(request, ArticleForm(initial=initial, organization=organization),
                      found=found)


@login_required
def article_edit(request, pk):
    article = get_object_or_404(Article, pk=pk)
    if not can_edit(request.user):
        messages.error(request, "Články v knihovně upravuje správce.")
        return redirect("article_list")
    form = ArticleForm(request.POST or None, instance=article,
                       organization=request.user.organization)
    if request.method == "POST" and form.is_valid():
        form.save()
        record(request, AuditLog.Action.UPDATE, article)
        messages.success(request, "Článek uložen.")
        return redirect("article_list")
    return _form_page(request, form, article)


@login_required
@require_POST
def article_status(request, pk):
    """Rychlé zařazení nebo zamítnutí ze seznamu."""
    article = get_object_or_404(Article, pk=pk)
    status = request.POST.get("stav")
    if can_edit(request.user) and status in Article.Status.values:
        article.status = status
        article.save(update_fields=["status", "updated_at"])
        record(request, AuditLog.Action.UPDATE, article, status=status)
        if status == Article.Status.APPROVED and not (article.key_finding
                                                      or article.curator_note):
            messages.warning(request, "Článek je zařazený, ale nemá vyplněné hlavní zjištění – "
                                      "model pak ví jen jeho název.")
    back = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
        back = reverse("article_list")
    return redirect(back)
