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

from apps.core.models import Organization, OrgScopedModel, TimeStampedModel


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
    rest_seconds = models.PositiveSmallIntegerField(
        "pauza mezi pokusy (s)", null=True, blank=True,
        help_text="Při zadávání se nabídne odpočet pauzy. Prázdné = bez odpočtu.")
    rpe_after = models.BooleanField(
        "po testu zaznamenat RPE", default=False,
        help_text="Při zadávání se nabídne škála RPE (subjektivně vnímané úsilí). "
                  "Hodí se u zátěžových testů – Wingate, spiroergometrie, terénní běhy.")
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
    class TrialRule(models.TextChoices):
        MEAN = "prumer", "Průměr platných pokusů"
        BEST = "nejlepsi", "Nejlepší pokus"
        LAST = "posledni", "Poslední pokus"

    # Jak z pokusů vznikne hodnota dne. U výskoků se obvykle průměruje,
    # u sprintu nebo síly stisku se bere nejlepší pokus.
    trial_rule = models.CharField(
        "hodnota dne z pokusů", max_length=10, choices=TrialRule.choices,
        default=TrialRule.MEAN,
        help_text="Nejlepší = nejvyšší, nebo nejnižší hodnota podle žádoucího směru "
                  "(u času sprintu nejkratší). U ukazatelů bez směru se průměruje.")
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

    def day_value(self, values: list[float]) -> float:
        """Hodnota dne z pokusů (seřazených podle pořadí) podle pravidla metriky."""
        if not values:
            raise ValueError("žádné pokusy")
        if self.trial_rule == self.TrialRule.LAST:
            return values[-1]
        if self.trial_rule == self.TrialRule.BEST:
            if self.direction == Direction.HIGHER:
                return max(values)
            if self.direction == Direction.LOWER:
                return min(values)
        return sum(values) / len(values)

    @property
    def trial_rule_note(self) -> str:
        """Krátká poznámka do tabulek, když se nepočítá průměr."""
        if self.trial_rule == self.TrialRule.LAST:
            return "poslední pokus"
        if self.trial_rule == self.TrialRule.BEST and self.direction in (Direction.HIGHER,
                                                                          Direction.LOWER):
            return "nejlepší pokus"
        return ""

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

    # Vestavěné přístroje (VALD) mají kód z Device; přístroje přidané
    # průvodcem „vlastni:<kód>“ (viz DeviceFormat).
    device = models.CharField("přístroj", max_length=64)
    test_type = models.CharField("typ testu v exportu", max_length=120, blank=True,
                                 help_text="Přesně jak ho píše export, např. "
                                           "„Countermovement Jump“. U přístroje přidaného "
                                           "průvodcem prázdné.")
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
        label = f"{self.device_label}: {self.test_type}" if self.test_type else self.device_label
        return f"{label} → {self.protocol.name}"

    @property
    def device_label(self) -> str:
        if self.device.startswith(DeviceFormat.PREFIX):
            device = DeviceFormat.objects.filter(code=self.device.removeprefix(DeviceFormat.PREFIX)).first()
            return device.name if device else self.device
        return dict(self.Device.choices).get(self.device, self.device)


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
    # Jen u přístrojů z průvodce: sloupec patří k jedné straně či části těla
    # („Left Arm Lean (g)“). VALD stranu pozná sám z názvu sloupce.
    side = models.CharField("strana", max_length=1, blank=True,
                            choices=[("B", "celkem / obě"), ("L", "levá"), ("R", "pravá")])
    segment = models.CharField("část těla", max_length=32, blank=True,
                               help_text="Např. paze, noha, trup.")

    class Meta:
        verbose_name = "importovaný sloupec"
        verbose_name_plural = "importované sloupce"
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(fields=["profile", "column"], name="uniq_import_column"),
        ]

    def __str__(self):
        return f"{self.column} → {self.metric.code}"


class DeviceFormat(CatalogModel):
    """
    Přístroj přidaný průvodcem „Nový přístroj“ – export ve tvaru tabulky
    (CSV nebo Excel), jeden řádek = jedno měření jednoho člověka.

    Tady je, kde v souboru najít, kdo a kdy se měřil. Které sloupce se
    importují jako které metriky, je v profilu importu (ImportProfile
    s ``device = "vlastni:<kód>"``), stejně jako u VALD.
    """

    PREFIX = "vlastni:"

    name = models.CharField("název přístroje", max_length=120)
    code = models.SlugField("kód", max_length=40,
                            help_text="Vznikne z názvu a už se nemění – podle něj se "
                                      "přístroj pozná i po přenosu katalogu.")
    protocol = models.ForeignKey(Protocol, verbose_name="test", on_delete=models.PROTECT,
                                 related_name="device_formats")
    header_row = models.PositiveSmallIntegerField("řádek s názvy sloupců", default=1)
    columns_seen = models.JSONField("sloupce v souboru", default=list, blank=True,
                                    help_text="Názvy sloupců z ukázkového souboru (bez dat).")
    name_column = models.CharField("jméno a příjmení", max_length=200, blank=True)
    first_name_column = models.CharField("křestní jméno", max_length=200, blank=True)
    last_name_column = models.CharField("příjmení", max_length=200, blank=True)
    id_column = models.CharField("ID v přístroji", max_length=200, blank=True)
    birth_column = models.CharField("datum narození", max_length=200, blank=True)
    sex_column = models.CharField("pohlaví", max_length=200, blank=True)
    date_column = models.CharField("datum měření", max_length=200, blank=True)
    time_column = models.CharField("čas měření", max_length=200, blank=True)
    is_active = models.BooleanField("připravený k importu", default=False)

    IDENTITY_FIELDS = ("name_column", "first_name_column", "last_name_column", "id_column",
                       "birth_column", "sex_column", "date_column", "time_column")

    class Meta:
        verbose_name = "přístroj (vlastní formát)"
        verbose_name_plural = "přístroje (vlastní formát)"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "code"], name="uniq_device_format"),
        ]

    def __str__(self):
        return self.name

    @property
    def adapter_code(self) -> str:
        return f"{self.PREFIX}{self.code}"

    @property
    def identity_columns(self) -> set[str]:
        return {getattr(self, f) for f in self.IDENTITY_FIELDS if getattr(self, f)}

    def profile(self):
        return (ImportProfile.objects.filter(device=self.adapter_code)
                .prefetch_related("columns__metric").first())


