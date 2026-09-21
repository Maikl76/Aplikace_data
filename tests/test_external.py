"""Testy pojistky pro doporučení – omezení zátěže z AKESO."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.models import Organization
from apps.external.models import ExternalExam
from apps.subjects.models import Subject


@pytest.fixture
def sportovec(db):
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    return Subject.objects.create(organization=org, code="FTVS-0001")


def test_plne_omezeni_je_aktivni(sportovec):
    exam = ExternalExam.objects.create(
        subject=sportovec, exam_type=ExternalExam.ExamType.MEDICAL,
        date=timezone.localdate(), load_restriction=ExternalExam.Restriction.FULL,
    )
    assert exam.restriction_is_active is True
    assert ExternalExam.active_restriction_for(sportovec) == exam


def test_prosle_omezeni_uz_neblokuje(sportovec):
    ExternalExam.objects.create(
        subject=sportovec, exam_type=ExternalExam.ExamType.MEDICAL,
        date=timezone.localdate() - timedelta(days=90),
        load_restriction=ExternalExam.Restriction.FULL,
        restriction_valid_until=timezone.localdate() - timedelta(days=1),
    )
    assert ExternalExam.active_restriction_for(sportovec) is None


def test_bez_omezeni(sportovec):
    ExternalExam.objects.create(
        subject=sportovec, exam_type=ExternalExam.ExamType.MEDICAL,
        date=timezone.localdate(), load_restriction=ExternalExam.Restriction.NONE,
    )
    assert ExternalExam.active_restriction_for(sportovec) is None
