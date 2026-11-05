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
                                    if report.session_id else ", z genetického vzorku."),
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
