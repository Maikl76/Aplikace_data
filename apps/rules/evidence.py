"""
Napojení nálezů na literaturu.

Článek se ke zprávě dostane dvěma cestami:

* **přes pravidlo** – pravidlo, ke kterému je článek připojený, u měření
  našlo nález. Takový článek je ve zprávě vždycky.
* **přes téma** – článek se vztahuje k ukazateli nebo testu, který se
  u sportovce měřil. Model ho dostane jako podklad; do seznamu zdrojů ve
  zprávě se dostane, jen když na něj text odkáže číslem [n].

Vždy jen články, které jsou v knihovně schválené – u každého tvrzení
ve zprávě je tak dohledatelné, odkud se vzalo.
"""

import re

from django.db.models import Q

from apps.evidence.models import Article

# Kolik článků k tématům dostane model nejvýš. Vybírají se ty k ukazatelům,
# které se skutečně změnily nebo mají stranový rozdíl nad prahem, pak podle
# síly důkazu – ne náhodných osm z padesáti článků o výskoku.
MAX_TOPIC_ARTICLES = 8
ASYMMETRY_THRESHOLD_PCT = 10.0

RULE, TOPIC = "pravidlo", "tema"


def articles_for(findings) -> list[dict]:
    """
    Citace pro sadu nálezů, bez duplicit a v pořadí podle závažnosti.

    U každé se hlásí, jestli studovaná populace odpovídá sportovci. Studie
    na mužích fotbalistech neospravedlňuje doporučení pro sedmnáctiletou
    tenistku – zpráva to musí říct, ne zamlčet.
    """
    seen: dict[int, dict] = {}
    for finding in findings:
        if finding.suppressed:
            continue
        subject = finding.session.subject
        for link in finding.rule.rule_articles.select_related("article"):
            article = link.article
            if article.status != Article.Status.APPROVED:
                continue
            if article.pk in seen:
                seen[article.pk]["findings"].append(finding)
                continue
            seen[article.pk] = {
                "article": article,
                "kind": RULE,
                "relevance": link.relevance_note,
                "findings": [finding],
                "population_matches": article.matches_population(subject, finding.session.date),
            }
    for item in seen.values():
        item["reason"] = item["relevance"] or "k nálezu: " + "; ".join(
            f.text for f in item["findings"])
    return list(seen.values())


def report_citations(session, findings, *, frozen=None) -> list[dict]:
    """
    Všechny články ke zprávě s čísly [n]: nejdřív k nálezům pravidel, pak
    k tématům. ``frozen`` je seznam článků z konceptu zprávy (Report.literature)
    – čísla pak zůstanou stejná, i když se knihovna mezitím změní.
    """
    items = articles_for(findings)
    rule_ids = {item["article"].pk for item in items}
    only = None if frozen is None else [pk for pk in frozen if pk not in rule_ids]
    items += topic_articles(session, exclude=rule_ids, only=only)

    position = {pk: i for i, pk in enumerate(frozen or [])}
    next_number = len(position) + 1
    for item in items:
        pk = item["article"].pk
        if pk in position:
            item["number"] = position[pk] + 1
        else:
            item["number"] = next_number
            next_number += 1
    return sorted(items, key=lambda item: item["number"])


