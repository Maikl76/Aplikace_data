"""Startovní oblasti genetiky – zakládá je seed_catalog, dál se spravují v administraci."""

from .models import Domain

DOMAINS = [
    ("vykon", "Výkon a trénink",
     "Silově-rychlostní a vytrvalostní předpoklady, trénovatelnost."),
    ("pohybovy_aparat", "Pohybový aparát", "Pojivové tkáně, zatížení, prevence přetížení."),
    ("regenerace", "Regenerace", "Zánětlivá odpověď na zátěž a zotavení."),
    ("kofein", "Kofein", "Metabolismus kofeinu a individuální odezva."),
    ("laktoza", "Laktóza", "Laktázová persistence a sportovní výživa."),
    ("hmotnost", "Hmotnost a metabolický kontext",
     "Vývoj hmotnosti, stravovací návyky; bez zdravotních závěrů."),
]


# Fenotyp oblasti: ukazatele z katalogu, které zpráva ukáže před genotypem.
# Doplní se jen do oblasti bez ukazatelů; výběr pak patří administraci.
DOMAIN_METRICS = {
    "vykon": ["cmj_height", "cmj_peak_power_bm", "wingate_pmax_th", "wingate_work_th",
              "sprint_30m", "vo2max", "vt2_power"],
    "pohybovy_aparat": ["sls_cop_area", "imtp_peak_force", "cmj_landing_force"],
    "hmotnost": ["body_mass", "body_fat_pct", "lean_mass"],
}
DOMAIN_FATIGUE = {"regenerace"}


def seed_domains() -> int:
    """Doplní chybějící sdílené oblasti; existující nemění. Vrací počet nových."""
    from apps.catalog.models import MetricDef

    created = 0
    for order, (code, name, description) in enumerate(DOMAINS, start=1):
        domain, is_new = Domain.objects.get_or_create(
            organization=None, code=code,
            defaults={"name": name, "description": description, "order": order,
                      "uses_fatigue": code in DOMAIN_FATIGUE})
        created += is_new
        if code in DOMAIN_METRICS and not domain.metrics.exists():
            domain.metrics.set(MetricDef.objects.filter(organization__isnull=True,
                                                        code__in=DOMAIN_METRICS[code]))
    return created


def domain_for(name: str):
    """Oblast podle názvu z podkladů („Výkon a trénink“); neznámou založí."""
    wanted = (name or "").strip().lower()
    for code, label, _ in DOMAINS:
        if label.lower() == wanted:
            return Domain.objects.get_or_create(
                organization=None, code=code,
                defaults={"name": label, "order": [c for c, _, _ in DOMAINS].index(code) + 1})[0]
    found = Domain.objects.filter(name__iexact=wanted).first()
    if found:
        return found
    from django.utils.text import slugify

    return Domain.objects.create(organization=None, code=slugify(wanted)[:64] or "ostatni",
                                 name=name.strip() or "Ostatní", order=99)


# --- dotazník ke genetickému vyšetření ------------------------------------------
# Obsahová osnova z podkladů (dokument „Dotazník, fenotyp a report“). Není to
# validovaný formulář: laboratoř ho dokončí v administraci (Katalog → Dotazníky).
# Otázky jsou data; kódy otázek a možností používají scénáře karet.

QUESTIONNAIRE_CODE = "genetika"

