"""
Denní postup laboratoře pro Přehled: kdo dnes přijde, hodnoty, kontrola,
zprávy, předání. Počítá se z dat dne – nic se neodškrtává ručně.
"""

from django.urls import reverse
from django.utils import timezone

from .steps import step

MAX_SESSIONS_FOR_CHECK = 40  # nad tolik dnů se nestabilní pokusy nepočítají (drahé)


def daily_steps(user, today=None) -> list[dict]:
    from apps.measurements.models import Measurement, TestSession
    from apps.measurements.planning import DERIVED_PROTOCOLS
    from apps.measurements.questionnaires import RPE
    from apps.reports.models import Audience, Report
    from apps.reports.results import protocol_results
    from apps.subjects.models import Consent

    today = today or timezone.localdate()
    sessions = list(TestSession.objects.for_user(user).filter(date=today)
                    .select_related("subject")
                    .prefetch_related("protocol_runs__protocol", "protocol_runs__trials",
                                      "responses__questionnaire"))
    runs = [(s, r) for s in sessions for r in s.protocol_runs.all()
            if r.protocol.code not in DERIVED_PROTOCOLS]
    without_values = [(s, r) for s, r in runs if not r.trials.all()]
    measured = [(s, r) for s, r in runs if r.trials.all()]
    rpe_missing = [(s, r) for s, r in measured if r.protocol.rpe_after and not any(
        resp.protocol_run_id == r.pk and resp.questionnaire.code == RPE
        for resp in s.responses.all())]
    suspicious = (Measurement.objects.filter(trial__protocol_run__session__in=sessions)
                  .exclude(quality=Measurement.Quality.OK).count()) if sessions else 0
    unstable = 0
    issue_session = None
    if sessions and len(sessions) <= MAX_SESSIONS_FOR_CHECK:
        for s in sessions:
            rows = [row for block in protocol_results(s) for row in block["unstable"]]
            if rows:
                unstable += len(rows)
                issue_session = issue_session or s
    if issue_session is None and rpe_missing:
        issue_session = rpe_missing[0][0]
    if issue_session is None and suspicious:
        issue_session = sessions[0]

    reports = Report.objects.for_user(user)
    drafts = list(reports.filter(status=Report.Status.DRAFT).order_by("-created_at"))
    reported = set(reports.filter(session__in=sessions).values_list("session_id", flat=True))
    unreported = [s for s in sessions if s.pk not in reported
                  and any(r.trials.all() for r in s.protocol_runs.all())]
    undelivered = [r for r in reports.filter(status=Report.Status.RELEASED,
                                             audience=Audience.CLINICIAN,
                                             deliveries__isnull=True).select_related("subject")
                   if Consent.has(r.subject, Consent.Scope.REPORT_HANDOVER)]

    checks = []
    if unstable:
        checks.append(f"{unstable}× nestabilní pokusy")
    if suspicious:
        checks.append(f"{suspicious}× hodnota mimo věrohodný rozsah")
    if rpe_missing:
        checks.append(f"{len(rpe_missing)}× chybí RPE po zátěžovém testu")
    report_pending = len(drafts) + len(unreported)
    from apps.subjects import retest

    due = retest.due_plans(user, today=today)
    overdue = [p for p in due if p.status == "overdue"]
    return [
        step(1, "Kdo dnes přijde", bool(sessions),
             (f"{len(sessions)} testovacích dnů." if sessions else
              "Dnes není založený žádný testovací den. Založte ho ze skupiny, nebo vznikne sám "
              "z exportu přístroje."),
             url=reverse("today"), button="Dnešní testování"),
        step(2, "Hodnoty", not without_values,
             (f"{len(without_values)} testů čeká na hodnoty – zadejte je u přístroje, nebo "
              "nahrajte export." if without_values else "Všechny dnešní testy mají hodnoty."),
             url=(reverse("session_detail", args=[without_values[0][0].pk]) if without_values
                  else reverse("import_list")),
             button="Zadat nebo nahrát", count=len(without_values) or None),
        step(3, "Kontrola", not checks,
             ("; ".join(checks) + ". Pokud je sportovec ještě v laboratoři, test zopakujte."
              if checks else "Nic k zopakování ani k doplnění."),
             url=reverse("session_detail", args=[issue_session.pk]) if issue_session
             else reverse("session_list"),
             button="Zkontrolovat", count=(unstable + suspicious + len(rpe_missing)) or None),
        step(4, "Zprávy", not report_pending,
             (" ".join(filter(None, [
                 f"{len(unreported)} dnešních dnů bez zprávy." if unreported else "",
                 f"{len(drafts)} konceptů ke kontrole a vydání." if drafts else ""]))
              if report_pending else "Žádná zpráva nečeká na vydání."),
             url=(reverse("report_detail", args=[drafts[0].pk]) if drafts
                  else reverse("session_detail", args=[unreported[0].pk]) if unreported
                  else reverse("report_list")),
             button="Ke zprávám", count=report_pending or None),
        step(5, "Předání", not undelivered,
             (f"{len(undelivered)} vydaných zpráv pro lékaře se souhlasem čeká na záznam "
              "o předání." if undelivered else "Žádná zpráva nečeká na předání."),
             url=(reverse("report_detail", args=[undelivered[0].pk]) if undelivered
                  else reverse("report_list")),
             button="Zaznamenat předání", count=len(undelivered) or None),
        step(6, "Na řadě", not due,
             (f"{len(due)} sportovců má termín dalšího měření do 30 dnů"
              + (f", {len(overdue)} už prošel" if overdue else "") + "." if due
              else "Nikdo nemá termín dalšího měření do 30 dnů."),
             url=reverse("subject_list") + "?na_rade=1", button="Kdo je na řadě",
             optional=True, count=len(due) or None),
    ]
