"""
Vygeneruje FIKTIVNÍ data pro vývoj.

Vyvíjí se na syntetických datech, ne na reálných. Notebook se ztrácí,
krade a zálohuje se do cizích cloudů – zdravotní data tam nepatří.
Reálná data se poprvé objeví až na fakultním serveru.

    python manage.py seed_demo --subjects 40 --sessions 3
"""

import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Direction, MetricDef, Protocol, ProtocolMetric, TestFamily
from apps.core.models import Organization, Role, User
from apps.measurements.models import Measurement, Mode, ProtocolRun, Side, TestSession, Trial
from apps.subjects.models import Consent, Sex, Sport, Subject, Team

# Katalog pro demo. V provozu se zakládá v administraci, ne v kódu –
# tohle je jen rozumný výchozí obsah, na kterém se dá hned pracovat.
METRIKY = [
    # kód, název, rodina, jednotka, směr, MDC, SWC, min, max
    ("cmj_height", "Výška výskoku (CMJ)", TestFamily.FORCE_PLATE, "cm", Direction.HIGHER, 1.8, 1.0, 5, 80),
    ("cmj_peak_force", "Vrcholová síla (CMJ)", TestFamily.FORCE_PLATE, "N", Direction.HIGHER, 95, 55, 200, 5000),
    ("cmj_rsi_mod", "RSI modified", TestFamily.FORCE_PLATE, "-", Direction.HIGHER, 0.05, 0.03, 0.05, 1.2),
    ("imtp_peak_force", "Vrcholová síla (IMTP)", TestFamily.FORCE_PLATE, "N", Direction.HIGHER, 120, 70, 300, 6000),
    ("shoulder_rot_torque", "Točivý moment rotátorů ramene", TestFamily.DYNAMOMETRY, "Nm", Direction.HIGHER, 3.1, 1.8, 5, 150),
    ("ir_er_ratio", "Poměr IR/ER", TestFamily.DYNAMOMETRY, "-", Direction.OPTIMAL, 0.08, 0.05, 0.3, 2.5),
    ("grip_strength", "Síla stisku ruky", TestFamily.DYNAMOMETRY, "kg", Direction.HIGHER, 2.4, 1.4, 5, 100),
    ("vo2max", "VO2max", TestFamily.SPIROERGOMETRY, "ml/kg/min", Direction.HIGHER, 2.2, 1.3, 15, 90),
    ("vt2_power", "Výkon na VT2", TestFamily.SPIROERGOMETRY, "W", Direction.HIGHER, 12, 7, 50, 600),
    ("lean_mass", "Beztuková hmota", TestFamily.BODY_COMPOSITION, "kg", Direction.HIGHER, 0.6, 0.4, 20, 100),
    ("body_fat_pct", "Podíl tělesného tuku", TestFamily.BODY_COMPOSITION, "%", Direction.LOWER, 1.1, 0.7, 3, 45),
]

PROTOKOLY = [
    ("cmj", "Countermovement jump", TestFamily.FORCE_PLATE, "force plate",
     ["cmj_height", "cmj_peak_force", "cmj_rsi_mod"], 3),
    ("imtp", "Izometrický tah z podřepu (IMTP)", TestFamily.FORCE_PLATE, "force plate",
     ["imtp_peak_force"], 3),
    ("iso_shoulder", "Izokinetika ramene", TestFamily.DYNAMOMETRY, "izokinetický dynamometr",
     ["shoulder_rot_torque", "ir_er_ratio"], 3),
    ("grip", "Síla stisku ruky", TestFamily.DYNAMOMETRY, "ruční dynamometr",
     ["grip_strength"], 2),
    ("spiro_ramp", "Spiroergometrie – rampový protokol", TestFamily.SPIROERGOMETRY, "spiroergometr",
     ["vo2max", "vt2_power"], 1),
    ("bodycomp", "Složení těla", TestFamily.BODY_COMPOSITION, "DXA",
     ["lean_mass", "body_fat_pct"], 1),
]