QUESTIONNAIRE = {
    "code": QUESTIONNAIRE_CODE,
    "name": "Dotazník ke genetickému vyšetření",
    "description": "Odpovědi doplňují výsledek genetického vyšetření o kontext: cíl, trénink, "
                   "zkušenost a obtíže. Nejsou to otázky na zdravotní stav; co nevíte nebo se "
                   "vás netýká, tak označte.",
    "questions": [
        # Profil a cíle
        {"code": "hlavni_sport", "section": "Profil a cíle", "kind": "text",
         "text": "Hlavní sport nebo disciplína"},
        {"code": "zamereni", "section": "Profil a cíle", "kind": "choice",
         "text": "Sportovní zaměření",
         "options": [("rekreacni", "rekreační"), ("vykonnostni", "výkonnostní"),
                     ("vrcholove", "vrcholové")]},
        {"code": "cil", "section": "Profil a cíle", "kind": "choice",
         "text": "Hlavní cíl pro nejbližší období",
         "options": [("vytrvalost", "vytrvalost a aerobní kapacita"),
                     ("sila_rychlost", "síla, rychlost, výbušnost"),
                     ("hmotnost", "hmotnost a složení těla"),
                     ("zdravi", "zdraví a prevence zranění"), ("jiny", "jiný")]},
        {"code": "cil_upresneni", "section": "Profil a cíle", "kind": "text",
         "text": "Upřesnění cíle a očekávání", "required": False},
        {"code": "praxe_let", "section": "Profil a cíle", "kind": "number", "unit": "let",
         "text": "Délka sportovní praxe"},
        # Trénink a výkon
        {"code": "jednotek_tydne", "section": "Trénink a výkon", "kind": "number",
         "unit": "jednotek", "text": "Počet tréninkových jednotek za týden (poslední 4 týdny)"},
        {"code": "hodin_tydne", "section": "Trénink a výkon", "kind": "number", "unit": "h",
         "text": "Hodin tréninku za týden (poslední 4 týdny)"},
        {"code": "slozka", "section": "Trénink a výkon", "kind": "multi",
         "text": "Co v tréninku převažuje",
         "options": [("vytrvalostni", "vytrvalostní"), ("silova", "silová"),
                     ("intenzivni", "intenzivní intervalová"), ("herni", "herní a technická")]},
        {"code": "zmena_objemu", "section": "Trénink a výkon", "kind": "choice",
         "text": "Změnil se objem tréninku v posledních 4 týdnech?", "allow_unknown": True,
         "options": [("zvysil", "zvýšil se"), ("snizil", "snížil se"),
                     ("beze_zmeny", "beze změny")]},
        {"code": "vykonovy_profil", "section": "Trénink a výkon", "kind": "choice",
         "text": "Vlastní zkušenost s výkonem", "allow_unknown": True,
         "help_text": "Sebehodnocení – zkušenost, ne měření.",
         "options": [("vytrvalost", "Lépe zvládám delší souvislou zátěž a vytrvalostní trénink "
                                    "než krátké maximální výkony"),
                     ("sila", "Dosahuji velmi dobrých výsledků v krátkých sprintech, silových "
                              "testech nebo krátkých intenzivních intervalech"),
                     ("neutralni", "Ani jedno výrazně nepřevažuje")]},
        # Pohybový aparát
        {"code": "obtize_nyni", "section": "Pohybový aparát", "kind": "yesno",
         "text": "Máte nyní bolesti nebo obtíže pohybového aparátu?"},
        {"code": "obtize_popis", "section": "Pohybový aparát", "kind": "text",
         "text": "Kde, jak dlouho a v jakém vztahu k zátěži", "required": False},
        {"code": "slachy_opakovane", "section": "Pohybový aparát", "kind": "choice",
         "text": "Bolesti Achillovy nebo patelární šlachy při vyšším tréninkovém objemu",
         "allow_unknown": True,
         "options": [("opakovane", "mívám opakovaně"), ("vyjimecne", "výjimečně"),
                     ("nikdy", "nemívám ani při vyšší běžecké nebo silové zátěži")]},
        {"code": "zraneni_drive", "section": "Pohybový aparát", "kind": "text",
         "text": "Dřívější poranění a omezení tréninku", "required": False,
         "help_text": "Subjektivní obtíže, ne diagnózy."},
        # Regenerace
        {"code": "unava", "section": "Regenerace", "kind": "scale", "min": 0, "max": 10,
         "text": "Únava mezi tréninky v posledních 4 týdnech",
         "anchors": {"0": "žádná", "5": "střední", "10": "maximální"}},
        {"code": "bolestivost", "section": "Regenerace", "kind": "choice",
         "text": "Svalová bolestivost a zotavení po náročném tréninku", "allow_unknown": True,
         "options": [("vyrazna", "výrazná bolestivost, potřebuji delší čas na zotavení"),
                     ("bezna", "zotavím se rychle a mohu brzy znovu kvalitně trénovat")]},
        {"code": "spanek_h", "section": "Regenerace", "kind": "number", "unit": "h",
         "text": "Obvyklá délka spánku"},
        {"code": "stres", "section": "Regenerace", "kind": "scale", "min": 0, "max": 10,
         "text": "Pracovní a psychická zátěž", "anchors": {"0": "žádná", "10": "maximální"}},
        {"code": "odpocinek_dny", "section": "Regenerace", "kind": "number", "unit": "dny",
         "text": "Odpočinkové dny v týdnu"},
        # Kofein
        {"code": "kofein_zdroje", "section": "Kofein", "kind": "multi", "text": "Zdroje kofeinu",
         "options": [("kava", "káva"), ("caj", "čaj"), ("energeticke", "energetické nápoje"),
                     ("tablety", "tablety, gely, doplňky"), ("zadne", "žádné")]},
        {"code": "kofein_davky", "section": "Kofein", "kind": "number", "unit": "dávek denně",
         "text": "Obvyklé množství", "allow_na": True},
        {"code": "kofein_casovani", "section": "Kofein", "kind": "choice",
         "text": "Kofein před výkonem", "allow_na": True,
         "options": [("pravidelne", "pravidelně"), ("obcas", "občas"), ("nikdy", "nikdy")]},
        {"code": "kofein_ucinek", "section": "Kofein", "kind": "choice",
         "text": "Vnímaný účinek kofeinu před výkonem", "allow_unknown": True, "allow_na": True,
         "options": [("pozitivni", "lepší soustředění a menší únava bez výrazných nežádoucích "
                                   "účinků"),
                     ("negativni", "nervozita, bušení srdce, horší spánek nebo žádné zlepšení "
                                   "výkonu"),
                     ("zadny", "nepozoruji rozdíl")]},
        # Laktóza a sportovní výživa
        {"code": "mleko_obtize", "section": "Laktóza a sportovní výživa", "kind": "choice",
         "text": "Po čerstvém mléce nebo mléčných výrobcích", "allow_unknown": True,
         "allow_na": True,
         "options": [("obtize", "mívám nadýmání, křeče nebo průjem"),
                     ("bez", "snáším je bez potíží")]},
        {"code": "whey_obtize", "section": "Laktóza a sportovní výživa", "kind": "choice",
         "text": "Po whey koncentrátu nebo mléčném regeneračním nápoji", "allow_unknown": True,
         "allow_na": True,
         "options": [("obtize", "mívám zažívací obtíže"), ("bez", "bez obtíží")]},
        {"code": "bezlaktozove", "section": "Laktóza a sportovní výživa", "kind": "yesno",
         "text": "Pozorujete rozdíl u bezlaktózových variant?", "allow_unknown": True,
         "allow_na": True},
        # Hmotnost a metabolický kontext
        {"code": "hmotnost_vyvoj", "section": "Hmotnost a metabolický kontext", "kind": "choice",
         "text": "Vývoj hmotnosti za posledních 6 měsíců", "allow_unknown": True,
         "options": [("narust", "nárůst"), ("pokles", "pokles"), ("stabilni", "stabilní")]},
        {"code": "hmotnost_zamer", "section": "Hmotnost a metabolický kontext", "kind": "choice",
         "text": "Záměr", "options": [("snizit", "snížit"), ("zvysit", "zvýšit"),
                                      ("udrzet", "udržet"), ("bez", "bez záměru")]},
        {"code": "strava", "section": "Hmotnost a metabolický kontext", "kind": "text",
         "text": "Stravovací režim a dietní omezení", "required": False},
        {"code": "leky_suplementy", "section": "Hmotnost a metabolický kontext", "kind": "text",
         "text": "Léky nebo doplňky, které mohou ovlivnit doporučení", "required": False,
         "help_text": "Jen to, co je pro doporučení potřeba."},
        # Dostupnost dalších informací
        {"code": "vysetreni", "section": "Dostupnost dalších informací", "kind": "multi",
         "text": "Mám k dispozici výsledky", "required": False,
         "options": [("spiro", "spiroergometrie (VO₂max)"), ("wingate", "Wingate test"),
                     ("cmj", "výskok (CMJ)"), ("antropometrie", "antropometrie / složení těla"),
                     ("lekarske", "lékařské vyšetření")]},
    ],
}

