"""
Genetika ve sportu.

Obsah (genové karty) je data s verzí a stavem, ne kód: do zprávy smí jen
schválená verze karty a schválenou verzi nikdo nepřepíše – změna je nová
verze. Původní znění z podkladů zůstává jako verze 1 „jen ke čtení“, aby
bylo kdykoli dohledatelné, co se při revizi změnilo a proč.

Za každou oblast (výkon a trénink, pohybový aparát, regenerace…) odpovídá
garant – metodik, který její karty schvaluje. Genotypy sportovců leží
šifrovaně vlastním klíčem, vždy za platným souhlasem „Genetická data“;
odvolání souhlasu je smaže. Trenér genetiku nevidí nikdy.
"""

from django.conf import settings
from django.db import models

from apps.catalog.models import CatalogModel
from apps.core.models import TimeStampedModel

from . import crypto


class Domain(CatalogModel):
    """Oblast, za kterou odpovídá konkrétní metodik (garant)."""

    code = models.SlugField("kód", max_length=64)
    name = models.CharField("název", max_length=120)
    description = models.TextField("popis", blank=True)
    order = models.PositiveSmallIntegerField("pořadí", default=0)
    guarantors = models.ManyToManyField(
        settings.AUTH_USER_MODEL, verbose_name="garanti", blank=True,
        related_name="guaranteed_domains",
        help_text="Metodici, kteří za oblast odpovídají. Jen garant oblasti smí schválit "
                  "její genovou kartu.")
    is_active = models.BooleanField("aktivní", default=True)

    class Meta:
        verbose_name = "oblast"
        verbose_name_plural = "oblasti"
        ordering = ["order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "code"], name="uniq_domain_code"),
        ]

    def __str__(self):
        return self.name

    def is_guarantor(self, user) -> bool:
        if user is None or not user.is_authenticated:
            return False
        return bool(user.is_superuser) or self.guarantors.filter(pk=user.pk).exists()


class GeneVariant(CatalogModel):
    """
    Jedna varianta panelu (gen + rsID). Drží kanonický zápis genotypů;
    jak genotyp píše laboratoř, říká položka panelu.
    """

    gene = models.CharField("gen", max_length=32, help_text="Např. ACTN3 nebo MCM6/LCT.")
    full_name = models.CharField("plný název genu", max_length=200, blank=True)
    rsid = models.CharField("rsID", max_length=32, help_text="Např. rs1815739.")
    notation = models.CharField("zápis varianty", max_length=200, blank=True,
                                help_text="Např. rs1815739 (c.1729C>T; p.Arg577Ter; R577X).")
    domain = models.ForeignKey(Domain, verbose_name="oblast", on_delete=models.PROTECT,
                               related_name="variants")
    subtitle = models.CharField("podtitul", max_length=200, blank=True,
                                help_text="Např. „Síla a výbušnost“.")
    genotypes = models.JSONField(
        "genotypy", default=list,
        help_text='Kanonický zápis, např. ["CC", "CT", "TT"] nebo ["II", "ID", "DD"].')
    genotype_aliases = models.JSONField(
        "jiné zápisy genotypů", default=dict, blank=True,
        help_text='Např. {"CC": "RR", "CT": "RX", "TT": "XX"}.')
    strand_note = models.TextField(
        "poznámka k zápisu", blank=True,
        help_text="Strandová nejednoznačnost, vztah k jinému rsID, konvence A/G vs. C/T…")
    frequency_source = models.CharField("zdroj frekvencí", max_length=500, blank=True)
    order = models.PositiveSmallIntegerField("pořadí", default=0)
    is_active = models.BooleanField(
        "aktivní", default=True,
        help_text="Vypnutá varianta se nikde nezobrazuje a do zpráv nejde; uložené genotypy "
                  "zůstávají. Vyřazení z panelu se dělá u panelu.")

    class Meta:
        verbose_name = "genová varianta"
        verbose_name_plural = "genové varianty"
        ordering = ["order", "gene"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "rsid"], name="uniq_variant_rsid"),
        ]

    def __str__(self):
        return self.label

    @property
    def label(self) -> str:
        return f"{self.gene} / {self.rsid}"

    def alias(self, genotype: str) -> str:
        return str(self.genotype_aliases.get(genotype, "") or "")

    def genotype_label(self, genotype: str) -> str:
        alias = self.alias(genotype)
        return f"{genotype} ({alias})" if alias else genotype

    def canonical(self, raw: str) -> str | None:
        """
        Kanonický genotyp ze zápisu („C/T“, „TC“, „RX“ → „CT“), nebo None,
        když zápis neodpovídá žádnému známému genotypu. Nikdy nehádá.
        """
        text = (raw or "").strip().upper().replace("/", "").replace(" ", "").replace("-", "")
        if not text:
            return None
        codes = {str(g).upper(): str(g) for g in self.genotypes}
        aliases = {str(v).upper(): k for k, v in self.genotype_aliases.items() if v}
        for candidate in (text, text[::-1] if len(text) == 2 else ""):
            if candidate in codes:
                return codes[candidate]
            if candidate in aliases:
                return aliases[candidate]
        return None

    def current_card(self):
        """Schválená verze karty, nebo None – jen ta smí do zprávy."""
        return self.cards.filter(status=GeneCard.Status.APPROVED).order_by("-version").first()

    def latest_card(self):
        return self.cards.order_by("-version").first()


