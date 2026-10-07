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


class Audience(models.TextChoices):
    """Pro koho je zpráva – podle toho model volí jazyk, hloubku a strukturu."""

    ATHLETE = "sportovec", "Sportovec"
    COACH = "trener", "Trenér"
    CLINICIAN = "lekar", "Lékař / fyzioterapeut"


# „pro koho“ ve 4. pádě – do nadpisů a odkazů
AUDIENCE_FOR = {Audience.ATHLETE: "pro sportovce", Audience.COACH: "pro trenéra",
                Audience.CLINICIAN: "pro lékaře / fyzioterapeuta"}


class Report(OrgScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Koncept"
        RELEASED = "released", "Vydáno"
        SUPERSEDED = "superseded", "Nahrazeno novější verzí"

    class Rating(models.TextChoices):
        GOOD = "dobry", "Dobrý – stačily drobnosti"
        USABLE = "pouzitelny", "Použitelný – musel jsem upravit"
        REWRITTEN = "prepsano", "Nepoužitelný – přepsal jsem ho"

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
    audience = models.CharField("pro koho", max_length=10, choices=Audience.choices,
                                default=Audience.COACH)
    title = models.CharField("název", max_length=200, default="Zpráva z funkčního testování")
    summary = models.TextField("souhrn", blank=True)
    custom_note = models.TextField("vlastní komentář", blank=True)
    disclaimer = models.TextField("doložka", default=DISCLAIMER)

    # Otisk pro rekonstrukci: proč zpráva říká to, co říká.
    rules_version = models.CharField("verze sady pravidel", max_length=40, blank=True)
    llm_model = models.CharField("text sestavil", max_length=80, blank=True,
                                 help_text="Název jazykového modelu, nebo „šablona“.")
    generation_note = models.TextField("poznámka ke vzniku textu", blank=True,
                                       help_text="Proč se model nepoužil, pokud se "
                                                 "nepoužil – např. odmítnutý text.")
    input_fingerprint = models.CharField("otisk vstupů", max_length=64, blank=True)

    # Úpravy člověkem. Text od modelu je návrh: diagnostik ho smí opravit
    # a za vydaný text odpovídá on. Původní verze se schovává kvůli
    # dohledatelnosti, co napsal model a co člověk.
    summary_generated = models.TextField("souhrn, jak vznikl", blank=True)
    summary_edited = models.BooleanField("souhrn upraven diagnostikem", default=False)
    note_ai_model = models.CharField(
        "návrh doporučení připravil", max_length=80, blank=True,
        help_text="Model, který navrhl text komentáře; prázdné = psal jen člověk.")
    note_pending_review = models.BooleanField(
        "návrh od modelu čeká na kontrolu", default=False,
        help_text="Dokud diagnostik návrh neprojde a neuloží, zprávu nelze vydat.")
    # Zpětná vazba k textu od modelu – podle ní se ladí pokyny a vybírá model.
    ai_rating = models.CharField("hodnocení textu od AI", max_length=10, blank=True,
                                 choices=Rating.choices)
    ai_rating_note = models.CharField("co bylo špatně", max_length=300, blank=True)
    is_example = models.BooleanField(
        "vzorová zpráva", default=False,
        help_text="Model dostane souhrn této zprávy jako ukázku stylu u podobných zpráv.")
    in_test_set = models.BooleanField(
        "ve zkušební sadě", default=False,
        help_text="Na zprávách ve zkušební sadě se porovnávají modely a pokyny.")
    rendered_html = models.TextField(
        "podoba při vydání", blank=True,
        help_text="Snímek zprávy pořízený při vydání; vydaná zpráva se už nepřepočítává.")

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

    @property
    def audience_for(self) -> str:
        return AUDIENCE_FOR.get(self.audience, "")

    @property
    def written_by_model(self) -> bool:
        return bool(self.llm_model) and self.llm_model != "šablona"

    @property
    def rewrite_share(self) -> float | None:
        """Kolik textu od modelu diagnostik změnil (0 = nic, 1 = všechno)."""
        if not self.written_by_model or not self.summary_generated:
            return None
        from difflib import SequenceMatcher

        return 1 - SequenceMatcher(None, self.summary_generated, self.summary).ratio()

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


class ReportStyle(OrgScopedModel):
    """
    Pokyny pro model k jedné variantě zprávy (tón, struktura, délka),
    upravitelné v aplikaci. Pevná pravidla (žádná vymyšlená čísla ani
    diagnózy) jsou v kódu a měnit nejdou.
    """

    audience = models.CharField("pro koho", max_length=10, choices=Audience.choices)
    instructions = models.TextField("pokyny pro model")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="upravil",
                                   on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")

    class Meta:
        verbose_name = "styl zprávy"
        verbose_name_plural = "styly zpráv"
        constraints = [
            models.UniqueConstraint(fields=["organization", "audience"],
                                    name="uniq_report_style"),
        ]

    def __str__(self):
        return self.get_audience_display()


class ModelTrial(TimeStampedModel):
    """
    Zkušební text: jak by souhrn zprávy ze zkušební sady napsal jiný model
    nebo tentýž model s jinými pokyny. Do zprávy se nikdy nedostane.
    """

    report = models.ForeignKey(Report, verbose_name="zpráva", on_delete=models.CASCADE,
                               related_name="model_trials")
    model = models.CharField("model", max_length=120)
    audience = models.CharField("pro koho", max_length=10, choices=Audience.choices)
    text = models.TextField("text", blank=True)
    seconds = models.FloatField("trvání (s)", default=0)
    problems = models.JSONField("čísla bez opory v datech", default=list, blank=True)
    error = models.CharField("chyba", max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="spustil",
                                   on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        verbose_name = "zkušební text modelu"
        verbose_name_plural = "zkušební texty modelů"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.report.report_number} – {self.model}"