# Které odpovědi odpovídají scénářům z karet („Výstup odpovědi: …“). Převod
# karet podle toho scénář napojí na otázku; scénář ale zůstává neaktivní,
# dokud ho garant po revizi nezapne.
SCENARIO_LINKS = {
    ("vykonovy_profil", "vytrvalost"): [
        "Lépe zvládám delší souvislou zátěž a vytrvalostní trénink než krátké maximální výkony.",
        "Lépe zvládám dlouhé série nebo vytrvalostní trénink než krátké maximální výkony.",
        "Lépe zvládám dlouhodobou vytrvalostní zátěž než krátké maximální úseky.",
    ],
    ("vykonovy_profil", "sila"): [
        "Dosahuji velmi dobrých výsledků v krátkých sprintech, silových testech nebo krátkých "
        "intenzivních intervalech.",
        "Dosahuji velmi dobrých výsledků v krátkých sprintech a výbušných cvičeních.",
        "Lépe mi sedí krátké intenzivní úseky než dlouhé vytrvalostní zatížení.",
    ],
    ("slachy_opakovane", "opakovane"): [
        "Opakovaně mívám bolesti Achillovy nebo patelární šlachy při vyšším tréninkovém objemu.",
    ],
    ("slachy_opakovane", "nikdy"): [
        "Šlachové potíže nemívám ani při vyšší běžecké nebo silové zátěži.",
    ],
    ("bolestivost", "vyrazna"): [
        "Po náročném tréninku mívám výraznou svalovou bolestivost a potřebuji delší čas na "
        "zotavení.",
    ],
    ("bolestivost", "bezna"): [
        "Obvykle se po intenzivním tréninku zotavím rychle a mohu brzy znovu kvalitně trénovat.",
    ],
    ("kofein_ucinek", "pozitivni"): [
        "Po kofeinu před delším výkonem cítím lepší soustředění, menší únavu a zároveň nemám "
        "výrazné nežádoucí účinky.",
    ],
    ("kofein_ucinek", "negativni"): [
        "Po kofeinu bývám nervózní, mám bušení srdce, horší spánek nebo nepozoruji žádné "
        "zlepšení výkonu.",
    ],
    ("mleko_obtize", "obtize"): ["Po vypití čerstvého mléka mívám nadýmání, křeče nebo průjem."],
    ("mleko_obtize", "bez"): ["Mléko a běžné mléčné výrobky snáším bez potíží."],
    ("whey_obtize", "obtize"): [
        "Po whey koncentrátu nebo mléčném regeneračním nápoji mívám zažívací obtíže.",
    ],
    ("whey_obtize", "bez"): ["Bez problémů toleruji i větší množství mléka nebo whey koncentrátu."],
}


