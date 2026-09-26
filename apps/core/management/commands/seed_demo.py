"""
Vygeneruje FIKTIVNÍ data pro vývoj.

Vyvíjí se na syntetických datech, ne na reálných. Notebook se ztrácí,
krade a zálohuje se do cizích cloudů – zdravotní data tam nepatří.
Reálná data se poprvé objeví až na fakultním serveru.

    python manage.py seed_demo --subjects 40 --sessions 3
"""

import os
import random
from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import MetricDef, Protocol
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
    "cmj_peak_power_bm": (40, 65), "cmj_depth": (25, 40), "cmj_contraction_time": (650, 900),
    "cmj_ecc_braking_rfd": (3000, 9000), "cmj_landing_force": (3500, 7000),
    "imtp_peak_force_bm": (25, 42), "imtp_force_100": (900, 1800), "imtp_force_200": (1300, 2400),
    "imtp_rfd_100": (4000, 9000), "imtp_rfd_200": (3000, 6500), "imtp_time_to_peak": (1.2, 3.5),
    "sls_cop_area": (600, 2500), "sls_total_excursion": (900, 2200),
    "sls_mean_velocity": (30, 75),
    "boxlift_hip_flex_lift": (90, 125), "boxlift_hip_flex_lower": (85, 120),
    "boxlift_knee_flex_lift": (70, 130), "boxlift_knee_flex_lower": (65, 125),
    "boxlift_shoulder_flex": (60, 125), "boxlift_trunk_ext": (0, 18),
    "boxlift_spine_flex_lift": (15, 45), "boxlift_spine_flex_lower": (15, 45),
    "boxlift_trunk_flex_lift": (40, 80), "boxlift_trunk_flex_lower": (40, 85),
    "sj_height": (26, 44), "sj_peak_power_bm": (40, 60),
    "wingate_pmax": (850, 1350), "wingate_pmin": (330, 520), "wingate_p5s_max": (830, 1320),
    "wingate_p5s_min": (320, 500), "wingate_work": (20, 32), "wingate_fatigue_index": (45, 72),
    "wingate_revolutions": (55, 80), "lactate_max": (9, 16), "hr_max": (170, 200),
}

# Baterie testů pro demo sporty (kód sportu, kategorie, protokoly v pořadí).
DEMO_BATTERIES = [
    ("tenis", "", ["bodycomp", "cmj", "grip", "iso_shoulder", "serve"]),
    ("veslovani", "", ["bodycomp", "spiro_ramp", "imtp", "cmj"]),
    ("atletika", "", ["bodycomp", "cmj", "sj", "imtp", "sls"]),
    ("hokej", "dorost", ["bodycomp", "wingate", "sj", "cmj", "imtp"]),
]



