"""
Objednávky testování od klientů.

Klient (sportovec, nebo trenér za celý tým) vyplní veřejný formulář:
co chce testovat (testy a balíčky z nabídky s cenou), volný termín,
účastníky a pár údajů o sobě. Žádost čeká na schválení laboratoří;
po schválení se z ní samy založí sportovci, souhlasy a testovací dny.

Jména, kontakty, data narození a zranění jsou zdravotně citlivé údaje
od lidí, kteří ještě nejsou klienty – ukládají se šifrovaně stejně jako
identita sportovce.
"""

import secrets
from datetime import date

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from apps.core.models import OrgScopedModel
from apps.subjects import crypto
from apps.subjects.models import Sex, Subject


class Offer(OrgScopedModel):
    """Položka nabídky: jednotlivý test, nebo balíček testů. Cena je za osobu."""

    class Kind(models.TextChoices):
        PACKAGE = "balicek", "Balíček"
        TEST = "test", "Jednotlivý test"

    kind = models.CharField("druh", max_length=10, choices=Kind.choices, default=Kind.TEST)
    name = models.CharField("název", max_length=120)
    description = models.TextField("popis pro klienta", blank=True)
    price = models.PositiveIntegerField("cena za osobu (Kč)", default=0)
    duration_min = models.PositiveSmallIntegerField("orientační délka (min)", default=30)
    protocols = models.ManyToManyField("catalog.Protocol", verbose_name="testy", blank=True,
                                       related_name="offers",
                                       help_text="Které testy se po schválení založí.")
    order = models.PositiveSmallIntegerField("pořadí", default=0)
    is_active = models.BooleanField("nabízet", default=True)

    class Meta:
        verbose_name = "položka nabídky"
        verbose_name_plural = "nabídka testování"
        ordering = ["kind", "order", "name"]

    def __str__(self):
        return f"{self.name} ({self.price} Kč)"


class Slot(OrgScopedModel):
    """Volný termín. Kapacita = kolik osob se na něj vejde (tým potřebuje víc)."""

    start = models.DateTimeField("začátek")
    duration_min = models.PositiveSmallIntegerField("délka (min)", default=60)
    location = models.CharField("laboratoř / místo", max_length=120, blank=True)
    capacity = models.PositiveSmallIntegerField("kapacita (osob)", default=1)
    note = models.CharField("poznámka pro klienta", max_length=200, blank=True)
    is_active = models.BooleanField("nabízet", default=True)

    class Meta:
        verbose_name = "volný termín"
        verbose_name_plural = "volné termíny"
        ordering = ["start"]

    def __str__(self):
        local = timezone.localtime(self.start)
        return f"{local:%d.%m.%Y %H:%M}{' – ' + self.location if self.location else ''}"

    def booked(self) -> int:
        """Obsazená místa: žádosti čekající na vyřízení a schválené."""
        return (Participant.objects
                .filter(request__slot=self, request__status__in=BookingRequest.HOLDS_SLOT)
                .count())

    def free(self) -> int:
        return max(0, self.capacity - self.booked())

    @classmethod
    def available(cls, organization):
        """Budoucí nabízené termíny s volnými místy (s atributem .volno)."""
        slots = list(cls.objects.filter(organization=organization, is_active=True,
                                        start__gt=timezone.now()))
        taken = dict(Participant.objects
                     .filter(request__slot__in=slots,
                             request__status__in=BookingRequest.HOLDS_SLOT)
                     .values_list("request__slot").annotate(n=models.Count("pk")))
        out = []
        for slot in slots:
            slot.volno = max(0, slot.capacity - taken.get(slot.pk, 0))
            if slot.volno:
                out.append(slot)
        return out


def _token() -> str:
    return secrets.token_urlsafe(24)


