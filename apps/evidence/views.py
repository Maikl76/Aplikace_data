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

from . import ai_draft, lookup
from .forms import ArticleForm
from .models import Article


def can_edit(user) -> bool:
    """Knihovnu spravuje správce – co se do ní zařadí, cituje se ve zprávách."""
    return can_edit_catalog(user) or user.has_perm("evidence.change_article")


SORTS = {
    "rok": (("-year", "title"), "nejnovější studie"),
    "pridano": (("-created_at",), "naposledy přidané"),
    "dukaz": (("evidence_order", "-year"), "nejsilnější důkaz"),
    "nazev": (("title",), "podle názvu"),
}
PER_PAGE = 30


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@login_required
def article_list(request):
    from django.core.paginator import Paginator
    from django.db.models import Case, IntegerField, Value, When

    from apps.catalog.models import MetricDef, Protocol
    from apps.subjects.models import Sport

    from .models import EvidenceLevel

    get = request.GET
    f = {key: get.get(key, "").strip() for key in
         ("stav", "q", "sport", "test", "ukazatel", "dukaz", "pohlavi", "vek", "chybi",
          "razeni")}
    articles = Article.objects.annotate(pocet_pravidel=Count("rule_articles", distinct=True))
    if f["stav"] in Article.Status.values:
        articles = articles.filter(status=f["stav"])
    if f["q"]:
        articles = articles.filter(Q(title__icontains=f["q"]) | Q(authors__icontains=f["q"])
                                   | Q(doi__icontains=f["q"]) | Q(pmid=f["q"])
                                   | Q(key_finding__icontains=f["q"])
                                   | Q(journal__icontains=f["q"]))
    if sport := Sport.objects.filter(pk=_int(f["sport"])).first():
        articles = articles.filter(Q(sports=sport)
                                   | Q(population_sport__icontains=sport.name))
    if test := _int(f["test"]):
        articles = articles.filter(protocols=test)
    if metric := _int(f["ukazatel"]):
        articles = articles.filter(metrics=metric)
    if f["dukaz"] in EvidenceLevel.values:
        articles = articles.filter(evidence_level=f["dukaz"])
    if f["pohlavi"] in ("F", "M"):
        # Studie na ženách sedí na ženy; studie na obou pohlavích i bez údaje taky.
        articles = articles.filter(population_sex__in=[f["pohlavi"], "B", ""])
    if (age := _int(f["vek"])) is not None:
        articles = articles.filter(
            Q(population_age_min__isnull=True) | Q(population_age_min__lte=age),
            Q(population_age_max__isnull=True) | Q(population_age_max__gte=age))
    if f["chybi"] == "zjisteni":
        articles = articles.filter(key_finding="", curator_note="")
    elif f["chybi"] == "vazba":
        articles = articles.filter(pocet_pravidel=0, metrics__isnull=True,
                                   protocols__isnull=True)
    elif f["chybi"] == "sport":
        articles = articles.filter(sports__isnull=True, population_sport="")
    articles = articles.distinct()

    sort = f["razeni"] if f["razeni"] in SORTS else "rok"
    articles = articles.annotate(evidence_order=Case(
        *[When(evidence_level=value, then=Value(i)) for i, value in enumerate(EvidenceLevel.values)],
        default=Value(99), output_field=IntegerField())).order_by(*SORTS[sort][0])
    page = Paginator(articles.prefetch_related("metrics", "protocols", "sports"),
                     PER_PAGE).get_page(get.get("strana"))

    used = Article.objects.all()
    counts = dict(used.values_list("status").annotate(n=Count("pk")))
    keep = request.GET.copy()
    keep.pop("strana", None)
    without_status = keep.copy()
    without_status.pop("stav", None)
    active = [k for k in ("sport", "test", "ukazatel", "dukaz", "pohlavi", "vek", "chybi", "q")
              if f[k]]
    return render(request, "evidence/articles.html", {
        "page": page, "articles": page.object_list, "f": f, "sort": sort,
        "query_string": keep.urlencode(), "active_filters": len(active),
        "status_qs": without_status.urlencode(),
        "can_edit": can_edit(request.user),
        "statuses": [(value, label, counts.get(value, 0))
                     for value, label in Article.Status.choices],
        "sports": Sport.objects.filter(Q(articles__isnull=False)).distinct().order_by("name"),
        "tests": Protocol.objects.filter(articles__isnull=False).distinct().order_by("name"),
        "metrics": MetricDef.objects.filter(articles__isnull=False).distinct()
        .order_by("name"),
        "levels": EvidenceLevel.choices,
        "sorts": [(key, label) for key, (_, label) in SORTS.items()],
    })