def _norm(text: str) -> str:
    return " ".join(text.lower().replace("„", "").replace("“", "").replace('"', "")
                    .rstrip(".").split())


def seed_questionnaire():
    """Založí sdílený dotazník genetiky; existující otázky nemění, chybějící doplní."""
    from apps.catalog.models import Question, Questionnaire

    questionnaire, _ = Questionnaire.objects.get_or_create(
        organization=None, code=QUESTIONNAIRE["code"],
        defaults={"name": QUESTIONNAIRE["name"], "description": QUESTIONNAIRE["description"]})
    for order, q in enumerate(QUESTIONNAIRE["questions"], start=1):
        Question.objects.get_or_create(
            questionnaire=questionnaire, code=q["code"],
            defaults={
                "text": q["text"], "order": order, "kind": q["kind"],
                "section": q.get("section", ""), "help_text": q.get("help_text", ""),
                "options": [{"code": c, "label": label} for c, label in q.get("options", [])],
                "unit": q.get("unit", ""), "required": q.get("required", True),
                "allow_unknown": q.get("allow_unknown", False),
                "allow_na": q.get("allow_na", False),
                "scale_min": q.get("min", 0), "scale_max": q.get("max", 10),
                "anchors": q.get("anchors", {}),
            })
    return questionnaire


def link_scenarios(scenarios=None) -> int:
    """
    Napojí scénáře z dotazníku na otázku a odpověď podle známých znění.
    Vrací počet napojených. Scénář zůstává neaktivní – zapíná ho garant.
    """
    from apps.catalog.models import Question

    from .models import ContextScenario

    questionnaire = seed_questionnaire()
    questions = {q.code: q for q in Question.objects.filter(questionnaire=questionnaire)}
    lookup = {_norm(statement): (code, option) for (code, option), statements in
              SCENARIO_LINKS.items() for statement in statements}
    rows = scenarios if scenarios is not None else ContextScenario.objects.filter(
        kind=ContextScenario.Kind.QUESTIONNAIRE, question__isnull=True)
    linked = 0
    for scenario in rows:
        match = lookup.get(_norm(scenario.statement))
        if not match or match[0] not in questions:
            continue
        scenario.question = questions[match[0]]
        scenario.answer_match = {"choices": [match[1]]}
        scenario.save(update_fields=["question", "answer_match"])
        linked += 1
    return linked


def seed_genetics() -> None:
    """Oblasti a dotazník genetiky – volá seed_catalog při každém startu."""
    seed_domains()
    seed_questionnaire()