class BookingRequest(OrgScopedModel):
    """Žádost o testování – od jednotlivce, nebo za tým."""

    class Kind(models.TextChoices):
        INDIVIDUAL = "jednotlivec", "Jednotlivec"
        TEAM = "tym", "Tým / skupina"

    class Status(models.TextChoices):
        VERIFY = "overeni", "Čeká na potvrzení e-mailu"
        NEW = "nova", "Nová – ke schválení"
        APPROVED = "schvalena", "Schválená"
        REJECTED = "zamitnuta", "Zamítnutá"

    class Goal(models.TextChoices):
        ENTRY = "vstupni", "Vstupní diagnostika"
        PROGRESS = "progres", "Kontrola tréninkového progresu"
        SEASON = "sezona", "Příprava na sezónu"
        RETURN = "navrat", "Návrat po zranění"
        OTHER = "jine", "Jiný cíl"

    # Termín drží místo i žádost čekající na schválení – jinak by se na
    # jeden termín mohli objednat dva a jednoho by bylo nutné odmítnout.
    HOLDS_SLOT = ("nova", "schvalena")

    kind = models.CharField("kdo žádá", max_length=12, choices=Kind.choices,
                            default=Kind.INDIVIDUAL)
    status = models.CharField("stav", max_length=10, choices=Status.choices, default=Status.NEW,
                              db_index=True)
    slot = models.ForeignKey(Slot, verbose_name="termín", on_delete=models.PROTECT,
                             related_name="requests")
    offers = models.ManyToManyField(Offer, verbose_name="objednané testy", related_name="requests")
    price_total = models.PositiveIntegerField("cena celkem (Kč)", default=0,
                                              help_text="Podle ceníku v době objednání.")

    team_name = models.CharField("tým / klub", max_length=120, blank=True)
    sport_name = models.CharField("sport", max_length=100, blank=True)
    category = models.CharField("kategorie", max_length=60, blank=True)
    goal = models.CharField("cíl testování", max_length=10, choices=Goal.choices,
                            default=Goal.ENTRY)
    goal_note = models.TextField("cíl – upřesnění", blank=True)
    level = models.CharField("výkonnostní úroveň", max_length=20, choices=Subject.Level.choices,
                             default=Subject.Level.TRAINED)
    season_phase = models.CharField("tréninkové období", max_length=10, blank=True,
                                    choices=[("prep", "Přípravné období"),
                                             ("comp", "Závodní období"),
                                             ("trans", "Přechodné období"),
                                             ("rtp", "Návrat po zranění")])

    contact_name_enc = models.TextField("kontaktní osoba (šifrovaně)", blank=True)
    email_enc = models.TextField("e-mail (šifrovaně)", blank=True)
    phone_enc = models.TextField("telefon (šifrovaně)", blank=True)

    consent_testing = models.BooleanField("souhlas s testováním a zpracováním údajů",
                                          default=False)
    consent_handover = models.BooleanField("souhlas s předáním zprávy lékaři", default=False)
    consent_guardian = models.BooleanField("souhlas zákonných zástupců nezletilých",
                                           default=False)

    token = models.CharField("odkaz pro klienta", max_length=40, unique=True, default=_token,
                             editable=False)
    verified_at = models.DateTimeField("e-mail potvrzen", null=True, blank=True)
    decided_at = models.DateTimeField("vyřízeno", null=True, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="vyřídil",
                                   on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    decision_note = models.TextField("zpráva klientovi", blank=True)

    class Meta:
        verbose_name = "objednávka"
        verbose_name_plural = "objednávky"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Objednávka {self.number}"

    @property
    def number(self) -> str:
        return f"OBJ-{self.pk:05d}" if self.pk else "OBJ-nová"

    # --- šifrované údaje --------------------------------------------------
    def set_contact(self, name: str, email: str, phone: str):
        self.contact_name_enc = crypto.encrypt(name)
        self.email_enc = crypto.encrypt(email)
        self.phone_enc = crypto.encrypt(phone)

    @property
    def contact_name(self) -> str:
        return crypto.decrypt(self.contact_name_enc)

    @property
    def email(self) -> str:
        return crypto.decrypt(self.email_enc)

    @property
    def phone(self) -> str:
        return crypto.decrypt(self.phone_enc)

    def price_per_person(self) -> int:
        return self.offers.aggregate(s=Sum("price"))["s"] or 0

    def protocols(self) -> list:
        seen, out = set(), []
        for offer in self.offers.prefetch_related("protocols"):
            for protocol in offer.protocols.all():
                if protocol.pk not in seen:
                    seen.add(protocol.pk)
                    out.append(protocol)
        return out


class Participant(models.Model):
    """Účastník testování. U jednotlivce jeden, u týmu každý hráč zvlášť."""

    request = models.ForeignKey(BookingRequest, verbose_name="objednávka",
                                on_delete=models.CASCADE, related_name="participants")
    first_name_enc = models.TextField("jméno (šifrovaně)")
    last_name_enc = models.TextField("příjmení (šifrovaně)")
    birth_date_enc = models.TextField("datum narození (šifrovaně)")
    sex = models.CharField("pohlaví", max_length=1, choices=Sex.choices, default=Sex.OTHER)
    injury_enc = models.TextField("zranění (šifrovaně)", blank=True)
    subject = models.ForeignKey("subjects.Subject", verbose_name="sportovec v aplikaci",
                                on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="+")
    session = models.ForeignKey("measurements.TestSession", verbose_name="testovací den",
                                on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="+")

    class Meta:
        verbose_name = "účastník"
        verbose_name_plural = "účastníci"
        ordering = ["pk"]

    def __str__(self):
        return f"účastník {self.pk} ({self.request})"

    def set_data(self, first_name, last_name, birth_date: date, injury=""):
        self.first_name_enc = crypto.encrypt(first_name)
        self.last_name_enc = crypto.encrypt(last_name)
        self.birth_date_enc = crypto.encrypt(birth_date.isoformat())
        self.injury_enc = crypto.encrypt(injury)

    @property
    def first_name(self) -> str:
        return crypto.decrypt(self.first_name_enc)

    @property
    def last_name(self) -> str:
        return crypto.decrypt(self.last_name_enc)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def birth_date(self) -> date:
        return date.fromisoformat(crypto.decrypt(self.birth_date_enc))

    @property
    def injury(self) -> str:
        return crypto.decrypt(self.injury_enc)

    def age_on(self, day: date) -> int:
        born = self.birth_date
        return day.year - born.year - ((day.month, day.day) < (born.month, born.day))
