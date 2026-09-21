"""
Šev pro AKESO.

Data tečou JEDNÍM směrem: FTVS vydá zprávu, AKESO si ji zařadí do
dokumentace. FTVS nikdy nedrží zdravotnická data – žádné diagnózy,
žádné nálezy MRI.

Tahle tabulka je jediná výjimka a záměrně minimální: neukládá NÁLEZ,
jen PROVOZNÍ DŮSLEDEK (je / není omezení zátěže). To stačí jako pojistka,
aby aplikace nedoporučila plyometrii sportovci s omezením, a přitom
o zdravotním stavu neví nic.
"""

from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel


class ExternalExam(TimeStampedModel):
    class ExamType(models.TextChoices):
        MEDICAL = "medical", "Lékařská prohlídka"
        IMAGING = "imaging", "Zobrazovací vyšetření"
        LAB = "lab", "Laboratorní vyšetření"
        OTHER = "other", "Jiné"

    class Restriction(models.TextChoices):
        NONE = "none", "Bez omezení"
        PARTIAL = "partial", "Částečné omezení"
        FULL = "full", "Plné omezení zátěže"
        UNKNOWN = "unknown", "Neuvedeno"

    subject = models.ForeignKey("subjects.Subject", verbose_name="sportovec",
                                on_delete=models.CASCADE, related_name="external_exams")
    exam_type = models.CharField("typ vyšetření", max_length=12, choices=ExamType.choices)
    date = models.DateField("datum")
    provider = models.CharField("poskytovatel", max_length=120, default="AKESO")
    external_reference = models.CharField("externí reference", max_length=120, blank=True,
                                          help_text="Identifikátor u poskytovatele. "
                                                    "Nikdy ne obsah nálezu.")
    load_restriction = models.CharField("omezení zátěže", max_length=10,
                                        choices=Restriction.choices,
                                        default=Restriction.UNKNOWN)
    restriction_valid_until = models.DateField("omezení platí do", null=True, blank=True)
    note = models.CharField("provozní poznámka", max_length=255, blank=True,
                            help_text="Bez diagnóz a bez popisu nálezu.")

    class Meta:
        verbose_name = "externí vyšetření"
        verbose_name_plural = "externí vyšetření"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.subject.code} – {self.get_exam_type_display()} {self.date:%d.%m.%Y}"

    @property
    def restriction_is_active(self) -> bool:
        if self.load_restriction in (self.Restriction.NONE, self.Restriction.UNKNOWN):
            return False
        if self.restriction_valid_until and self.restriction_valid_until < timezone.localdate():
            return False
        return True

    @classmethod
    def active_restriction_for(cls, subject):
        for exam in cls.objects.filter(subject=subject).order_by("-date"):
            if exam.restriction_is_active:
                return exam
        return None
