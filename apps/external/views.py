"""
Externí vyšetření na kartě sportovce místo administrace: lékařská
prohlídka či jiné vyšetření a jeho provozní důsledek – zda a dokdy platí
omezení zátěže. Aplikace neukládá nálezy ani diagnózy; z omezení plyne
jen to, že zpráva nevydá doporučení vyžadující zátěž.
"""

from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.audit import record
from apps.core.models import AuditLog
from apps.subjects.models import Subject

from .models import ExternalExam

FIELDS = ("exam_type", "date", "provider", "external_reference", "load_restriction",
          "restriction_valid_until", "note")


def _may_edit(user) -> bool:
    """Vyšetření zapisuje ten, kdo vidí identitu sportovce (laborant, správce)."""
    return user.is_superuser or user.sees_identity


def _denied(request, reason):
    return render(request, "core/odepreno.html", {"duvod": reason}, status=403)


def _date(text: str):
    """ISO datum z formuláře; prázdné → None; nesmysl → ValueError."""
    text = (text or "").strip()
    return date.fromisoformat(text) if text else None


def _form_data(exam, post=None) -> dict:
    if post is not None:
        return {f: post.get(f, "").strip() for f in FIELDS}
    if exam is None:
        return {"exam_type": ExternalExam.ExamType.MEDICAL, "date": timezone.localdate().isoformat(),
                "provider": "AKESO", "external_reference": "",
                "load_restriction": ExternalExam.Restriction.NONE, "restriction_valid_until": "",
                "note": ""}
    return {
        "exam_type": exam.exam_type, "date": exam.date.isoformat(), "provider": exam.provider,
        "external_reference": exam.external_reference, "load_restriction": exam.load_restriction,
        "restriction_valid_until": (exam.restriction_valid_until.isoformat()
                                    if exam.restriction_valid_until else ""),
        "note": exam.note,
    }


def _parse(data: dict) -> tuple[dict, list[str]]:
    errors = []
    exam_type = (data["exam_type"] if data["exam_type"] in ExternalExam.ExamType.values
                 else ExternalExam.ExamType.OTHER)
    restriction = (data["load_restriction"] if data["load_restriction"] in ExternalExam.Restriction.values
                   else ExternalExam.Restriction.UNKNOWN)
    today = timezone.localdate()
    try:
        when = _date(data["date"])
    except ValueError:
        when = None
        errors.append("Datum vyšetření není platné.")
    if when is None and not errors:
        errors.append("Doplňte datum vyšetření.")
    elif when is not None and when > today:
        errors.append("Datum vyšetření je v budoucnosti.")
    elif when is not None and when < date(1990, 1, 1):
        errors.append("Zkontrolujte rok vyšetření.")
    try:
        until = _date(data["restriction_valid_until"])
    except ValueError:
        until = None
        errors.append("Datum „omezení platí do“ není platné.")
    if until is not None and when is not None and until < when:
        errors.append("„Omezení platí do“ je dřív než datum vyšetření.")
    if restriction in (ExternalExam.Restriction.NONE, ExternalExam.Restriction.UNKNOWN):
        until = None
    provider = data["provider"][:120] or "AKESO"
    values = {"exam_type": exam_type, "date": when, "provider": provider,
              "external_reference": data["external_reference"][:120],
              "load_restriction": restriction, "restriction_valid_until": until,
              "note": data["note"][:255]}
    return values, errors


@login_required
def exam_edit(request, pk, epk=None):
    user = request.user
    if not _may_edit(user):
        return _denied(request, "Vyšetření zapisuje účet s přístupem k vyšetřením.")
    subject = get_object_or_404(Subject.objects.for_user(user), pk=pk)
    exam = get_object_or_404(subject.external_exams, pk=epk) if epk else None
    if request.method == "POST":
        data = _form_data(None, request.POST)
        values, errors = _parse(data)
        if not errors:
            created = exam is None
            if created:
                exam = ExternalExam(subject=subject)
            for name, value in values.items():
                setattr(exam, name, value)
            exam.save()
            record(request, AuditLog.Action.CREATE if created else AuditLog.Action.UPDATE, exam,
                   subject_code=subject.code, omezeni=exam.load_restriction)
            active = ExternalExam.active_restriction_for(subject)
            messages.success(request, f"Vyšetření {exam.get_exam_type_display().lower()} "
                                      f"z {exam.date:%d.%m.%Y} je uložené. "
                                      + ("Platí omezení zátěže – zpráva nevydá doporučení "
                                         "vyžadující zátěž." if active else
                                         "Omezení zátěže teď neplatí."))
            return redirect(reverse("subject_detail", args=[subject.pk]) + "#vysetreni")
        for error in errors:
            messages.error(request, error)
    else:
        data = _form_data(exam)
    return render(request, "external/exam_form.html", {
        "subject": subject, "exam": exam, "data": data,
        "display_name": subject.display_for(user),
        "types": ExternalExam.ExamType.choices, "restrictions": ExternalExam.Restriction.choices,
        "today": timezone.localdate().isoformat(),
        "restriction": ExternalExam.active_restriction_for(subject),
    })


@login_required
@require_POST
def exam_delete(request, pk, epk):
    user = request.user
    if not _may_edit(user):
        return _denied(request, "Vyšetření maže účet s přístupem k vyšetřením.")
    subject = get_object_or_404(Subject.objects.for_user(user), pk=pk)
    exam = get_object_or_404(subject.external_exams, pk=epk)
    record(request, AuditLog.Action.DELETE, exam, subject_code=subject.code)
    label = f"{exam.get_exam_type_display().lower()} z {exam.date:%d.%m.%Y}"
    exam.delete()
    messages.info(request, f"Vyšetření {label} je smazané.")
    return redirect(reverse("subject_detail", args=[subject.pk]) + "#vysetreni")
