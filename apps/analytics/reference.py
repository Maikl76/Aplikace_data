"""
Interní referenční hodnoty laboratoře.

Z vlastních měření pracoviště: pro klíčový ukazatel a skupinu (sport,
pohlaví, věkové pásmo) medián a pásmo P25–P75 z poslední hodnoty dne
každého sportovce. Skupina se použije až od minimálního počtu sportovců
(nastavení pracoviště); když ho nedosáhne, zkusí se táž skupina bez
rozlišení věku, jinak nic.

Je to orientace laboratoře, ne norma: nemá zdroj, nejde citovat a nikdy
nejde do zprávy ani do portálu – ukazuje se jen v laboratoři (dlaždice
a grafy na kartě sportovce, týmový přehled). Z koho se počítá, určuje
nastavení pracoviště: výchozí jsou jen sportovci s platným souhlasem se
sekundárním použitím pro výzkum; správce může přepnout na všechny aktivní
sportovce, pokud to souhlasy pracoviště pokrývají.
"""

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass

from django.utils import timezone

from apps.catalog.models import Direction, MetricDef, Protocol, ProtocolMetric
from apps.core.models import Organization
from apps.core.steps import step
from apps.measurements.models import Measurement, canonical_side
from apps.subjects.models import Consent, Sex, Sport, Subject

from .charts import cz, qualifier_label

AGE_BANDS = (
    (None, 14, "do 14 let"),
    (15, 17, "15–17 let"),
    (18, 23, "18–23 let"),
    (24, 34, "24–34 let"),
    (35, None, "35 a více let"),
)
MIN_SUBJECTS_FLOOR = 3      # pod tolik sportovců nemá ani medián smysl
MIN_SUBJECTS_CEILING = 100
SEX_LABEL = {Sex.FEMALE: "ženy", Sex.MALE: "muži"}
ALL_AGES = "všechny věky"


def age_band(age) -> str:
    """Popisek věkového pásma; prázdný, když věk není známý."""
    if age is None:
        return ""
    for low, high, label in AGE_BANDS:
        if (low is None or age >= low) and (high is None or age <= high):
            return label
    return ""


def _band_order(label: str) -> int:
    labels = [b[2] for b in AGE_BANDS]
    return labels.index(label) if label in labels else len(labels)


@dataclass
class Band:
    """Pásmo jedné skupiny: P25–P75 a medián z poslední hodnoty dne každého sportovce."""

    metric: MetricDef
    qualifiers: dict
    sport_name: str
    sex: str
    age_band: str           # "" = všechny věky
    n: int
    p25: float
    p50: float
    p75: float

    @property
    def group_text(self) -> str:
        return " · ".join([self.sport_name, SEX_LABEL.get(self.sex, self.sex),
                           self.age_band or ALL_AGES])

    @property
    def range_txt(self) -> str:
        d = self.metric.decimals
        return f"{cz(self.p25, d)}–{cz(self.p75, d)}"

    @property
    def median_txt(self) -> str:
        return cz(self.p50, self.metric.decimals)

    @property
    def text(self) -> str:
        return f"{self.range_txt} (medián {self.median_txt}) · {self.group_text} · n = {self.n}"

    def position(self, value: float) -> dict:
        """Kde hodnota leží vůči pásmu: slovy a stupeň (top / low / far / "") podle směru."""
        d = self.metric.decimals
        v = round(value, d)
        if v > round(self.p75, d):
            where, above = "nad P75", True
        elif v < round(self.p25, d):
            where, above = "pod P25", False
        else:
            return {"text": "v pásmu P25–P75", "tier": ""}
        if self.metric.direction == Direction.HIGHER:
            tier = "top" if above else "low"
        elif self.metric.direction == Direction.LOWER:
            tier = "low" if above else "top"
        else:
            tier = "far"
        return {"text": where, "tier": tier}


def _quartiles(values: list[float]) -> tuple[float, float, float]:
    p25, p50, p75 = statistics.quantiles(values, n=4, method="inclusive")
    return p25, p50, p75


