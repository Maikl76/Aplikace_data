"""
Přenos nastavení mezi instancemi (počítače v laboratoři, zkušební
provoz na webu, server).

Všechno, co se v aplikaci nastavuje – katalog testů a ukazatelů s MDC,
normy, pravidla, články, genetika, dotazníky, baterie, sporty a týmy,
nabídka objednávek, nastavení pracoviště – žije v databázi, a databáze se
mezi instancemi nepřenáší. Tady se převádí na jeden soubor (balíček)
a zpět: v aplikaci Nastavení → Přenos nastavení (stáhnout / nahrát
s náhledem), nebo příkazy export_katalog / import_katalog přes git.

Sportovci, měření, zprávy, objednávky, účty ani klíče do balíčku nepatří.

Záznamy se párují podle kódů (ne podle čísel řádků, ta jsou v každé
databázi jiná). Import přidává a aktualizuje, nikdy nemaže: co v souboru
chybí, zůstane v databázi beze změny. Beze změny se nepřepisuje ani to,
co je v souboru stejné – jde pak poznat, co přenos opravdu změnil.
"""

import socket

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.models import Organization
from apps.evidence.models import Article
from apps.rules.models import Rule, RuleArticle
from apps.subjects.models import Sport, Team

from .models import (
    BatteryItem,
    DeviceFormat,
    ImportColumn,
    ImportProfile,
    MetricDef,
    Norm,
    Protocol,
    ProtocolMetric,
    Question,
    Questionnaire,
    TestBattery,
)
from .norms import normalize_fields

FORMAT_VERSION = 1
SKIP = {"id", "created_at", "updated_at", "organization"}
# Nastavení pracoviště, které má smysl přenášet (ne stav údržby ani název).
ORGANIZATION_SETTINGS = ("auto_draft", "reference_enabled", "reference_min_subjects",
                         "reference_source")


