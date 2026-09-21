"""
Knihovna vědeckých článků.

Hybridní model: kurátorované jádro (vy zařadíte a anotujete) + dávkové
návrhy novinek z PubMedu, které procházejí schválením. Do zprávy se
nedostane nic, co jste neschválil.
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
    population_sport = models.CharField("populace – sport", max_length=120, blank=True)
    population_sex = models.CharField("populace – pohlaví", max_length=1, blank=True,
                                      choices=[("F", "Ženy"), ("M", "Muži"), ("B", "Obě")])
    population_age_min = models.PositiveSmallIntegerField("populace – věk od",
                                                          null=True, blank=True)
    population_age_max = models.PositiveSmallIntegerField("populace – věk do",
                                                          null=True, blank=True)
    population_level = models.CharField("populace – úroveň", max_length=60, blank=True)
    sample_size = models.PositiveIntegerField("velikost vzorku", null=True, blank=True)

    curator_note = models.TextField("anotace kurátora", blank=True,
                                    help_text="K čemu je studie relevantní, jaká má omezení.")
    tags = models.JSONField("štítky", default=list, blank=True)

    # Embedding pro sémantické vyhledávání (fáze 4, pgvector).
    # embedding = VectorField(dimensions=1536, null=True, blank=True)

    class Meta:
        verbose_name = "článek"
        verbose_name_plural = "články"
        ordering = ["-year", "title"]

    def __str__(self):
        first_author = self.authors.split(",")[0] if self.authors else "?"
        return f"{first_author} ({self.year}): {self.title[:70]}"

    def matches_population(self, subject) -> bool:
        """Sedí studie na tohoto sportovce? Pokud ne, zpráva to uvede."""
        if self.population_sex and self.population_sex != "B":
            if subject.sex != self.population_sex:
                return False
        age = subject.age
        if age is not None:
            if self.population_age_min and age < self.population_age_min:
                return False
            if self.population_age_max and age > self.population_age_max:
                return False
        return True