class ReferenceIndex:
    """
    Interní reference pracoviště spočítané najednou: jeden dotaz na měření
    klíčových ukazatelů, pak slovníky. Skupina = (ukazatel, kvalifikátory,
    sport, pohlaví, věkové pásmo); každá hodnota je zároveň i ve skupině
    bez rozlišení věku, na kterou se padá při malém počtu.
    """

    def __init__(self, organization, *, today=None):
        self.organization = organization
        self.today = today or timezone.localdate()
        self.enabled = bool(organization is not None and organization.reference_enabled)
        self.min_subjects = (max(MIN_SUBJECTS_FLOOR, organization.reference_min_subjects)
                             if organization is not None else 8)
        self.source = (organization.reference_source if organization is not None
                       else Organization.ReferenceSource.RESEARCH)
        self.candidates = 0     # aktivních sportovců pracoviště
        self.included = 0       # kolik z nich do výpočtu vstupuje (souhlasy)
        self.metrics: dict[int, MetricDef] = {}
        self._groups = None
        self._bands: dict = {}
        self._sports: dict[int, str] = {}

    @property
    def source_label(self) -> str:
        return Organization.ReferenceSource(self.source).label

    # --- data ---------------------------------------------------------------------

    def subjects(self) -> dict[int, Subject]:
        rows = list(Subject.objects.filter(organization=self.organization, is_active=True)
                    .select_related("sport"))
        self.candidates = len(rows)
        if self.source == Organization.ReferenceSource.RESEARCH:
            consented = {c.subject_id for c in Consent.objects.filter(
                subject__in=rows, scope=Consent.Scope.RESEARCH) if c.is_valid}
            rows = [s for s in rows if s.pk in consented]
        self.included = len(rows)
        return {s.pk: s for s in rows}

    def _load(self):
        if self._groups is not None:
            return
        self._groups = defaultdict(list)
        self._sports = dict(Sport.objects.filter(organization=self.organization)
                            .values_list("pk", "name"))
        subjects = self.subjects()
        if not self.enabled or not subjects:
            return
        primary: dict[int, set[int]] = defaultdict(set)   # ukazatel -> testy, kde je klíčový
        for metric_id, protocol_id in (ProtocolMetric.objects.filter(is_primary=True)
                                       .values_list("metric_id", "protocol_id")):
            primary[metric_id].add(protocol_id)
        if not primary:
            return
        codes = dict(Protocol.objects.values_list("pk", "code"))
        rows = (Measurement.objects
                .filter(trial__protocol_run__session__subject__in=list(subjects),
                        trial__is_valid=True, trial__protocol_run__is_primary=True,
                        metric__in=list(primary))
                .order_by("trial__number")
                .values_list("trial__protocol_run__session__subject_id",
                             "trial__protocol_run__session__date",
                             "trial__protocol_run__protocol_id",
                             "metric_id", "side", "mode", "speed", "segment", "value"))
        # (sportovec, ukazatel, kvalifikátory) -> den -> test -> hodnoty pokusů
        buckets = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        for subject_id, day, protocol_id, metric_id, side, mode, speed, segment, value in rows:
            key = (subject_id, metric_id, canonical_side(side), mode or "", speed, segment or "")
            buckets[key][day][protocol_id].append(value)
        self.metrics = MetricDef.objects.in_bulk({k[1] for k in buckets})
        ages: dict = {}
        for (subject_id, metric_id, side, mode, speed, segment), by_day in buckets.items():
            subject = subjects[subject_id]
            if subject.sport_id is None or subject.sex not in SEX_LABEL:
                continue
            day = max(by_day)                     # poslední hodnota dne sportovce
            by_protocol = by_day[day]
            protocol_id = min(by_protocol, key=lambda p: (
                p not in primary.get(metric_id, ()), codes.get(p, ""), p))
            value = self.metrics[metric_id].day_value(by_protocol[protocol_id])
            if (subject_id, day) not in ages:
                ages[(subject_id, day)] = subject.age_on(day)   # věk v den měření
            group = (metric_id, side, mode, speed, segment, subject.sport_id, subject.sex)
            band = age_band(ages[(subject_id, day)])
            if band:
                self._groups[group + (band,)].append(value)
            self._groups[group + ("",)].append(value)

    @staticmethod
    def _key(metric, qualifiers, sport_id, sex, age_band_label):
        q = qualifiers or {}
        return (metric.pk, canonical_side(q.get("side") or ""), q.get("mode") or "",
                q.get("speed"), q.get("segment") or "", sport_id, sex, age_band_label)

    # --- použití -------------------------------------------------------------------

    def band(self, metric, qualifiers, sport_id, sex, age_band_label="") -> Band | None:
        """Pásmo skupiny, má-li dost sportovců; jinak None."""
        self._load()
        key = self._key(metric, qualifiers, sport_id, sex, age_band_label)
        if key not in self._bands:
            values = self._groups.get(key, [])
            band = None
            if len(values) >= self.min_subjects:
                p25, p50, p75 = _quartiles(values)
                band = Band(metric, dict(qualifiers or {}), self._sports.get(sport_id, "?"),
                            sex, age_band_label, len(values), p25, p50, p75)
            self._bands[key] = band
        return self._bands[key]

    def band_for(self, subject, metric, qualifiers=None) -> Band | None:
        """Pásmo pro sportovce: jeho sport, pohlaví a věkové pásmo; při malém počtu bez věku."""
        if not self.enabled or subject.sport_id is None or subject.sex not in SEX_LABEL:
            return None
        label = age_band(subject.age_on(self.today))
        exact = self.band(metric, qualifiers, subject.sport_id, subject.sex, label) if label else None
        return exact or self.band(metric, qualifiers, subject.sport_id, subject.sex, "")

    def dominant_group(self, subjects) -> tuple | None:
        """Nejčastější (sport, pohlaví, věkové pásmo) ve skupině – pro patičku týmového přehledu."""
        counter = Counter((s.sport_id, s.sex, age_band(s.age_on(self.today))) for s in subjects
                          if s.sport_id is not None and s.sex in SEX_LABEL)
        return counter.most_common(1)[0][0] if counter else None

    # --- přehled pro nastavení -----------------------------------------------------

    def overview(self) -> list[dict]:
        """Všechny skupiny s počtem sportovců a pásmem; i ty, které na minimum nedosáhnou."""
        self._load()
        rows = []
        for key, values in self._groups.items():
            metric_id, side, mode, speed, segment, sport_id, sex, band_label = key
            metric = self.metrics[metric_id]
            qualifiers = {"side": "" if side == "B" else side, "mode": mode, "speed": speed,
                          "segment": segment}
            n = len(values)
            quartiles = _quartiles(values) if n >= 2 else None
            d = metric.decimals
            rows.append({
                "metric": metric, "label": qualifier_label(qualifiers),
                "sport": self._sports.get(sport_id, "?"), "sex": SEX_LABEL.get(sex, sex),
                "age_band": band_label or ALL_AGES, "n": n, "ok": n >= self.min_subjects,
                "p25": cz(quartiles[0], d) if quartiles else "",
                "p50": cz(quartiles[1], d) if quartiles else "",
                "p75": cz(quartiles[2], d) if quartiles else "",
                "_order": (metric.name, qualifier_label(qualifiers), self._sports.get(sport_id, ""),
                           sex, _band_order(band_label)),
            })
        rows.sort(key=lambda r: r["_order"])
        return rows

    def summary(self) -> dict:
        self._load()
        groups = len(self._groups)
        usable = sum(1 for values in self._groups.values() if len(values) >= self.min_subjects)
        return {"groups": groups, "usable": usable, "included": self.included,
                "candidates": self.candidates, "min": self.min_subjects}


