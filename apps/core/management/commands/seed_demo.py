"""
Vygeneruje FIKTIVNÍ data pro vývoj.

Vyvíjí se na syntetických datech, ne na reálných. Notebook se ztrácí,
krade a zálohuje se do cizích cloudů – zdravotní data tam nepatří.
Reálná data se poprvé objeví až na fakultním serveru.

    python manage.py seed_demo --subjects 40 --sessions 3
"""

import random
from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import MetricDef, Protocol
from apps.catalog.seed_data import PROTOCOLS
from apps.core.models import Organization, Role, User
from apps.measurements.models import Measurement, Mode, ProtocolRun, Side, TestSession, Trial
from apps.subjects.models import Consent, Sex, Sport, Subject, Team

# MDC a SWC jsou tu VYMYŠLENÉ, jen aby měla analytika na demo datech co
# ukazovat. seed_catalog je schválně nechává prázdné – do provozu patří
# hodnoty z literatury nebo z vlastní reliability studie.
DEMO_MDC = {
    "cmj_height": (1.8, 1.0), "cmj_peak_force": (95, 55), "cmj_rsi_mod": (0.05, 0.03),
    "imtp_peak_force": (120, 70), "shoulder_ir_torque": (3.1, 1.8),
    "shoulder_er_torque": (3.1, 1.8), "ir_er_ratio": (0.08, 0.05),
    "grip_strength": (2.4, 1.4), "vo2max": (2.2, 1.3), "vt2_power": (12, 7),
    "lean_mass": (0.6, 0.4), "body_fat_pct": (1.1, 0.7), "body_mass": (0.5, 0.3),
    "segment_mass": (0.3, 0.2), "segment_lean_mass": (0.3, 0.2), "serve_speed": (4, 2),
}

# Rozumná rozmezí pro generování hodnot.
RANGES = {
    "cmj_height": (28, 48), "cmj_peak_force": (1400, 2600), "cmj_rsi_mod": (0.35, 0.75),
    "imtp_peak_force": (1800, 3400), "shoulder_ir_torque": (30, 65),
    "shoulder_er_torque": (20, 45), "ir_er_ratio": (0.85, 1.45),
    "grip_strength": (32, 62), "vo2max": (45, 68), "vt2_power": (210, 380),
    "body_mass": (58, 92), "height": (162, 196), "lean_mass": (48, 72),
    "body_fat_pct": (8, 22), "segment_mass": (3, 12), "segment_lean_mass": (2.5, 10),
    "serve_speed": (150, 210),
}



class Command(BaseCommand):
    help = "Vygeneruje fiktivní sportovce a měření pro vývoj."

    def add_arguments(self, parser):
        parser.add_argument("--subjects", type=int, default=30)
        parser.add_argument("--sessions", type=int, default=3)
        parser.add_argument("--seed", type=int, default=42)

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(options["seed"])

        call_command("seed_catalog", verbosity=0)

        org, _ = Organization.objects.get_or_create(
            short_name="ftvs", defaults={"name": "FTVS UK – laboratoř funkční diagnostiky"},
        )

        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser(
                "admin", "admin@example.cz", "demo-heslo-1234",
                organization=org, role=Role.ADMIN,
            )
            self.stdout.write("Vytvořen účet admin / demo-heslo-1234 (jen pro vývoj).")

        metrics = {m.code: m for m in MetricDef.objects.filter(organization=None)}
        for code, (mdc, swc) in DEMO_MDC.items():
            if metric := metrics.get(code):
                metric.mdc, metric.swc = mdc, swc
                metric.typical_error = round(mdc / 1.96, 3)
                metric.save(update_fields=["mdc", "swc", "typical_error"])

        protocols = {p.code: p for p in Protocol.objects.filter(organization=None)}

        sports = {}
        for name, code in [("Tenis", "tenis"), ("Veslování", "veslovani"), ("Atletika", "atletika")]:
            sports[code], _ = Sport.objects.get_or_create(
                organization=org, code=code, defaults={"name": name},
            )
        teams = {
            code: Team.objects.get_or_create(
                organization=org, name=f"{sport.name} – reprezentace", sport=sport,
            )[0]
            for code, sport in sports.items()
        }

        today = timezone.localdate()
        created = 0

        for i in range(1, options["subjects"] + 1):
            sport_code = random.choice(list(sports))
            subject, _ = Subject.objects.update_or_create(
                organization=org, code=f"FTVS-{i:04d}",
                defaults={
                    "sport": sports[sport_code],
                    "team": teams[sport_code],
                    "sex": random.choice([Sex.FEMALE, Sex.MALE]),
                    "birth_year": random.randint(today.year - 32, today.year - 17),
                    "level": random.choice([Subject.Level.TRAINED, Subject.Level.NATIONAL]),
                    "dominant_side": random.choice(["L", "R"]),
                },
            )
            for scope in (Consent.Scope.TESTING, Consent.Scope.LONGITUDINAL):
                Consent.objects.get_or_create(
                    subject=subject, scope=scope,
                    defaults={"granted_on": today - timedelta(days=400)},
                )

            ability = {code: random.uniform(-1, 1) for code in RANGES}

            for index in range(options["sessions"]):
                day = today - timedelta(
                    days=(options["sessions"] - index - 1) * 120 + random.randint(0, 20))
                session, _ = TestSession.objects.get_or_create(
                    organization=org, subject=subject, date=day,
                    defaults={"location": "Laboratoř FTVS",
                              "season_phase": random.choice(
                                  [TestSession.SeasonPhase.PREPARATION,
                                   TestSession.SeasonPhase.COMPETITION]),
                              "fatigue_rating": random.randint(2, 7)},
                )

                chosen = random.sample(list(PROTOCOLS), k=random.randint(3, len(PROTOCOLS)))
                for code in chosen:
                    protocol = protocols[code]
                    run, _ = ProtocolRun.objects.get_or_create(session=session, protocol=protocol)

                    for t in range(1, protocol.default_trials + 1):
                        trial, _ = Trial.objects.get_or_create(protocol_run=run, number=t)
                        # Kombinace bere z definice protokolu – stejně jako
                        # zadávací formulář, takže demo data mají tvar,
                        # jaký vznikne i ručním zadáním.
                        for pm in protocol.protocol_metrics.select_related("metric"):
                            created += self._make_values(trial, pm, ability, index)

        self.stdout.write(self.style.SUCCESS(
            f"Hotovo: {options['subjects']} fiktivních sportovců, {created} hodnot."
        ))

    def _make_values(self, trial, protocol_metric, ability, session_index) -> int:
        metric = protocol_metric.metric
        low, high = RANGES[metric.code]
        centre = low + (high - low) * (0.5 + ability[metric.code] * 0.2)
        trend = session_index * (high - low) * 0.015

        made = 0
        for combo in protocol_metric.qualifier_combinations():
            # mírná asymetrie, ať má analytika co najít
            bias = random.uniform(0.9, 1.0) if combo["side"] == Side.LEFT else 1.0
            value = (centre + trend) * bias * random.uniform(0.97, 1.03)
            _, is_new = Measurement.objects.get_or_create(
                trial=trial, metric=metric,
                side=combo["side"], mode=combo["mode"] or Mode.NA,
                speed=combo["speed"], segment=combo["segment"],
                defaults={"value": round(value, metric.decimals)},
            )
            made += int(is_new)
        return made