def instance_label() -> str:
    """Odkud balíček je: veřejná adresa, jinak jméno počítače."""
    return settings.PUBLIC_BASE_URL or socket.gethostname()


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
    from apps.booking.models import Offer

    return {
        "format": FORMAT_VERSION,
        "meta": {"vytvoreno": timezone.now().isoformat(timespec="seconds"),
                 "instance": instance_label(),
                 "organizace": list(Organization.objects.order_by("short_name")
                                    .values_list("short_name", flat=True))},
        "pracoviste": [
            {"organizace": o.short_name, **{k: getattr(o, k) for k in ORGANIZATION_SETTINGS}}
            for o in Organization.objects.order_by("short_name")
        ],
        "sporty": [
            {"organizace": _org(sp), **_plain(sp)}
            for sp in Sport.objects.select_related("organization").order_by("code")
        ],
        "tymy": [
            {"organizace": _org(t), "sport": t.sport.code, "name": t.name}
            for t in Team.objects.select_related("sport", "organization")
            .order_by("sport__code", "name")
        ],
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
        # Přístroje z průvodce „Nový přístroj“ – jen nastavení, žádná data.
        "pristroje": [
            {"organizace": _org(d), "protokol": d.protocol.code,
             "verze_protokolu": d.protocol.version, **_plain(d)}
            for d in DeviceFormat.objects.select_related("protocol").order_by("code")
        ],
        "profily_importu": [
            {
                "organizace": _org(ip), "protokol": ip.protocol.code,
                "verze_protokolu": ip.protocol.version, **_plain(ip),
                "sloupce": [
                    {"metrika": c.metric.code, **_plain(c, skip={"profile", "metric"})}
                    for c in ip.columns.select_related("metric")
                ],
            }
            for ip in ImportProfile.objects.select_related("protocol")
            .order_by("device", "test_type")
        ],
        "baterie": [
            {"sport": _sport(b.sport), "category": b.category, "name": b.name, "note": b.note,
             "retest_weeks": b.retest_weeks,
             "protokoly": [{"kod": i.protocol.code, "verze": i.protocol.version}
                           for i in b.items.select_related("protocol")]}
            for b in TestBattery.objects.select_related("sport", "sport__organization")
            .order_by("sport__code", "category")
        ],
        # Nabídka testování pro objednávky (položky a ceny) – termíny ne, ty jsou provoz.
        "nabidka": [
            {"organizace": _org(o), **_plain(o),
             "testy": sorted({p.code for p in o.protocols.all()})}
            for o in Offer.objects.select_related("organization").prefetch_related("protocols")
            .order_by("order", "name")
        ],
        # Pokyny pro jazykový model k variantám zprávy (AI zprávy → Pokyny).
        "styly_zprav": _report_styles(),
        "dotazniky": [
            {"organizace": _org(q), **_plain(q),
             "otazky": [_plain(o, skip={"questionnaire"}) for o in q.questions.all()]}
            for q in Questionnaire.objects.order_by("code")
        ],
        "normy": [
            {"organizace": _org(n), "metrika": n.metric.code, "sport": _sport(n.sport),
             **_plain(n)}
            for n in Norm.objects.select_related("metric", "sport")
            .order_by("metric__code", "sex", "age_min", "speed", "pk")
        ],
        "clanky": [
            {**_plain(a, skip={"pdf", "ai_draft", "ai_writing_model",
                               "ai_writing_started_at"}),
             # Témata: ukazatele a testy podle kódu (čísla řádků se mezi databázemi liší).
             "metriky": sorted({m.code for m in a.metrics.all()}),
             "testy": sorted({p.code for p in a.protocols.all()}),
             "sporty": [_sport(sp) for sp in a.sports.order_by("code")]}
            for a in Article.objects.order_by("year", "title")
            .prefetch_related("metrics", "protocols")
        ],
        "genetika": _genetics_export(),
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


def _genetics_export() -> dict:
    from apps.genetics.transfer import export_genetics

    return export_genetics()


def _report_styles() -> list[dict]:
    from apps.reports.models import ReportStyle

    return [{"organizace": _org(st), "audience": st.audience, "kind": st.kind,
             "instructions": st.instructions}
            for st in ReportStyle.objects.select_related("organization")
            .order_by("organization__short_name", "audience", "kind")]


class ImportError_(Exception):
    """Soubor nejde načíst – uživatel se musí dozvědět proč."""


def _same(current, new) -> bool:
    """Hodnota v databázi odpovídá hodnotě ze souboru (datum může přijít jako text)."""
    if current == new:
        return True
    if current is None or new is None:
        return False
    return str(current) == str(new)


def empty_counts() -> dict:
    return {"nove": 0, "zmenene": 0, "beze_zmeny": 0}


class _Importer:
    def __init__(self, default_org: Organization | None):
        self.default_org = default_org
        self.counts: dict[str, dict[str, int]] = {}

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

    def count(self, label, key):
        self.counts.setdefault(label, empty_counts())[key] += 1

    def upsert(self, label, model, lookup, values):
        """Založí, nebo upraví záznam; stejný záznam nechá být (a nepřepíše mu čas změny)."""
        existing = model.objects.filter(**lookup).first()
        if existing is not None and all(_same(getattr(existing, k), v)
                                        for k, v in values.items()):
            self.count(label, "beze_zmeny")
            return existing
        obj, created = model.objects.update_or_create(**lookup, defaults=values)
        self.count(label, "nove" if created else "zmenene")
        return obj

    def metric(self, code, org):
        metric = (MetricDef.objects.filter(code=code, organization=org).first()
                  or MetricDef.objects.filter(code=code).first())
        if metric is None:
            raise ImportError_(f"Metrika „{code}“ v souboru chybí.")
        return metric


def _protocol(item: dict, org) -> Protocol:
    protocol = (Protocol.objects.filter(code=item["protokol"], version=item["verze_protokolu"],
                                        organization=org).first()
                or Protocol.objects.filter(code=item["protokol"],
                                           version=item["verze_protokolu"]).first())
    if protocol is None:
        raise ImportError_(f"Protokol „{item['protokol']}“ v souboru chybí.")
    return protocol


def _data_fields(item: dict, *remove) -> dict:
    return {k: v for k, v in item.items() if k not in {"organizace", *remove}}


@transaction.atomic
def import_catalog(data: dict, *, default_org: Organization | None = None) -> dict:
    if data.get("format") != FORMAT_VERSION:
        raise ImportError_(f"Neznámý formát souboru ({data.get('format')!r}).")

    imp = _Importer(default_org)

    # Nastavení pracoviště: jen volby, ne název ani stav údržby. Pracoviště
    # se nezakládá – neznámá zkratka se převede na zadané (výchozí).
    for item in data.get("pracoviste", []):
        org = imp.org(item["organizace"])
        values = {k: item[k] for k in ORGANIZATION_SETTINGS if k in item}
        if org is not None and values:
            imp.upsert("nastavení pracoviště", Organization, {"pk": org.pk}, values)

    for item in data.get("sporty", []):
        org = imp.org(item["organizace"])
        imp.upsert("sporty", Sport, {"organization": org, "code": item["code"]},
                   _data_fields(item, "code"))

    for item in data.get("tymy", []):
        sport = imp.sport({"organizace": item["organizace"], "code": item["sport"],
                           "name": item["sport"]})
        imp.upsert("týmy", Team, {"organization": sport.organization, "sport": sport,
                                  "name": item["name"]}, {})

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

    for item in data.get("pristroje", []):
        org = imp.org(item["organizace"])
        protocol = _protocol(item, org)
        imp.upsert("přístroje", DeviceFormat, {"organization": org, "code": item["code"]},
                   {**_data_fields(item, "code", "protokol", "verze_protokolu"),
                    "protocol": protocol})

    for item in data.get("profily_importu", []):
        org = imp.org(item["organizace"])
        protocol = _protocol(item, org)
        profile = imp.upsert(
            "profily importu", ImportProfile,
            {"organization": org, "device": item["device"], "test_type": item["test_type"]},
            {**_data_fields(item, "device", "test_type", "protokol", "verze_protokolu",
                            "sloupce"), "protocol": protocol})
        for col in item["sloupce"]:
            imp.upsert("importované sloupce", ImportColumn,
                       {"profile": profile, "column": col["column"]},
                       {"metric": imp.metric(col["metrika"], org), "factor": col["factor"],
                        "with_sides": col.get("with_sides", True),
                        "side": col.get("side", ""), "segment": col.get("segment", "")})

    # Baterie: chybějící testy se doplní a pořadí srovná podle souboru;
    # testy, které v souboru nejsou, zůstanou (import nic nemaže).
    for item in data.get("baterie", []):
        sport = imp.sport(item["sport"])
        values = {"organization": sport.organization, "name": item["name"],
                  "note": item.get("note", "")}
        if "retest_weeks" in item:     # starší soubory interval nemají – nepřepsat ho prázdným
            values["retest_weeks"] = item["retest_weeks"]
        battery = imp.upsert("baterie testů", TestBattery,
                             {"sport": sport, "category": item["category"]}, values)
        for order, ref in enumerate(item["protokoly"], start=1):
            protocol = Protocol.objects.filter(code=ref["kod"], version=ref["verze"]).first()
            if protocol is None:
                raise ImportError_(f"Protokol „{ref['kod']}“ z baterie v souboru chybí.")
            BatteryItem.objects.update_or_create(battery=battery, protocol=protocol,
                                                 defaults={"order": order})

    from apps.booking.models import Offer

    for item in data.get("nabidka", []):
        org = imp.org(item["organizace"])
        if org is None:
            continue
        offer = imp.upsert("nabídka objednávek", Offer, {"organization": org, "name": item["name"]},
                           _data_fields(item, "name", "testy"))
        if "testy" in item:
            offer.protocols.set(Protocol.objects.filter(code__in=item["testy"]))

    from apps.reports.models import ReportStyle

    for item in data.get("styly_zprav", []):
        org = imp.org(item["organizace"])
        if org is not None:
            imp.upsert("styly zpráv", ReportStyle,
                       {"organization": org, "audience": item["audience"],
                        "kind": item.get("kind") or ReportStyle.Kind.SUMMARY},
                       {"instructions": item["instructions"]})

    for item in data.get("dotazniky", []):
        questionnaire = imp.upsert(
            "dotazníky", Questionnaire,
            {"organization": imp.org(item["organizace"]), "code": item["code"]},
            _data_fields(item, "code", "otazky"))
        for q in item["otazky"]:
            imp.upsert("otázky dotazníků", Question,
                       {"questionnaire": questionnaire, "code": q["code"]},
                       _data_fields(q, "code"))

    # Normy nemají přirozený klíč; párují se podle toho, pro koho platí.
    for item in data["normy"]:
        org = imp.org(item["organizace"])
        # Starší soubory mají úroveň, stranu a režim jako volný text.
        for lost in normalize_fields(item):
            item["note"] = f"{item.get('note', '')}\nPři převodu nešlo poznat: {lost}.".strip()
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
        article = imp.upsert("články", Article, key,
                             _data_fields(item, *key, "metriky", "testy", "sporty"))
        if "metriky" in item:
            article.metrics.set(MetricDef.objects.filter(code__in=item["metriky"]))
        if "testy" in item:
            article.protocols.set(Protocol.objects.filter(code__in=item["testy"]))
        if "sporty" in item:
            article.sports.set([imp.sport(sp) for sp in item["sporty"]])

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

    if data.get("genetika"):
        from apps.genetics.transfer import import_genetics

        try:
            import_genetics(data["genetika"], imp)
        except ValueError as exc:
            raise ImportError_(str(exc)) from exc

    return imp.counts


def preview_catalog(data: dict, *, default_org: Organization | None = None) -> dict:
    """Co by import udělal: proběhne celý a vrátí se zpět, databáze zůstane, jak byla."""
    with transaction.atomic():
        counts = import_catalog(data, default_org=default_org)
        transaction.set_rollback(True)
    return counts


def totals(counts: dict) -> dict:
    """Součet přes všechny části balíčku."""
    total = empty_counts()
    for entry in counts.values():
        for key in total:
            total[key] += entry.get(key, 0)
    return total


def describe(data: dict) -> dict:
    """Odkud a z kdy balíček je a kolik čeho obsahuje (pro náhled před načtením)."""
    meta = data.get("meta") or {}
    counts = {label: len(data.get(key) or []) for key, label in INVENTORY}
    genetics = data.get("genetika") or {}
    counts["genové karty"] = len(genetics.get("karty") or [])
    return {"instance": meta.get("instance", ""), "vytvoreno": meta.get("vytvoreno", ""),
            "organizace": meta.get("organizace", []),
            "polozky": {k: v for k, v in counts.items() if v}}


INVENTORY = [
    ("sporty", "sporty"), ("tymy", "týmy"), ("metriky", "ukazatele"), ("protokoly", "testy"),
    ("baterie", "baterie testů"), ("normy", "normy"), ("pravidla", "pravidla"),
    ("clanky", "články"), ("dotazniky", "dotazníky"), ("pristroje", "přístroje"),
    ("profily_importu", "profily importu"), ("nabidka", "nabídka objednávek"),
    ("styly_zprav", "pokyny pro model"),
]

# Tvary pro „1 sport, 3 sporty, 5 sportů“ u částí balíčku.
FORMS = {
    "sporty": ("sport", "sporty", "sportů"),
    "týmy": ("tým", "týmy", "týmů"),
    "ukazatele": ("ukazatel", "ukazatele", "ukazatelů"),
    "testy": ("test", "testy", "testů"),
    "baterie testů": ("baterie testů", "baterie testů", "baterií testů"),
    "normy": ("norma", "normy", "norem"),
    "pravidla": ("pravidlo", "pravidla", "pravidel"),
    "články": ("článek", "články", "článků"),
    "dotazníky": ("dotazník", "dotazníky", "dotazníků"),
    "přístroje": ("přístroj", "přístroje", "přístrojů"),
    "profily importu": ("profil importu", "profily importu", "profilů importu"),
    "nabídka objednávek": ("položka nabídky", "položky nabídky", "položek nabídky"),
    "pokyny pro model": ("pokyn pro model", "pokyny pro model", "pokynů pro model"),
    "genové karty": ("genová karta", "genové karty", "genových karet"),
}


def with_count(label: str, n: int) -> str:
    """„1 sport“, „3 články“, „17 genových karet“."""
    one, few, many = FORMS.get(label, (label, label, label))
    return f"{n} {one if n == 1 else few if 2 <= n <= 4 else many}"


def inventory() -> dict:
    """Kolik čeho by balíček z této instance obsahoval (bez sestavování celého balíčku)."""
    from apps.booking.models import Offer
    from apps.genetics.models import GeneCard
    from apps.reports.models import ReportStyle

    models = [
        ("sporty", Sport), ("týmy", Team), ("ukazatele", MetricDef), ("testy", Protocol),
        ("baterie testů", TestBattery), ("normy", Norm), ("pravidla", Rule), ("články", Article),
        ("dotazníky", Questionnaire), ("přístroje", DeviceFormat),
        ("profily importu", ImportProfile), ("nabídka objednávek", Offer),
        ("pokyny pro model", ReportStyle), ("genové karty", GeneCard),
    ]
    return {label: n for label, model in models if (n := model.objects.count())}
