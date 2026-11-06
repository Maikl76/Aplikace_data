"""
Uzavřená smyčka doporučení.

Zpráva dává doporučení; při dalším testovacím dni diagnostik jedním klikem
označí, zda se plnilo (plnilo se / částečně / neplnilo se / nelze říct).
Nová zpráva na to naváže – fakta pro model i souhrn ze šablony uvedou
doporučení z minulé zprávy i s plněním – a trenér i sportovec to vidí
v portálu u poslední zprávy.
"""

from django.db.models import Q

from .models import RecommendationReview, Report

KINDS = (Report.Kind.TESTING, Report.Kind.PERIOD)


def items(report) -> list[dict]:
    """Doporučení ze zprávy: z pravidel (snímek při vydání) a komentář diagnostika (index −1)."""
    out = [{"index": i, "text": text}
           for i, text in enumerate((report.snapshot or {}).get("recommendations", []))]
    note = (report.custom_note or "").strip()
    if note:
        out.append({"index": -1, "text": note})
    return out


def previous_report(session):
    """Poslední vydaná zpráva před tímto dnem, která má nějaké doporučení."""
    candidates = (Report.objects.filter(subject=session.subject, status=Report.Status.RELEASED,
                                        kind__in=KINDS)
                  .filter(Q(session__date__lt=session.date) | Q(period_to__lt=session.date))
                  .select_related("session").order_by("-released_at")[:10])
    for report in candidates:
        if items(report):
            return report
    return None


def state(session, *, report=None) -> dict | None:
    """Doporučení z minulé zprávy a jejich posouzení v tomto dni; None, když není co posuzovat."""
    report = report or previous_report(session)
    if report is None:
        return None
    reviews = {r.index: r for r in RecommendationReview.objects.filter(session=session, report=report)}
    rows = []
    for item in items(report):
        review = reviews.get(item["index"])
        rows.append({**item, "review": review,
                     "status": review.status if review else "",
                     "label": review.get_status_display() if review else "",
                     "note": review.note if review else ""})
    reviewed = sum(1 for r in rows if r["status"])
    return {"report": report, "rows": rows, "reviewed": reviewed, "total": len(rows),
            "done": reviewed == len(rows)}


def save(session, report, post, *, user) -> int:
    """Z formuláře (stav_<index>, pozn_<index>) uloží posouzení; vrací jejich počet."""
    saved = 0
    for item in items(report):
        status = post.get(f"stav_{item['index']}", "")
        if status not in RecommendationReview.Status.values:
            continue
        RecommendationReview.objects.update_or_create(
            session=session, report=report, index=item["index"],
            defaults={"text": item["text"][:2000], "status": status,
                      "note": (post.get(f"pozn_{item['index']}") or "").strip()[:200],
                      "reviewed_by": user})
        saved += 1
    return saved


def when(report):
    return report.session.date if report.session_id else report.period_to


def facts(session) -> list[dict]:
    """Do faktů zprávy: doporučení z minulé zprávy a jak se plnila (neposouzené výslovně)."""
    current = state(session)
    if current is None:
        return []
    report = current["report"]
    day = when(report)
    out = []
    for row in current["rows"]:
        item = {"zprava": report.report_number, "vydano": day.strftime("%d. %m. %Y") if day else "",
                "text": row["text"], "plneni": row["label"] if row["status"] else "neposouzeno"}
        if row["note"]:
            item["poznamka"] = row["note"]
        out.append(item)
    return out


def latest_for_portal(subject, audience) -> dict | None:
    """Poslední vydaná zpráva pro čtenáře s doporučeními a jejich plnění z pozdějších dnů."""
    candidates = (Report.objects.filter(subject=subject, audience=audience, kind__in=KINDS,
                                        status=Report.Status.RELEASED)
                  .select_related("session").order_by("-released_at")[:5])
    report = next((r for r in candidates if items(r)), None)
    if report is None:
        return None
    reviews = {}
    for review in (RecommendationReview.objects.filter(report=report)
                   .select_related("session").order_by("session__date")):
        reviews[review.index] = review      # poslední posouzení vyhraje
    rows = []
    for item in items(report):
        review = reviews.get(item["index"])
        rows.append({"text": item["text"], "status": review.status if review else "",
                     "label": review.get_status_display() if review else "",
                     "note": review.note if review else "",
                     "date": review.session.date if review else None})
    return {"report": report, "rows": rows, "when": when(report),
            "reviewed": sum(1 for r in rows if r["status"])}
