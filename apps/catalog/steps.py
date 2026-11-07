"""Kroky nastavení testování: sporty, baterie, klíčové ukazatele, MDC, normy, dotazníky (a jejich kroky)."""

from django.db.models import Q

from apps.core.steps import step


def catalog_status(user) -> dict:
    """Čísla, ze kterých se skládají kroky tady i ve Stavu pracoviště."""
    from apps.rules.models import Rule
    from apps.subjects.models import Sport

    from .models import Norm, TestBattery

    shared = Q(organization__isnull=True) | Q(organization=user.organization)
    sports = list(Sport.objects.for_user(user))
    batteries = list(TestBattery.objects.for_user(user)
                     .prefetch_related("items__protocol__protocol_metrics__metric"))
    with_battery = {b.sport_id for b in batteries if b.items.all()}
    protocols = {item.protocol.pk: item.protocol for b in batteries for item in b.items.all()}
    no_metrics = [p for p in protocols.values() if not p.protocol_metrics.all()]
    no_key = [p for p in protocols.values() if p.protocol_metrics.all()
              and not any(pm.is_primary for pm in p.protocol_metrics.all())]
    key_metrics = {pm.metric.pk: pm.metric for p in protocols.values()
                   for pm in p.protocol_metrics.all() if pm.is_primary}
    return {
        "sports": sports, "sports_without": [s for s in sports if s.pk not in with_battery],
        "protocols": protocols, "no_metrics": no_metrics, "no_key": no_key,
        "key_metrics": key_metrics, "no_mdc": [m for m in key_metrics.values() if m.mdc is None],
        "no_text": [m for m in key_metrics.values() if not m.athlete_text],
        "norms": Norm.objects.filter(shared).count(),
        "rules": Rule.objects.filter(shared, is_active=True).count(),
    }


def catalog_steps(user, status: dict | None = None) -> list[dict]:
    from django.urls import reverse

    from apps.core import access

    c = status or catalog_status(user)
    sports, without = c["sports"], c["sports_without"]
    protocols, no_metrics, no_key = c["protocols"], c["no_metrics"], c["no_key"]
    key_metrics, no_mdc = c["key_metrics"], c["no_mdc"]
    may_add = access.may_add_sport(user)
    return [
        step(1, "Sporty", bool(sports),
             f"{len(sports)} sportů." if sports else "Založte sport, který v laboratoři testujete.",
             url=reverse("sport_list") + ("#pridat-sport" if may_add else ""),
             button="Přidat sport" if may_add else "Sporty"),
        step(2, "Baterie testů", bool(sports) and not without,
             (f"{len(sports) - len(without)} z {len(sports)} sportů má baterii; bez ní se "
              "testovací den nepředvyplní." if sports else "Které testy se u sportu měří "
                                                          "a v jakém pořadí."),
             url=reverse("sport_list"), button="Sestavit baterie",
             count=len(without) or None),
        step(3, "Klíčové ukazatele", bool(protocols) and not no_metrics and not no_key,
             (" ".join(filter(None, [
                 f"{len(no_metrics)} testů bez ukazatelů." if no_metrics else "",
                 f"{len(no_key)} testů bez klíčového ukazatele – ten jde na kartu sportovce "
                 "a do týmového přehledu." if no_key else ""]))
              or (f"{len(protocols)} testů v bateriích, každý má klíčový ukazatel."
                  if protocols else "Testy přibudou s bateriemi.")),
             url=reverse("test_list"), button="Testy", count=(len(no_metrics) + len(no_key)) or None),
        step(4, "MDC u klíčových ukazatelů", bool(key_metrics) and not no_mdc,
             (f"{len(no_mdc)} z {len(key_metrics)} klíčových ukazatelů nemá MDC – bez něj zpráva "
              "neřekne „zlepšení“, jen že změnu nelze odlišit od chyby měření."
              if no_mdc else (f"Všech {len(key_metrics)} klíčových ukazatelů má MDC."
                              if key_metrics else "Nejdřív klíčové ukazatele.")),
             url=reverse("mdc_settings"), button="Doplnit MDC", admin_only=True,
             count=len(no_mdc) or None),
        step(5, "Normy a pravidla", c["norms"] > 0 or c["rules"] > 0,
             (f"{c['norms']} norem, {c['rules']} aktivních pravidel." if c["norms"] or c["rules"]
              else "Bez norem zpráva neukáže postavení vůči referenci; pravidla dávají nálezy "
                   "a doporučení. Zapíná je ten, kdo za práh ručí."),
             url=reverse("norms_settings"), button="Normy a pravidla", optional=True),
        step(6, "Popisy pro klienta", bool(key_metrics) and not c["no_text"],
             (f"{len(c['no_text'])} z {len(key_metrics)} klíčových ukazatelů nemá popis pro "
              "sportovce – portál ukáže jen číslo." if c["no_text"] else
              (f"Všech {len(key_metrics)} klíčových ukazatelů má popis pro sportovce."
               if key_metrics else "Nejdřív klíčové ukazatele.")),
             url=reverse("client_texts"), button="Doplnit popisy", admin_only=True,
             optional=True, count=len(c["no_text"]) or None),
    ]


