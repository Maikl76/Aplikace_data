"""Kroky v portálu: sportovec (účet, souhlasy, sdílení, dotazník, výsledky) a trenér."""

from django.urls import reverse

from apps.core.steps import step


def athlete_steps(subject, *, pending, today_session, reports, sessions) -> list[dict]:
    from apps.measurements.models import QuestionnaireResponse
    from apps.measurements.questionnaires import RPE
    from apps.subjects.models import Consent, Sharing

    consent = Consent.has(subject, Consent.Scope.TESTING)
    sharing_active = subject.sharings.filter(status=Sharing.Status.ACTIVE).exists()
    pending, reports = list(pending), list(reports)
    rpe_done = bool(today_session) and QuestionnaireResponse.objects.filter(
        session=today_session, questionnaire__code=RPE,
        source=QuestionnaireResponse.Source.SUBJECT).exists()
    measured = [s for s in sessions if s.hodnot]
    consents_url = reverse("portal_consents", args=[subject.pk])
    return [
        step(1, "Účet", True, "Jste přihlášeni a sportovec je připojený k vašemu účtu."),
        step(2, "Souhlasy", consent,
             ("Souhlas s testováním platí." if consent else
              "Bez souhlasu s testováním laboratoř výsledky nezpracuje – zkontrolujte souhlasy."),
             url=consents_url, button="Souhlasy"),
        step(3, "Sdílení s trenérem", not pending,
             (f"{len(pending)} trenérů žádá o přístup k vašim výsledkům – rozhodněte."
              if pending else "Sdílení s trenérem je aktivní." if sharing_active else
              "Nikdo nežádá; trenéra si můžete vybrat sami v souhlasech."),
             url=consents_url + "#sdileni", button="Rozhodnout" if pending else "Sdílení",
             count=len(pending) or None, optional=not pending),
        step(4, "Dotazník", not today_session or rpe_done,
             ("Dnes máte měření – po testu vyplňte, jak náročné vám přišlo."
              if today_session and not rpe_done else
              "Dnešní dotazník je vyplněný." if today_session else
              "Nic k vyplnění; dotazník se objeví v den měření."),
             url=reverse("portal_questionnaire", args=[subject.pk]) if today_session else "",
             button="Vyplnit RPE" if today_session and not rpe_done else "",
             optional=not today_session),
        step(5, "Výsledky", bool(measured) and bool(reports),
             (f"{len(measured)} měření, {len(reports)} vydaných zpráv pro vás." if measured and reports
              else f"{len(measured)} měření; zpráva pro vás zatím nebyla vydána." if measured
              else "Po prvním měření tu uvidíte klíčové ukazatele a vývoj."),
             url="#zpravy" if reports else "#mereni", button="Zprávy" if reports else ""),
    ]


def coach_steps(subjects, pending, tables) -> list[dict]:
    subjects, pending = list(subjects), list(pending)
    return [
        step(1, "Žádost o sdílení", bool(subjects) or bool(pending),
             (f"{len(subjects)} sportovců sdílí, {len(pending)} žádostí čeká."
              if subjects or pending else
              "Požádejte kódem sportovce – má ho na QR kartě a ve svém účtu."),
             url="#zadost", button="Požádat"),
        step(2, "Potvrzení sportovcem", not pending,
             (f"{len(pending)} žádostí čeká na potvrzení ve sportovcově účtu."
              if pending else "Žádná žádost nečeká; sportovec může sdílení kdykoli odvolat."),
             count=len(pending) or None, optional=not pending),
        step(3, "Přehled týmu", bool(tables),
             ("Klíčové ukazatele baterie, poslední hodnota a změna proti minule."
              if tables else "Objeví se, až někdo sdílení potvrdí a má měření."),
             url="#prehled", button="Přehled" if tables else ""),
    ]
