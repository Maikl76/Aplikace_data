"""
Úpravy návrhů karet (katalog/karty) po kontrole proti podkladům v02.

1. Texty „budoucího měření“ podle podkladů „Dotazník, fenotyp a report“:
   měření se navrhuje podle cíle klienta, ne proto, že je varianta v panelu;
   text neslibuje srovnání s normou (první verze měření nevyhodnocuje)
   a parametr uvádí až schválený katalog testů.
2. Stejná obecná doporučení pod jedním klíčem pro slučování mají jedno
   znění – zpráva je spojí do jednoho doporučení s více důvody, místo aby
   je hlásila jako rozpor „k odbornému posouzení“.

Klíč: (rsID, verze karty, původní text). Používá migrace 0005 (jen
neschválené karty s nezměněným textem) a skript, který upravil soubory karet.
"""

ENDURANCE = ["vytrvalost"]
POWER = ["sila_rychlost"]

MEASUREMENT = {
    ("rs1799752", 2,
     "Vytrvalostní předpoklady a jejich vývoj ukáže spiroergometrie (VO₂max, ventilační prahy); "
     "zpráva porovná výsledek s normou a s minulým měřením."):
    ("Pro přesnější posouzení aerobní kapacity ve vztahu k Vašemu sportovnímu cíli by bylo "
     "vhodné doplnit spiroergometrické vyšetření.", ENDURANCE),
    ("rs1799752", 2,
     "Silově-rychlostní předpoklady posoudí výskok na silové desce a Wingate test; zpráva porovná "
     "výsledek s normou a s minulým měřením."):
    ("Pro přesnější posouzení výbušnosti a krátkodobé intenzivní zátěže ve vztahu k Vašemu "
     "sportovnímu cíli by bylo vhodné doplnit výskok na silové desce (CMJ) a Wingate test.", POWER),
    ("rs1815739", 2,
     "Sílu a výbušnost posoudí výskok na silové desce (CMJ) a Wingate test; zpráva porovná "
     "výsledek s normou a s minulým měřením."):
    ("Pro přesnější posouzení výbušnosti a krátkodobé intenzivní zátěže ve vztahu k Vašemu "
     "sportovnímu cíli by bylo vhodné doplnit výskok na silové desce (CMJ) a Wingate test.", POWER),
    ("rs12722", 2,
     "Sílu při dopadu a asymetrii ve výskoku na silové desce sledujte v čase; zpráva porovná "
     "měření s minulým."):
    ("Při cíli prevence zranění by bylo vhodné sledovat v čase sílu při dopadu a asymetrii "
     "ve výskoku na silové desce (CMJ).", ["zdravi"]),
    ("rs762551", 2,
     "Zda vám kofein skutečně pomáhá, ukáže pokus: stejný test jednou bez kofeinu a jednou "
     "s obvyklou dávkou. Dávka se zapíše v podmínkách provedení testu a zpráva obě provedení "
     "porovná."):
    ("Zda Vám kofein skutečně pomáhá, by ukázal pokus: stejný test jednou bez kofeinu a jednou "
     "s obvyklou dávkou. Dávka se zapíše v podmínkách provedení testu, aby šla obě provedení "
     "porovnat.", []),
    ("rs9939609", 1,
     "Vývoj hmotnosti a složení těla ukáže opakované měření složení těla; zpráva porovná měření "
     "v čase."):
    ("Pro posouzení vývoje hmotnosti a složení těla ve vztahu k Vašemu cíli by bylo vhodné "
     "doplnit opakované měření složení těla (antropometrie).", ["hmotnost"]),
    ("rs8192678", 2,
     "Reakci na vytrvalostní trénink ukáže opakovaná spiroergometrie (VO₂max, ventilační prahy) "
     "v odstupu týdnů; zpráva porovná měření a změnu posoudí podle chyby měření."):
    ("Reakci na vytrvalostní trénink by ukázala opakovaná spiroergometrie v odstupu několika "
     "týdnů; změnu je třeba posuzovat vůči chybě měření.", ENDURANCE),
    ("rs1049434", 1,
     "Anaerobní výkon a pokles výkonu během zátěže ukáže Wingate test; zpráva porovná výsledek "
     "s normou a s minulým měřením."):
    ("Pro přesnější posouzení krátkodobé intenzivní zátěže ve vztahu k Vašemu sportovnímu cíli "
     "by bylo vhodné doplnit Wingate test (WT30).", POWER),
}


TRAINING = ("Zaměření a dávkování tréninku vychází z cíle, sportu, tréninkové historie a měření, "
            "ne z genotypu.")
DIET = ("Stravu a hmotnost nastavujte podle cíle, tréninkového zatížení a měření složení těla, "
        "ne podle genotypu; při záměru měnit hmotnost se poraďte se sportovním nutričním "
        "specialistou.")

# (rsID, verze, původní text) → nové znění (klíč pro slučování zůstává)
GENERAL = {
    ("rs1799752", 2, "Zaměření tréninku (vytrvalost, síla, kombinace) vychází z cíle, sportu, "
                     "tréninkové historie a měření, ne z genotypu."): TRAINING,
    ("rs1815739", 2, "O zaměření tréninku rozhoduje sport, cíl, tréninková historie a měření; "
                     "genotyp ACTN3 není důvod trénink měnit [S4]."): TRAINING,
    ("rs8192678", 2, "Zaměření a dávkování vytrvalostního tréninku vychází z cíle, sportu, "
                     "tréninkové historie a měření, ne z genotypu."): TRAINING,
    ("rs1049434", 1, "Dávkování intenzivní intervalové zátěže vychází z cíle, sportu, tréninkové "
                     "historie a měření, ne z genotypu."): TRAINING,
    ("rs9939609", 1, "Stravu nastavujte podle cíle, tréninkového zatížení a měření složení těla, "
                     "ne podle genotypu; při záměru měnit hmotnost se poraďte se sportovním "
                     "nutričním specialistou."): DIET,
    ("rs7903146", 1, "Stravu a hmotnost nastavujte podle cíle, tréninku a měření; s otázkami na "
                     "hladinu cukru nebo metabolické zdraví se obraťte na lékaře, ne na "
                     "genotyp."): DIET,
}

# Co ze sjednoceného znění vypadlo, zůstane jako samostatné doporučení té karty:
# (rsID, verze, původní text) → pole nového doporučení
SPLIT = {
    ("rs7903146", 1, "Stravu a hmotnost nastavujte podle cíle, tréninku a měření; s otázkami na "
                     "hladinu cukru nebo metabolické zdraví se obraťte na lékaře, ne na "
                     "genotyp."): {
        "kind": "risk", "basis": "general", "merge_key": "metabolicke-zdravi-lekar",
        "text": "S otázkami na hladinu cukru nebo metabolické zdraví se obraťte na lékaře; "
                "genotyp TCF7L2 vyšetření nenahrazuje."},
}
