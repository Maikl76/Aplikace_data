"""
Jádro: organizace, uživatelé, role, audit a základní třídy modelů.

Multi-tenancy: každý model s daty o lidech nese ``organization`` a dotazy
na něj chodí přes ``OrgScopedManager``. Dnes je organizace jedna (FTVS),
ale doplnit ten sloupec zpětně do hotové aplikace znamená projít každý
dotaz v kódu – proto je tady od začátku.
"""

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("vytvořeno", auto_now_add=True)
    updated_at = models.DateTimeField("změněno", auto_now=True)

    class Meta:
        abstract = True


class Organization(TimeStampedModel):
    """Pracoviště. Katalogové záznamy s organization=NULL jsou sdílené."""

    name = models.CharField("název", max_length=200)
    short_name = models.SlugField("zkratka", max_length=32, unique=True)
    is_active = models.BooleanField("aktivní", default=True)

    class Meta:
        verbose_name = "organizace"
        verbose_name_plural = "organizace"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Role(models.TextChoices):
    ADMIN = "admin", "Správce"
    LAB = "lab", "Laborant / diagnostik"
    RESEARCHER = "researcher", "Výzkumník (anonymizovaný pohled)"
    COACH = "coach", "Trenér (vlastní tým)"
    ATHLETE = "athlete", "Sportovec (vlastní výsledky)"


class User(AbstractUser):
    organization = models.ForeignKey(
        Organization, verbose_name="organizace", on_delete=models.PROTECT,
        null=True, blank=True, related_name="users",
    )
    role = models.CharField("role", max_length=20, choices=Role.choices, default=Role.LAB)

    class Meta:
        verbose_name = "uživatel"
        verbose_name_plural = "uživatelé"

    @property
    def sees_identity(self) -> bool:
        """Jen tyto role smějí vidět jméno sportovce, ne jen pseudonym."""
        return self.role in {Role.ADMIN, Role.LAB}


class OrgScopedQuerySet(models.QuerySet):
    def for_user(self, user):
        """Jediné místo, kde se rozhoduje, na co uživatel vidí."""
        if user.is_superuser:
            return self
        if user.organization_id is None:
            return self.none()
        return self.filter(organization_id=user.organization_id)


class OrgScopedManager(models.Manager.from_queryset(OrgScopedQuerySet)):
    pass


class OrgScopedModel(TimeStampedModel):
    """Základ pro všechno, co obsahuje data o konkrétních lidech."""

    organization = models.ForeignKey(
        Organization, verbose_name="organizace", on_delete=models.PROTECT,
        related_name="%(class)s_set",
    )

    objects = OrgScopedManager()

    class Meta:
        abstract = True


class AuditLog(models.Model):
    """
    Kdo se kdy na koho díval a co změnil. U zdravotních dat není volitelný.
    Zapisuje se přes apps.core.audit.record().
    """

    class Action(models.TextChoices):
        VIEW = "view", "Zobrazení"
        CREATE = "create", "Vytvoření"
        UPDATE = "update", "Změna"
        DELETE = "delete", "Smazání"
        EXPORT = "export", "Export / stažení"
        RELEASE = "release", "Vydání zprávy"

    timestamp = models.DateTimeField("kdy", auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="kdo", on_delete=models.PROTECT, null=True,
    )
    action = models.CharField("akce", max_length=20, choices=Action.choices)
    object_type = models.CharField("typ objektu", max_length=100)
    object_id = models.CharField("id objektu", max_length=64)
    subject_code = models.CharField("kód sportovce", max_length=32, blank=True, db_index=True)
    detail = models.JSONField("podrobnosti", default=dict, blank=True)
    ip_address = models.GenericIPAddressField("IP adresa", null=True, blank=True)

    class Meta:
        verbose_name = "záznam auditu"
        verbose_name_plural = "audit"
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M} {self.user} {self.action} {self.object_type}"
