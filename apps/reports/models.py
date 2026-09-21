"""
Zprávy a jejich předání.

Vydaná zpráva je nevratná: jakmile ji převezme poskytovatel zdravotních
služeb, stává se součástí jeho dokumentace a drží se tam podle jeho
pravidel. Oprava se proto řeší vydáním NOVÉ verze, nikdy přepsáním.

Zpráva obsahuje výhradně výsledky funkčního testování a končí větou,
která přenáší posouzení kontraindikací na ošetřujícího lékaře.
"""

import hashlib
import json

from django.conf import settings
from django.db import models

from apps.core.models import OrgScopedModel, TimeStampedModel

DISCLAIMER = (
    "Uvedená doporučení vycházejí výhradně z výsledků funkčního testování. "
    "Jejich zařazení je podmíněno posouzením zdravotního stavu a případných "
    "kontraindikací ošetřujícím lékařem."
)


class Report(OrgScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Koncept"
        RELEASED = "released", "Vydáno"
        SUPERSEDED = "superseded", "Nahrazeno novější verzí"

    subject = models.ForeignKey("subjects.Subject", verbose_name="sportovec",
                                on_delete=models.PROTECT, related_name="reports")
    session = models.ForeignKey("measurements.TestSession", verbose_name="testovací den",
                                on_delete=models.PROTECT, related_name="reports",
                                null=True, blank=True)
    report_number = models.CharField("číslo zprávy", max_length=40, unique=True)
    version = models.PositiveSmallIntegerField("verze", default=1)
    supersedes = models.ForeignKey("self", verbose_name="nahrazuje", on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="superseded_by")

    status = models.CharField("stav", max_length=12, choices=Status.choices,
                              default=Status.DRAFT)
    title = models.CharField("název", max_length=200, default="Zpráva z funkčního testování")
    summary = models.TextField("souhrn", blank=True)
    custom_note = models.TextField("vlastní komentář", blank=True)
    disclaimer = models.TextField("doložka", default=DISCLAIMER)

    # Otisk pro rekonstrukci: proč zpráva říká to, co říká.
    rules_version = models.CharField("verze sady pravidel", max_length=40, blank=True)
    llm_model = models.CharField("použitý jazykový model", max_length=80, blank=True)
    input_fingerprint = models.CharField("otisk vstupů", max_length=64, blank=True)

    pdf = models.FileField("PDF", upload_to="reports/%Y/%m/", blank=True)
    data_json = models.FileField("strojově čitelná příloha", upload_to="reports/%Y/%m/",
                                 blank=True)

    released_at = models.DateTimeField("vydáno", null=True, blank=True)
    released_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="vydal",
                                    on_delete=models.PROTECT, null=True, blank=True,
                                    related_name="released_reports")

    class Meta:
        verbose_name = "zpráva"
        verbose_name_plural = "zprávy"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.report_number} ({self.subject.code})"

    @property
    def is_editable(self) -> bool:
        return self.status == self.Status.DRAFT

    def compute_fingerprint(self, inputs: dict) -> str:
        """Otisk vstupů, ze kterých zpráva vznikla."""
        payload = json.dumps(inputs, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()


class ReportDelivery(TimeStampedModel):
    """
    Záznam o předání. Vydání je vědomý krok s potvrzením, ne tlačítko
    "stáhnout PDF".
    """

    class Channel(models.TextChoices):
        SECURE_LINK = "link", "Zabezpečený odkaz"
        HANDOVER = "handover", "Osobní předání"
        API = "api", "Rozhraní"

    report = models.ForeignKey(Report, verbose_name="zpráva", on_delete=models.PROTECT,
                               related_name="deliveries")
    recipient = models.CharField("příjemce", max_length=200)
    channel = models.CharField("kanál", max_length=12, choices=Channel.choices,
                               default=Channel.SECURE_LINK)
    delivered_at = models.DateTimeField("předáno")
    delivered_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="předal",
                                     on_delete=models.PROTECT, related_name="deliveries")
    consent_verified = models.BooleanField("souhlas s předáním ověřen", default=False)
    acknowledged_at = models.DateTimeField("potvrzeno příjemcem", null=True, blank=True)
    note = models.CharField("poznámka", max_length=255, blank=True)

    class Meta:
        verbose_name = "předání zprávy"
        verbose_name_plural = "předání zpráv"
        ordering = ["-delivered_at"]

    def __str__(self):
        return f"{self.report.report_number} -> {self.recipient}"
