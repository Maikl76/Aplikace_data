"""
Měření: testovací den -> protokol -> pokusy -> jednotlivé hodnoty.

Dvě rozhodnutí, která tvarují celý model:

1. Ukládají se POKUSY, ne průměry. Tři výskoky na force plate nesou jinou
   informaci než jejich průměr – variabilita mezi pokusy je sama o sobě
   ukazatel. Jakmile uložíte jen průměr, zpátky se nedostanete.

2. Kvalifikátory (strana, režim, rychlost, segment) jsou POLE, ne součást
   názvu metriky. Původní "Vnitrni rotace koncentricka (210°/s)" mělo
   v jednom řetězci schované čtyři nezávislé osy. Takhle jde asymetrii
   počítat obecně pro force plate, izokinetiku i sílu úchopu najednou.
"""

from django.conf import settings
from django.db import models

from apps.core.models import OrgScopedModel, TimeStampedModel


class Side(models.TextChoices):
    LEFT = "L", "Levá"
    RIGHT = "R", "Pravá"
    BILATERAL = "B", "Oboustranně"
    DOMINANT = "D", "Dominantní"
    NONDOMINANT = "N", "Nedominantní"


class Mode(models.TextChoices):
    CONCENTRIC = "con", "Koncentricky"
    ECCENTRIC = "ecc", "Excentricky"
    ISOMETRIC = "iso", "Izometricky"
    NA = "", "Neurčeno"


class TestSession(OrgScopedModel):
    """Jedna návštěva laboratoře. Kontext je součást dat, ne poznámka."""

    class SeasonPhase(models.TextChoices):
        PREPARATION = "prep", "Přípravné období"
        COMPETITION = "comp", "Závodní období"
        TRANSITION = "trans", "Přechodné období"
        RETURN = "rtp", "Návrat po zranění"
        UNKNOWN = "", "Neuvedeno"

    subject = models.ForeignKey("subjects.Subject", verbose_name="sportovec",
                                on_delete=models.PROTECT, related_name="sessions")
    date = models.DateField("datum", db_index=True)
    location = models.CharField("místo", max_length=120, blank=True)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="operátor",
                                 on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="sessions")
    season_phase = models.CharField("fáze sezóny", max_length=10,
                                    choices=SeasonPhase.choices, blank=True)
    fatigue_rating = models.PositiveSmallIntegerField("subjektivní únava (1–10)",
                                                      null=True, blank=True)
    # Prostředí – u terénních testů a Wingate ovlivňuje výkon.
    temperature_c = models.FloatField("teplota (°C)", null=True, blank=True)
    humidity_pct = models.FloatField("vlhkost (%)", null=True, blank=True)
    note = models.TextField("poznámka", blank=True)

    class Meta:
        verbose_name = "testovací den"
        verbose_name_plural = "testovací dny"
        ordering = ["-date"]
        indexes = [models.Index(fields=["subject", "-date"])]

    def __str__(self):
        return f"{self.subject.code} – {self.date:%d.%m.%Y}"


class ProtocolRun(TimeStampedModel):
    """Provedení jednoho protokolu v rámci testovacího dne."""

    session = models.ForeignKey(TestSession, verbose_name="testovací den",
                                on_delete=models.CASCADE, related_name="protocol_runs")
    protocol = models.ForeignKey("catalog.Protocol", verbose_name="protokol",
                                 on_delete=models.PROTECT, related_name="runs")
    conditions = models.JSONField("podmínky", default=dict, blank=True,
                                  help_text='Např. {"teplota": 21, "rozcvicka_min": 10}')
    note = models.TextField("poznámka", blank=True)

    # Kdy přesně test proběhl. Většinou se protokol měří jednou za den,
    # ale jde i opakovaně (před zátěží / po zátěži) – pak má každé
    # provedení vlastní čas a jen jedno je „hlavní“ hodnotou dne.
    started_at = models.DateTimeField("čas testu", null=True, blank=True)
    is_primary = models.BooleanField(
        "hlavní měření dne", default=True,
        help_text="Z hlavního provedení se berou hodnoty dne do trendů, pravidel "
                  "a srovnání. Opakovaná měření téhož dne se ukazují zvlášť.")
    external_ref = models.CharField(
        "identifikace ve zdroji", max_length=200, blank=True, db_index=True,
        help_text="Např. ID testu z VALD. Díky ní opakovaný import téhož testu "
                  "nic nezdvojí, jen aktualizuje hodnoty.")

    class Meta:
        verbose_name = "provedení protokolu"
        verbose_name_plural = "provedení protokolů"
        ordering = ["started_at", "created_at"]

    def __str__(self):
        return f"{self.session} / {self.protocol.code}"


class Trial(models.Model):
    """
    Jeden pokus. Neplatný pokus se NEMAŽE – označí se a zůstane v datech
    i s důvodem, aby šlo zpětně doložit, proč se s ním nepočítalo.
    """

    protocol_run = models.ForeignKey(ProtocolRun, verbose_name="provedení protokolu",
                                     on_delete=models.CASCADE, related_name="trials")
    number = models.PositiveSmallIntegerField("pořadí pokusu")
    is_valid = models.BooleanField("platný", default=True)
    invalid_reason = models.CharField("důvod neplatnosti", max_length=255, blank=True)

    class Meta:
        verbose_name = "pokus"
        verbose_name_plural = "pokusy"
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(fields=["protocol_run", "number"], name="uniq_trial_number"),
        ]

    def __str__(self):
        return f"{self.protocol_run} – pokus {self.number}"


