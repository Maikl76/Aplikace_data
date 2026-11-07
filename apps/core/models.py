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
    reminders_checked_on = models.DateField(
        "připomínky měření naposledy zkontrolovány", null=True, blank=True,
        help_text="Přehled je kontroluje jednou denně sám.")
    auto_draft = models.BooleanField(
        "koncept zprávy po dokončení dne", default=True,
        help_text="Jakmile mají všechny testy dne hodnoty, vznikne koncept zprávy ke kontrole.")
    import_checked_at = models.DateTimeField(
        "sledovaná složka naposledy zkontrolována", null=True, blank=True,
        help_text="Zapisuje hlídač složky (hlidat_slozku); podle toho se pozná, že běží.")

    # Interní referenční hodnoty: z vlastních měření pracoviště, jen pro
    # orientaci laboratoře (necitovatelné, nikdy do zprávy ani do portálu).
    class ReferenceSource(models.TextChoices):
        RESEARCH = "vyzkum", "jen sportovci s platným souhlasem s výzkumem"
        ALL = "vsichni", "všichni aktivní sportovci pracoviště"

    reference_enabled = models.BooleanField(
        "interní referenční hodnoty", default=True,
        help_text="Šedé pásmo P25–P75 z vlastních měření v grafech a v týmovém přehledu.")
    reference_min_subjects = models.PositiveSmallIntegerField(
        "nejméně sportovců ve skupině", default=8,
        help_text="Pod tento počet se skupina (sport, pohlaví, věk) nepoužije.")
    reference_source = models.CharField(
        "z koho se reference počítají", max_length=10, choices=ReferenceSource.choices,
        default=ReferenceSource.RESEARCH)

    # Denní údržba (záloha, úklid, připomínky, týdenní stav správci) – co
    # a kdy naposledy proběhlo; ukazuje to Nastavení → Provoz a zálohy.
    maintenance_at = models.DateTimeField("denní údržba naposledy", null=True, blank=True)
    maintenance_log = models.JSONField("výsledek poslední údržby", default=dict, blank=True)
    backup_at = models.DateTimeField("záloha naposledy", null=True, blank=True)
    backup_note = models.CharField("záloha – kam, nebo proč ne", max_length=300, blank=True)
    status_mailed_on = models.DateField("stav správci naposledy odeslán", null=True, blank=True)

    class Meta:
        verbose_name = "organizace"
        verbose_name_plural = "organizace"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Role(models.TextChoices):
    ADMIN = "admin", "Správce"
    LAB = "lab", "Laborant / diagnostik"
    METHODOLOGIST = "metodik", "Metodik (sporty a metodiky měření)"
    RESEARCHER = "researcher", "Výzkumník (anonymizovaný pohled)"
    COACH = "coach", "Trenér (vlastní tým)"
    ATHLETE = "athlete", "Sportovec / zákonný zástupce (vlastní výsledky)"


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
        """Smí účet vidět jméno sportovce, ne jen pseudonym? Rozhoduje přístup účtu (access.py)."""
        from . import access

        return access.can(self, "names")

    def save(self, *args, **kwargs):
        # Účet bez pracoviště by v aplikaci neviděl nic a založení sportu nebo
        # sportovce by skončilo chybou. Pole je v administraci snadné přehlédnout
        # (a createsuperuser se na něj neptá) – když je pracoviště jediné,
        # patří k němu každý účet.
        if self.organization_id is None and (org := default_organization()) is not None:
            self.organization = org
            if (fields := kwargs.get("update_fields")) is not None:
                kwargs["update_fields"] = {*fields, "organization"}
        super().save(*args, **kwargs)


def default_organization():
    """Jediné pracoviště v instanci (laboratoř FTVS); když je jich víc nebo žádné, None."""
    found = list(Organization.objects.order_by("pk")[:2])
    return found[0] if len(found) == 1 else None


class OrgScopedQuerySet(models.QuerySet):
    def for_user(self, user):
        """
        Jediné místo, kde se rozhoduje, na co uživatel vidí.

        Laboratoř vidí své pracoviště. Sportovec a trenér jen sportovce,
        na které mají nárok (apps.subjects.access) – u tabulek bez vazby
        na sportovce nic.
        """
        if user.is_superuser:
            return self
        if user.organization_id is None:
            return self.none()
        qs = self.filter(organization_id=user.organization_id)
        if getattr(user, "role", "") in (Role.ATHLETE, Role.COACH):
            from apps.subjects.access import subject_ids_for

            ids = subject_ids_for(user)
            if self.model._meta.model_name == "subject":
                return qs.filter(pk__in=ids)
            if any(f.name == "subject" for f in self.model._meta.fields):
                return qs.filter(subject_id__in=ids)
            return qs.none()
        # Laboratoř: rozsah dat podle přístupu účtu (sporty, týmy) – access.scope_queryset.
        from . import access

        return access.scope_queryset(self.model, qs, user)


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


