"""
Výchozí obsah katalogu.

Tohle NENÍ konfigurace aplikace – je to startovní sada, kterou si pak
spravujete v administraci. Kód sem sahá jen při zakládání databáze
(``manage.py seed_catalog``).

MDC a SWC se tu záměrně nevyplňují. Jsou to hodnoty z literatury nebo
z vlastní reliability studie, ne čísla k vymyšlení – a dokud chybí,
analytická vrstva poctivě řekne, že změnu nelze odlišit od šumu měření.
"""

from apps.catalog.models import Direction, TestFamily

# (kód, název, rodina, jednotka, směr, min, max, desetinná místa)
METRICS = [
    # --- force plate ---------------------------------------------------
    ("cmj_height", "Výška výskoku (CMJ)", TestFamily.FORCE_PLATE, "cm", Direction.HIGHER, 5, 80, 1),
    ("cmj_peak_force", "Vrcholová síla (CMJ)", TestFamily.FORCE_PLATE, "N", Direction.HIGHER, 200, 5000, 0),
    ("cmj_rsi_mod", "RSI modified", TestFamily.FORCE_PLATE, "-", Direction.HIGHER, 0.05, 1.2, 2),
    ("imtp_peak_force", "Vrcholová síla (IMTP)", TestFamily.FORCE_PLATE, "N", Direction.HIGHER, 300, 6000, 0),

    # --- dynamometrie ---------------------------------------------------
    ("shoulder_ir_torque", "Vnitřní rotace ramene – točivý moment", TestFamily.DYNAMOMETRY, "Nm", Direction.HIGHER, 3, 200, 1),
    ("shoulder_er_torque", "Vnější rotace ramene – točivý moment", TestFamily.DYNAMOMETRY, "Nm", Direction.HIGHER, 3, 200, 1),
    ("ir_er_ratio", "Poměr IR/ER", TestFamily.DYNAMOMETRY, "-", Direction.OPTIMAL, 0.3, 2.5, 2),
    ("grip_strength", "Síla stisku ruky", TestFamily.DYNAMOMETRY, "kg", Direction.HIGHER, 5, 100, 1),

    # --- spiroergometrie -------------------------------------------------
    ("vo2max", "VO2max", TestFamily.SPIROERGOMETRY, "ml/kg/min", Direction.HIGHER, 15, 90, 1),
    ("vt2_power", "Výkon na VT2", TestFamily.SPIROERGOMETRY, "W", Direction.HIGHER, 50, 600, 0),

    # --- složení těla a antropometrie ------------------------------------
    ("body_mass", "Tělesná hmotnost", TestFamily.BODY_COMPOSITION, "kg", Direction.NEUTRAL, 30, 180, 1),
    ("height", "Tělesná výška", TestFamily.BODY_COMPOSITION, "cm", Direction.NEUTRAL, 120, 230, 0),
    ("lean_mass", "Celková beztuková hmota", TestFamily.BODY_COMPOSITION, "kg", Direction.HIGHER, 20, 100, 1),
    ("body_fat_pct", "Podíl tělesného tuku", TestFamily.BODY_COMPOSITION, "%", Direction.LOWER, 3, 45, 1),
    ("segment_mass", "Hmotnost segmentu", TestFamily.BODY_COMPOSITION, "kg", Direction.NEUTRAL, 0.5, 60, 2),
    ("segment_lean_mass", "Beztuková hmota segmentu", TestFamily.BODY_COMPOSITION, "kg", Direction.HIGHER, 0.3, 55, 2),

    # --- terénní ----------------------------------------------------------
    ("serve_speed", "Rychlost podání", TestFamily.FIELD, "km/h", Direction.HIGHER, 50, 260, 0),
]