class GenePanel(CatalogModel):
    """Sada variant, kterou laboratoř vyšetřuje, včetně zápisu genotypů laboratoře."""

    code = models.SlugField("kód", max_length=64)
    name = models.CharField("název", max_length=200)
    version = models.PositiveSmallIntegerField("verze", default=1)
    provider = models.CharField("laboratoř", max_length=200, blank=True,
                                help_text="Kdo genotypizaci provádí.")
    note = models.TextField("poznámka", blank=True)
    is_active = models.BooleanField("aktivní", default=True)

    class Meta:
        verbose_name = "panel variant"
        verbose_name_plural = "panely variant"
        ordering = ["name", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "code", "version"],
                                    name="uniq_panel_code_version"),
        ]

    def __str__(self):
        return f"{self.name} (v{self.version})"

    def active_items(self):
        return (self.items.filter(variant__is_active=True)
                .select_related("variant", "variant__domain").order_by("order", "pk"))


class PanelItem(models.Model):
    panel = models.ForeignKey(GenePanel, verbose_name="panel", on_delete=models.CASCADE,
                              related_name="items")
    variant = models.ForeignKey(GeneVariant, verbose_name="varianta", on_delete=models.PROTECT,
                                related_name="panel_items")
    order = models.PositiveSmallIntegerField("pořadí", default=0)
    lab_label = models.CharField("označení u laboratoře", max_length=120, blank=True,
                                 help_text="Jak variantu píše laboratoř ve výsledku.")
    genotype_map = models.JSONField(
        "převod zápisu laboratoře", default=dict, blank=True,
        help_text='Zápis laboratoře → kanonický genotyp, např. {"RR": "CC", "RX": "CT"}. '
                  "Prázdné = laboratoř píše kanonicky (nebo některý z jiných zápisů varianty).")
    note = models.CharField("poznámka", max_length=255, blank=True)

    class Meta:
        verbose_name = "varianta v panelu"
        verbose_name_plural = "varianty v panelu"
        ordering = ["order", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["panel", "variant"], name="uniq_panel_variant"),
        ]

    def __str__(self):
        return f"{self.panel} – {self.variant}"

    def normalize(self, raw: str) -> str | None:
        text = (raw or "").strip()
        if not text:
            return None
        mapping = {str(k).strip().upper(): v for k, v in (self.genotype_map or {}).items()}
        mapped = mapping.get(text.upper().replace("/", "").replace(" ", ""))
        if mapped is None:
            mapped = mapping.get(text.upper())
        return self.variant.canonical(mapped if mapped is not None else text)


