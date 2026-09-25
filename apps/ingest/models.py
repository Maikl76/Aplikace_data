"""
Import dat z přístrojů.

Pravidlo: import nikdy nezapisuje rovnou do provozních tabulek. Nejdřív
staging s náhledem ("našel jsem 12 sportovců, 3 neznámé, 5 hodnot mimo
rozsah"), potvrzení člověkem, teprve pak commit.

Adaptér na formát přístroje je jedna malá třída v adapters/, testovatelná
na uložených vzorových souborech.
"""

from django.conf import settings
from django.db import models

from apps.core.models import OrgScopedModel


class ImportBatch(OrgScopedModel):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Nahráno"
        PARSED = "parsed", "Zpracováno, čeká na kontrolu"
        COMMITTED = "committed", "Uloženo"
        FAILED = "failed", "Chyba"
        CANCELLED = "cancelled", "Zrušeno"

    raw_file = models.ForeignKey("measurements.RawFile", verbose_name="zdrojový soubor",
                                 on_delete=models.PROTECT, related_name="import_batches")
    adapter = models.CharField("adaptér", max_length=64)
    protocol = models.ForeignKey("catalog.Protocol", verbose_name="výchozí protokol",
                                 on_delete=models.PROTECT, related_name="import_batches",
                                 null=True, blank=True,
                                 help_text="Použije se u řádků, které protokol neurčují samy.")
    status = models.CharField("stav", max_length=12, choices=Status.choices,
                              default=Status.UPLOADED)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="nahrál",
                                    on_delete=models.PROTECT, related_name="import_batches")
    summary = models.JSONField("souhrn kontroly", default=dict, blank=True)
    error = models.TextField("chyba", blank=True)

    class Meta:
        verbose_name = "import"
        verbose_name_plural = "importy"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.raw_file.original_name} ({self.get_status_display()})"

    @property
    def adapter_label(self) -> str:
        from .adapters import registry

        adapter = registry.get(self.adapter)
        return adapter.label if adapter else self.adapter

    def purge_staging(self):
        """
        Po uložení se staging maže. Obsahuje ``subject_hint`` – identifikaci
        tak, jak stála ve zdrojovém souboru, tedy u starých Excelů jméno.
        V provozních tabulkách už žádné jméno není, tak ať nezůstává ani tady.
        """
        self.staged.all().delete()


class StagedMeasurement(models.Model):
    """Rozparsovaná hodnota čekající na potvrzení."""

    class Flag(models.TextChoices):
        OK = "ok", "V pořádku"
        UNKNOWN_SUBJECT = "unknown_subject", "Neznámý sportovec"
        UNKNOWN_METRIC = "unknown_metric", "Neznámá metrika"
        OUT_OF_RANGE = "range", "Mimo věrohodný rozsah"
        DUPLICATE = "duplicate", "Test už je v aplikaci"

    batch = models.ForeignKey(ImportBatch, verbose_name="import", on_delete=models.CASCADE,
                              related_name="staged")
    row_number = models.PositiveIntegerField("řádek zdroje", default=0)
    subject_hint = models.CharField("identifikace ze souboru", max_length=200, blank=True,
                                    help_text="Jen pro náhled. Po uložení se maže.")
    subject_key = models.CharField("klíč sportovce", max_length=64, blank=True, db_index=True,
                                   help_text="Hash identifikace ze zdroje – páruje opakované "
                                             "importy téže osoby bez ukládání jména.")
    subject = models.ForeignKey("subjects.Subject", verbose_name="sportovec",
                                on_delete=models.SET_NULL, null=True, blank=True)
    protocol_code = models.CharField("kód protokolu", max_length=64, blank=True)
    protocol = models.ForeignKey("catalog.Protocol", verbose_name="protokol",
                                 on_delete=models.SET_NULL, null=True, blank=True)
    session_date = models.DateField("datum měření", null=True, blank=True)
    metric_code = models.CharField("kód metriky", max_length=64, blank=True)
    metric = models.ForeignKey("catalog.MetricDef", verbose_name="metrika",
                               on_delete=models.SET_NULL, null=True, blank=True)
    run_key = models.CharField("identifikace testu ve zdroji", max_length=200, blank=True)
    run_started_at = models.DateTimeField("čas testu", null=True, blank=True)
    trial_number = models.PositiveSmallIntegerField("pokus", default=1)
    side = models.CharField("strana", max_length=1, blank=True)
    mode = models.CharField("režim", max_length=3, blank=True)
    speed = models.FloatField("rychlost", null=True, blank=True)
    segment = models.CharField("segment", max_length=32, blank=True)
    value = models.FloatField("hodnota", null=True, blank=True)
    flag = models.CharField("příznak", max_length=20, choices=Flag.choices, default=Flag.OK)
    message = models.CharField("zpráva", max_length=255, blank=True)

    class Meta:
        verbose_name = "hodnota ke kontrole"
        verbose_name_plural = "hodnoty ke kontrole"
        ordering = ["row_number"]

    def __str__(self):
        return f"{self.subject_hint} / {self.metric_code} = {self.value}"