ROZSAHY = {
    "cmj_height": (28, 48), "cmj_peak_force": (1400, 2600), "cmj_rsi_mod": (0.35, 0.75),
    "imtp_peak_force": (1800, 3400), "shoulder_rot_torque": (28, 62),
    "ir_er_ratio": (0.85, 1.45), "grip_strength": (32, 62), "vo2max": (45, 68),
    "vt2_power": (210, 380), "lean_mass": (48, 72), "body_fat_pct": (8, 22),
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

        org, _ = Organization.objects.get_or_create(
            short_name="ftvs", defaults={"name": "FTVS UK – laboratoř funkční diagnostiky"},
        )

        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser(
                "admin", "admin@example.cz", "demo-heslo-1234",
                organization=org, role=Role.ADMIN,
            )
            self.stdout.write("Vytvořen účet admin / demo-heslo-1234 (jen pro vývoj).")

        metriky = {}
        for code, name, family, unit, direction, mdc, swc, lo, hi in METRIKY:
            metriky[code], _ = MetricDef.objects.update_or_create(
                organization=None, code=code,
                defaults={"name": name, "family": family, "unit": unit,
                          "direction": direction, "mdc": mdc, "swc": swc,
                          "typical_error": round(mdc / 1.96, 3),
                          "plausible_min": lo, "plausible_max": hi},
            )

        protokoly = {}
        for code, name, family, device, metric_codes, n_trials in PROTOKOLY:
            protocol, _ = Protocol.objects.update_or_create(
                organization=None, code=code, version=1,
                defaults={"name": name, "family": family, "device": device},
            )
            for order, mcode in enumerate(metric_codes):
                ProtocolMetric.objects.update_or_create(
                    protocol=protocol, metric=metriky[mcode],
                    defaults={"order": order, "is_primary": order == 0},
                )
            protokoly[code] = (protocol, metric_codes, n_trials)

        sporty = {}
        for name, code in [("Tenis", "tenis"), ("Veslování", "veslovani"), ("Atletika", "atletika")]:
            sporty[code], _ = Sport.objects.get_or_create(
                organization=org, code=code, defaults={"name": name},
            )
        tymy = {
            code: Team.objects.get_or_create(
                organization=org, name=f"{sport.name} – reprezentace", sport=sport,
            )[0]
            for code, sport in sporty.items()
        }

        dnes = timezone.localdate()
        vytvoreno = 0

        for i in range(1, options["subjects"] + 1):
            sport_code = random.choice(list(sporty))
            subject, _ = Subject.objects.update_or_create(
                organization=org, code=f"FTVS-{i:04d}",
                defaults={
                    "sport": sporty[sport_code],
                    "team": tymy[sport_code],
                    "sex": random.choice([Sex.FEMALE, Sex.MALE]),
                    "birth_year": random.randint(dnes.year - 32, dnes.year - 17),
                    "level": random.choice([Subject.Level.TRAINED, Subject.Level.NATIONAL]),
                    "dominant_side": random.choice(["L", "R"]),
                },
            )
            Consent.objects.get_or_create(
                subject=subject, scope=Consent.Scope.TESTING,
                defaults={"granted_on": dnes - timedelta(days=400)},
            )
            Consent.objects.get_or_create(
                subject=subject, scope=Consent.Scope.LONGITUDINAL,
                defaults={"granted_on": dnes - timedelta(days=400)},
            )

            # osobní úroveň sportovce – aby data nebyla jen šum
            uroven = {code: random.uniform(-1, 1) for code in ROZSAHY}

            for s_index in range(options["sessions"]):
                datum = dnes - timedelta(days=(options["sessions"] - s_index - 1) * 120
                                              + random.randint(0, 20))
                session, _ = TestSession.objects.get_or_create(
                    organization=org, subject=subject, date=datum,
                    defaults={"location": "Laboratoř FTVS",
                              "season_phase": random.choice(
                                  [TestSession.SeasonPhase.PREPARATION,
                                   TestSession.SeasonPhase.COMPETITION]),
                              "fatigue_rating": random.randint(2, 7)},
                )

                for code in random.sample(list(protokoly), k=random.randint(3, len(protokoly))):
                    protocol, metric_codes, n_trials = protokoly[code]
                    run, _ = ProtocolRun.objects.get_or_create(session=session, protocol=protocol)

                    for t in range(1, n_trials + 1):
                        trial, _ = Trial.objects.get_or_create(protocol_run=run, number=t)
                        for mcode in metric_codes:
                            lo, hi = ROZSAHY[mcode]
                            stred = lo + (hi - lo) * (0.5 + uroven[mcode] * 0.2)
                            trend = s_index * (hi - lo) * 0.015
                            oboustranne = protocol.family in (
                                TestFamily.SPIROERGOMETRY, TestFamily.BODY_COMPOSITION)
                            strany = [Side.BILATERAL] if oboustranne else [Side.LEFT, Side.RIGHT]

                            for side in strany:
                                # mírná asymetrie, ať má co analytika najít
                                bias = 0 if side == Side.BILATERAL else (
                                    random.uniform(0.94, 1.0) if side == Side.LEFT else 1.0)
                                hodnota = (stred + trend) * (bias or 1) * random.uniform(0.97, 1.03)
                                mode = (Mode.CONCENTRIC if code == "iso_shoulder" else Mode.NA)
                                speed = 210.0 if code == "iso_shoulder" else None
                                _, created = Measurement.objects.get_or_create(
                                    trial=trial, metric=metriky[mcode], side=side,
                                    mode=mode, speed=speed, segment="",
                                    defaults={"value": round(hodnota, 3)},
                                )
                                vytvoreno += int(created)

        self.stdout.write(self.style.SUCCESS(
            f"Hotovo: {options['subjects']} fiktivních sportovců, "
            f"{vytvoreno} hodnot, {len(metriky)} metrik, {len(protokoly)} protokolů."
        ))
