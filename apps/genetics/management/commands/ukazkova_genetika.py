"""
Ukázkové genetické vzorky pro zkušební provoz.

Prvním třem dospělým sportovcům (podle kódu) zapíše souhlas s genetickými
daty a jeden vzorek s fiktivními genotypy pro aktivní panel. Vzorek zůstane
neověřený: ověření příslušnosti je potvrzení diagnostika, že výsledek patří
tomuto člověku, a to za něj skript dělat nemá. Kdo vzorek už má, zůstane
beze změny; nezletilí a sportovci bez data narození se přeskočí, protože
genetika je v aplikaci jen pro dospělé.

Běží sám při aktualizaci zkušebního provozu (DEMO_MODE). Mimo ukázku se
vzorky založí jen vyjmenovaným sportovcům (--kody), aby fiktivní data
nikdy nevznikla u skutečného sportovce omylem.
"""

import datetime

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.core.models import Organization
from apps.genetics import crypto, services
from apps.genetics.models import GenePanel
from apps.subjects.models import Subject

NOTE = "Fiktivní výsledek pro zkušební provoz – nejde o skutečná data."
CONSENT_NOTE = "ukázka – fiktivní souhlas pro zkušební provoz"


def fictitious_genotypes(panel, index: int) -> dict:
    """
    Genotyp pro každou variantu panelu. Pořadí genotypů v kartě se posouvá
    podle pořadí sportovce, takže se tři sportovci liší; každá druhá varianta
    dostane zápis v notaci laboratoře (např. RX místo CT), aby bylo vidět
    převod na kanonický zápis.
    """
    out = {}
    for j, item in enumerate(panel.active_items()):
        variant = item.variant
        options = [str(g) for g in (variant.genotypes or [])]
        if not options:
            continue
        value = options[(index + j) % len(options)]
        if j % 2 and variant.genotype_aliases:
            value = str((variant.genotype_aliases or {}).get(value, value))
        out[item.variant_id] = value
    return out


def panel_for(org):
    return (GenePanel.objects.filter(is_active=True)
            .filter(Q(organization__isnull=True) | Q(organization=org))
            .order_by("organization_id", "pk").first())


class Command(BaseCommand):
    help = ("Ukázkové genetické vzorky s fiktivními genotypy prvním třem dospělým sportovcům; "
            "jen při DEMO_MODE, jinde jen pro --kody.")

    def add_arguments(self, parser):
        parser.add_argument("--pocet", type=int, default=3, help="Kolik sportovců má mít vzorek.")
        parser.add_argument("--kody", nargs="+", default=None,
                            help="Kódy sportovců; mimo DEMO_MODE povinné.")

    def handle(self, *args, pocet=3, kody=None, **options):
        if not settings.DEMO_MODE and not kody:
            self.stdout.write("Jen v ukázce (DEMO_MODE=True) – nic se nezměnilo. Mimo ukázku "
                              "zadejte sportovce: --kody FTVS-0001 FTVS-0003")
            return
        if not crypto.configured():
            self.stdout.write(crypto.CHYBI)
            return
        org = Organization.objects.order_by("pk").first()
        panel = panel_for(org) if org else None
        if panel is None or not panel.active_items().exists():
            self.stdout.write("Není aktivní panel variant (Genetika → krok 3 Panel a laboratoř) – "
                              "vzorky se nezaložily.")
            return
        subjects = Subject.objects.filter(organization=org).order_by("code")
        if kody:
            subjects = subjects.filter(code__in=kody)
            pocet = len(kody)
        done = created = 0
        today = timezone.localdate()
        for subject in subjects:
            if done >= pocet:
                break
            if subject.genetic_samples.exists():
                done += 1
                self.stdout.write(f"{subject.code}: vzorek už má, nechávám být.")
                continue
            state = services.consent_state(subject)
            if state.blocked_reason:
                self.stdout.write(f"{subject.code}: přeskočeno – {state.blocked_reason}")
                continue
            services.grant_consent(subject, note=CONSENT_NOTE)
            sample = services.record_sample(
                subject, panel, by=None,
                data={"provider": panel.provider or "Ukázková laboratoř",
                      "sampled_on": today - datetime.timedelta(days=21),
                      "reported_on": today - datetime.timedelta(days=7),
                      "external_reference": f"UKAZKA-{subject.code}", "note": NOTE},
                genotypes=fictitious_genotypes(panel, done))
            done += 1
            created += 1
            self.stdout.write(f"{subject.code}: založen vzorek „{panel.name}“ "
                              f"s {sample.genotypes.count()} genotypy (neověřený).")
        self.stdout.write(f"Ukázková genetika: nových vzorků {created}, sportovců se vzorkem {done}.")
