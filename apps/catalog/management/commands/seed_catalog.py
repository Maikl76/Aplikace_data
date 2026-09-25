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
from apps.catalog.seed_data import EXAMPLE_RULES, IMPORT_PROFILES, METRICS, PROTOCOLS


class Command(BaseCommand):
    help = "Založí sdílené metriky a protokoly (organization = NULL)."

    @transaction.atomic
    def handle(self, *args, **options):
        metrics = {}
        for code, name, family, unit, direction, lo, hi, decimals in METRICS:
            metrics[code], _ = MetricDef.objects.update_or_create(
                organization=None, code=code,
                defaults={"name": name, "family": family, "unit": unit,
                          "direction": direction, "plausible_min": lo,
                          "plausible_max": hi, "decimals": decimals},
            )

        for code, spec in PROTOCOLS.items():
            protocol, _ = Protocol.objects.update_or_create(
                organization=None, code=code, version=1,
                defaults={"name": spec["name"], "family": spec["family"],
                          "device": spec["device"],
                          "default_trials": spec.get("trials", 3)},
            )
            for order, entry in enumerate(spec["metrics"]):
                ProtocolMetric.objects.update_or_create(
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

        from apps.rules.models import Rule

        for spec in EXAMPLE_RULES:
            Rule.objects.update_or_create(
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
