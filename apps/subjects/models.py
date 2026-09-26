"""
Sportovci, jejich identita a souhlasy.

Zásada: v provozních tabulkách nefiguruje jméno, jen pseudonymní ``code``.
Jméno žije v ``SubjectIdentity``, šifrovaně a s vlastním oprávněním.
(Původní aplikace používala klíč "Jan Novák, 1998-03-12" – přesně to,
čemu se tady vyhýbáme.)
"""

from django.db import models
from django.utils import timezone

from apps.core.models import OrgScopedModel, TimeStampedModel

from . import crypto


class Sex(models.TextChoices):
    FEMALE = "F", "Žena"
    MALE = "M", "Muž"
    OTHER = "X", "Jiné / neuvedeno"


class Sport(OrgScopedModel):
    name = models.CharField("název", max_length=100)
    code = models.SlugField("kód", max_length=32)

    class Meta:
        verbose_name = "sport"
        verbose_name_plural = "sporty"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "code"], name="uniq_sport_code_per_org"),
        ]

    def __str__(self):
        return self.name


class Team(OrgScopedModel):
    name = models.CharField("název", max_length=120)
    sport = models.ForeignKey(Sport, verbose_name="sport", on_delete=models.PROTECT,
                              related_name="teams")

    class Meta:
        verbose_name = "tým"
        verbose_name_plural = "týmy"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Subject(OrgScopedModel):
    """Měřená osoba. Navenek vystupuje pod pseudonymním kódem."""

    class Level(models.TextChoices):
        RECREATIONAL = "rec", "Rekreační"
        TRAINED = "trained", "Trénovaný"
        NATIONAL = "national", "Národní úroveň"
        INTERNATIONAL = "intl", "Mezinárodní úroveň"

    code = models.CharField("kód", max_length=32, db_index=True,
                            help_text="Pseudonym, např. FTVS-0001. Nikdy neobsahuje jméno.")
    sport = models.ForeignKey(Sport, verbose_name="sport", on_delete=models.PROTECT,
                              related_name="subjects", null=True, blank=True)
    team = models.ForeignKey(Team, verbose_name="tým", on_delete=models.SET_NULL,
                             related_name="subjects", null=True, blank=True)
    sex = models.CharField("pohlaví", max_length=1, choices=Sex.choices, default=Sex.OTHER)
    birth_year = models.PositiveSmallIntegerField("rok narození", null=True, blank=True,
                                                  help_text="Jen rok – přesné datum není potřeba.")
    category = models.CharField("kategorie", max_length=60, blank=True,
                                help_text="Věková nebo výkonnostní kategorie, např. „dorost“. "
                                          "Podle ní se vybírá baterie testů.")
    level = models.CharField("úroveň", max_length=20, choices=Level.choices,
                             default=Level.TRAINED)
    dominant_side = models.CharField("dominantní strana", max_length=1,
                                     choices=[("L", "Levá"), ("R", "Pravá")], blank=True)
    source_key = models.CharField("klíč zdroje", max_length=64, blank=True, db_index=True,
                                  help_text="Hash identifikačních údajů ze zdrojového souboru. "
                                            "Umožňuje opakovaný import téže osoby, aniž by se "
                                            "kamkoli ukládalo jméno.")
    is_active = models.BooleanField("aktivní", default=True)
    note = models.TextField("poznámka", blank=True,
                            help_text="Provozní poznámka. Nikdy diagnózy ani zdravotní údaje.")

    class Meta:
        verbose_name = "sportovec"
        verbose_name_plural = "sportovci"
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "code"], name="uniq_subject_code_per_org"),
        ]

    def __str__(self):
        return self.code

    @property
    def age(self):
        if not self.birth_year:
            return None
        return timezone.localdate().year - self.birth_year

    def display_for(self, user):
        """Jméno jen těm, kdo na ně mají mít nárok; ostatním pseudonym."""
        if user.sees_identity and hasattr(self, "identity"):
            return self.identity.full_name or self.code
        return self.code


