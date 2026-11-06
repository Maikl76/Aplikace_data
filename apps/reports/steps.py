"""Kroky zprávy: koncept, souhrn, doporučení, kontrola, vydání, předání."""

from apps.core.steps import step

from .models import Audience, Report


def report_steps(report, *, has_consent: bool, number_problems=(), text_problems=(),
                 recommendations: int = 0) -> list[dict]:
    released = report.status in (Report.Status.RELEASED, Report.Status.SUPERSEDED)
    editable = report.is_editable
    writing = report.is_writing
    deliveries = list(report.deliveries.all())
    clinician = report.audience == Audience.CLINICIAN

    if writing:
        summary_text = "Model píše souhrn; stránku můžete zavřít, doplní se sám."
    elif report.llm_model and report.llm_model != "šablona":
        summary_text = (f"Napsal model {report.llm_model}"
                        + (", upraveno diagnostikem." if report.summary_edited
                           else " – přečtěte a opravte, co nesedí."))
    else:
        summary_text = "Sestavila šablona – doplňte, co šablona neumí říct."

    checks = []
    if number_problems:
        checks.append("čísla bez opory ve výsledcích: " + ", ".join(list(number_problems)[:5])
                      + " (pokud jsou správně, můžete je ponechat)")
    if text_problems:
        checks.append("nepřípustný výrok: „" + "“, „".join(text_problems) + "“")
    if clinician and not has_consent:
        checks.append("chybí souhlas sportovce s předáním zprávy lékaři")

    return [
        step(1, "Koncept", True,
             report.audience_for + (f", testovací den {report.session.date:%d.%m.%Y}."
                                    if report.session_id else
                                    f", souhrn za období {report.period_text}."
                                    if report.is_period else ", z genetického vzorku."),
             url="#koncept"),
        step(2, "Souhrn", bool(report.summary) and not writing, summary_text,
             url="#souhrn", button="Zkontrolovat" if editable and not writing else ""),
        step(3, "Doporučení", not report.note_pending_review and not writing,
             ("Návrh od modelu čeká na vaši kontrolu – projděte, opravte a uložte."
              if report.note_pending_review else
              f"{recommendations} z pravidel"
              + (", komentář diagnostika doplněn." if report.custom_note
                 else "; vlastní doporučení napište do komentáře.")),
             url="#doporuceni", button="Projít" if editable and not writing else ""),
        step(4, "Kontrola", not checks and not writing,
             "; ".join(checks) + "." if checks else "Text sedí s výsledky a souhlasy.",
             url="#souhrn" if (number_problems or text_problems) else "#vydat",
             button="Opravit" if checks and editable else ""),
        step(5, "Vydání", released,
             (f"Vydáno {report.released_at:%d.%m.%Y}." if released and report.released_at else
              "Vydání je nevratné; oprava se dělá novou verzí."),
             url="#vydat",
             button="Vydat" if editable and not writing and not report.note_pending_review
             and not text_problems and not (clinician and not has_consent) else ""),
        step(6, "Předání", bool(deliveries),
             (f"Předáno: {', '.join(d.recipient for d in deliveries)}." if deliveries else
              "Zaznamenejte, komu a jak byla zpráva předána." if released and has_consent else
              "Jen se souhlasem s předáním zprávy poskytovateli zdravotních služeb."
              if released else "Po vydání."),
             url="#predani", optional=not (clinician and has_consent),
             button="Zaznamenat předání" if released and has_consent and not deliveries else ""),
    ]


def ai_steps(*, llm_enabled: bool, models_available, server_error: str, styles, examples,
             stats: dict, test_set, info: dict | None = None) -> list[dict]:
    custom = sum(1 for s in styles for part in s["parts"] if part["custom"])
    examples, test_set = list(examples), list(test_set)
    info = info or {}
    if info.get("blocked"):
        model_text = info["blocked"]
    elif not llm_enabled:
        model_text = "Jazykový model je vypnutý (LLM_ENABLED); souhrny píše šablona."
    elif server_error:
        model_text = server_error
    else:
        model_text = f"{len(models_available)} modelů na serveru."
        if info.get("remote"):
            model_text = (f"Cloudový model ({info.get('host')}), jen zkušební provoz se "
                          f"smyšlenými daty; " + model_text)
    return [
        step(1, "Model běží", llm_enabled and bool(models_available) and not info.get("blocked"),
             model_text, url="?tab=modely", button="Modely"),
        step(2, "Pokyny pro model", custom > 0,
             (f"{custom} vlastních pokynů; ostatní výchozí." if custom else
              "Tón, struktura a délka souhrnu pro každého čtenáře; zatím výchozí pokyny."),
             url="?tab=pokyny", button="Pokyny", optional=True),
        step(3, "Vzorové zprávy", bool(examples),
             (f"{len(examples)} vzorových zpráv." if examples else
              "U dobré vydané zprávy zvolte „Použít jako vzorovou“ – model dostane její styl."),
             url="?tab=pokyny", button="Vzorové zprávy", optional=True),
        step(4, "Hodnocení textů", stats.get("celkem", 0) > 0,
             (f"{stats.get('celkem', 0)} hodnocených zpráv." if stats.get("celkem") else
              "U textu od modelu označte, jak se povedl; podle toho se ladí pokyny."),
             url="?tab=kvalita", button="Kvalita textů"),
        step(5, "Zkušební sada", bool(test_set),
             (f"{len(test_set)} zpráv ve zkušební sadě." if test_set else
              "Vybrané vydané zprávy, na kterých se zkouší jiný model nebo nové pokyny."),
             url="?tab=sada", button="Zkušební sada", optional=True),
    ]