# Definice protokolů včetně toho, jaké kombinace kvalifikátorů se u nich
# měří. Zadávací formulář se z toho generuje sám – nový protokol se založí
# v administraci a obrazovka pro něj vznikne bez psaní kódu.
PROTOCOLS = {
    "cmj": {
        "name": "Countermovement jump", "family": TestFamily.FORCE_PLATE,
        "device": "force plate", "trials": 3,
        "metrics": [
            {"code": "cmj_height", "sides": ["B"], "primary": True},
            {"code": "cmj_peak_force", "sides": ["L", "R"]},
            {"code": "cmj_rsi_mod", "sides": ["B"]},
        ],
    },
    "imtp": {
        "name": "Izometrický tah (IMTP)", "family": TestFamily.FORCE_PLATE,
        "device": "force plate", "trials": 3,
        "metrics": [
            {"code": "imtp_peak_force", "sides": ["L", "R"], "primary": True},
        ],
    },
    "iso_shoulder": {
        "name": "Izokinetika ramene", "family": TestFamily.DYNAMOMETRY,
        "device": "izokinetický dynamometr", "trials": 3,
        "metrics": [
            {"code": "shoulder_ir_torque", "sides": ["L", "R"],
             "modes": ["con", "ecc"], "speeds": [210, 300], "primary": True},
            {"code": "shoulder_er_torque", "sides": ["L", "R"],
             "modes": ["con", "ecc"], "speeds": [210, 300]},
            {"code": "ir_er_ratio", "sides": ["L", "R"], "speeds": [210, 300]},
        ],
    },
    "grip": {
        "name": "Síla stisku ruky", "family": TestFamily.DYNAMOMETRY,
        "device": "ruční dynamometr", "trials": 2,
        "metrics": [
            {"code": "grip_strength", "sides": ["L", "R"], "primary": True},
        ],
    },
    "spiro_ramp": {
        "name": "Spiroergometrie – rampový protokol", "family": TestFamily.SPIROERGOMETRY,
        "device": "spiroergometr", "trials": 1,
        "metrics": [
            {"code": "vo2max", "sides": ["B"], "primary": True},
            {"code": "vt2_power", "sides": ["B"]},
        ],
    },
    "bodycomp": {
        "name": "Složení těla", "family": TestFamily.BODY_COMPOSITION,
        "device": "DXA / BIA", "trials": 1,
        "metrics": [
            {"code": "body_mass", "sides": ["B"], "primary": True},
            {"code": "height", "sides": ["B"]},
            {"code": "lean_mass", "sides": ["B"]},
            {"code": "body_fat_pct", "sides": ["B"]},
            {"code": "segment_mass", "sides": ["L", "R"],
             "segments": ["paze", "noha", "trup"]},
            {"code": "segment_lean_mass", "sides": ["L", "R"],
             "segments": ["paze", "noha", "trup"]},
        ],
    },
    "serve": {
        "name": "Rychlost podání", "family": TestFamily.FIELD,
        "device": "radar", "trials": 3,
        "metrics": [
            {"code": "serve_speed", "sides": ["B"], "primary": True},
        ],
    },
}

# ---------------------------------------------------------------------------
# Mapování sloupců původního Excelu na kanonické metriky.
#
# Tohle je celá teze nového modelu na jednom místě. Osm sloupců
#
#     Vnitrni rotace koncentricka (210°/s)
#     Vnejsi rotace koncentricka (210°/s)
#     Vnitrni rotace excentricka (210°/s)
#     ... a totéž pro 300°/s
#
# jsou ve skutečnosti DVĚ metriky × dva režimy × dvě rychlosti. Jakmile
# jsou režim a rychlost pole a ne text v názvu, stačí dvě definice metrik
# místo osmi – a analytika (asymetrie, trend, srovnání s normou) funguje
# na všechny kombinace bez jediného ifu navíc.
#
# POZNÁMKA KE STRANĚ: původní formát stranu vůbec nerozlišoval. Proto se
# importuje side="" (neurčeno) a z historických dat NELZE spočítat
# asymetrii. Nová měření už stranu nesou.
# ---------------------------------------------------------------------------

LEGACY_COLUMN_MAP = {
    # sloupec: (protokol, metrika, strana, režim, rychlost, segment)
    "Vnitrni rotace koncentricka (210°/s)": ("iso_shoulder", "shoulder_ir_torque", "", "con", 210.0, ""),
    "Vnejsi rotace koncentricka (210°/s)":  ("iso_shoulder", "shoulder_er_torque", "", "con", 210.0, ""),
    "Vnitrni rotace excentricka (210°/s)":  ("iso_shoulder", "shoulder_ir_torque", "", "ecc", 210.0, ""),
    "Vnejsi rotace excentricka (210°/s)":   ("iso_shoulder", "shoulder_er_torque", "", "ecc", 210.0, ""),
    "Vnitrni rotace koncentricka (300°/s)": ("iso_shoulder", "shoulder_ir_torque", "", "con", 300.0, ""),
    "Vnejsi rotace koncentricka (300°/s)":  ("iso_shoulder", "shoulder_er_torque", "", "con", 300.0, ""),
    "Vnitrni rotace excentricka (300°/s)":  ("iso_shoulder", "shoulder_ir_torque", "", "ecc", 300.0, ""),
    "Vnejsi rotace excentricka (300°/s)":   ("iso_shoulder", "shoulder_er_torque", "", "ecc", 300.0, ""),

    "IR/ER (210°/s)": ("iso_shoulder", "ir_er_ratio", "", "", 210.0, ""),
    "IR/ER (300°/s)": ("iso_shoulder", "ir_er_ratio", "", "", 300.0, ""),

    "Sila uchopu":    ("grip", "grip_strength", "", "", None, ""),
    "Rychlost podani": ("serve", "serve_speed", "", "", None, ""),

    # Segmentální složení těla – segment a strana jsou kvalifikátory,
    # takže "Dominantni paze" a "Dominantni noha" sdílejí jednu metriku.
    "Dominantni paze":             ("bodycomp", "segment_mass", "D", "", None, "paze"),
    "Dominantni paze - beztukova": ("bodycomp", "segment_lean_mass", "D", "", None, "paze"),
    "Dominantni noha":             ("bodycomp", "segment_mass", "D", "", None, "noha"),
    "Dominantni noha - beztukova": ("bodycomp", "segment_lean_mass", "D", "", None, "noha"),
    "Trupova hmotnost":            ("bodycomp", "segment_mass", "", "", None, "trup"),
    # Překlep "betukovy" je v původních datech; mapujeme obě varianty.
    "Trup - betukovy":             ("bodycomp", "segment_lean_mass", "", "", None, "trup"),
    "Trup - beztukovy":            ("bodycomp", "segment_lean_mass", "", "", None, "trup"),

    "Beztukova hmota": ("bodycomp", "lean_mass", "", "", None, ""),
    "Telesny tuk":     ("bodycomp", "body_fat_pct", "", "", None, ""),
    "Hmotnost":        ("bodycomp", "body_mass", "", "", None, ""),
    "Vyska":           ("bodycomp", "height", "", "", None, ""),
}