class GeneCard(CatalogModel):
    """
    Verze genové karty. Původní znění (v1) je jen ke čtení; revize se dělá
    v nové verzi; schválit ji smí jen garant oblasti; schválená verze je
    neměnná – další změna je zase nová verze.
    """

    class Status(models.TextChoices):
        ORIGINAL = "original", "Původní znění (jen ke čtení)"
        DRAFT = "draft", "Návrh"
        REVIEW = "review", "V revizi (čeká na garanta)"
        APPROVED = "approved", "Schváleno"
        SUPERSEDED = "superseded", "Nahrazeno novější verzí"
        RETIRED = "retired", "Vyřazeno"

    EDITABLE = (Status.DRAFT, Status.REVIEW)

    variant = models.ForeignKey(GeneVariant, verbose_name="varianta", on_delete=models.CASCADE,
                                related_name="cards")
    version = models.PositiveSmallIntegerField("verze", default=1)
    status = models.CharField("stav", max_length=12, choices=Status.choices,
                              default=Status.DRAFT)
    supersedes = models.ForeignKey("self", verbose_name="nahrazuje", on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="superseded_by")
    review_priorities = models.TextField("revizní priority", blank=True)
    biology_expert = models.TextField("biologická funkce – odborně", blank=True)
    biology_client = models.TextField("biologická funkce – pro klienta", blank=True)
    effect = models.TextField("účinek varianty", blank=True)
    limitations = models.TextField("omezení interpretace", blank=True)
    frequency_note = models.TextField("poznámka k frekvencím", blank=True)
    related_areas = models.JSONField("související oblasti", default=list, blank=True,
                                     help_text="Volný seznam, např. [\"Aerobní kapacita\"].")
    import_note = models.TextField("poznámka z podkladů", blank=True,
                                   help_text="Co o kartě říkaly podklady při převodu; jen ke čtení.")
    change_summary = models.TextField("přehled změn proti předchozí verzi", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="založil",
                                   on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="schválil",
                                    on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="approved_gene_cards")
    approved_at = models.DateTimeField("schváleno", null=True, blank=True)

    class Meta:
        verbose_name = "genová karta"
        verbose_name_plural = "genové karty"
        ordering = ["variant__order", "variant__gene", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["variant", "version"], name="uniq_card_version"),
        ]

    def __str__(self):
        return f"{self.variant.label} v{self.version}"

    @property
    def label(self) -> str:
        return str(self)

    @property
    def is_editable(self) -> bool:
        return self.status in self.EDITABLE

    @property
    def is_approved(self) -> bool:
        return self.status == self.Status.APPROVED

    def text_for(self, genotype: str):
        return self.genotype_texts.filter(genotype=genotype).first()


class GenotypeText(models.Model):
    """Co karta říká o jednom genotypu – klientovi a odborníkovi."""

    card = models.ForeignKey(GeneCard, verbose_name="karta", on_delete=models.CASCADE,
                             related_name="genotype_texts")
    genotype = models.CharField("genotyp", max_length=16)
    client_text = models.TextField("interpretace pro klienta", blank=True)
    expert_text = models.TextField("interpretace pro odborníka", blank=True)
    frequency = models.CharField("frekvence", max_length=200, blank=True,
                                 help_text="S populací a zdrojem, např. „32 % (Evropané, gnomAD v4)“.")
    order = models.PositiveSmallIntegerField("pořadí", default=0)

    class Meta:
        verbose_name = "text pro genotyp"
        verbose_name_plural = "texty pro genotypy"
        ordering = ["order", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["card", "genotype"], name="uniq_card_genotype_text"),
        ]

    def __str__(self):
        return f"{self.card} – {self.genotype}"


