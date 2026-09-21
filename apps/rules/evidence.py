"""
Napojení nálezů na literaturu.

Evidence visí na PRAVIDLE, ne na volném textu – proto je u každého tvrzení
ve zprávě dohledatelné, odkud se vzalo. Do zprávy se dostanou jen články,
které jsou v knihovně schválené.
"""

from apps.evidence.models import Article


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
                "relevance": link.relevance_note,
                "findings": [finding],
                "population_matches": article.matches_population(subject),
            }
    return list(seen.values())


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
    bits = []
    if article.population_sport:
        bits.append(article.population_sport)
    if article.population_sex == "F":
        bits.append("ženy")
    elif article.population_sex == "M":
        bits.append("muži")
    if article.population_age_min or article.population_age_max:
        bits.append(f"{article.population_age_min or '?'}–{article.population_age_max or '?'} let")
    return f" ({', '.join(bits)})" if bits else ""