# Sloupce, které nejsou měřením – popisují osobu nebo návštěvu.
LEGACY_IDENTITY_COLUMNS = ["Jmeno", "Prijmeni", "Narozen"]
LEGACY_META_COLUMNS = ["Identifikace", "Vek", "DatumMereni", "Pohlavi", "Sport"]


# ---------------------------------------------------------------------------
# PŘÍKLADY PRAVIDEL
#
# Pozor: prahy níže jsou ILUSTRATIVNÍ, aby bylo na čem ukázat, jak pravidla
# fungují. NEJSOU to ověřené klinické hodnoty a nemají u sebe citace.
#
# Před použitím na reálných sportovcích je potřeba u každého pravidla:
#   1. ověřit práh v literatuře nebo z vlastních dat,
#   2. připojit citace (rules.RuleArticle),
#   3. rozhodnout, pro který sport a populaci platí.
#
# Dokud se to nestane, nechte je neaktivní (is_active = False) – tak se
# zakládají.
# ---------------------------------------------------------------------------

EXAMPLE_RULES = [
    {
        "code": "ir_er_pomer",
        "name": "PŘÍKLAD: poměr IR/ER pod doporučenou hodnotou",
        "condition": {"metric": "ir_er_ratio", "op": "<", "value": 1.0,
                      "where": {"speed": 210}},
        "contraindication": {"load_restriction": True},
        "severity": "medium",
        "finding_template": (
            "Poměr vnitřní a vnější rotace ramene {value_txt} při {speed_txt} °/s "
            "je pod orientační hodnotou {threshold_txt}."
        ),
        "recommendation_template": (
            "Zvážit posílení zevních rotátorů ramene. Práh i postup je třeba "
            "ověřit proti literatuře pro daný sport."
        ),
    },
    {
        "code": "asymetrie",
        "name": "PŘÍKLAD: stranová asymetrie nad prahem",
        "condition": {"asymmetry": "*", "op": ">", "value": 10},
        "contraindication": {"load_restriction": True},
        "severity": "medium",
        "finding_template": (
            "{metric}: rozdíl mezi stranami {index_txt} % "
            "(levá {left_txt}, pravá {right_txt} {unit}), silnější je {silnejsi} "
            "strana. Překračuje orientační práh {threshold_txt} %."
        ),
        "recommendation_template": (
            "Zvážit jednostranné zatížení slabší strany a kontrolní měření."
        ),
    },
    {
        "code": "pokles_vysky_vyskoku",
        "name": "PŘÍKLAD: pokles výšky výskoku nad chybu měření",
        "condition": {"change": "cmj_height", "op": "<", "value": 0,
                      "require_mdc": True},
        "severity": "high",
        "finding_template": (
            "Výška výskoku klesla o {delta_txt} {unit} proti minulému měření "
            "(z {predchozi} na {value_txt}). Změna přesahuje nejmenší "
            "detekovatelnou změnu {mdc_txt} {unit}, nejde tedy o šum měření."
        ),
        "recommendation_template": (
            "Prověřit tréninkové zatížení a regeneraci, zvážit kontrolní měření."
        ),
    },
    {
        "code": "vo2max_pod_normou",
        "name": "PŘÍKLAD: VO2max pod normou",
        "condition": {"z": "vo2max", "op": "<", "value": -1.0},
        "severity": "low",
        "finding_template": (
            "VO2max {value_txt} {unit} odpovídá z-skóre {z} vůči normě "
            "(průměr {norma} {unit}, zdroj: {citace})."
        ),
        "recommendation_template": (
            "Zvážit zařazení rozvoje aerobní kapacity."
        ),
    },
]
