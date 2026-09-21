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

# kód -> (název, rodina, přístroj, [kódy metrik], počet pokusů)
PROTOCOLS = {
    "cmj": ("Countermovement jump", TestFamily.FORCE_PLATE, "force plate",
            ["cmj_height", "cmj_peak_force", "cmj_rsi_mod"], 3),
    "imtp": ("Izometrický tah (IMTP)", TestFamily.FORCE_PLATE, "force plate",
             ["imtp_peak_force"], 3),
    "iso_shoulder": ("Izokinetika ramene", TestFamily.DYNAMOMETRY, "izokinetický dynamometr",
                     ["shoulder_ir_torque", "shoulder_er_torque", "ir_er_ratio"], 3),
    "grip": ("Síla stisku ruky", TestFamily.DYNAMOMETRY, "ruční dynamometr",
             ["grip_strength"], 2),
    "spiro_ramp": ("Spiroergometrie – rampový protokol", TestFamily.SPIROERGOMETRY, "spiroergometr",
                   ["vo2max", "vt2_power"], 1),
    "bodycomp": ("Složení těla", TestFamily.BODY_COMPOSITION, "DXA / BIA",
                 ["body_mass", "height", "lean_mass", "body_fat_pct",
                  "segment_mass", "segment_lean_mass"], 1),
    "serve": ("Rychlost podání", TestFamily.FIELD, "radar",
              ["serve_speed"], 3),
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
