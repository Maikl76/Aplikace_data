"""Kroky nastavení testování: sporty, baterie, klíčové ukazatele, MDC, normy."""

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
        "norms": Norm.objects.filter(shared).count(),
        "rules": Rule.objects.filter(shared, is_active=True).count(),
    }


def catalog_steps(user, status: dict | None = None) -> list[dict]:
    from django.urls import reverse

    c = status or catalog_status(user)
    sports, without = c["sports"], c["sports_without"]
    protocols, no_metrics, no_key = c["protocols"], c["no_metrics"], c["no_key"]
    key_metrics, no_mdc = c["key_metrics"], c["no_mdc"]
    return [
        step(1, "Sporty", bool(sports),
             f"{len(sports)} sportů." if sports else "Založte sport, který v laboratoři testujete.",
             url=reverse("sport_list") + "#pridat-sport", button="Přidat sport"),
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
             url="/admin/catalog/metricdef/", button="Doplnit MDC", admin_only=True,
             count=len(no_mdc) or None),
        step(5, "Normy a pravidla", c["norms"] > 0 or c["rules"] > 0,
             (f"{c['norms']} norem, {c['rules']} aktivních pravidel." if c["norms"] or c["rules"]
              else "Bez norem zpráva neukáže postavení vůči referenci; pravidla dávají nálezy "
                   "a doporučení. Zapíná je ten, kdo za práh ručí."),
             url="/admin/catalog/norm/", button="Normy a pravidla", optional=True,
             admin_only=True),
    ]