class Access(TimeStampedModel):
    """
    Přístup účtu kolegy: na co vidí (rozsah dat) a co smí (oprávnění).

    Role je jen šablona výchozích hodnot (access.PRESETS); správce položky
    upraví u konkrétního účtu v Kolegové → Přístup. Správce má vždy vše,
    portálové role (sportovec, trenér) záznam nemají – jejich rozsah určuje
    účet a sdílení (apps.subjects.access). O všem rozhoduje apps/core/access.py.
    """

    user = models.OneToOneField(settings.AUTH_USER_MODEL, verbose_name="účet",
                                on_delete=models.CASCADE, related_name="access")
    configured = models.BooleanField(
        "přístup potvrdil správce", default=False,
        help_text="Dokud ne, platí výchozí šablona podle role; Stav pracoviště na to upozorní.")
    # rozsah dat
    all_sports = models.BooleanField("všechny sporty", default=True)
    sports = models.ManyToManyField("subjects.Sport", verbose_name="sporty", blank=True,
                                    related_name="+")
    teams = models.ManyToManyField("subjects.Team", verbose_name="jen týmy", blank=True,
                                   related_name="+",
                                   help_text="Užší než sporty; prázdné = všechny týmy sportů.")
    all_families = models.BooleanField("všechny metodiky měření", default=True)
    families = models.JSONField("metodiky měření (rodiny testů)", default=list, blank=True)
    names = models.BooleanField("jména sportovců", default=True)
    genetics = models.BooleanField("genetika", default=False)
    exams = models.BooleanField("externí vyšetření", default=True)
    bookings = models.BooleanField("objednávky", default=True)
    # oprávnění
    measure = models.BooleanField("zadávat a importovat měření", default=True)
    subjects_edit = models.BooleanField("sportovci, souhlasy, účty a sdílení", default=True)
    reports_draft = models.BooleanField("koncepty zpráv", default=True)
    reports_release = models.BooleanField("vydávat a předávat zprávy", default=False)
    settings_sports = models.BooleanField("sporty, baterie, normy, pravidla, dotazníky",
                                          default=False)
    settings_tests = models.BooleanField("testy, ukazatele, MDC, přístroje", default=False)
    exports = models.BooleanField("exporty dat", default=False)
    articles = models.BooleanField("úpravy knihovny článků", default=False)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="naposledy nastavil",
                                   on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")

    class Meta:
        verbose_name = "přístup účtu"
        verbose_name_plural = "přístupy účtů"

    def __str__(self):
        return f"přístup {self.user}"


class Remark(TimeStampedModel):
    """
    Připomínka kolegy k postupu. Vzniká tam, kde ji napadne (tlačítko u kroků
    nebo dole v menu), správce ji má v seznamu a vyřídí ji s odpovědí.
    Ve zkušebním provozu je to hlavní kanál, kudy se dozvíme, co změnit.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Nová"
        DONE = "done", "Vyřízená"

    organization = models.ForeignKey(Organization, verbose_name="organizace",
                                     on_delete=models.CASCADE, null=True, blank=True,
                                     related_name="remarks")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="kdo", on_delete=models.SET_NULL,
                             null=True, blank=True, related_name="remarks")
    page = models.CharField("stránka", max_length=300, blank=True)
    context = models.CharField("k čemu", max_length=200, blank=True,
                               help_text="Oddíl a krok, kterého se připomínka týká.")
    text = models.TextField("připomínka")
    status = models.CharField("stav", max_length=8, choices=Status.choices, default=Status.OPEN)
    answer = models.TextField("odpověď správce", blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="vyřídil",
                                    on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")
    resolved_at = models.DateTimeField("vyřízeno", null=True, blank=True)

    class Meta:
        verbose_name = "připomínka"
        verbose_name_plural = "připomínky"
        ordering = ["status", "-created_at"]

    def __str__(self):
        return f"{self.context or self.page}: {self.text[:50]}"
