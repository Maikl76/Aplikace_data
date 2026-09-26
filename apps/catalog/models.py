"""
Katalog: protokoly, metriky, normy.

Tohle je vrstva, která v původní aplikaci chyběla – byla zadrátovaná
v kódu (``GRAPH_GROUPS``, ``variable_legends``, ``desired_direction``
v analyza.py). Přidat nový test tam znamenalo editovat tři slovníky
a nasadit novou verzi. Tady je to záznam v databázi, který založíte
v administraci.

Záznamy s ``organization = NULL`` jsou sdílené napříč pracovišti.
"""

from django.db import models

from apps.core.models import Organization, TimeStampedModel


class TestFamily(models.TextChoices):
    FORCE_PLATE = "force_plate", "Force plate"
    DYNAMOMETRY = "dynamometry", "Dynamometrie"
    SPIROERGOMETRY = "spiro", "Spiroergometrie"
    BODY_COMPOSITION = "body_comp", "Složení těla"
    FIELD = "field", "Terénní test"
    OTHER = "other", "Jiné"


class CatalogModel(TimeStampedModel):
    """Katalogový záznam: buď sdílený (organization=NULL), nebo vlastní."""

    organization = models.ForeignKey(
        Organization, verbose_name="organizace", on_delete=models.CASCADE,
        null=True, blank=True, related_name="%(class)s_set",
        help_text="Prázdné = sdílený záznam platný pro všechna pracoviště.",
    )

    class Meta:
        abstract = True

    @property
    def is_shared(self) -> bool:
        return self.organization_id is None


class Protocol(CatalogModel):
    """
    Konkrétní testovací procedura, např. "CMJ na force plate" nebo
    "izokinetika ramene 210°/s". Verzovaná – změna procedury znamená
    novou verzi, ne přepis té staré, aby zůstala srovnatelnost.
    """

    code = models.SlugField("kód", max_length=64)
    name = models.CharField("název", max_length=200)
    family = models.CharField("rodina testů", max_length=20, choices=TestFamily.choices)
    version = models.PositiveSmallIntegerField("verze", default=1)
    description = models.TextField("popis procedury", blank=True)
    device = models.CharField("přístroj", max_length=120, blank=True)
    default_trials = models.PositiveSmallIntegerField("počet pokusů", default=3,
                                                      help_text="Kolik opakování se standardně "
                                                                "měří. Zadávací formulář podle "
                                                                "toho udělá sloupce.")
    is_active = models.BooleanField("aktivní", default=True)

    class Meta:
        verbose_name = "protokol"
        verbose_name_plural = "protokoly"
        ordering = ["family", "name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "code", "version"],
                                    name="uniq_protocol_code_version"),
        ]

    def __str__(self):
        return f"{self.name} (v{self.version})"


class Direction(models.TextChoices):
    """Co je u metriky žádoucí. Nahrazuje slovník desired_direction."""

    HIGHER = "higher", "Vyšší je lepší"
    LOWER = "lower", "Nižší je lepší"
    OPTIMAL = "optimal", "Optimum v pásmu"
    NEUTRAL = "neutral", "Neutrální (jen sledovaná)"


