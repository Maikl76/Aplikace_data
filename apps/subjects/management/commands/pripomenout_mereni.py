"""
Připomínky dalšího měření z příkazové řádky: pro plánovanou úlohu
(PythonAnywhere, Plánovač úloh ve Windows) nebo při startu spustit.bat.
Totéž dělá Přehled jednou denně sám; příkaz se hodí tam, kde Přehled
nikdo neotvírá. Připomínka témuž sportovci odejde nejdřív po 30 dnech,
takže opakované spuštění nic nerozešle dvakrát.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.core.models import Organization
from apps.subjects import retest
from apps.subjects.models import Subject


class Command(BaseCommand):
    help = "Rozešle e-mailem připomínky dalšího měření sportovcům, kterým se blíží termín."

    def add_arguments(self, parser):
        parser.add_argument("--dny", type=int, default=retest.REMIND_DAYS_BEFORE,
                            help="kolik dní před termínem připomínat (výchozí 14)")
        parser.add_argument("--jen-vypsat", action="store_true", dest="dry",
                            help="jen vypsat, komu by připomínka šla; nic neposílat")
        parser.add_argument("--odkaz", default="",
                            help="veřejná adresa aplikace do odkazu na objednání "
                                 "(výchozí PUBLIC_BASE_URL z .env)")

    def handle(self, *args, **options):
        if not settings.EMAIL_HOST and not options["dry"]:
            self.stdout.write("Poštovní server není nastavený (EMAIL_HOST) – připomínky se "
                              "neposílají; Kdo je na řadě je na Přehledu.")
            return
        link = retest.booking_link(options["odkaz"])
        for org in Organization.objects.filter(is_active=True):
            if options["dry"]:
                plans = [p for p in retest.plans_for(
                    Subject.objects.filter(organization=org, is_active=True))
                    if p.is_due and p.days_left <= options["dny"]]
                self.stdout.write(f"{org.short_name}: {len(plans)} sportovců na řadě")
                for plan in plans:
                    addresses = retest.recipients(plan.subject)
                    self.stdout.write(f"  {plan.subject.code}: {plan.badge()[1]}, "
                                      f"{len(addresses)} adres")
                continue
            result = retest.run_due(org, booking_url=link, days_before=options["dny"])
            self.stdout.write(f"{org.short_name}: na řadě {len(result['due'])}, "
                              f"odesláno {len(result['sent'])}, přeskočeno "
                              f"{len(result['skipped'])} (bez adresy nebo připomenuto nedávno)")
