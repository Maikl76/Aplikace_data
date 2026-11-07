"""
Plán opakování měření: kdy má sportovec přijít znovu, kdo je na řadě
a připomínky e‑mailem.

Termín dalšího měření plyne z dat: poslední měření s hodnotami plus
interval (vlastní u sportovce, jinak z baterie testů jeho sportu), nebo
konkrétní datum zapsané u sportovce. Naplánovaný testovací den bez hodnot
nebo objednávka čekající na schválení znamenají „už je domluveno“.

Připomínka odchází e‑mailem na uložený kontakt sportovce a na účty
zákonných zástupců, nejdřív 14 dní před termínem a pak nejdřív po 30
dnech znovu. Bez poštovního serveru se nic neposílá – „Kdo je na řadě“
na Přehledu funguje i tak.
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from django.conf import settings
from django.db.models import Count, Max
from django.utils import timezone

from .models import Guardian, RetestReminder, Subject, SubjectIdentity

logger = logging.getLogger(__name__)

REMIND_DAYS_BEFORE = 14   # první připomínka tolik dní před termínem
REMIND_AGAIN_DAYS = 30    # další připomínka témuž sportovci nejdřív po tolika dnech
SOON_DAYS = 30            # „na řadě“ = termín do tolika dnů, nebo prošlý


def days_text(days: int, *, after: str = "do") -> str:
    """Dny po předložce: „do 1 dne“, „do 5 dnů“; „o 1 den“, „o 2 dny“, „o 5 dnů“."""
    if after == "do":
        return f"do {days} {'dne' if days == 1 else 'dnů'}"
    return f"{after} {days} {'den' if days == 1 else 'dny' if days <= 4 else 'dnů'}"


def weeks_text(weeks: int) -> str:
    """„každý týden“, „každé 3 týdny“, „každých 12 týdnů“."""
    if weeks == 1:
        return "každý týden"
    if 2 <= weeks <= 4:
        return f"každé {weeks} týdny"
    return f"každých {weeks} týdnů"


@dataclass
class Plan:
    subject: Subject
    weeks: int | None = None        # interval, který platí
    source: str = ""                # „sportovec“ (vlastní) nebo „baterie“
    last_date: date | None = None   # poslední měření s hodnotami
    due: date | None = None         # termín dalšího měření
    explicit: bool = False          # termín je zapsané datum, ne interval
    planned: date | None = None     # naplánovaný testovací den bez hodnot
    booked: bool = False            # objednávka čeká na schválení
    today: date = None

    @property
    def days_left(self) -> int | None:
        return (self.due - self.today).days if self.due else None

    @property
    def status(self) -> str:
        if self.planned:
            return "planned"
        if self.booked:
            return "booked"
        if self.due is None:
            return "none"
        if self.days_left < 0:
            return "overdue"
        if self.days_left <= SOON_DAYS:
            return "soon"
        return "ok"

    @property
    def is_due(self) -> bool:
        return self.status in ("overdue", "soon")

    @property
    def interval_text(self) -> str:
        if not self.weeks:
            return ""
        return (weeks_text(self.weeks)
                + (" (vlastní interval)" if self.source == "sportovec" else " podle baterie"))

    def text(self) -> str:
        """Věta pro kartu sportovce a Přehled."""
        s = self.status
        if s == "planned":
            return f"Další měření je naplánované na {self.planned:%d.%m.%Y}."
        if s == "booked":
            return "Objednávka na další měření čeká na schválení."
        if s == "none":
            if self.weeks and self.last_date is None:
                return (f"Zatím bez měření; po prvním měření se termín dalšího spočítá "
                        f"({self.interval_text}).")
            return ("Bez plánu opakování: nastavte interval u baterie sportu, nebo vlastní "
                    "u sportovce.")
        base = f"Další měření do {self.due:%d.%m.%Y}"
        if self.explicit:
            base += " (zapsaný termín)"
        elif self.weeks:
            base += f" ({self.interval_text}, poslední {self.last_date:%d.%m.%Y})"
        if s == "overdue":
            return base + f". Termín prošel {days_text(-self.days_left, after='o')} – domluvte nové měření."
        if s == "soon":
            n = self.days_left
            return base + f", {'zbývá' if n == 1 or n >= 5 else 'zbývají'} {n} " \
                          f"{'den' if n == 1 else 'dny' if n <= 4 else 'dnů'}."
        return base + "."

    def badge(self) -> tuple[str, str]:
        """(css, text) pro odznak v seznamech."""
        s = self.status
        if s == "planned":
            return "badge-good", f"naplánováno {self.planned:%d.%m.}"
        if s == "booked":
            return "badge-good", "objednáno"
        if s == "overdue":
            return "badge-bad", f"prošlo {days_text(-self.days_left, after='o')}"
        if s == "soon":
            return "badge-warn", (days_text(self.days_left) if self.days_left else "dnes")
        if s == "ok":
            return "badge", f"do {self.due:%d.%m.%Y}"
        return "", ""


# --- výpočet ----------------------------------------------------------------------------------

def _batteries_for(subjects) -> dict:
    """Baterie podle (sport, kategorie) pro dané sportovce – jedním dotazem."""
    from apps.catalog.models import TestBattery

    sports = {s.sport_id for s in subjects if s.sport_id}
    if not sports:
        return {}
    return {(b.sport_id, (b.category or "").lower()): b
            for b in TestBattery.objects.filter(sport_id__in=sports)}


def _weeks_for(subject, batteries: dict) -> tuple[int | None, str]:
    """Interval, který pro sportovce platí: vlastní, jinak z baterie (stejný výběr jako baterie testů)."""
    if subject.retest_weeks:
        return subject.retest_weeks, "sportovec"
    if not subject.sport_id:
        return None, ""
    battery = None
    if subject.category:
        battery = batteries.get((subject.sport_id, subject.category.lower()))
    if battery is None:
        battery = batteries.get((subject.sport_id, ""))
    if battery is not None and battery.retest_weeks:
        return battery.retest_weeks, "baterie"
    return None, ""


def plans_for(subjects, *, today: date | None = None) -> list[Plan]:
    """Plány pro víc sportovců najednou (seznam, Přehled, portál trenéra) bez dotazu na řádek."""
    from apps.booking.models import BookingRequest, Participant
    from apps.measurements.models import TestSession

    subjects = list(subjects)
    if not subjects:
        return []
    today = today or timezone.localdate()
    ids = [s.pk for s in subjects]
    batteries = _batteries_for(subjects)
    measured = dict(TestSession.objects.filter(
        subject_id__in=ids, protocol_runs__trials__measurements__isnull=False)
        .values("subject_id").annotate(d=Max("date")).values_list("subject_id", "d"))
    planned: dict[int, date] = {}
    for subject_id, day in (TestSession.objects.filter(subject_id__in=ids, date__gte=today)
                            .annotate(n=Count("protocol_runs__trials__measurements"))
                            .filter(n=0).values_list("subject_id", "date")):
        if subject_id not in planned or day < planned[subject_id]:
            planned[subject_id] = day
    booked = set(Participant.objects.filter(
        subject_id__in=ids, request__slot__start__gte=timezone.now(),
        request__status__in=(BookingRequest.Status.VERIFY, BookingRequest.Status.NEW))
        .values_list("subject_id", flat=True))
    plans = []
    for subject in subjects:
        weeks, source = _weeks_for(subject, batteries)
        last = measured.get(subject.pk)
        due, explicit = None, False
        if subject.next_test_date and (last is None or subject.next_test_date > last):
            due, explicit = subject.next_test_date, True
        elif weeks and last:
            due = last + timedelta(weeks=weeks)
        plans.append(Plan(subject=subject, weeks=weeks, source=source, last_date=last, due=due,
                          explicit=explicit, planned=planned.get(subject.pk),
                          booked=subject.pk in booked, today=today))
    return plans


def plan_for(subject, *, today: date | None = None) -> Plan:
    return plans_for([subject], today=today)[0]


def due_plans(user, *, today: date | None = None) -> list[Plan]:
    """Kdo je na řadě: aktivní sportovci s prošlým termínem nebo termínem do 30 dnů, nejdřív prošlí."""
    subjects = (Subject.objects.for_user(user).filter(is_active=True)
                .select_related("sport", "identity"))
    plans = [p for p in plans_for(subjects, today=today) if p.is_due]
    return sorted(plans, key=lambda p: p.due)


# --- připomínky ----------------------------------------------------------------------------------

def recipients(subject) -> list[str]:
    """Adresy pro připomínku: uložený kontakt, účet sportovce a účty zákonných zástupců."""
    identity = SubjectIdentity.objects.filter(subject=subject).select_related("user").first()
    if identity is None:
        return []
    out = []
    try:
        email = identity.email.strip().lower()
    except Exception:  # bez klíče nebo s jiným klíčem kontakt nejde číst
        email = ""
    if email:
        out.append(email)
    account = (identity.user.email or "").strip().lower() if identity.user_id else ""
    if account and account not in out:
        out.append(account)
    for guardian in Guardian.objects.filter(identity=identity).select_related("user"):
        address = (guardian.user.email or "").strip().lower()
        if address and address not in out:
            out.append(address)
    return out


def message(plan: Plan, booking_url: str = "") -> tuple[str, str]:
    """Předmět a text připomínky – bez jména, bez výsledků."""
    due = f"{plan.due:%d.%m.%Y}"
    if plan.status == "overdue":
        subject = "Další funkční testování: termín prošel"
        first = (f"podle plánu laboratoře FTVS UK mělo být další funkční testování do {due}. "
                 "Prosíme, domluvte si nový termín.")
    else:
        subject = f"Další funkční testování: termín do {due}"
        first = (f"podle plánu laboratoře FTVS UK je čas na další funkční testování – doporučený "
                 f"termín je do {due}.")
    interval = (f" Pravidelné opakování ({weeks_text(plan.weeks)}) ukáže, jak se výsledky "
                "vyvíjejí." if plan.weeks else "")
    parts = [f"Dobrý den,\n\n{first}{interval}"]
    if booking_url:
        parts.append(f"Objednat se můžete tady:\n{booking_url}")
    else:
        parts.append("Termín si domluvte s laboratoří.")
    parts.append("Pokud už máte termín domluvený, berte tento e‑mail jen jako připomenutí.")
    parts.append("Laboratoř funkční diagnostiky FTVS UK")
    return subject, "\n\n".join(parts)


def booking_link(base_url: str = "") -> str:
    """Odkaz na objednávkový formulář, když je objednávání zapnuté; jinak prázdný."""
    from django.urls import reverse

    from apps.booking import services as booking

    base = (base_url or settings.PUBLIC_BASE_URL or "").rstrip("/")
    if not base or not booking.enabled():
        return ""
    return base + reverse("booking_form")


def remind(plan: Plan, *, user=None, booking_url: str = "", manual: bool = False):
    """Pošle připomínku a zapíše ji. Vrací záznam, nebo None (bez adresy, bez pošty, chyba)."""
    from django.core.mail import send_mail

    if not settings.EMAIL_HOST or plan.due is None:
        return None
    addresses = recipients(plan.subject)
    if not addresses:
        return None
    subject, body = message(plan, booking_url)
    try:
        send_mail(subject, body, None, addresses)
    except Exception:  # poštovní server neodpovídá – připomínka počká na další den
        logger.exception("Připomínka měření pro %s neodešla.", plan.subject.code)
        return None
    return RetestReminder.objects.create(subject=plan.subject, due_date=plan.due, sent_by=user,
                                         manual=manual, recipients=len(addresses))


def run_due(organization, *, today: date | None = None, booking_url: str = "",
            days_before: int = REMIND_DAYS_BEFORE) -> dict:
    """
    Automatické připomínky: sportovcům, kterým termín prošel nebo se blíží
    (do ``days_before`` dnů) a kteří v posledních 30 dnech připomínku nedostali.
    """
    today = today or timezone.localdate()
    subjects = Subject.objects.filter(organization=organization, is_active=True)
    plans = [p for p in plans_for(subjects, today=today)
             if p.is_due and p.days_left <= days_before]
    recent = set(RetestReminder.objects.filter(
        subject__in=[p.subject for p in plans],
        created_at__date__gte=today - timedelta(days=REMIND_AGAIN_DAYS))
        .values_list("subject_id", flat=True))
    sent, skipped = [], []
    for plan in plans:
        if plan.subject.pk in recent:
            skipped.append(plan)
            continue
        if remind(plan, booking_url=booking_url) is not None:
            sent.append(plan)
        else:
            skipped.append(plan)
    return {"due": plans, "sent": sent, "skipped": skipped}


def daily_check(organization, *, booking_url: str = "") -> dict | None:
    """
    Jednou denně (při prvním otevření Přehledu) rozešle připomínky. Bez
    poštovního serveru jen poznamená, že proběhla kontrola. Vrací výsledek,
    nebo None, když dnes už proběhla.
    """
    today = timezone.localdate()
    if organization is None or organization.reminders_checked_on == today:
        return None
    result = (run_due(organization, today=today, booking_url=booking_url)
              if settings.EMAIL_HOST else {"due": [], "sent": [], "skipped": []})
    organization.reminders_checked_on = today
    organization.save(update_fields=["reminders_checked_on"])
    return result