def reference_steps(index: ReferenceIndex) -> list[dict]:
    """Kroky interních referencí: zdroj dat (souhlasy), skupiny s dostatkem sportovců, použití."""
    s = index.summary()
    research = index.source == Organization.ReferenceSource.RESEARCH
    enough = s["included"] >= s["min"]
    source_text = (f"{s['included']} z {s['candidates']} aktivních sportovců vstupuje do výpočtu "
                   f"({index.source_label}).")
    if research and not enough:
        source_text += (" Platný souhlas s výzkumem má málo sportovců: buď souhlasy doplňte, "
                        "nebo přepněte na všechny aktivní sportovce, pokud to souhlasy "
                        "pracoviště pokrývají.")
    return [
        step(1, "Zdroj dat", enough, source_text, url="#nastaveni", button="Nastavit",
             admin_only=True),
        step(2, "Skupiny", s["usable"] > 0,
             (f"{s['usable']} z {s['groups']} skupin (ukazatel × sport × pohlaví × věk) má aspoň "
              f"{s['min']} sportovců – jen ty se použijí." if s["groups"] else
              "Zatím žádné měření klíčových ukazatelů u sportovců, kteří do výpočtu vstupují."),
             url="#skupiny", button="Ke skupinám", count=(s["groups"] - s["usable"]) or None),
        step(3, "Použití", index.enabled,
             ("Pásmo P25–P75 je v dlaždicích a grafech na kartě sportovce (v grafu jen tam, kde "
              "ukazatel nemá normu) a v týmovém přehledu. Nikdy do zprávy ani do portálu – je "
              "interní a necitovatelné." if index.enabled else
              "Interní reference jsou vypnuté – v grafech ani v týmovém přehledu se neukazují."),
             url="#nastaveni", button="Nastavit", optional=True, admin_only=True),
    ]