class Measurement(models.Model):
    """
    Jedna naměřená hodnota. Kvalifikátory rozlišují, čeho se týká –
    proto stačí jedna definice metriky pro obě strany i všechny rychlosti.
    """

    class Quality(models.TextChoices):
        OK = "ok", "V pořádku"
        SUSPECT = "suspect", "Podezřelá hodnota"
        OUT_OF_RANGE = "range", "Mimo věrohodný rozsah"
        MANUAL = "manual", "Ručně upraveno"

    trial = models.ForeignKey(Trial, verbose_name="pokus", on_delete=models.CASCADE,
                              related_name="measurements")
    metric = models.ForeignKey("catalog.MetricDef", verbose_name="metrika",
                               on_delete=models.PROTECT, related_name="measurements")

    side = models.CharField("strana", max_length=1, choices=Side.choices, blank=True)
    mode = models.CharField("režim", max_length=3, choices=Mode.choices, blank=True)
    speed = models.FloatField("rychlost (°/s)", null=True, blank=True)
    segment = models.CharField("segment", max_length=32, blank=True,
                               help_text="Např. paže, trup, noha – u segmentálních metod.")

    value = models.FloatField("hodnota")
    quality = models.CharField("kvalita", max_length=10, choices=Quality.choices,
                               default=Quality.OK)
    note = models.CharField("poznámka", max_length=255, blank=True)

    class Meta:
        verbose_name = "měření"
        verbose_name_plural = "měření"
        indexes = [
            models.Index(fields=["metric", "side", "mode", "speed"]),
            models.Index(fields=["trial", "metric"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["trial", "metric", "side", "mode", "speed", "segment"],
                name="uniq_measurement_qualifiers",
            ),
        ]

    def __str__(self):
        bits = [self.metric.code]
        if self.side:
            bits.append(self.get_side_display())
        if self.mode:
            bits.append(self.get_mode_display())
        if self.speed:
            bits.append(f"{self.speed:g}°/s")
        return f"{' '.join(bits)} = {self.value:g}"

    @property
    def qualifier_key(self) -> tuple:
        """Klíč pro párování hodnot napříč měřeními (levá vs pravá, v čase)."""
        return (self.metric_id, self.mode, self.speed, self.segment)


class RawFile(TimeStampedModel):
    """
    Originální export z přístroje. Nikdy se nepřepisuje ani nemaže –
    za dva roky můžete chtít přepočítat metriku, kterou dnes neznáte.
    Velké časové řady (křivka síla-čas, breath-by-breath) jdou jako
    parquet do objektového úložiště, v databázi zůstává jen ukazatel.
    """

    protocol_run = models.ForeignKey(ProtocolRun, verbose_name="provedení protokolu",
                                     on_delete=models.CASCADE, related_name="raw_files",
                                     null=True, blank=True)
    file = models.FileField("soubor", upload_to="raw/%Y/%m/")
    original_name = models.CharField("původní název", max_length=255)
    content_hash = models.CharField("otisk obsahu (SHA-256)", max_length=64, db_index=True,
                                    help_text="Zabrání dvojímu importu téhož souboru.")
    device = models.CharField("přístroj", max_length=120, blank=True)
    format = models.CharField("formát", max_length=40, blank=True)
    size_bytes = models.BigIntegerField("velikost", default=0)

    class Meta:
        verbose_name = "zdrojový soubor"
        verbose_name_plural = "zdrojové soubory"
        ordering = ["-created_at"]

    def __str__(self):
        return self.original_name


class QuestionnaireResponse(TimeStampedModel):
    """
    Vyplněný dotazník (např. RPE) k testovacímu dni, případně ke konkrétnímu
    testu. Vyplnit ho může operátor, nebo sportovec sám přes QR kód.
    """

    class Source(models.TextChoices):
        OPERATOR = "operator", "Zadal operátor"
        SUBJECT = "sportovec", "Vyplnil sportovec"

    session = models.ForeignKey(TestSession, verbose_name="testovací den",
                                on_delete=models.CASCADE, related_name="responses")
    protocol_run = models.ForeignKey(ProtocolRun, verbose_name="po testu",
                                     on_delete=models.CASCADE, null=True, blank=True,
                                     related_name="responses")
    questionnaire = models.ForeignKey("catalog.Questionnaire", verbose_name="dotazník",
                                      on_delete=models.PROTECT, related_name="responses")
    source = models.CharField("kdo vyplnil", max_length=10, choices=Source.choices,
                              default=Source.OPERATOR)

    class Meta:
        verbose_name = "vyplněný dotazník"
        verbose_name_plural = "vyplněné dotazníky"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.session} / {self.questionnaire.code}"


class Answer(models.Model):
    response = models.ForeignKey(QuestionnaireResponse, verbose_name="vyplněný dotazník",
                                 on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey("catalog.Question", verbose_name="otázka",
                                 on_delete=models.PROTECT, related_name="answers")
    value = models.FloatField("hodnota", null=True, blank=True)

    class Meta:
        verbose_name = "odpověď"
        verbose_name_plural = "odpovědi"
        constraints = [
            models.UniqueConstraint(fields=["response", "question"], name="uniq_answer"),
        ]

    def __str__(self):
        return f"{self.question.code} = {self.value}"
