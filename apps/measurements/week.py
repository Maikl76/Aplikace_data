"""
Přehled na týden: co laboratoř čeká den po dni.

Naplánované testovací dny po skupinách (baterie testů), objednávky na
termíny v týdnu, kdo má v týdnu termín dalšího měření a které dny týdne
ještě čekají na zprávu. Všechno se počítá z dat – nic se tu nezadává;
plánuje se v Dnešním testování a v objednávkách.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from .models import TestSession
from .planning import DERIVED_PROTOCOLS

DAY_NAMES = ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"]
DAY_SHORT = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]
MAX_NAMES = 4   # kolik jmen se u skupiny vypíše; zbytek jako „+N“


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def parse_monday(text: str | None, today: date) -> date:
    """Pondělí týdne z ``?od=`` (stačí kterýkoli den týdne); neplatné = tento týden."""
    try:
        return monday_of(date.fromisoformat(text or ""))
    except ValueError:
        return monday_of(today)


def title(monday: date) -> str:
    """„9.–15. 11. 2026“, přes měsíc „27. 10. – 2. 11. 2026“."""
    sunday = monday + timedelta(days=6)
    if monday.month == sunday.month:
        return f"{monday.day}.–{sunday.day}. {sunday.month}. {sunday.year}"
    return f"{monday.day}. {monday.month}. – {sunday.day}. {sunday.month}. {sunday.year}"


@dataclass
class Group:
    """Testovací dny jedné skupiny (baterie) v jednom dni."""

    day: date
    battery: object = None          # TestBattery, nebo None u sportovce bez baterie
    sessions: list = field(default_factory=list)
    names: list = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.battery.label if self.battery else "bez baterie testů"

    @property
    def done(self) -> int:
        return sum(1 for s in self.sessions if s.stav == "hotovo")

    @property
    def started(self) -> int:
        return sum(1 for s in self.sessions if s.stav == "rozpracovano")

    @property
    def waiting(self) -> int:
        return sum(1 for s in self.sessions if s.stav == "ceka")

    @property
    def more(self) -> int:
        return max(len(self.sessions) - MAX_NAMES, 0)

    @property
    def url(self) -> str:
        if self.battery is not None:
            return reverse("today") + f"?datum={self.day.isoformat()}&baterie={self.battery.pk}"
        if len(self.sessions) == 1:
            return reverse("session_detail", args=[self.sessions[0].pk])
        return reverse("session_list")


def _batteries(subjects) -> dict:
    """Baterie podle (sport, kategorie) jedním dotazem – stejný výběr jako u sportovce."""
    from apps.catalog.models import TestBattery

    sports = {s.sport_id for s in subjects if s.sport_id}
    if not sports:
        return {}
    return {(b.sport_id, (b.category or "").lower()): b
            for b in TestBattery.objects.filter(sport_id__in=sports).select_related("sport")}


def _battery_for(subject, batteries: dict):
    if not subject.sport_id:
        return None
    if subject.category:
        exact = batteries.get((subject.sport_id, subject.category.lower()))
        if exact is not None:
            return exact
    return batteries.get((subject.sport_id, ""))


def _state(session) -> str:
    if session.testu and session.zmereno >= session.testu:
        return "hotovo"
    return "rozpracovano" if session.zmereno else "ceka"


def overview(user, monday: date, *, today: date | None = None) -> dict:
    """
    Týden po dnech pro šablonu a pro proužek na Přehledu.

    Každý den: skupiny s testovacími dny (hotovo / rozpracováno / čeká),
    objednávky na termíny toho dne (schválené i čekající na schválení), kdo
    má ten den termín dalšího měření a které dny s hodnotami nemají zprávu.
    """
    from apps.booking.models import BookingRequest
    from apps.core import access
    from apps.reports.models import Report
    from apps.subjects import retest
    from apps.subjects.models import Subject
    from apps.subjects.search import names_for

    today = today or timezone.localdate()
    sunday = monday + timedelta(days=6)
    measured = ~Q(protocol_runs__protocol__code__in=DERIVED_PROTOCOLS)
    sessions = list(
        TestSession.objects.for_user(user).filter(date__range=(monday, sunday))
        .select_related("subject", "subject__sport")
        .annotate(testu=Count("protocol_runs", distinct=True, filter=measured),
                  zmereno=Count("protocol_runs", distinct=True, filter=measured & Q(
                      protocol_runs__trials__measurements__isnull=False)))
        .order_by("date", "pk"))
    reported = set(Report.objects.for_user(user).filter(session__in=sessions)
                   .values_list("session_id", flat=True))
    batteries = _batteries([s.subject for s in sessions])

    subjects = list(Subject.objects.for_user(user).filter(is_active=True)
                    .select_related("sport", "identity"))
    plans = retest.plans_for(subjects, today=today)
    due = [p for p in plans if p.due and monday <= p.due <= sunday
           and p.status in ("soon", "overdue", "ok")]
    overdue = sum(1 for p in plans if p.status == "overdue")

    names = names_for([s.subject for s in sessions] + [p.subject for p in due], user)

    bookings = []
    if access.can(user, "bookings"):
        start = timezone.make_aware(datetime.combine(monday, time.min))
        end = timezone.make_aware(datetime.combine(sunday + timedelta(days=1), time.min))
        bookings = list(BookingRequest.objects.for_user(user)
                        .filter(status__in=BookingRequest.HOLDS_SLOT,
                                slot__start__gte=start, slot__start__lt=end)
                        .select_related("slot")
                        .annotate(osob=Count("participants", distinct=True))
                        .order_by("slot__start"))
        for booking in bookings:
            booking.den = timezone.localtime(booking.slot.start).date()
            booking.schvalena = booking.status == BookingRequest.Status.APPROVED

    days = []
    for offset in range(7):
        day = monday + timedelta(days=offset)
        groups: dict = {}
        day_sessions = [s for s in sessions if s.date == day]
        for session in day_sessions:
            session.stav = _state(session)
            session.jmeno = names.get(session.subject_id) or session.subject.code
            session.ma_zpravu = session.pk in reported
            battery = _battery_for(session.subject, batteries)
            key = battery.pk if battery is not None else None
            group = groups.setdefault(key, Group(day=day, battery=battery))
            group.sessions.append(session)
        for group in groups.values():
            group.sessions.sort(key=lambda s: s.jmeno.lower())
            group.names = [s.jmeno for s in group.sessions[:MAX_NAMES]]
        day_due = [p for p in due if p.due == day]
        for plan in day_due:
            plan.jmeno = names.get(plan.subject.pk) or plan.subject.code
        unreported = [s for s in day_sessions if s.zmereno and not s.ma_zpravu]
        day_bookings = [b for b in bookings if b.den == day]
        days.append({
            "date": day, "name": DAY_NAMES[offset], "short": DAY_SHORT[offset],
            "is_today": day == today, "past": day < today,
            "groups": sorted(groups.values(), key=lambda g: g.label.lower()),
            "bookings": day_bookings, "due": day_due, "unreported": unreported,
            "sessions": len(day_sessions),
            "done": sum(1 for s in day_sessions if s.stav == "hotovo"),
            "empty": not (day_sessions or day_bookings or day_due),
            "today_url": reverse("today") + f"?datum={day.isoformat()}",
        })

    return {
        "monday": monday, "sunday": sunday, "days": days,
        "title": title(monday), "week_number": monday.isocalendar()[1],
        "prev": monday - timedelta(days=7), "next": monday + timedelta(days=7),
        "this": monday_of(today), "is_this_week": monday == monday_of(today),
        "summary": {
            "sessions": len(sessions),
            "done": sum(1 for s in sessions if s.stav == "hotovo"),
            "waiting": sum(1 for s in sessions if s.stav == "ceka"),
            "bookings": len(bookings),
            "due": len(due), "overdue": overdue,
            "unreported": sum(1 for s in sessions if s.zmereno and not s.ma_zpravu),
            "drafts": Report.objects.for_user(user).filter(status=Report.Status.DRAFT).count(),
        },
    }