class TestBattery(OrgScopedModel):
    """
    Baterie testů: které protokoly se u sportu (případně kategorie) měří
    a v jakém pořadí. Nový testovací den se podle ní předvyplní.

    Odebrání testu z baterie nemaže žádná naměřená data – změní jen to,
    co se bude nabízet příště.
    """

    sport = models.ForeignKey("subjects.Sport", verbose_name="sport", on_delete=models.CASCADE,
                              related_name="batteries")
    category = models.CharField("kategorie", max_length=60, blank=True,
                                help_text="Např. „dorost“. Prázdné = platí pro celý sport.")
    name = models.CharField("název", max_length=120, blank=True)
    note = models.TextField("poznámka", blank=True)

    class Meta:
        verbose_name = "baterie testů"
        verbose_name_plural = "baterie testů"
        ordering = ["sport__name", "category"]

    def __str__(self):
        return self.label

    @property
    def label(self) -> str:
        if self.name:
            return self.name
        return f"{self.sport.name} – {self.category}" if self.category else self.sport.name

    def protocols(self):
        return [item.protocol for item in self.items.select_related("protocol")]

    @classmethod
    def for_subject(cls, subject):
        """Baterie pro sport a kategorii sportovce; když pro kategorii není, tak pro sport."""
        if not subject.sport_id:
            return None
        qs = cls.objects.filter(sport_id=subject.sport_id)
        if subject.category:
            exact = qs.filter(category__iexact=subject.category).first()
            if exact:
                return exact
        return qs.filter(category="").first()


class BatteryItem(models.Model):
    battery = models.ForeignKey(TestBattery, verbose_name="baterie", on_delete=models.CASCADE,
                                related_name="items")
    protocol = models.ForeignKey(Protocol, verbose_name="protokol", on_delete=models.PROTECT,
                                 related_name="battery_items")
    order = models.PositiveSmallIntegerField("pořadí", default=0)

    class Meta:
        verbose_name = "test v baterii"
        verbose_name_plural = "testy v baterii"
        ordering = ["order", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["battery", "protocol"], name="uniq_battery_protocol"),
        ]

    def __str__(self):
        return f"{self.battery} / {self.protocol.name}"


class Questionnaire(CatalogModel):
    """
    Dotazník nebo škála, kterou vyplňuje sportovec (nebo za něj operátor),
    např. RPE. Otázky jsou data – další dotazník se založí v administraci.
    """

    code = models.SlugField("kód", max_length=64)
    name = models.CharField("název", max_length=200)
    description = models.TextField("pokyn pro sportovce", blank=True)
    is_active = models.BooleanField("aktivní", default=True)

    class Meta:
        verbose_name = "dotazník"
        verbose_name_plural = "dotazníky"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "code"],
                                    name="uniq_questionnaire_code"),
        ]

    def __str__(self):
        return self.name


class Question(models.Model):
    """Jedna otázka dotazníku. Zatím škála (celá čísla od–do s popisky)."""

    questionnaire = models.ForeignKey(Questionnaire, verbose_name="dotazník",
                                      on_delete=models.CASCADE, related_name="questions")
    code = models.SlugField("kód", max_length=64)
    text = models.CharField("otázka", max_length=300)
    order = models.PositiveSmallIntegerField("pořadí", default=0)
    scale_min = models.SmallIntegerField("škála od", default=0)
    scale_max = models.SmallIntegerField("škála do", default=10)
    anchors = models.JSONField(
        "popisky bodů škály", default=dict, blank=True,
        help_text='Např. {"0": "klid", "10": "maximální úsilí"}. Body bez popisku '
                  "se ukážou jen číslem.")

    class Meta:
        verbose_name = "otázka"
        verbose_name_plural = "otázky"
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(fields=["questionnaire", "code"], name="uniq_question_code"),
        ]

    def __str__(self):
        return self.text

    def points(self) -> list[tuple[int, str]]:
        return [(v, self.anchors.get(str(v), "")) for v in range(self.scale_min,
                                                               self.scale_max + 1)]

    def label(self, value) -> str:
        return self.anchors.get(str(int(value)), "") if value is not None else ""