class Recommendation(models.Model):
    """Doporučení s důvodem. Bez důvodu se karta neschválí."""

    class Kind(models.TextChoices):
        SPORT = "sport", "Sportovní doporučení"
        TRAINING = "training", "Tréninková doporučení"
        NUTRITION = "nutrition", "Výživa"
        REGENERATION = "regeneration", "Regenerace"
        RISK = "risk", "Rizika"
        OTHER = "other", "Jiné"

    class Basis(models.TextChoices):
        VARIANT = "variant", "Doložená interpretace varianty"
        QUESTIONNAIRE = "questionnaire", "Odpověď v dotazníku"
        GENERAL = "general", "Obecný postup (platí bez ohledu na genotyp)"
        MEASUREMENT = "measurement", "Budoucí měření"

    card = models.ForeignKey(GeneCard, verbose_name="karta", on_delete=models.CASCADE,
                             related_name="recommendations")
    genotype = models.CharField("genotyp", max_length=16, blank=True,
                                help_text="Prázdné = platí pro všechny genotypy.")
    kind = models.CharField("druh", max_length=12, choices=Kind.choices, default=Kind.OTHER)
    text = models.TextField("text")
    basis = models.CharField("důvod doporučení", max_length=14, choices=Basis.choices, blank=True,
                             help_text="Co doporučení odůvodňuje. Bez důvodu kartu nejde schválit.")
    merge_key = models.SlugField("klíč pro slučování", max_length=64, blank=True,
                                 help_text="Stejný klíč napříč kartami = ve zprávě se doporučení "
                                           "sloučí (důvody zůstanou).")
    order = models.PositiveSmallIntegerField("pořadí", default=0)

    class Meta:
        verbose_name = "doporučení"
        verbose_name_plural = "doporučení"
        ordering = ["order", "pk"]

    def __str__(self):
        return f"{self.get_kind_display()} ({self.genotype or 'všechny'})"


class CardEvidence(models.Model):
    """Řádek důkazů (E01…): znak, podklad a omezení, co z něj smí do reportu."""

    card = models.ForeignKey(GeneCard, verbose_name="karta", on_delete=models.CASCADE,
                             related_name="evidence")
    code = models.CharField("označení", max_length=12, blank=True, help_text="Např. E01.")
    trait = models.CharField("znak", max_length=200)
    basis_text = models.TextField("podklad a omezení")
    usage = models.TextField("použití v reportu", blank=True)
    source_labels = models.CharField("zdroje", max_length=120, blank=True,
                                     help_text="Označení zdrojů karty, např. „S1, S2“.")
    article = models.ForeignKey("evidence.Article", verbose_name="článek v knihovně",
                                on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="gene_evidence")
    order = models.PositiveSmallIntegerField("pořadí", default=0)

    class Meta:
        verbose_name = "důkaz"
        verbose_name_plural = "důkazy"
        ordering = ["order", "pk"]

    def __str__(self):
        return f"{self.code} {self.trait}".strip()


class CardSource(models.Model):
    """Zdroj (literatura) karty; může být napojený na článek v knihovně."""

    card = models.ForeignKey(GeneCard, verbose_name="karta", on_delete=models.CASCADE,
                             related_name="sources")
    label = models.CharField("označení", max_length=12, blank=True, help_text="Např. S1.")
    title = models.CharField("k čemu", max_length=200, blank=True)
    citation = models.TextField("citace")
    url = models.CharField("odkaz", max_length=500, blank=True)
    article = models.ForeignKey("evidence.Article", verbose_name="článek v knihovně",
                                on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="gene_sources")
    order = models.PositiveSmallIntegerField("pořadí", default=0)

    class Meta:
        verbose_name = "zdroj karty"
        verbose_name_plural = "zdroje karty"
        ordering = ["order", "pk"]

    def __str__(self):
        return f"{self.label} {self.citation[:60]}".strip()


class ForbiddenStatement(models.Model):
    """Výrok, který se ve zprávě nesmí objevit. Bez karty = platí pro všechny."""

    card = models.ForeignKey(GeneCard, verbose_name="karta", on_delete=models.CASCADE,
                             null=True, blank=True, related_name="forbidden_statements",
                             help_text="Prázdné = platí pro všechny karty.")
    text = models.CharField("výrok", max_length=300)
    note = models.CharField("proč", max_length=255, blank=True)

    class Meta:
        verbose_name = "nepřípustný výrok"
        verbose_name_plural = "nepřípustné výroky"
        ordering = ["pk"]

    def __str__(self):
        return self.text