def topic_articles(session, *, exclude=(), only=None) -> list[dict]:
    """Schválené články k ukazatelům a testům, které se u sportovce měřily."""
    from apps.analytics import queries

    current = queries.session_metric_values(session)
    codes = {key[0] for key in current}
    protocols = set(session.protocol_runs.values_list("protocol__code", flat=True))
    articles = (Article.objects.filter(status=Article.Status.APPROVED)
                .filter(Q(metrics__code__in=codes) | Q(protocols__code__in=protocols))
                .exclude(pk__in=exclude).distinct()
                .prefetch_related("metrics", "protocols", "sports"))
    if only is not None:
        articles = articles.filter(pk__in=only)
    articles = list(articles)
    if not articles:
        return []

    notable = _notable_metrics(session, current)
    subject = session.subject
    sport = subject.sport if subject.sport_id else None
    out = []
    for article in articles:
        metrics = [m for m in article.metrics.all() if m.code in codes]
        tests = sorted({p.name for p in article.protocols.all() if p.code in protocols})
        hot = [m for m in metrics if m.code in notable]
        priority = 0 if hot else 1 if metrics else 2
        same_sport = article.has_sport(sport)
        reason = []
        if metrics:
            names = sorted({m.name for m in metrics})
            reason.append(f"k měřenému ukazateli: {', '.join(names)}")
        if tests:
            reason.append(f"k testu: {', '.join(tests)}")
        if hot:
            reason.append("u sportovce: " + "; ".join(
                sorted({f"{m.name} – {notable[m.code]}" for m in hot})))
        out.append({
            "article": article, "kind": TOPIC, "relevance": "", "findings": [],
            "population_matches": article.matches_population(subject, session.date),
            "reason": "; ".join(reason),
            "_order": (priority, not same_sport, article.evidence_rank, -(article.year or 0)),
        })
    out.sort(key=lambda item: item.pop("_order"))
    return out if only is not None else out[:MAX_TOPIC_ARTICLES]


def _notable_metrics(session, current) -> dict[str, str]:
    """Ukazatele, u kterých se něco děje: změna nad chybou měření, stranový rozdíl."""
    from apps.analytics import queries

    out = {}
    previous = queries.previous_session_values(session)
    for key, entry in current.items():
        metric = entry["metric"]
        if (before := previous.get(key)) and metric.mdc is not None:
            if metric.change_is_real(entry["value"] - before["value"]):
                out[metric.code] = "změna přesahující chybu měření"
    for row in queries.session_asymmetries(session, threshold_pct=ASYMMETRY_THRESHOLD_PCT):
        if row["exceeds_threshold"]:
            out.setdefault(row["metric"].code, "stranový rozdíl nad prahem")
    return out


CITED = re.compile(r"\[(\d+(?:\s*[,;–-]\s*\d+)*)\]")


def cited_numbers(*texts) -> set[int]:
    """Čísla zdrojů, na která text odkazuje: [1], [1, 3], [2–4]."""
    out = set()
    for text in texts:
        for group in CITED.findall(text or ""):
            for part in re.split(r"\s*[,;]\s*", group):
                bounds = [int(x) for x in re.split(r"\s*[–-]\s*", part) if x]
                if len(bounds) == 2 and 0 < bounds[1] - bounds[0] < 50:
                    out.update(range(bounds[0], bounds[1] + 1))
                else:
                    out.update(bounds)
    return out


def shown_citations(citations, *texts) -> list[dict]:
    """
    Zdroje do zprávy: články k nálezům vždy, články k tématům jen ty, na
    které souhrn nebo doporučení odkazují.
    """
    cited = cited_numbers(*texts)
    return [c for c in citations if c.get("kind", RULE) == RULE or c["number"] in cited]


def population_warnings(citations: list[dict]) -> list[str]:
    """Věty do zprávy tam, kde evidence pochází z jiné populace."""
    warnings = []
    for item in citations:
        if not item["population_matches"]:
            article = item["article"]
            warnings.append(
                f"Studie {_short(article)} vychází z odlišné populace"
                f"{_population_detail(article)}; přenositelnost závěru je omezená."
            )
    return warnings


def _short(article) -> str:
    first = article.authors.split(",")[0].strip() if article.authors else "?"
    return f"{first} ({article.year})" if article.year else first


def _population_detail(article) -> str:
    bits = article.sport_names()
    if article.population_sex == "F":
        bits.append("ženy")
    elif article.population_sex == "M":
        bits.append("muži")
    if article.population_age_min or article.population_age_max:
        bits.append(f"{article.population_age_min or '?'}–{article.population_age_max or '?'} let")
    return f" ({', '.join(bits)})" if bits else ""