def _form_page(request, form, article=None, found=None, filled=None):
    from apps.reports import ai_models, llm

    return render(request, "evidence/article_form.html", {
        "form": form, "article": article, "found": found, "filled": filled or [],
        "evidence_levels": form.fields["evidence_level"].choices,
        "llm_enabled": llm.is_enabled(),
        "model_choices": ai_models.choices() if llm.is_enabled() else [],
        "max_pdf_mb": ai_draft.MAX_PDF_MB,
    })


def _save(request, form, *, created: bool):
    """
    Uložení článku i s PDF. Tlačítko „Uložit a navrhnout pomocí AI“ pak
    spustí model. Uložením formuláře se případný návrh od AI považuje za
    zkontrolovaný (jeho text je teď v polích) a zahodí se.
    """
    upload = request.FILES.get("pdf_soubor")
    if upload is not None:
        try:
            ai_draft.check_pdf(upload)
        except ai_draft.DraftError as exc:
            form.add_error(None, str(exc))
            return None
    article = form.save(commit=False)
    if request.POST.get("akce") != "ai":
        article.ai_draft = None
    if request.POST.get("smazat_pdf") and article.pdf:
        article.pdf.delete(save=False)
    if upload is not None and request.POST.get("ulozit_pdf"):
        article.pdf.save(upload.name, upload, save=False)
    article.save()
    form.save_m2m()
    record(request, AuditLog.Action.CREATE if created else AuditLog.Action.UPDATE, article)

    if request.POST.get("akce") != "ai":
        messages.success(request, f"Článek uložen ({article.get_status_display().lower()}).")
        return redirect("article_list")
    from apps.reports.ai_models import is_offered

    model = request.POST.get("model", "").strip()
    try:
        text, source = ai_draft.source_for(article, upload,
                                           abstract_only=bool(request.POST.get("jen_abstrakt")))
        ai_draft.start(article, model=model if is_offered(model) else None, text=text,
                       source=source)
    except ai_draft.DraftError as exc:
        messages.error(request, f"Článek uložen, ale návrh nejde připravit: {exc}")
    else:
        messages.info(request, "Článek uložen. Model píše návrh z "
                               + ("abstraktu." if source == ai_draft.SOURCE_ABSTRACT
                                  else "celého textu článku."))
    return redirect("article_edit", article.pk)


@login_required
def article_new(request):
    if not can_edit(request.user):
        messages.error(request, "Články do knihovny přidává správce.")
        return redirect("article_list")
    organization = request.user.organization
    if request.method == "POST":
        form = ArticleForm(request.POST, request.FILES, organization=organization)
        if form.is_valid() and (response := _save(request, form, created=True)):
            return response
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
    organization = request.user.organization
    if request.method == "POST" and request.POST.get("akce") == "zahodit":
        article.ai_draft = None
        article.save(update_fields=["ai_draft"])
        messages.info(request, "Návrh od AI zahozen.")
        return redirect("article_edit", article.pk)
    if request.method == "POST":
        form = ArticleForm(request.POST, request.FILES, instance=article,
                           organization=organization)
        if form.is_valid() and (response := _save(request, form, created=False)):
            return response
        return _form_page(request, form, article)

    ai_draft.clear_stalled(article)
    initial, filled = {}, []
    if article.ai_draft_ready and not article.ai_writing:
        initial, filled = ai_draft.initial_from(article.ai_draft, article, organization)
    form = ArticleForm(instance=article, initial=initial, organization=organization)
    return _form_page(request, form, article, filled=filled)


@login_required
def article_ai_state(request, pk):
    """Stav psaní návrhu (HTMX dotaz každých pár sekund)."""
    from django.http import HttpResponse
    from django.utils import timezone

    article = get_object_or_404(Article, pk=pk)
    ai_draft.clear_stalled(article)
    if not article.ai_writing:
        response = HttpResponse("")
        response["HX-Refresh"] = "true"
        return response
    seconds = int((timezone.now() - article.ai_writing_started_at).total_seconds())
    return HttpResponse(f"{seconds // 60} min {seconds % 60:02d} s")


@login_required
def article_pdf(request, pk):
    """Uložené PDF – jen pro přihlášené, ne přes veřejnou adresu médií."""
    from django.http import FileResponse, Http404

    article = get_object_or_404(Article, pk=pk)
    if not article.pdf:
        raise Http404
    name = article.pdf.name.rsplit("/", 1)[-1]
    return FileResponse(article.pdf.open("rb"), content_type="application/pdf",
                        filename=name)


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