class ContextScenario(models.Model):
    """
    Kontext: co karta říká, když klient v dotazníku odpoví určitým způsobem
    (nebo když něco ukáže měření). Scénáře s měřením jsou ve V1 vypnuté –
    měření genotyp nikdy „nepotvrzuje“.
    """

    class Kind(models.TextChoices):
        QUESTIONNAIRE = "questionnaire", "Odpověď v dotazníku"
        MEASUREMENT = "measurement", "Měření"
        OTHER = "other", "Jiný"

    card = models.ForeignKey(GeneCard, verbose_name="karta", on_delete=models.CASCADE,
                             related_name="scenarios")
    kind = models.CharField("zdroj", max_length=14, choices=Kind.choices, default=Kind.OTHER)
    title = models.CharField("název", max_length=200, blank=True)
    statement = models.TextField("odpověď / výsledek",
                                 help_text="Např. „Lépe zvládám delší souvislou zátěž…“")
    condition = models.JSONField("podmínka nad měřením", default=dict, blank=True,
                                 help_text='Stejný zápis jako u pravidel, např. '
                                           '{"z": "wingate_pmax_th", "op": ">", "value": 1}.')
    is_active = models.BooleanField("aktivní", default=False,
                                    help_text="Jen aktivní scénář se použije ve zprávě.")
    order = models.PositiveSmallIntegerField("pořadí", default=0)

    class Meta:
        verbose_name = "kontextový scénář"
        verbose_name_plural = "kontextové scénáře"
        ordering = ["order", "pk"]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.statement[:60]}"


class ScenarioText(models.Model):
    scenario = models.ForeignKey(ContextScenario, verbose_name="scénář", on_delete=models.CASCADE,
                                 related_name="texts")
    genotype = models.CharField("genotyp", max_length=16)
    text = models.TextField("text")

    class Meta:
        verbose_name = "text scénáře"
        verbose_name_plural = "texty scénáře"
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(fields=["scenario", "genotype"],
                                    name="uniq_scenario_genotype"),
        ]

    def __str__(self):
        return f"{self.scenario} – {self.genotype}"


class GeneInteraction(CatalogModel):
    """Kombinace variant. Vyhodnotit lze jen tu, jejíž varianty jsou všechny v panelu."""

    class Status(models.TextChoices):
        HYPOTHESIS = "hypothesis", "Hypotéza (k odbornému posouzení)"
        APPROVED = "approved", "Schváleno"
        REJECTED = "rejected", "Zamítnuto"

    title = models.CharField("název", max_length=300)
    areas = models.JSONField("související oblasti", default=list, blank=True)
    assumption = models.TextField("předpoklad", blank=True,
                                  help_text="Např. „Za předpokladu kombinace ACE DD nebo ID + ACTN3 CC nebo CT“.")
    text = models.TextField("text")
    variants = models.JSONField("varianty", default=list, blank=True,
                                help_text='rsID všech variant kombinace, např. ["rs1799752", "rs1815739"].')
    status = models.CharField("stav", max_length=12, choices=Status.choices,
                              default=Status.HYPOTHESIS)
    source_card = models.ForeignKey(GeneCard, verbose_name="z karty", on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="interactions")
    order = models.PositiveSmallIntegerField("pořadí", default=0)

    class Meta:
        verbose_name = "interakce variant"
        verbose_name_plural = "interakce variant"
        ordering = ["order", "pk"]

    def __str__(self):
        return self.title[:80]

    def missing_variants(self, panel) -> list[str]:
        """rsID z kombinace, které v panelu nejsou – taková kombinace se vyhodnotit nedá."""
        present = set(panel.items.values_list("variant__rsid", flat=True)) if panel else set()
        return [rs for rs in self.variants if rs not in present]


