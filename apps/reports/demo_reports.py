"""
Ukázkové zprávy od jazykového modelu pro veřejnou ukázku.

Na PythonAnywhere model neběží. Zprávu proto vygeneruje laboratorní
počítač (s LM Studiem) z VYMYŠLENÝCH ukázkových dat, vydá ji a příkaz
``ulozit_ukazku_zpravy`` uloží její snímek do repozitáře. Ukázka ho pak
příkazem ``nacist_ukazky_zprav`` načte jako vydanou zprávu – kolegové
vidí skutečný výstup modelu, i když na ukázce žádný model neběží.
"""

import json
from datetime import datetime
from pathlib import Path

from django.conf import settings

DIRECTORY = Path(settings.BASE_DIR) / "demo" / "ukazkove_zpravy"
PREFIX = "AI-"
FIELDS = ["report_number", "title", "summary", "summary_generated", "summary_edited",
          "custom_note", "note_ai_model", "llm_model", "generation_note", "disclaimer",
          "rules_version", "rendered_html"]


class DemoReportError(Exception):
    pass


def check(report):
    """Do veřejné ukázky smí jen vydaná zpráva sportovce bez jména (ukázková data)."""
    from apps.reports.models import Report

    if report.status != Report.Status.RELEASED or not report.rendered_html:
        raise DemoReportError(f"Zpráva {report.report_number} není vydaná. Ukázkou může být "
                              f"jen vydaná zpráva – ta se už nemění.")
    if hasattr(report.subject, "identity"):
        raise DemoReportError(
            f"Sportovec {report.subject.code} má uložené jméno – nejspíš jde o skutečného "
            f"člověka. Do veřejné ukázky patří jen zprávy z vymyšlených ukázkových dat "
            f"(sportovci FTVS-00xx bez jména).")
    if not report.llm_model or report.llm_model == "šablona":
        raise DemoReportError(f"Zprávu {report.report_number} sestavila šablona, ne jazykový "
                              f"model. Vytvořte zprávu se zapnutým LM Studiem.")


def export(report) -> Path:
    check(report)
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    data = {field: getattr(report, field) for field in FIELDS}
    data.update({"released_at": report.released_at.isoformat(),
                 "subject_code": report.subject.code,
                 "session_date": report.session.date.isoformat() if report.session else None})
    path = DIRECTORY / f"{report.report_number}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_all(organization) -> int:
    """Načte ukázkové zprávy ze složky; už načtené přeskočí. Vrací počet nových."""
    from apps.reports.models import Report
    from apps.subjects.models import Subject

    created = 0
    for path in sorted(DIRECTORY.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        number = PREFIX + data["report_number"]
        if Report.objects.filter(report_number=number).exists():
            continue
        # Vlastní „sportovec“ jen pro ukázku – kódy FTVS-00xx v ukázce patří
        # jiným vygenerovaným lidem a jejich karta by se zprávou nesouhlasila.
        subject, _ = Subject.objects.get_or_create(
            organization=organization, code=f"{data['subject_code']}-AI",
            defaults={"note": "Jen pro ukázkovou zprávu od jazykového modelu "
                              "(vymyšlená data z laboratorního počítače)."})
        report = Report(organization=organization, subject=subject, report_number=number,
                        status=Report.Status.RELEASED,
                        released_at=datetime.fromisoformat(data["released_at"]),
                        **{f: data[f] for f in FIELDS if f != "report_number"})
        report.generation_note = (
            f"Ukázka: text napsal model {data['llm_model']} na laboratorním počítači "
            f"z vymyšlených dat (měření {data.get('session_date') or '—'}). "
            + (data.get("generation_note") or "")).strip()
        report.save()
        created += 1
    return created
