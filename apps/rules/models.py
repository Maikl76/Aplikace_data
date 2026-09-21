"""
Pravidla jako data, ne jako kód.

Třívrstvý model doporučení:
  1. Pravidlo (deterministické)  -> vzniká nález a VŠECHNA čísla
  2. Evidence (apps.evidence)    -> k nálezu se připojí citace
  3. Jazykový model              -> text, který nesmí počítat ani citovat nic navíc

Díky tomu je každé tvrzení ve zprávě dohledatelné a obhajitelné.
"""

from django.db import models

from apps.catalog.models import CatalogModel
from apps.core.models import TimeStampedModel


class Severity(models.TextChoices):
    INFO = "info", "Informativní"
    LOW = "low", "Nízká"
    MEDIUM = "medium", "Střední"
    HIGH = "high", "Vysoká"


class Rule(CatalogModel):
    """
    Podmínka se vyhodnocuje nad metrikami měření. Formát podmínky je
    záměrně omezený (ne volný Python) – pravidlo musí být čitelné,
    auditovatelné a musí ho umět zkontrolovat i nekodér.

    Příklad condition:
        {"metric": "ir_er_ratio", "op": "<", "value": 1.0, "speed": 210}

    Příklad contraindication (bezpečnostní pojistka):
        {"external_exam": "load_restriction", "state": "none"}
    """

    code = models.SlugField("kód", max_length=64)
    name = models.CharField("název", max_length=200)
    version = models.PositiveSmallIntegerField("verze", default=1)
    applies_to_sport = models.ForeignKey("subjects.Sport", verbose_name="platí pro sport",
                                         on_delete=models.CASCADE, null=True, blank=True,
                                         help_text="Prázdné = napříč sporty.")
    condition = models.JSONField("podmínka", default=dict)
    contraindication = models.JSONField("kontraindikace", default=dict, blank=True,
                                        help_text="Podmínka, která pravidlo potlačí.")
    severity = models.CharField("závažnost", max_length=10, choices=Severity.choices,
                                default=Severity.MEDIUM)
    finding_template = models.TextField("text nálezu",
                                        help_text="Šablona, např. 'Poměr IR/ER {value:.2f} "
                                                  "je pod doporučenou hodnotou {threshold:.2f}.'")
    recommendation_template = models.TextField("text doporučení", blank=True)
    is_active = models.BooleanField("aktivní", default=True)

    class Meta:
        verbose_name = "pravidlo"
        verbose_name_plural = "pravidla"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "code", "version"],
                                    name="uniq_rule_code_version"),
        ]

    def __str__(self):
        return f"{self.name} (v{self.version})"


class RuleArticle(models.Model):
    """Evidence visí na pravidle, ne na volném textu."""

    rule = models.ForeignKey(Rule, verbose_name="pravidlo", on_delete=models.CASCADE,
                             related_name="rule_articles")
    article = models.ForeignKey("evidence.Article", verbose_name="článek",
                                on_delete=models.PROTECT, related_name="rule_articles")
    relevance_note = models.CharField("proč je relevantní", max_length=500, blank=True)

    class Meta:
        verbose_name = "evidence pravidla"
        verbose_name_plural = "evidence pravidel"
        constraints = [
            models.UniqueConstraint(fields=["rule", "article"], name="uniq_rule_article"),
        ]

    def __str__(self):
        return f"{self.rule.code} <- {self.article}"


class Finding(TimeStampedModel):
    """Konkrétní nález pro konkrétní měření. Tady vznikají čísla do zprávy."""

    session = models.ForeignKey("measurements.TestSession", verbose_name="testovací den",
                                on_delete=models.CASCADE, related_name="findings")
    rule = models.ForeignKey(Rule, verbose_name="pravidlo", on_delete=models.PROTECT,
                             related_name="findings")
    rule_version = models.PositiveSmallIntegerField("verze pravidla")
    severity = models.CharField("závažnost", max_length=10, choices=Severity.choices)
    values = models.JSONField("hodnoty", default=dict,
                              help_text="Čísla, která pravidlo použilo. Text zprávy "
                                        "nesmí obsahovat žádná jiná.")
    text = models.TextField("text nálezu")
    suppressed = models.BooleanField("potlačeno kontraindikací", default=False)
    suppressed_reason = models.CharField("důvod potlačení", max_length=255, blank=True)

    class Meta:
        verbose_name = "nález"
        verbose_name_plural = "nálezy"
        ordering = ["-severity", "rule__code"]

    def __str__(self):
        return f"{self.session.subject.code}: {self.rule.code}"
