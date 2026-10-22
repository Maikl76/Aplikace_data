"""
Sjednocení volně psaných hodnot normy (úroveň, strana, režim) na kódy.

Dřív byly tato pole volný text, takže v nich mohlo být „elite“, „Levá“
nebo „con“. Výběr normy je porovnával s kódy sportovce a měření a volný
text nikdy neseděl – norma pro elitní levou stranu se tak použila na
rekreačního sportovce vpravo. Tady se text převádí na kód; co nejde
převést, zůstane prázdné (= norma platí obecně) a původní text se
zapíše do poznámky, aby se nic neztratilo.
"""

LEVELS = {
    "rec": "rec", "rekreacni": "rec", "recreational": "rec", "amater": "rec",
    "amateur": "rec", "hobby": "rec",
    "trained": "trained", "trenovany": "trained", "trenovani": "trained",
    "vykonnostni": "trained", "competitive": "trained", "sub-elite": "trained",
    "subelite": "trained", "regional": "trained", "regionalni": "trained",
    "national": "national", "narodni": "national", "narodni uroven": "national",
    "intl": "intl", "international": "intl", "mezinarodni": "intl",
    "mezinarodni uroven": "intl", "elite": "intl", "elitni": "intl", "vrcholovy": "intl",
    "vrcholova": "intl", "olympic": "intl", "professional": "intl", "profesionalni": "intl",
}
SIDES = {
    "l": "L", "left": "L", "leva": "L", "levá": "L",
    "r": "R", "right": "R", "prava": "R", "pravá": "R",
    "b": "B", "bilateral": "B", "both": "B", "obe": "B", "oboustranne": "B",
    "d": "D", "dominant": "D", "dominantni": "D",
    "n": "N", "nondominant": "N", "non-dominant": "N", "nedominantni": "N",
}
MODES = {
    "con": "con", "concentric": "con", "koncentricky": "con", "koncentricka": "con",
    "ecc": "ecc", "eccentric": "ecc", "excentricky": "ecc", "excentricka": "ecc",
    "iso": "iso", "isometric": "iso", "izometricky": "iso", "izometricka": "iso",
}


def _fold(text: str) -> str:
    import unicodedata

    plain = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return " ".join(plain.lower().replace("_", " ").split())


def normalize(value, table: dict) -> str | None:
    """Kód pro zapsanou hodnotu; None, když nejde poznat (prázdná hodnota -> \"\")."""
    if value is None or not str(value).strip():
        return ""
    return table.get(_fold(value), table.get(str(value).strip().lower()))


def normalize_fields(data: dict) -> list[str]:
    """
    Upraví level/side/mode v ``data`` na kódy. Vrací, co se nepodařilo
    převést (a tedy se vymazalo), ve tvaru „úroveň: elite“.
    """
    lost = []
    for field, table, label in (("level", LEVELS, "úroveň"), ("side", SIDES, "strana"),
                                ("mode", MODES, "režim")):
        if field not in data:
            continue
        code = normalize(data[field], table)
        if code is None:
            lost.append(f"{label}: {data[field]}")
            code = ""
        data[field] = code
    return lost
