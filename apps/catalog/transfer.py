"""
Přenos katalogu mezi počítači a na server.

Katalog (protokoly, metriky s MDC, normy, pravidla, články) se zadává
v administraci, takže žije v databázi – a databáze se mezi počítači
nepřenáší. Tady se převádí na soubor v repozitáři a zpět. Katalog pak
putuje s kódem přes git a je vidět, kdy se které pravidlo nebo MDC změnilo.

Záznamy se párují podle kódů (ne podle čísel řádků, ta jsou v každé
databázi jiná). Import přidává a aktualizuje, nikdy nemaže: co v souboru
chybí, zůstane v databázi beze změny.
"""

from django.db import transaction

from apps.core.models import Organization
from apps.evidence.models import Article
from apps.rules.models import Rule, RuleArticle
from apps.subjects.models import Sport

from .models import MetricDef, Norm, Protocol, ProtocolMetric

FORMAT_VERSION = 1
SKIP = {"id", "created_at", "updated_at", "organization"}


def _plain(obj, *, skip=()) -> dict:
    """Obyčejná pole záznamu – bez klíčů, cizích klíčů a časových razítek."""
    return {
        f.name: getattr(obj, f.name)
        for f in obj._meta.concrete_fields
        if f.name not in SKIP and f.name not in skip and not f.is_relation
    }


def _org(obj) -> str | None:
    return obj.organization.short_name if obj.organization_id else None


def _sport(sport) -> dict | None:
    if sport is None:
        return None
    return {"code": sport.code, "name": sport.name,
            "organizace": sport.organization.short_name}


def _article_key(article) -> dict:
    """Článek nemá kód; pozná se podle DOI, PMID, nebo názvu a roku."""
    if article.doi:
        return {"doi": article.doi}
    if article.pmid:
        return {"pmid": article.pmid}
    return {"title": article.title, "year": article.year}


def export_catalog() -> dict:
    return {
        "format": FORMAT_VERSION,
        "metriky": [
            {"organizace": _org(m), **_plain(m)}
            for m in MetricDef.objects.order_by("code")
        ],
        "protokoly": [
            {
                "organizace": _org(p), **_plain(p),
                "metriky": [
                    {"metrika": pm.metric.code, **_plain(pm, skip={"protocol", "metric"})}
                    for pm in p.protocol_metrics.select_related("metric").order_by("order")
                ],
            }
            for p in Protocol.objects.order_by("code", "version")
        ],
        "normy": [
            {"organizace": _org(n), "metrika": n.metric.code, "sport": _sport(n.sport),
             **_plain(n)}
            for n in Norm.objects.select_related("metric", "sport")
            .order_by("metric__code", "sex", "age_min", "speed", "pk")
        ],
        "clanky": [
            _plain(a) for a in Article.objects.order_by("year", "title")
        ],
        "pravidla": [
            {
                "organizace": _org(r), "sport": _sport(r.applies_to_sport), **_plain(r),
                "clanky": [
                    {"clanek": _article_key(ra.article), "relevance_note": ra.relevance_note}
                    for ra in r.rule_articles.select_related("article")
                ],
            }
            for r in Rule.objects.order_by("code", "version")
        ],
    }


class ImportError_(Exception):
    """Soubor nejde načíst – uživatel se musí dozvědět proč."""


class _Importer:
    def __init__(self, default_org: Organization | None):
        self.default_org = default_org
        self.counts: dict[str, list[int]] = {}

    def org(self, short_name):
        if short_name is None:
            return None
        found = Organization.objects.filter(short_name=short_name).first()
        if found:
            return found
        if self.default_org:
            return self.default_org
        raise ImportError_(
            f"V databázi není organizace „{short_name}“. Založte ji, nebo zadejte "
            f"--organizace se zkratkou existující organizace."
        )

    def sport(self, data):
        if not data:
            return None
        org = self.org(data["organizace"])
        sport, _ = Sport.objects.get_or_create(organization=org, code=data["code"],
                                               defaults={"name": data["name"]})
        return sport

    def upsert(self, label, model, lookup, values):
        obj, created = model.objects.update_or_create(**lookup, defaults=values)
        created_n, updated_n = self.counts.setdefault(label, [0, 0])
        self.counts[label] = [created_n + created, updated_n + (not created)]
        return obj

    def metric(self, code, org):
        metric = (MetricDef.objects.filter(code=code, organization=org).first()
                  or MetricDef.objects.filter(code=code).first())
        if metric is None:
            raise ImportError_(f"Metrika „{code}“ v souboru chybí.")
        return metric


def _data_fields(item: dict, *remove) -> dict:
    return {k: v for k, v in item.items() if k not in {"organizace", *remove}}


@transaction.atomic
def import_catalog(data: dict, *, default_org: Organization | None = None) -> dict:
    if data.get("format") != FORMAT_VERSION:
        raise ImportError_(f"Neznámý formát souboru ({data.get('format')!r}).")

    imp = _Importer(default_org)

    for item in data["metriky"]:
        org = imp.org(item["organizace"])
        imp.upsert("metriky", MetricDef, {"organization": org, "code": item["code"]},
                   _data_fields(item, "code"))

    for item in data["protokoly"]:
        org = imp.org(item["organizace"])
        protocol = imp.upsert(
            "protokoly", Protocol,
            {"organization": org, "code": item["code"], "version": item["version"]},
            _data_fields(item, "code", "version", "metriky"))
        for pm in item["metriky"]:
            imp.upsert("metriky protokolů", ProtocolMetric,
                       {"protocol": protocol, "metric": imp.metric(pm["metrika"], org)},
                       _data_fields(pm, "metrika"))

    # Normy nemají přirozený klíč; párují se podle toho, pro koho platí.
    for item in data["normy"]:
        org = imp.org(item["organizace"])
        lookup = {
            "organization": org,
            "metric": imp.metric(item["metrika"], org),
            "sport": imp.sport(item["sport"]),
            **{k: item[k] for k in ("sex", "age_min", "age_max", "level",
                                    "side", "mode", "speed")},
        }
        imp.upsert("normy", Norm, lookup,
                   _data_fields(item, "metrika", "sport", *lookup))

    for item in data["clanky"]:
        key = _article_key(Article(**{k: item.get(k) for k in ("doi", "pmid", "title",
                                                                  "year")}))
        imp.upsert("články", Article, key, _data_fields(item, *key))

    for item in data["pravidla"]:
        org = imp.org(item["organizace"])
        rule = imp.upsert(
            "pravidla", Rule,
            {"organization": org, "code": item["code"], "version": item["version"]},
            {**_data_fields(item, "code", "version", "sport", "clanky"),
             "applies_to_sport": imp.sport(item["sport"])})
        for link in item["clanky"]:
            article = Article.objects.filter(**link["clanek"]).first()
            if article is None:
                raise ImportError_(f"Pravidlo {rule.code} odkazuje na článek, "
                                   f"který v souboru není: {link['clanek']}.")
            imp.upsert("vazby pravidel na články", RuleArticle,
                       {"rule": rule, "article": article},
                       {"relevance_note": link["relevance_note"]})

    return imp.counts
