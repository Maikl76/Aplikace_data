"""
Založí sdílený katalog metrik a protokolů.

Spouští se jednou při zakládání databáze. Dál se katalog spravuje
v administraci – tohle je jen startovní obsah, ne konfigurace aplikace.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import (
    ImportColumn,
    ImportProfile,
    MetricDef,
    Protocol,
    ProtocolMetric,
)
from apps.catalog.seed_data import (
    DSI_RULES,
    EXAMPLE_RULES,
    IMPORT_PROFILES,
    METRIC_EXTRAS,
    METRICS,
    PROTOCOLS,
    SEED_ARTICLES,
)


class Command(BaseCommand):
    help = "Založí sdílené metriky a protokoly (organization = NULL)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--jen-chybejici", action="store_true", dest="only_missing",
            help="Jen doplní, co v katalogu chybí (nové metriky, protokoly, pravidla). "
                 "Nic existujícího nepřepíše – úpravy z administrace zůstanou. "
                 "Takhle ho volá spustit.bat při každém startu.")

    @transaction.atomic
    def handle(self, *args, **options):
        only_missing = options.get("only_missing")
        # Při doplňování se existující záznamy nemění (get_or_create),
        # při zakládání databáze se srovnají s výchozí sadou (update_or_create).
        save = "get_or_create" if only_missing else "update_or_create"
        metrics = {}
        for code, name, family, unit, direction, lo, hi, decimals in METRICS:
            metrics[code], _ = getattr(MetricDef.objects, save)(
                organization=None, code=code,
                defaults={"name": name, "family": family, "unit": unit,
                          "direction": direction, "plausible_min": lo,
                          "plausible_max": hi, "decimals": decimals},
            )

        for code, extras in METRIC_EXTRAS.items():
            metric = metrics[code]
            changed = []
            if extras.get("ods") and not metric.ods_role:
                metric.ods_role = extras["ods"]
                changed.append("ods_role")
            if extras.get("cv") and metric.trial_cv_limit is None:
                metric.trial_cv_limit = extras["cv"]
                changed.append("trial_cv_limit")
            if changed:
                metric.save(update_fields=changed)

        for code, spec in PROTOCOLS.items():
            protocol, _ = getattr(Protocol.objects, save)(
                organization=None, code=code, version=1,
                defaults={"name": spec["name"], "family": spec["family"],
                          "device": spec["device"],
                          "default_trials": spec.get("trials", 3)},
            )
            for order, entry in enumerate(spec["metrics"]):
                getattr(ProtocolMetric.objects, save)(
                    protocol=protocol, metric=metrics[entry["code"]],
                    defaults={
                        "order": order,
                        "is_primary": entry.get("primary", False),
                        "sides": entry.get("sides", []),
                        "modes": entry.get("modes", []),
                        "speeds": entry.get("speeds", []),
                        "segments": entry.get("segments", []),
                    },
                )

        # Profily importu se jen zakládají, nepřepisují – úpravy
        # v administraci (další sloupce, jiné přiřazení) musí přežít.
        for device, test_type, protocol_code, columns in IMPORT_PROFILES:
            profile, _ = ImportProfile.objects.get_or_create(
                organization=None, device=device, test_type=test_type,
                defaults={"protocol": Protocol.objects.get(organization=None,
                                                           code=protocol_code, version=1)},
            )
            for column, metric_code, factor, *sides in columns:
                ImportColumn.objects.get_or_create(
                    profile=profile, column=column,
                    defaults={"metric": metrics[metric_code], "factor": factor,
                              "with_sides": sides[0] if sides else True},
                )

        from apps.evidence.models import Article
        from apps.rules.models import Rule, RuleArticle

        articles = {}
        for spec in SEED_ARTICLES:
            articles[spec["doi"]], _ = Article.objects.get_or_create(
                doi=spec["doi"], defaults={k: v for k, v in spec.items() if k != "doi"})

        # Pravidla k DSI mají literaturu, ale prahy jsou orientační –
        # zakládají se neaktivní stejně jako ostatní příklady.
        for spec in DSI_RULES:
            rule, _ = Rule.objects.get_or_create(
                organization=None, code=spec["code"], version=1,
                defaults={
                    "name": spec["name"], "condition": spec["condition"],
                    "contraindication": spec.get("contraindication", {}),
                    "severity": spec["severity"],
                    "finding_template": spec["finding_template"],
                    "recommendation_template": spec.get("recommendation_template", ""),
                    "is_active": False,
                },
            )
            for doi in spec.get("articles", []):
                RuleArticle.objects.get_or_create(rule=rule, article=articles[doi])

        for spec in EXAMPLE_RULES:
            getattr(Rule.objects, save)(
                organization=None, code=spec["code"], version=1,
                defaults={
                    "name": spec["name"],
                    "condition": spec["condition"],
                    "contraindication": spec.get("contraindication", {}),
                    "severity": spec["severity"],
                    "finding_template": spec["finding_template"],
                    "recommendation_template": spec.get("recommendation_template", ""),
                    # Příklady se zakládají NEAKTIVNÍ. Prahy v nich nejsou
                    # ověřené a nemají citace – zapnout je smí až člověk,
                    # který za ně ručí.
                    "is_active": False,
                },
            )

        if only_missing:
            return

        self.stdout.write(self.style.SUCCESS(
            f"Katalog: {len(metrics)} metrik, {len(PROTOCOLS)} protokolů, "
            f"{len(EXAMPLE_RULES)} ukázkových pravidel."
        ))
        self.stdout.write(self.style.WARNING(
            "Pravidla jsou založená NEAKTIVNÍ. Prahy v nich jsou ilustrativní "
            "a nemají citace – než je zapnete, ověřte je a připojte literaturu."
        ))

        bez_mdc = [m.code for m in metrics.values() if m.mdc is None]
        if bez_mdc:
            self.stdout.write(self.style.WARNING(
                f"\n{len(bez_mdc)} metrik nemá vyplněnou MDC. Dokud chybí, "
                f"analytika u opakovaného měření neřekne „zlepšení“, ale že "
                f"změnu nelze odlišit od chyby měření.\n"
                f"Doplňte v administraci z literatury nebo z vlastní "
                f"reliability studie: {', '.join(bez_mdc[:6])}"
                f"{' …' if len(bez_mdc) > 6 else ''}"
            ))