class CardRevision(TimeStampedModel):
    """
    Záznam o sporném tvrzení nebo o tom, co se má doplnit: původní znění,
    návrh, důvod, zdroj a rozhodnutí. Nic se při revizi neztratí bez záznamu.
    """

    class Decision(models.TextChoices):
        OPEN = "open", "K rozhodnutí"
        ACCEPTED = "accepted", "Přijato"
        REJECTED = "rejected", "Zamítnuto"

    card = models.ForeignKey(GeneCard, verbose_name="karta", on_delete=models.CASCADE,
                             related_name="revisions")
    part = models.CharField("část karty", max_length=120)
    original = models.TextField("původní znění", blank=True)
    proposal = models.TextField("navrhovaná úprava", blank=True)
    reason = models.TextField("důvod", blank=True)
    source = models.TextField("zdroj", blank=True)
    decision = models.CharField("rozhodnutí", max_length=10, choices=Decision.choices,
                                default=Decision.OPEN)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="rozhodl",
                                   on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    decided_at = models.DateTimeField("rozhodnuto", null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="zapsal",
                                   on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")

    class Meta:
        verbose_name = "revizní záznam"
        verbose_name_plural = "revizní záznamy"
        ordering = ["pk"]

    def __str__(self):
        return f"{self.card} – {self.part}"


class GeneticSample(TimeStampedModel):
    """
    Vzorek a výsledek z laboratoře. Soubor s výsledkem se neukládá, jen
    reference a otisk; než se výsledek použije, diagnostik ověří, že
    patří sportovci.
    """

    class Status(models.TextChoices):
        RECEIVED = "received", "Přijato (neověřeno)"
        VERIFIED = "verified", "Ověřeno"
        INVALID = "invalid", "Nevalidní vstup"
        WITHDRAWN = "withdrawn", "Souhlas odvolán – genotypy smazány"

    subject = models.ForeignKey("subjects.Subject", verbose_name="sportovec",
                                on_delete=models.CASCADE, related_name="genetic_samples")
    panel = models.ForeignKey(GenePanel, verbose_name="panel", on_delete=models.PROTECT,
                              related_name="samples")
    provider = models.CharField("laboratoř", max_length=200, blank=True)
    sampled_on = models.DateField("datum odběru", null=True, blank=True)
    reported_on = models.DateField("datum výsledku", null=True, blank=True)
    external_reference = models.CharField("reference laboratoře", max_length=120, blank=True,
                                          help_text="Číslo vzorku nebo výsledku u laboratoře.")
    report_hash = models.CharField("otisk souboru s výsledkem", max_length=64, blank=True)
    consent = models.ForeignKey("subjects.Consent", verbose_name="souhlas",
                                on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="genetic_samples")
    status = models.CharField("stav", max_length=10, choices=Status.choices,
                              default=Status.RECEIVED)
    invalid_reason = models.CharField("důvod nevalidity", max_length=255, blank=True)
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="zadal",
                                   on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="ověřil",
                                    on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")
    verified_at = models.DateTimeField("ověřeno", null=True, blank=True)
    note = models.CharField("poznámka", max_length=255, blank=True)

    class Meta:
        verbose_name = "genetický vzorek"
        verbose_name_plural = "genetické vzorky"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.subject.code} – {self.panel} ({self.get_status_display()})"

    @property
    def is_usable(self) -> bool:
        return self.status == self.Status.VERIFIED


class Genotype(TimeStampedModel):
    """Výsledek pro jednu variantu – šifrovaně, zápis laboratoře i kanonický."""

    class Quality(models.TextChoices):
        OK = "ok", "V pořádku"
        UNCLEAR = "unclear", "Nejasný zápis"
        MISSING = "missing", "Chybí"
        FAILED = "failed", "Selhalo"

    sample = models.ForeignKey(GeneticSample, verbose_name="vzorek", on_delete=models.CASCADE,
                               related_name="genotypes")
    variant = models.ForeignKey(GeneVariant, verbose_name="varianta", on_delete=models.PROTECT,
                                related_name="subject_genotypes")
    raw_enc = models.TextField("zápis laboratoře (šifrovaně)", blank=True)
    value_enc = models.TextField("genotyp (šifrovaně)", blank=True)
    quality = models.CharField("kvalita", max_length=8, choices=Quality.choices,
                               default=Quality.OK)
    note = models.CharField("poznámka", max_length=255, blank=True)

    class Meta:
        verbose_name = "genotyp"
        verbose_name_plural = "genotypy"
        ordering = ["variant__order", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["sample", "variant"], name="uniq_sample_variant"),
        ]

    def __str__(self):
        return f"{self.sample.subject.code} – {self.variant.label}"

    def set_values(self, raw: str, value: str | None):
        self.raw_enc = crypto.encrypt(raw or "")
        self.value_enc = crypto.encrypt(value or "")

    @property
    def raw(self) -> str:
        return crypto.decrypt(self.raw_enc)

    @property
    def value(self) -> str:
        return crypto.decrypt(self.value_enc)
