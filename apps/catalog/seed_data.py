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
    # Výška výskoku z impulzu a hybnosti (VALD „Imp-Mom“) – ne z doby letu.
    # Obě metody dávají rozdíl několika cm, takže se nesmí míchat.
    ("cmj_height", "Výška výskoku (CMJ)", TestFamily.FORCE_PLATE, "cm", Direction.HIGHER, 5, 80, 1),
    ("cmj_peak_force", "Koncentrická vrcholová síla (CMJ)", TestFamily.FORCE_PLATE, "N", Direction.HIGHER, 200, 6000, 0),
    ("cmj_rsi_mod", "RSI modified", TestFamily.FORCE_PLATE, "m/s", Direction.HIGHER, 0.05, 1.5, 2),
    ("cmj_peak_power_bm", "Vrcholový výkon / hmotnost (CMJ)", TestFamily.FORCE_PLATE, "W/kg", Direction.HIGHER, 15, 100, 1),
    ("cmj_depth", "Hloubka protipohybu (CMJ)", TestFamily.FORCE_PLATE, "cm", Direction.NEUTRAL, 5, 80, 1),
    ("cmj_contraction_time", "Doba kontrakce (CMJ)", TestFamily.FORCE_PLATE, "ms", Direction.LOWER, 200, 1500, 0),
    ("cmj_ecc_braking_rfd", "Excentrické brzdné RFD (CMJ)", TestFamily.FORCE_PLATE, "N/s", Direction.HIGHER, 100, 30000, 0),
    ("cmj_landing_force", "Vrcholová síla při doskoku (CMJ)", TestFamily.FORCE_PLATE, "N", Direction.NEUTRAL, 300, 20000, 0),
    ("imtp_peak_force", "Vrcholová síla (IMTP)", TestFamily.FORCE_PLATE, "N", Direction.HIGHER, 300, 6000, 0),
    ("imtp_peak_force_bm", "Vrcholová síla / hmotnost (IMTP)", TestFamily.FORCE_PLATE, "N/kg", Direction.HIGHER, 8, 70, 1),
    ("imtp_force_100", "Síla ve 100 ms (IMTP)", TestFamily.FORCE_PLATE, "N", Direction.HIGHER, 0, 5000, 0),
    ("imtp_force_200", "Síla ve 200 ms (IMTP)", TestFamily.FORCE_PLATE, "N", Direction.HIGHER, 0, 5000, 0),
    ("imtp_rfd_100", "RFD 0–100 ms (IMTP)", TestFamily.FORCE_PLATE, "N/s", Direction.HIGHER, -2000, 40000, 0),
    ("imtp_rfd_200", "RFD 0–200 ms (IMTP)", TestFamily.FORCE_PLATE, "N/s", Direction.HIGHER, -2000, 30000, 0),
    ("imtp_time_to_peak", "Čas do vrcholové síly (IMTP)", TestFamily.FORCE_PLATE, "s", Direction.LOWER, 0.1, 10, 2),
    # Dynamic Strength Index = koncentrická vrcholová síla v CMJ ÷ vrcholová
    # síla v IMTP. Nepočítá se ručně – dopočítá ho aplikace (analytics/derived).
    ("dsi", "Dynamic Strength Index (CMJ ÷ IMTP)", TestFamily.FORCE_PLATE, "-", Direction.NEUTRAL, 0.2, 1.6, 2),
    ("sls_cop_area", "Plocha elipsy CoP (stoj na 1 DK)", TestFamily.FORCE_PLATE, "mm²", Direction.LOWER, 50, 30000, 0),
    ("sls_total_excursion", "Celková dráha CoP (stoj na 1 DK)", TestFamily.FORCE_PLATE, "mm", Direction.LOWER, 100, 15000, 0),
    ("sls_mean_velocity", "Průměrná rychlost CoP (stoj na 1 DK)", TestFamily.FORCE_PLATE, "mm/s", Direction.LOWER, 3, 500, 1),
    ("sj_height", "Výška výskoku (SJ)", TestFamily.FORCE_PLATE, "cm", Direction.HIGHER, 5, 80, 1),
    ("sj_peak_power_bm", "Vrcholový výkon / hmotnost (SJ)", TestFamily.FORCE_PLATE, "W/kg", Direction.HIGHER, 15, 100, 1),
    # Eccentric Utilization Ratio = výška CMJ ÷ výška SJ; dopočítá se.
    ("eur", "Eccentric Utilization Ratio (CMJ ÷ SJ)", TestFamily.FORCE_PLATE, "-", Direction.NEUTRAL, 0.7, 1.6, 2),
    # --- Wingate (anaerobní test 30 s) ------------------------------------
    ("wingate_pmax", "Maximální výkon (Wingate)", TestFamily.SPIROERGOMETRY, "W", Direction.HIGHER, 200, 2500, 0),
    ("wingate_pmin", "Minimální výkon (Wingate)", TestFamily.SPIROERGOMETRY, "W", Direction.HIGHER, 50, 1500, 0),
    ("wingate_p5s_max", "Nejvyšší pětivteřinový průměr (Wingate)", TestFamily.SPIROERGOMETRY, "W", Direction.HIGHER, 200, 2500, 1),
    ("wingate_p5s_min", "Nejnižší pětivteřinový průměr (Wingate)", TestFamily.SPIROERGOMETRY, "W", Direction.HIGHER, 50, 1500, 1),
    ("wingate_work", "Celková práce (Wingate)", TestFamily.SPIROERGOMETRY, "kJ", Direction.HIGHER, 3, 60, 1),
    ("wingate_fatigue_index", "Index únavy (Wingate)", TestFamily.SPIROERGOMETRY, "%", Direction.LOWER, 5, 95, 1),
    ("wingate_revolutions", "Počet otáček (Wingate)", TestFamily.SPIROERGOMETRY, "", Direction.HIGHER, 10, 200, 0),
    ("lactate_max", "Laktát maximální", TestFamily.SPIROERGOMETRY, "mmol/l", Direction.NEUTRAL, 1, 30, 1),
    ("hr_max", "Maximální tepová frekvence", TestFamily.SPIROERGOMETRY, "BPM", Direction.NEUTRAL, 100, 230, 0),
    # relativní hodnoty – dopočítají se z hmotnosti (TH) a aktivní hmoty (ATH)
    ("wingate_pmax_th", "Maximální výkon / TH (Wingate)", TestFamily.SPIROERGOMETRY, "W/kg", Direction.HIGHER, 3, 30, 1),
    ("wingate_pmax_ath", "Maximální výkon / ATH (Wingate)", TestFamily.SPIROERGOMETRY, "W/kg", Direction.HIGHER, 3, 35, 1),
    ("wingate_pmin_th", "Minimální výkon / TH (Wingate)", TestFamily.SPIROERGOMETRY, "W/kg", Direction.HIGHER, 1, 20, 1),
    ("wingate_work_th", "Celková práce / TH (Wingate) – anaerobní kapacita", TestFamily.SPIROERGOMETRY, "J/kg", Direction.HIGHER, 50, 700, 0),
    ("wingate_work_ath", "Celková práce / ATH (Wingate)", TestFamily.SPIROERGOMETRY, "J/kg", Direction.HIGHER, 50, 800, 0),
    # --- analýza pohybu (HumanTrak) ------------------------------------
    ("boxlift_hip_flex_lift", "Flexe kyčle při max. flexi kolene – zvedání", TestFamily.FIELD, "°", Direction.NEUTRAL, 0, 180, 1),
    ("boxlift_hip_flex_lower", "Flexe kyčle při max. flexi kolene – pokládání", TestFamily.FIELD, "°", Direction.NEUTRAL, 0, 180, 1),
    ("boxlift_knee_flex_lift", "Max. flexe kolene – zvedání", TestFamily.FIELD, "°", Direction.NEUTRAL, 0, 180, 1),
    ("boxlift_knee_flex_lower", "Max. flexe kolene – pokládání", TestFamily.FIELD, "°", Direction.NEUTRAL, 0, 180, 1),
    ("boxlift_shoulder_flex", "Max. flexe ramene při zakládání", TestFamily.FIELD, "°", Direction.NEUTRAL, 0, 200, 1),
    ("boxlift_trunk_ext", "Max. extenze trupu", TestFamily.FIELD, "°", Direction.NEUTRAL, -60, 90, 1),
    ("boxlift_spine_flex_lift", "Flexe páteře při max. flexi kolene – zvedání", TestFamily.FIELD, "°", Direction.LOWER, -30, 120, 1),
    ("boxlift_spine_flex_lower", "Flexe páteře při max. flexi kolene – pokládání", TestFamily.FIELD, "°", Direction.LOWER, -30, 120, 1),
    ("boxlift_trunk_flex_lift", "Flexe trupu při max. flexi kolene – zvedání", TestFamily.FIELD, "°", Direction.NEUTRAL, -30, 150, 1),
    ("boxlift_trunk_flex_lower", "Flexe trupu při max. flexi kolene – pokládání", TestFamily.FIELD, "°", Direction.NEUTRAL, -30, 150, 1),

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
        "device": "VALD ForceDecks", "trials": 3,
        "metrics": [
            {"code": "cmj_height", "sides": ["B"], "primary": True},
            {"code": "cmj_rsi_mod", "sides": ["B"]},
            {"code": "cmj_peak_force", "sides": ["B", "L", "R"]},
            {"code": "cmj_peak_power_bm", "sides": ["B"]},
            {"code": "cmj_depth", "sides": ["B"]},
            {"code": "cmj_contraction_time", "sides": ["B"]},
            {"code": "cmj_ecc_braking_rfd", "sides": ["B"]},
            {"code": "cmj_landing_force", "sides": ["B", "L", "R"]},
            {"code": "body_mass", "sides": ["B"]},
        ],
    },
    "imtp": {
        "name": "Izometrický tah (IMTP)", "family": TestFamily.FORCE_PLATE,
        "device": "VALD ForceDecks", "trials": 3,
        "metrics": [
            {"code": "imtp_peak_force", "sides": ["B", "L", "R"], "primary": True},
            {"code": "imtp_peak_force_bm", "sides": ["B"]},
            {"code": "imtp_force_100", "sides": ["B", "L", "R"]},
            {"code": "imtp_force_200", "sides": ["B", "L", "R"]},
            {"code": "imtp_rfd_100", "sides": ["B", "L", "R"]},
            {"code": "imtp_rfd_200", "sides": ["B", "L", "R"]},
            {"code": "imtp_time_to_peak", "sides": ["B"]},
        ],
    },
    "sj": {
        "name": "Squat jump", "family": TestFamily.FORCE_PLATE,
        "device": "VALD ForceDecks", "trials": 3,
        "metrics": [
            {"code": "sj_height", "sides": ["B"], "primary": True},
            {"code": "sj_peak_power_bm", "sides": ["B"]},
        ],
    },
    "eur": {
        "name": "Eccentric Utilization Ratio", "family": TestFamily.FORCE_PLATE,
        "device": "výpočet z CMJ a SJ", "trials": 1,
        "metrics": [{"code": "eur", "sides": ["B"], "primary": True}],
    },
    "wingate": {
        "name": "Wingate test 30 s", "family": TestFamily.SPIROERGOMETRY,
        "device": "bicyklový ergometr", "trials": 1,
        "metrics": [
            {"code": "wingate_pmax", "sides": ["B"]},
            {"code": "wingate_pmax_th", "sides": ["B"], "primary": True},
            {"code": "wingate_pmax_ath", "sides": ["B"]},
            {"code": "wingate_p5s_max", "sides": ["B"]},
            {"code": "wingate_pmin", "sides": ["B"]},
            {"code": "wingate_pmin_th", "sides": ["B"]},
            {"code": "wingate_p5s_min", "sides": ["B"]},
            {"code": "wingate_work", "sides": ["B"]},
            {"code": "wingate_work_th", "sides": ["B"], "primary": True},
            {"code": "wingate_work_ath", "sides": ["B"]},
            {"code": "wingate_fatigue_index", "sides": ["B"]},
            {"code": "wingate_revolutions", "sides": ["B"]},
            {"code": "lactate_max", "sides": ["B"]},
            {"code": "hr_max", "sides": ["B"]},
        ],
    },
    "dsi": {
        "name": "Dynamic Strength Index", "family": TestFamily.FORCE_PLATE,
        "device": "výpočet z CMJ a IMTP", "trials": 1,
        "metrics": [
            {"code": "dsi", "sides": ["B"], "primary": True},
        ],
    },
    "sls": {
        "name": "Stoj na jedné noze (SLS)", "family": TestFamily.FORCE_PLATE,
        "device": "VALD ForceDecks", "trials": 2,
        "metrics": [
            {"code": "sls_cop_area", "sides": ["L", "R"], "primary": True},
            {"code": "sls_total_excursion", "sides": ["L", "R"]},
            {"code": "sls_mean_velocity", "sides": ["L", "R"]},
        ],
    },
    "box_lift": {
        "name": "Box lift – nad hlavu", "family": TestFamily.FIELD,
        "device": "VALD HumanTrak", "trials": 1,
        "metrics": [
            {"code": "boxlift_spine_flex_lift", "sides": ["B"], "primary": True},
            {"code": "boxlift_spine_flex_lower", "sides": ["B"]},
            {"code": "boxlift_hip_flex_lift", "sides": ["B"]},
            {"code": "boxlift_hip_flex_lower", "sides": ["B"]},
            {"code": "boxlift_knee_flex_lift", "sides": ["B"]},
            {"code": "boxlift_knee_flex_lower", "sides": ["B"]},
            {"code": "boxlift_trunk_flex_lift", "sides": ["B"]},
            {"code": "boxlift_trunk_flex_lower", "sides": ["B"]},
            {"code": "boxlift_shoulder_flex", "sides": ["B"]},
            {"code": "boxlift_trunk_ext", "sides": ["B"]},
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


# ---------------------------------------------------------------------------
# Profily importu z přístrojů: typ testu v exportu → protokol, sloupec → metrika.
#
# U ForceDecks se zadává souhrnný sloupec; varianty „(Left)“ a „(Right)“
# adaptér najde sám a uloží jako levou a pravou stranu. Třetí položka je
# násobek (hloubka protipohybu je v exportu záporná), nepovinná čtvrtá
# říká, zda importovat i strany (u časů rozdíl stran nic neříká).
# ---------------------------------------------------------------------------
IMPORT_PROFILES = [
    ("vald_forcedecks", "Countermovement Jump", "cmj", [
        ("Jump Height (Imp-Mom) [cm]", "cmj_height", 1),
        ("RSI-modified (Imp-Mom) [m/s]", "cmj_rsi_mod", 1),
        ("Concentric Peak Force [N]", "cmj_peak_force", 1),
        ("Peak Power / BM [W/kg]", "cmj_peak_power_bm", 1),
        ("Countermovement Depth [cm]", "cmj_depth", -1),
        ("Contraction Time [ms]", "cmj_contraction_time", 1),
        ("Eccentric Braking RFD [N/s]", "cmj_ecc_braking_rfd", 1),
        ("Peak Landing Force [N]", "cmj_landing_force", 1),
        ("Body Weight [kg]", "body_mass", 1),
    ]),
    ("vald_forcedecks", "Isometric Mid-Thigh Pull", "imtp", [
        ("Peak Vertical Force [N]", "imtp_peak_force", 1),
        ("Peak Vertical Force / BM [N/kg]", "imtp_peak_force_bm", 1),
        ("Force at 100ms [N]", "imtp_force_100", 1),
        ("Force at 200ms [N]", "imtp_force_200", 1),
        ("RFD - 100ms [N/s]", "imtp_rfd_100", 1),
        ("RFD - 200ms [N/s]", "imtp_rfd_200", 1),
        ("Start Time to Peak Force [s]", "imtp_time_to_peak", 1, False),
    ]),
    ("vald_forcedecks", "Squat Jump", "sj", [
        ("Jump Height (Imp-Mom) [cm]", "sj_height", 1),
        ("Peak Power / BM [W/kg]", "sj_peak_power_bm", 1),
    ]),
    ("vald_forcedecks", "Single Leg Stand", "sls", [
        ("Area of CoP Ellipse [mm sq]", "sls_cop_area", 1),
        ("Total Excursion [mm]", "sls_total_excursion", 1),
        ("Mean Velocity [mm/s]", "sls_mean_velocity", 1),
    ]),
    ("vald_humantrak", "Box Lift - Overhead", "box_lift", [
        ("Hip Flexion at Peak Knee Flexion During Lift[°]", "boxlift_hip_flex_lift", 1),
        ("Hip Flexion at Peak Knee Flexion During Lower[°]", "boxlift_hip_flex_lower", 1),
        ("Peak Knee Flexion During Lift[°]", "boxlift_knee_flex_lift", 1),
        ("Peak Knee Flexion During Lower[°]", "boxlift_knee_flex_lower", 1),
        ("Peak Shoulder Flexion During Place[°]", "boxlift_shoulder_flex", 1),
        ("Peak Trunk Extension[°]", "boxlift_trunk_ext", 1),
        ("Spinal Flexion at Peak Knee Flexion During Lift[°]", "boxlift_spine_flex_lift", 1),
        ("Spinal Flexion at Peak Knee Flexion During Lower[°]", "boxlift_spine_flex_lower", 1),
        ("Trunk Flexion at Peak Knee Flexion During Lift[°]", "boxlift_trunk_flex_lift", 1),
        ("Trunk Flexion at Peak Knee Flexion During Lower[°]", "boxlift_trunk_flex_lower", 1),
    ]),
]


# ---------------------------------------------------------------------------
# Doplňkové vlastnosti metrik. Zakládají se jen tam, kde zatím nic není –
# úpravy v administraci se nepřepisují.
#
# ods: role v systému Outcome–Driver–Strategy (co sportovec dokázal / co to
#      pohání / jak pohyb provedl).
# cv:  orientační horní mez rozptylu pokusů téhož dne (variační koeficient
#      v %). Vyšší rozptyl = pokus stojí za zopakování. Hodnoty jsou
#      výchozí nastavení laboratoře, ne normy – upravte podle zkušenosti.
# ---------------------------------------------------------------------------
METRIC_EXTRAS = {
    "cmj_height": {"ods": "vysledek", "cv": 10},
    "cmj_rsi_mod": {"ods": "vysledek", "cv": 10},
    "cmj_peak_force": {"ods": "pricina", "cv": 10},
    "cmj_peak_power_bm": {"ods": "pricina", "cv": 10},
    "cmj_ecc_braking_rfd": {"ods": "pricina"},
    "cmj_depth": {"ods": "strategie"},
    "cmj_contraction_time": {"ods": "strategie"},
    "imtp_peak_force": {"cv": 10},
}


# Články k odvozeným ukazatelům. Zakládají se jako NAVRŽENÉ – do zprávy se
# dostanou až po schválení člověkem (Katalog → Články).
SEED_ARTICLES = [
    {
        "doi": "10.3390/sports5040072", "pmid": "29910432", "year": 2017,
        "title": "Influence of Dynamic Strength Index on Countermovement Jump Force-, "
                 "Power-, Velocity-, and Displacement-Time Curves",
        "authors": "McMahon JJ, Jones PA, Dos'Santos T, Comfort P",
        "journal": "Sports (Basel)", "evidence_level": "cross",
        "population_sex": "M", "population_level": "univerzitní sportovci",
        "sample_size": 53,
        "curator_note": "Nízké DSI (0,55) × vysoké (0,92): nízké DSI mělo vyšší sílu v IMTP, "
                        "ale větší brzdný impulz v CMJ. Podporuje balistický trénink při "
                        "nízkém a silový při vysokém DSI.",
    },
    {
        "doi": "10.3390/sports6040176", "pmid": "30572561", "year": 2018,
        "title": "Changes in Dynamic Strength Index in Response to Strength Training",
        "authors": "Comfort P, Thomas C, Dos'Santos T, Suchomel TJ, Jones PA, McMahon JJ",
        "journal": "Sports (Basel)", "evidence_level": "cohort",
        "population_sex": "B", "population_level": "univerzitní sportovci",
        "sample_size": 24,
        "curator_note": "Čtyři týdny silového tréninku snížily DSI u sportovců s vysokým DSI "
                        "(0,85 → 0,74), u nízkého DSI beze změny.",
    },
    {
        "doi": "10.1123/ijspp.2017-0255", "pmid": "28714767", "year": 2018,
        "title": "Comparison of Methods of Calculating Dynamic Strength Index",
        "authors": "Comfort P, Thomas C, Dos'Santos T, Jones PA, Suchomel TJ, McMahon JJ",
        "journal": "Int J Sports Physiol Perform", "evidence_level": "cross",
        "population_sex": "M", "population_age_min": 16, "population_age_max": 18,
        "population_level": "mládež – fotbal, ragby", "sample_size": 27,
        "curator_note": "DSI z CMJ je spolehlivější než ze squat jumpu (CV 3,8–4,6 %).",
    },
]

DSI_RULES = [
    {
        "code": "dsi_nizky",
        "name": "DSI nízký – prostor pro balistický trénink",
        "condition": {"metric": "dsi", "op": "<", "value": 0.60},
        "contraindication": {"load_restriction": True},
        "severity": "low",
        "finding_template": (
            "Dynamic Strength Index {value_txt} je pod orientační hranicí {threshold_txt}: "
            "sportovec v dynamickém pohybu využije jen menší část své maximální síly."
        ),
        "recommendation_template": (
            "Zvážit důraz na balistický a rychlostně-silový trénink (skoky, odhody, "
            "vzpěračské varianty); maximální síla je vůči projevu v pohybu dostatečná."
        ),
        "articles": ["10.3390/sports5040072", "10.1123/ijspp.2017-0255"],
    },
    {
        "code": "dsi_vysoky",
        "name": "DSI vysoký – prostor pro rozvoj maximální síly",
        "condition": {"metric": "dsi", "op": ">", "value": 0.80},
        "contraindication": {"load_restriction": True},
        "severity": "low",
        "finding_template": (
            "Dynamic Strength Index {value_txt} je nad orientační hranicí {threshold_txt}: "
            "sportovec v dynamickém pohybu využívá velkou část své maximální síly."
        ),
        "recommendation_template": (
            "Zvážit důraz na rozvoj maximální síly (těžký silový trénink); v dynamickém "
            "projevu je sportovec vůči své maximální síle dobře využitý."
        ),
        "articles": ["10.3390/sports5040072", "10.3390/sports6040176"],
    },
]