class MetricDef(CatalogModel):
    """
    Definice metriky. Kvalifikátory (strana, režim, rychlost, segment)
    se NEPÍŠÍ do názvu – jsou to pole na Measurement. Proto tu je jedna
    "Vnitřní rotace koncentricky" a ne čtyři varianty podle rychlosti
    a strany. Díky tomu jde asymetrii počítat obecně, jedním pravidlem
    pro všechny testy.
    """

    code = models.SlugField("kód", max_length=64)
    name = models.CharField("název", max_length=200)
    family = models.CharField("rodina testů", max_length=20, choices=TestFamily.choices)
    unit = models.CharField("jednotka", max_length=32, blank=True)
    direction = models.CharField("žádoucí směr", max_length=10, choices=Direction.choices,
                                 default=Direction.HIGHER)
    description = models.TextField("popis", blank=True,
                                   help_text="Text do legendy zprávy.")

    # Rozlišení skutečné změny od šumu měření. Bez těchto dvou čísel
    # nelze u opakovaného měření říct, jestli "o 2,31 vyšší" něco znamená.
    typical_error = models.FloatField("typická chyba měření", null=True, blank=True)
    mdc = models.FloatField("MDC", null=True, blank=True,
                            help_text="Nejmenší detekovatelná změna (v jednotkách metriky).")
    swc = models.FloatField("SWC", null=True, blank=True,
                            help_text="Nejmenší prakticky významná změna.")

    # Meze pro validaci importu – hodnota mimo rozsah se označí, neuloží mlčky.
    plausible_min = models.FloatField("věrohodné minimum", null=True, blank=True)
    plausible_max = models.FloatField("věrohodné maximum", null=True, blank=True)

    decimals = models.PositiveSmallIntegerField("desetinná místa", default=2)

    class OdsRole(models.TextChoices):
        OUTCOME = "vysledek", "Výsledek (co sportovec dokázal)"
        DRIVER = "pricina", "Příčina (co výsledek pohání)"
        STRATEGY = "strategie", "Strategie (jak pohyb provedl)"

    # Rozdělení metrik podle ODS (Outcome – Driver – Strategy). Zpráva pak
    # umí říct, proč se výsledek změnil: silou, nebo jiným provedením skoku.
    ods_role = models.CharField("role v ODS", max_length=10, choices=OdsRole.choices,
                                blank=True)
    trial_cv_limit = models.FloatField(
        "max. rozptyl pokusů (CV %)", null=True, blank=True,
        help_text="Když se pokusy téhož dne liší víc (variační koeficient), aplikace "
                  "upozorní, že je vhodné pokus zopakovat. Prázdné = nekontroluje se.")
    loinc_code = models.CharField("kód LOINC", max_length=20, blank=True,
                                  help_text="Jen tam, kde standard existuje (složení těla, laboratoř).")
    is_active = models.BooleanField("aktivní", default=True)

    class Meta:
        verbose_name = "metrika"
        verbose_name_plural = "metriky"
        ordering = ["family", "name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "code"], name="uniq_metric_code_per_org"),
        ]

    def __str__(self):
        return f"{self.name} [{self.unit}]" if self.unit else self.name

    def is_plausible(self, value: float) -> bool:
        if self.plausible_min is not None and value < self.plausible_min:
            return False
        if self.plausible_max is not None and value > self.plausible_max:
            return False
        return True

    def change_is_real(self, delta: float) -> bool:
        """Přesahuje změna chybu měření? Bez MDC nelze rozhodnout."""
        if self.mdc is None:
            return False
        return abs(delta) >= self.mdc

    def change_is_worthwhile(self, delta: float) -> bool:
        if self.swc is None:
            return False
        return abs(delta) >= self.swc


class ProtocolMetric(models.Model):
    """Které metriky daný protokol produkuje a v jakém pořadí."""

    protocol = models.ForeignKey(Protocol, verbose_name="protokol", on_delete=models.CASCADE,
                                 related_name="protocol_metrics")
    metric = models.ForeignKey(MetricDef, verbose_name="metrika", on_delete=models.PROTECT,
                               related_name="protocol_metrics")
    order = models.PositiveSmallIntegerField("pořadí", default=0)
    is_primary = models.BooleanField("klíčová metrika", default=False,
                                     help_text="Zobrazuje se na kartě sportovce a v souhrnu zprávy.")

    # Které kombinace kvalifikátorů se u téhle metriky v tomhle protokolu
    # měří. Díky tomu je zadávací formulář daný daty: nový protokol se
    # založí v administraci a obrazovka pro něj vznikne sama.
    sides = models.JSONField("strany", default=list, blank=True,
                             help_text='Např. ["L", "R"] nebo ["B"]. Prázdné = bez rozlišení.')
    modes = models.JSONField("režimy", default=list, blank=True,
                             help_text='Např. ["con", "ecc"]. Prázdné = bez rozlišení.')
    speeds = models.JSONField("rychlosti", default=list, blank=True,
                              help_text="Např. [210, 300]. Prázdné = bez rozlišení.")
    segments = models.JSONField("segmenty", default=list, blank=True,
                                help_text='Např. ["paze", "noha", "trup"].')

    class Meta:
        verbose_name = "metrika protokolu"
        verbose_name_plural = "metriky protokolu"
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(fields=["protocol", "metric"], name="uniq_protocol_metric"),
        ]

    def __str__(self):
        return f"{self.protocol.code} / {self.metric.code}"

    def qualifier_combinations(self) -> list[dict]:
        """
        Kartézský součin kvalifikátorů – jeden prvek = jeden řádek
        zadávacího formuláře. Prázdný seznam znamená "bez rozlišení",
        proto se nahrazuje [""] / [None].
        """
        sides = self.sides or [""]
        modes = self.modes or [""]
        speeds = self.speeds or [None]
        segments = self.segments or [""]

        return [
            {"side": side, "mode": mode, "speed": speed, "segment": segment}
            for segment in segments
            for side in sides
            for mode in modes
            for speed in speeds
        ]


