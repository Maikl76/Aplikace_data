"""Kroky knihovny článků a jednoho článku: identifikace, co dostane model, témata, zařazení."""

from django.db.models import Count
from django.urls import reverse

from apps.core.steps import step

from .models import Article


def library_steps() -> list[dict]:
    total = Article.objects.count()
    live = Article.objects.exclude(status=Article.Status.REJECTED)
    no_finding = live.filter(key_finding="").count()
    no_topic = (live.annotate(n_rules=Count("rule_articles", distinct=True))
                .filter(n_rules=0, metrics__isnull=True, protocols__isnull=True,
                        gene_sources__isnull=True, gene_evidence__isnull=True).distinct().count())
    suggested = Article.objects.filter(status=Article.Status.SUGGESTED).count()
    return [
        step(1, "Přidat článek", total > 0,
             (f"{total} článků v knihovně." if total else
              "Vložte DOI nebo PMID; název, autory a abstrakt doplní aplikace."),
             url=reverse("article_new"), button="Přidat článek"),
        step(2, "Co dostane model", no_finding == 0,
             (f"{no_finding} článků bez hlavního zjištění – model z nich nic nedostane."
              if no_finding else "Každý článek má hlavní zjištění pro praxi."),
             url=reverse("article_list") + "?chybi=zjisteni", button="Doplnit",
             count=no_finding or None),
        step(3, "Témata", no_topic == 0,
             (f"{no_topic} článků bez vazby na ukazatel, test, pravidlo ani genovou kartu – "
              "u sportovce se nikdy nepoužijí." if no_topic else
              "Každý článek má téma, pravidlo nebo genovou kartu."),
             url=reverse("article_list") + "?chybi=vazba", button="Doplnit témata",
             count=no_topic or None),
        step(4, "Zařazení", suggested == 0,
             (f"{suggested} navržených čeká na schválení; do zpráv jde jen zařazený článek."
              if suggested else "Nic nečeká na schválení."),
             url=reverse("article_list") + "?stav=suggested", button="Schválit",
             count=suggested or None, admin_only=True),
    ]


def article_steps(article) -> list[dict]:
    ident = bool(article.title) and bool(article.doi or article.pmid) and bool(article.year)
    model_missing = [label for label, value in (
        ("hlavní zjištění", article.key_finding), ("omezení", article.limitations),
        ("úroveň evidence", article.evidence_level)) if not value]
    population = bool(article.population_sex or article.population_age_min
                      or article.population_age_max or article.population_sport
                      or article.sports.exists())
    topics = (article.metrics.exists() or article.protocols.exists()
              or article.rule_articles.exists() or article.gene_sources.exists()
              or article.gene_evidence.exists())
    return [
        step(1, "Identifikace", ident,
             "Název, DOI nebo PMID a rok." if ident else "Chybí DOI nebo PMID, nebo rok."),
        step(2, "Co dostane model", not model_missing,
             ("Chybí: " + ", ".join(model_missing) + "." if model_missing else
              "Hlavní zjištění, omezení a úroveň evidence jsou vyplněné.")),
        step(3, "Populace a témata", population and topics,
             (" ".join(filter(None, [
                 "" if population else "Doplňte, na kom se studie dělala.",
                 "" if topics else "Vyberte ukazatel nebo test, kterého se článek týká."]))
              or "Populace i témata jsou vyplněné.")),
        step(4, "Zařazení", article.status == Article.Status.APPROVED,
             article.get_status_display() + ("" if article.status == Article.Status.APPROVED
                                             else " – zařazuje správce.")),
    ]