class SubjectExternalId(TimeStampedModel):
    """
    Jak sportovce znají přístroje a jiné systémy – např. ID ve VALD Hubu.

    Import podle toho pozná, komu soubor patří, i když se jméno ve zdroji
    napíše jinak. Identifikátory odvozené ze jména se ukládají jen jako
    hash (``system`` začíná na „hash_“).
    """

    class System(models.TextChoices):
        VALD = "vald", "VALD – ID sportovce"
        EXTID = "extid", "VALD – ExtId"
        NAME_BIRTH = "hash_jmeno_narozeni", "Jméno a datum narození (hash)"
        NAME = "hash_jmeno", "Jméno (hash)"

    subject = models.ForeignKey(Subject, verbose_name="sportovec", on_delete=models.CASCADE,
                                related_name="external_ids")
    system = models.CharField("systém", max_length=32, choices=System.choices)
    value = models.CharField("hodnota", max_length=128, db_index=True)

    class Meta:
        verbose_name = "identifikátor v jiném systému"
        verbose_name_plural = "identifikátory v jiných systémech"
        constraints = [
            models.UniqueConstraint(fields=["subject", "system", "value"],
                                    name="uniq_subject_external_id"),
        ]

    def __str__(self):
        return f"{self.subject.code}: {self.get_system_display()}"


class SubjectIdentity(TimeStampedModel):
    """
    Oddělený trezor. Obsah je šifrovaný, klíč je v konfiguraci aplikace.
    Přístup se loguje do auditu.
    """

    subject = models.OneToOneField(Subject, verbose_name="sportovec",
                                   on_delete=models.CASCADE, related_name="identity")
    first_name_enc = models.TextField("jméno (šifrovaně)", blank=True)
    last_name_enc = models.TextField("příjmení (šifrovaně)", blank=True)
    email_enc = models.TextField("e-mail (šifrovaně)", blank=True)
    phone_enc = models.TextField("telefon (šifrovaně)", blank=True)
    last_name_hash = models.CharField("hash příjmení", max_length=64, blank=True, db_index=True,
                                      help_text="Umožňuje přesné vyhledání bez dešifrování.")

    class Meta:
        verbose_name = "identita sportovce"
        verbose_name_plural = "identity sportovců"

    def __str__(self):
        return f"identita {self.subject.code}"

    def set_names(self, first_name: str, last_name: str):
        self.first_name_enc = crypto.encrypt(first_name)
        self.last_name_enc = crypto.encrypt(last_name)
        self.last_name_hash = crypto.search_hash(last_name)

    @property
    def full_name(self) -> str:
        first = crypto.decrypt(self.first_name_enc)
        last = crypto.decrypt(self.last_name_enc)
        return f"{first} {last}".strip()

    @classmethod
    def find_by_last_name(cls, last_name: str):
        return cls.objects.filter(last_name_hash=crypto.search_hash(last_name))


class Consent(TimeStampedModel):
    """
    Souhlas je entita s rozsahem a platností, ne zaškrtávátko. Odvolat
    jde po částech – aplikace to musí respektovat (např. přestat vydávat
    zprávu poskytovateli zdravotních služeb).
    """

    class Scope(models.TextChoices):
        TESTING = "testing", "Funkční testování"
        LONGITUDINAL = "longitudinal", "Opakované měření a sledování v čase"
        REPORT_HANDOVER = "handover", "Předání zprávy poskytovateli zdravotních služeb"
        RESEARCH = "research", "Sekundární použití pro výzkum (anonymizovaně)"
        GENETICS = "genetics", "Genetická data"
        MICROBIOME = "microbiome", "Mikrobiom"

    subject = models.ForeignKey(Subject, verbose_name="sportovec",
                                on_delete=models.CASCADE, related_name="consents")
    scope = models.CharField("rozsah", max_length=20, choices=Scope.choices)
    granted_on = models.DateField("uděleno")
    valid_until = models.DateField("platnost do", null=True, blank=True)
    revoked_on = models.DateField("odvoláno", null=True, blank=True)
    document = models.FileField("podepsaný dokument", upload_to="consents/", blank=True)
    note = models.CharField("poznámka", max_length=255, blank=True)

    class Meta:
        verbose_name = "souhlas"
        verbose_name_plural = "souhlasy"
        ordering = ["-granted_on"]

    def __str__(self):
        return f"{self.subject.code} – {self.get_scope_display()}"

    @property
    def is_valid(self) -> bool:
        today = timezone.localdate()
        if self.revoked_on and self.revoked_on <= today:
            return False
        if self.valid_until and self.valid_until < today:
            return False
        return self.granted_on <= today

    @classmethod
    def has(cls, subject, scope) -> bool:
        return any(c.is_valid for c in subject.consents.filter(scope=scope))
