"""Kroky u sportovce: údaje a souhlasy, účet, měření, zpráva, předání nebo sdílení, vyšetření."""

from django.urls import reverse

from apps.core.steps import step

from .models import Consent, Sharing


def subject_steps(subject, *, sessions, accounts, sharings, may_edit: bool,
                  exams=()) -> list[dict]:
    """``sessions`` od nejnovějšího s anotací ``hodnot`` a načtenými zprávami."""
    from apps.external.models import ExternalExam
    from apps.reports.models import Report, ReportDelivery

    missing = []
    if not subject.sport_id:
        missing.append("sport")
    if subject.birth_date is None and not subject.birth_year:
        missing.append("datum narození")
    if not Consent.has(subject, Consent.Scope.TESTING):
        missing.append("souhlas s testováním")
    measured = [s for s in sessions if s.hodnot]
    planned = [s for s in sessions if not s.hodnot]
    last = measured[0] if measured else None
    reports = list(last.reports.all()) if last else []
    released = [r for r in reports if r.status == Report.Status.RELEASED]
    drafts = [r for r in reports if r.status == Report.Status.DRAFT]
    has_account = bool(accounts and (accounts["athlete"] or accounts["guardians"]))
    invited = bool(accounts and accounts["invitations"])
    sharing = any(sh.status == Sharing.Status.ACTIVE for sh in sharings)
    delivered = ReportDelivery.objects.filter(report__subject=subject).exists()
    exams = list(exams)
    restriction = ExternalExam.active_restriction_for(subject) if exams else None
    return [
        step(1, "Údaje a souhlasy", not missing,
             ("Chybí: " + ", ".join(missing) + "." if missing
              else "Sport, datum narození i souhlas s testováním jsou vyplněné."),
             url=reverse("subject_edit", args=[subject.pk]),
             button="Upravit údaje" if may_edit else ""),
        step(2, "Účet v portálu", has_account,
             ("Účet je založený." if has_account else
              "Pozvánka vystavena, čeká na založení účtu." if invited else
              "Sportovec nebo zákonný zástupce dostane pozvánku – odkaz nebo QR kód."),
             url="#ucet", button="Pozvánka" if may_edit and not has_account else "",
             optional=True),
        step(3, "Měření", bool(measured),
             (f"Poslední měření {last.date:%d.%m.%Y}."
              + (f" {len(planned)} naplánovaných dnů bez hodnot." if planned else "")
              if measured else
              f"Naplánováno na {planned[0].date:%d.%m.%Y}, hodnoty zatím chybí." if planned else
              "Zatím žádné měření – nový testovací den se předvyplní podle baterie sportu."),
             url=(reverse("session_detail", args=[planned[0].pk]) if planned
                  else reverse("session_create") + f"?sportovec={subject.pk}"),
             button="Zadat hodnoty" if planned else "Nové měření", count=len(planned) or None),
        step(4, "Zpráva", bool(released),
             (f"Vydáno: {', '.join(r.report_number for r in released)}." if released else
              f"{len(drafts)} konceptů čeká na vydání." if drafts else
              "Z posledního měření zatím není zpráva." if last else "Po měření."),
             url=(reverse("report_detail", args=[drafts[0].pk]) if drafts else
                  reverse("session_detail", args=[last.pk]) + "#nova-zprava" if last else "#mereni"),
             button="Ke konceptu" if drafts else ("Vytvořit zprávu" if last else "")),
        step(5, "Předání nebo sdílení", delivered or sharing,
             ("Zpráva předána." if delivered else "Sdílení s trenérem je aktivní." if sharing else
              "Předání lékaři se zaznamenává u vydané zprávy; sdílení s trenérem potvrzuje "
              "sportovec ve svém účtu."),
             url="#ucet", button="Sdílení s trenérem" if may_edit else "", optional=True),
        step(6, "Externí vyšetření", bool(exams),
             (f"Platné omezení zátěže ({restriction.get_load_restriction_display().lower()}) "
              f"z {restriction.date:%d.%m.%Y}"
              + (f", do {restriction.restriction_valid_until:%d.%m.%Y}."
                 if restriction.restriction_valid_until else ".")
              if restriction else
              f"{len(exams)} záznamů, bez platného omezení zátěže." if exams else
              "Lékařskou prohlídku nebo omezení zátěže zapište – zpráva pak nedoporučí "
              "zátěž, kterou lékař omezil. Bez diagnóz, jen provozní důsledek."),
             url=("#vysetreni" if exams else reverse("exam_new", args=[subject.pk])),
             button=("Vyšetření" if exams else "Zapsat vyšetření") if may_edit else "",
             optional=True),
    ]