class Command(BaseCommand):
    help = "Vygeneruje fiktivní sportovce a měření pro vývoj."

    def add_arguments(self, parser):
        parser.add_argument("--subjects", type=int, default=30)
        parser.add_argument("--sessions", type=int, default=3)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--admin-password", default=None,
                            help="Heslo správce. Mimo vývoj povinné; lze zadat "
                                 "i proměnnou DEMO_ADMIN_PASSWORD.")

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(options["seed"])

        call_command("seed_catalog", verbosity=0)

        org, _ = Organization.objects.get_or_create(
            short_name="ftvs", defaults={"name": "FTVS UK – laboratoř funkční diagnostiky"},
        )

        self._ensure_admin(org, options.get("admin_password"))

        metrics = {m.code: m for m in MetricDef.objects.filter(organization=None)}
        for code, (mdc, swc) in DEMO_MDC.items():
            if metric := metrics.get(code):
                metric.mdc, metric.swc = mdc, swc
                metric.typical_error = round(mdc / 1.96, 3)
                metric.save(update_fields=["mdc", "swc", "typical_error"])

        protocols = {p.code: p for p in Protocol.objects.filter(organization=None)}

        sports = {}
        for name, code in [("Tenis", "tenis"), ("Veslování", "veslovani"),
                           ("Atletika", "atletika"), ("Lední hokej", "hokej")]:
            sports[code], _ = Sport.objects.get_or_create(
                organization=org, code=code, defaults={"name": name},
            )
        teams = {
            code: Team.objects.get_or_create(
                organization=org, name=f"{sport.name} – reprezentace", sport=sport,
            )[0]
            for code, sport in sports.items()
        }

        from apps.catalog.models import BatteryItem, TestBattery

        for sport_code, category, codes in DEMO_BATTERIES:
            battery, _ = TestBattery.objects.get_or_create(
                organization=org, sport=sports[sport_code], category=category)
            for order, code in enumerate(codes, start=1):
                BatteryItem.objects.get_or_create(battery=battery, protocol=protocols[code],
                                                  defaults={"order": order})

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
                    "birth_year": (random.randint(today.year - 18, today.year - 16)
                                   if sport_code == "hokej"
                                   else random.randint(today.year - 32, today.year - 17)),
                    "category": "dorost" if sport_code == "hokej" else "",
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

                # Měří se podle baterie sportu; občas jeden test vypadne,
                # ať data vypadají jako ze skutečného provozu.
                battery = next(codes for code, _, codes in DEMO_BATTERIES if code == sport_code)
                chosen = [c for c in battery if len(battery) < 4 or random.random() > 0.12]
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

        from apps.analytics.derived import recompute

        for session in TestSession.objects.filter(organization=org):
            recompute(session)

        self.stdout.write(self.style.SUCCESS(
            f"Hotovo: {options['subjects']} fiktivních sportovců, {created} hodnot."
        ))

    def _ensure_admin(self, org, password):
        """
        Účet správce pro demo.

        Výchozí známé heslo se založí jen ve vývoji. Na veřejné adrese by
        to byly otevřené dveře, takže tam se heslo musí zadat — jinak se
        účet nezaloží a příkaz to řekne.
        """
        from django.conf import settings

        if User.objects.filter(username="admin").exists():
            return

        password = password or os.environ.get("DEMO_ADMIN_PASSWORD")
        if not password:
            # Známé heslo jen při vývoji na vlastním stroji. Zapnutý
            # DEMO_MODE znamená veřejně dostupnou instanci, a tam by to
            # byly otevřené dveře bez ohledu na to, jaké nastavení běží.
            if not settings.DEBUG or settings.DEMO_MODE:
                self.stdout.write(self.style.ERROR(
                    "Účet správce se nezaložil: mimo vývoj je potřeba heslo. "
                    "Spusťte s --admin-password, nebo nastavte DEMO_ADMIN_PASSWORD."
                ))
                return
            password = "demo-heslo-1234"
            self.stdout.write("Vytvořen účet admin / demo-heslo-1234 (jen pro vývoj).")
        else:
            self.stdout.write("Vytvořen účet admin se zadaným heslem.")

        User.objects.create_superuser(
            "admin", "admin@example.cz", password, organization=org, role=Role.ADMIN,
        )

    def _make_values(self, trial, protocol_metric, ability, session_index) -> int:
        from apps.analytics.derived import DERIVED_METRICS

        metric = protocol_metric.metric
        if metric.code in DERIVED_METRICS:  # W/kg apod. se dopočítá
            return 0
        low, high = RANGES[metric.code]
        centre = low + (high - low) * (0.5 + ability[metric.code] * 0.2)
        trend = session_index * (high - low) * 0.015

        made = 0
        for combo in protocol_metric.qualifier_combinations():
            # mírná asymetrie, ať má analytika co najít
            bias = random.uniform(0.9, 1.0) if combo["side"] == Side.LEFT else 1.0
            # Když se měří celek i strany (síla na plošině), připadá na
            # každou nohu zhruba polovina.
            if combo["side"] in (Side.LEFT, Side.RIGHT) and "B" in protocol_metric.sides:
                bias /= 2
            value = (centre + trend) * bias * random.uniform(0.97, 1.03)
            _, is_new = Measurement.objects.get_or_create(
                trial=trial, metric=metric,
                side=combo["side"], mode=combo["mode"] or Mode.NA,
                speed=combo["speed"], segment=combo["segment"],
                defaults={"value": round(value, metric.decimals)},
            )
            made += int(is_new)
        return made