class Norm(CatalogModel):
    """
    Normativní hodnota pro srovnání. Vždy s citací zdroje – bez ní není
    jasné, proti čemu se sportovec porovnává, a zpráva to neobhájí.
    """

    metric = models.ForeignKey(MetricDef, verbose_name="metrika", on_delete=models.CASCADE,
                               related_name="norms")
    sport = models.ForeignKey("subjects.Sport", verbose_name="sport", on_delete=models.CASCADE,
                              null=True, blank=True,
                              help_text="Prázdné = platí napříč sporty.")
    sex = models.CharField("pohlaví", max_length=1, blank=True,
                           choices=[("F", "Žena"), ("M", "Muž")],
                           help_text="Prázdné = obě pohlaví.")
    age_min = models.PositiveSmallIntegerField("věk od", null=True, blank=True)
    age_max = models.PositiveSmallIntegerField("věk do", null=True, blank=True)
    level = models.CharField("úroveň", max_length=20, blank=True)

    # Kvalifikátory – norma pro 210°/s je jiná než pro 300°/s.
    side = models.CharField("strana", max_length=10, blank=True)
    mode = models.CharField("režim", max_length=20, blank=True)
    speed = models.FloatField("rychlost", null=True, blank=True)

    mean = models.FloatField("průměr", null=True, blank=True)
    sd = models.FloatField("směrodatná odchylka", null=True, blank=True)
    percentiles = models.JSONField("percentily", default=dict, blank=True,
                                   help_text='Např. {"10": 21.4, "50": 28.9, "90": 35.2}')

    source_citation = models.CharField("citace zdroje", max_length=500)
    source_doi = models.CharField("DOI", max_length=120, blank=True)
    sample_size = models.PositiveIntegerField("velikost vzorku", null=True, blank=True)
    note = models.TextField("poznámka", blank=True)

    class Meta:
        verbose_name = "norma"
        verbose_name_plural = "normy"
        ordering = ["metric", "sport", "sex"]
        indexes = [models.Index(fields=["metric", "sport", "sex"])]

    def __str__(self):
        parts = [self.metric.code]
        if self.sport_id:
            parts.append(str(self.sport))
        if self.sex:
            parts.append(self.get_sex_display())
        return " / ".join(parts)

    def z_score(self, value: float):
        if self.mean is None or not self.sd:
            return None
        return (value - self.mean) / self.sd


class ImportProfile(CatalogModel):
    """
    Jak číst export z přístroje: který typ testu patří ke kterému
    protokolu a které sloupce se importují jako které metriky.

    Je to data, ne kód – když přístroj přejmenuje sloupec nebo chcete
    sledovat další metriku, doplní se tady a nic se neprogramuje.
    """

    class Device(models.TextChoices):
        VALD_FORCEDECKS = "vald_forcedecks", "VALD ForceDecks"
        VALD_HUMANTRAK = "vald_humantrak", "VALD HumanTrak"

    device = models.CharField("přístroj", max_length=32, choices=Device.choices)
    test_type = models.CharField("typ testu v exportu", max_length=120,
                                 help_text="Přesně jak ho píše export, např. "
                                           "„Countermovement Jump“.")
    protocol = models.ForeignKey(Protocol, verbose_name="protokol", on_delete=models.PROTECT,
                                 related_name="import_profiles")
    is_active = models.BooleanField("aktivní", default=True)

    class Meta:
        verbose_name = "profil importu"
        verbose_name_plural = "profily importu"
        ordering = ["device", "test_type"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "device", "test_type"],
                                    name="uniq_import_profile"),
        ]

    def __str__(self):
        return f"{self.get_device_display()}: {self.test_type} → {self.protocol.name}"


class ImportColumn(models.Model):
    """
    Jeden importovaný sloupec. U ForceDecks stačí zadat souhrnný sloupec
    (např. „Concentric Peak Force [N]“) – varianty „(Left)“ a „(Right)“
    se najdou samy a uloží jako levá a pravá strana.
    """

    profile = models.ForeignKey(ImportProfile, verbose_name="profil", on_delete=models.CASCADE,
                                related_name="columns")
    column = models.CharField("sloupec v exportu", max_length=200)
    metric = models.ForeignKey(MetricDef, verbose_name="metrika", on_delete=models.PROTECT,
                               related_name="import_columns")
    with_sides = models.BooleanField(
        "i levá a pravá strana", default=True,
        help_text="Importovat i varianty „(Left)“ a „(Right)“, pokud je export má. "
                  "Vypněte u časů a poměrů, kde rozdíl stran nic neříká.")
    factor = models.FloatField("násobek", default=1.0,
                               help_text="Převod hodnoty, např. −1 pro obrácení znaménka "
                                         "nebo 0,001 pro ms → s.")

    class Meta:
        verbose_name = "importovaný sloupec"
        verbose_name_plural = "importované sloupce"
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(fields=["profile", "column"], name="uniq_import_column"),
        ]

    def __str__(self):
        return f"{self.column} → {self.metric.code}"