def norm_status(user, status: dict | None = None) -> dict:
    from .models import Norm

    c = status or catalog_status(user)
    shared = Q(organization__isnull=True) | Q(organization=user.organization)
    norms = list(Norm.objects.filter(shared).select_related("metric"))
    key_ids = set(c["key_metrics"])
    return {
        "catalog": c, "norms": norms,
        "key_with_norm": {n.metric_id for n in norms if n.metric_id in key_ids},
        "no_values": [n for n in norms if (n.mean is None or not n.sd) and not n.percentiles],
        "short_source": [n for n in norms if len(n.source_citation.strip()) < 30],
    }


def norm_steps(user, status: dict | None = None) -> list[dict]:
    """Kroky norem: klíčové ukazatele s normou, použitelné hodnoty, zdroje, pravidla."""
    from django.urls import reverse

    n = norm_status(user, status)
    c, key = n["catalog"], n["catalog"]["key_metrics"]
    missing = len(key) - len(n["key_with_norm"])
    return [
        step(1, "Normy u klíčových ukazatelů", bool(key) and missing == 0,
             (f"{len(n['key_with_norm'])} z {len(key)} klíčových ukazatelů má normu; bez ní "
              "zpráva u ukazatele neukáže postavení vůči referenci." if key
              else "Nejdřív klíčové ukazatele (Testy)."),
             url=reverse("norm_new"), button="Nová norma", count=missing or None),
        step(2, "Hodnoty", not n["no_values"],
             (f"{len(n['no_values'])} norem bez použitelných hodnot – průměr a SD, nebo "
              "percentily." if n["no_values"]
              else "Každá norma má průměr a SD, nebo percentily." if n["norms"]
              else "Zatím žádná norma."),
             url="#normy", button="K normám", count=len(n["no_values"]) or None),
        step(3, "Zdroje", not n["short_source"],
             (f"{len(n['short_source'])} norem s neúplnou citací – doplňte autory, název, "
              "časopis a rok." if n["short_source"]
              else "Každá norma má citaci zdroje." if n["norms"] else "Zatím žádná norma."),
             url="#normy", button="K normám", count=len(n["short_source"]) or None),
        step(4, "Pravidla", c["rules"] > 0,
             (f"{c['rules']} aktivních pravidel." if c["rules"]
              else "Pravidla dávají nálezy a doporučení; zapíná je ten, kdo za práh ručí."),
             url=reverse("rules_settings"), button="Pravidla", optional=True),
    ]


def question_problems(question) -> list[str]:
    """Co otázce chybí, aby šla vyplnit: dvě možnosti u výběru, správná škála."""
    Kind = question.Kind
    out = []
    if question.kind in (Kind.CHOICE, Kind.MULTI) and len(question.option_codes()) < 2:
        out.append("méně než dvě možnosti")
    if question.kind == Kind.SCALE and question.scale_min >= question.scale_max:
        out.append("škála „od“ není menší než „do“")
    return out


def questionnaire_problems(questionnaire) -> list[str]:
    questions = list(questionnaire.questions.all())
    if not questions:
        return ["bez otázek"]
    return [f"otázka „{q.text}“: {', '.join(p)}" for q in questions
            if (p := question_problems(q))]


def questionnaire_status(user) -> dict:
    from django.db.models import Count

    from apps.measurements.questionnaires import RPE, STANDALONE

    from .models import Questionnaire

    shared = Q(organization__isnull=True) | Q(organization=user.organization)
    rows = list(Questionnaire.objects.filter(shared).prefetch_related("questions")
                .annotate(vyplneni=Count("responses", distinct=True,
                                         filter=Q(responses__subject__organization=user.organization)))
                .order_by("-is_active", "name"))
    for q in rows:
        q.problems = questionnaire_problems(q)
        q.question_count = len(q.questions.all())
    active = [q for q in rows if q.is_active]
    return {
        "questionnaires": rows, "active": active,
        "invalid": [q for q in rows if q.is_active and q.problems],
        "custom": [q for q in rows if q.code not in (RPE, *STANDALONE)],
        "responses": sum(q.vyplneni for q in rows),
    }


def questionnaire_steps(user, status: dict | None = None) -> list[dict]:
    """Kroky dotazníků: aktivní dotazníky, úplné otázky, vyplnění."""
    from django.urls import reverse

    s = status or questionnaire_status(user)
    rows, active, invalid, custom = s["questionnaires"], s["active"], s["invalid"], s["custom"]
    return [
        step(1, "Dotazníky", bool(active),
             (f"{len(active)} aktivních z {len(rows)}: RPE po testu, dotazník genetiky"
              + (f", {len(custom)} vlastních." if custom else
                 ". Vlastní dotazník (únava, spánek, bolest) se nabídne v testovacím dni.")
              if rows else "Zatím žádný dotazník – RPE a dotazník genetiky doplní start aplikace."),
             url=reverse("questionnaire_new"), button="Nový dotazník"),
        step(2, "Otázky", not invalid,
             (f"{len(invalid)} aktivních dotazníků s neúplnými otázkami – bez otázek, s méně než "
              "dvěma možnostmi nebo se špatnou škálou." if invalid
              else "Každý aktivní dotazník má úplné otázky." if active
              else "Otázky se doplňují u dotazníku."),
             url="#dotazniky", button="K dotazníkům", count=len(invalid) or None),
        step(3, "Vyplnění", s["responses"] > 0,
             (f"{s['responses']} vyplněných dotazníků sportovců pracoviště." if s["responses"] else
              "Zatím nic vyplněného: RPE se zapisuje v testovacím dni (operátor, nebo sportovec "
              "přes QR kód), dotazník genetiky u sportovce v Genetice."),
             url=reverse("session_list"), button="Testovací dny", optional=True),
    ]
