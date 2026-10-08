"""
Knihovna vědeckých článků.

Hybridní model: kurátorované jádro (vy zařadíte a anotujete) + dávkové
návrhy novinek z PubMedu, které procházejí schválením. Do zprávy se
nedostane nic, co jste neschválil.

Do zprávy vede článek dvěma cestami (apps.rules.evidence):

* přes **pravidlo** – pravidlo, ke kterému je připojený, u měření našlo nález;
* přes **téma** – vztahuje se k ukazateli nebo testu, který se u sportovce měřil.
"""

from django.db import models

from apps.core.models import TimeStampedModel


class EvidenceLevel(models.TextChoices):
    META = "meta", "Metaanalýza / systematický přehled"
    RCT = "rct", "Randomizovaná kontrolovaná studie"
    COHORT = "cohort", "Kohortová studie"
    CROSS = "cross", "Průřezová studie"
    CASE = "case", "Kazuistika / série"
    EXPERT = "expert", "Expertní stanovisko"


class Article(TimeStampedModel):
    class Status(models.TextChoices):
        SUGGESTED = "suggested", "Navrženo (čeká na schválení)"
        APPROVED = "approved", "Zařazeno"
        REJECTED = "rejected", "Zamítnuto"

    title = models.TextField("název")
    authors = models.TextField("autoři", blank=True)
    journal = models.CharField("časopis", max_length=300, blank=True)
    year = models.PositiveSmallIntegerField("rok", null=True, blank=True)
    doi = models.CharField("DOI", max_length=120, blank=True, db_index=True)
    pmid = models.CharField("PMID", max_length=20, blank=True, db_index=True)
    abstract = models.TextField("abstrakt", blank=True)
    url = models.URLField("odkaz", blank=True, max_length=500)

    status = models.CharField("stav", max_length=12, choices=Status.choices,
                              default=Status.SUGGESTED)
    evidence_level = models.CharField("úroveň evidence", max_length=10,
                                      choices=EvidenceLevel.choices, blank=True)

    # Shoda populace. Studie na mužích fotbalistech neospravedlňuje
    # doporučení pro sedmnáctiletou tenistku – zpráva to musí umět říct.
    sports = models.ManyToManyField("subjects.Sport", verbose_name="sporty", blank=True,
                                    related_name="articles",
                                    help_text="Ve kterých sportech studie vznikla.")
    population_sport = models.CharField("jiný sport", max_length=120, blank=True,
                                        help_text="Sport, který v katalogu není (např. baseball).")
    population_sex = models.CharField("populace – pohlaví", max_length=1, blank=True,
                                      choices=[("F", "Ženy"), ("M", "Muži"), ("B", "Obě")])
    population_age_min = models.PositiveSmallIntegerField("populace – věk od",
                                                          null=True, blank=True)
    population_age_max = models.PositiveSmallIntegerField("populace – věk do",
                                                          null=True, blank=True)
    population_level = models.CharField("populace – úroveň", max_length=60, blank=True)
    sample_size = models.PositiveIntegerField("velikost vzorku", null=True, blank=True)

    # Co z článku dostane jazykový model: krátké, člověkem ověřené shrnutí.
    # Celý abstrakt model nedostává – vykládal by si ho po svém.
    key_finding = models.TextField(
        "hlavní zjištění pro praxi", blank=True,
        help_text="1–3 věty: co studie zjistila a co to znamená pro testování nebo trénink. "
                  "Tohle dostane jazykový model, když článek cituje.")
    limitations = models.TextField(
        "omezení", blank=True,
        help_text="Na co si dát pozor: malý vzorek, jiná populace, jen korelace…")
    curator_note = models.TextField("interní poznámka kurátora", blank=True,
                                    help_text="Pro laboratoř; model ji dostane, jen když "
                                              "chybí hlavní zjištění.")
    tags = models.JSONField("štítky", default=list, blank=True)

    # Témata: ke kterým ukazatelům a testům se článek vztahuje. Takový
    # článek dostane model i bez pravidla, když se ukazatel u sportovce měřil.
    metrics = models.ManyToManyField("catalog.MetricDef", verbose_name="ukazatele",
                                     blank=True, related_name="articles")
    protocols = models.ManyToManyField("catalog.Protocol", verbose_name="testy",
                                       blank=True, related_name="articles")

    # PDF článku jen pro interní potřebu laboratoře (a pro AI návrh). Ukládá
    # se jen na přání – licence článků jeho sdílení často nedovolují.
    pdf = models.FileField("PDF článku", upload_to="clanky/", blank=True)

    # Návrh hlavního zjištění, omezení a populace od jazykového modelu.
    # Do polí článku se dostane až tím, že ho kurátor zkontroluje a uloží –
    # do té doby ho zprávy nevidí.
    ai_draft = models.JSONField("návrh od AI", null=True, blank=True)
    ai_writing_model = models.CharField("návrh píše model", max_length=120, blank=True)
    ai_writing_started_at = models.DateTimeField("návrh se začal psát", null=True, blank=True)

    # Embedding pro sémantické vyhledávání (fáze 4, pgvector).
    # embedding = VectorField(dimensions=1536, null=True, blank=True)

    class Meta:
        verbose_name = "článek"
        verbose_name_plural = "články"
        ordering = ["-year", "title"]

    def __str__(self):
        first_author = self.authors.split(",")[0] if self.authors else "?"
        return f"{first_author} ({self.year}): {self.title[:70]}"

    @property
    def evidence_rank(self) -> int:
        """Pořadí podle síly důkazu (metaanalýza první) – kvůli výběru článků k tématu."""
        order = list(EvidenceLevel.values)
        return order.index(self.evidence_level) if self.evidence_level in order else len(order)

    def sport_names(self) -> list[str]:
        """Sporty studie: z katalogu i volným textem."""
        names = [sport.name.lower() for sport in self.sports.all()] if self.pk else []
        if self.population_sport:
            names.append(self.population_sport)
        return names

    def has_sport(self, sport) -> bool:
        if sport is None:
            return False
        if self.pk and any(s.pk == sport.pk for s in self.sports.all()):
            return True
        return bool(self.population_sport
                    and sport.name.casefold() in self.population_sport.casefold())

    def population_text(self, *, catalog_sports: bool = True) -> str:
        """Populace studie slovy: „fotbal, muži, 18–30 let, n = 42“."""
        bits = (self.sport_names() if catalog_sports
                else [self.population_sport] if self.population_sport else [])
        if self.population_sex == "F":
            bits.append("ženy")
        elif self.population_sex == "M":
            bits.append("muži")
        if self.population_age_min or self.population_age_max:
            bits.append(f"{self.population_age_min or '?'}–{self.population_age_max or '?'} let")
        if self.population_level:
            bits.append(self.population_level)
        if self.sample_size:
            bits.append(f"n = {self.sample_size}")
        return ", ".join(bits)

    @property
    def ai_writing(self) -> bool:
        return self.ai_writing_started_at is not None

    @property
    def ai_draft_ready(self) -> bool:
        return bool(self.ai_draft) and "chyba" not in self.ai_draft

    @property
    def population_without_sports(self) -> str:
        """Populace bez sportů z katalogu – ty má seznam článků jako zvláštní štítky."""
        return self.population_text(catalog_sports=False)

    def matches_population(self, subject, day=None) -> bool:
        """Sedí studie na tohoto sportovce (věk v den ``day``)? Pokud ne, zpráva to uvede."""
        if self.population_sex and self.population_sex != "B":
            if subject.sex != self.population_sex:
                return False
        age = subject.age_on(day)
        if age is not None:
            if self.population_age_min and age < self.population_age_min:
                return False
            if self.population_age_max and age > self.population_age_max:
                return False
        return True
