"""
Objednávky: přijetí žádosti, schválení a zamítnutí.

Schválení je místo, kde se objednávka „přenese do aplikace“: najde
sportovce (nebo ho založí), uloží souhlasy a založí testovací den
s objednanými testy. Sportovce hledá stejně jako import z VALD – podle
hashe jména a data narození – takže klient, který už u nás byl, dostane
nové testování ke své staré kartě.
"""

from dataclasses import dataclass, field
from datetime import date

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from apps.core.models import Organization
from apps.ingest.adapters.vald import identity_ids
from apps.measurements import planning
from apps.measurements.models import TestSession
from apps.subjects.models import Consent, Sport, Subject, SubjectExternalId, SubjectIdentity

from .models import BookingRequest, Offer, Participant, Slot

ADULT_AGE = 18


class BookingError(Exception):
    """Objednávku nejde přijmout nebo schválit – důvod je pro uživatele."""


def organization():
    """Pro koho je veřejný formulář: podle nastavení, jinak jediná / první organizace."""
    if settings.BOOKING_ORGANIZATION:
        return Organization.objects.filter(short_name=settings.BOOKING_ORGANIZATION).first()
    return Organization.objects.order_by("pk").first()


def enabled() -> bool:
    """Bez šifrovacího klíče nejde osobní údaje uložit – formulář se pak nenabízí."""
    return bool(settings.IDENTITY_ENCRYPTION_KEY) and organization() is not None


# --- přijetí --------------------------------------------------------------

@dataclass
class ParticipantData:
    first_name: str
    last_name: str
    birth_date: date
    sex: str = "X"
    injury: str = ""


@dataclass
class RequestData:
    kind: str
    slot_id: int
    offer_ids: list[int]
    participants: list[ParticipantData]
    contact_name: str
    email: str
    phone: str = ""
    team_name: str = ""
    sport_name: str = ""
    category: str = ""
    goal: str = BookingRequest.Goal.ENTRY
    goal_note: str = ""
    level: str = Subject.Level.TRAINED
    season_phase: str = ""
    consent_testing: bool = False
    consent_handover: bool = False
    consent_guardian: bool = False
    errors: list[str] = field(default_factory=list)


def has_minors(participants, on: date) -> bool:
    return any(_age(p.birth_date, on) < ADULT_AGE for p in participants)


def _age(born: date, day: date) -> int:
    return day.year - born.year - ((day.month, day.day) < (born.month, born.day))


@transaction.atomic
def submit(data: RequestData, org) -> BookingRequest:
    """Uloží žádost. Kapacitu termínu hlídá pod zámkem – dva naráz ji nepřeplní."""
    slot = (Slot.objects.select_for_update()
            .filter(pk=data.slot_id, organization=org, is_active=True,
                    start__gt=timezone.now()).first())
    if slot is None:
        raise BookingError("Vybraný termín už není k dispozici. Vyberte prosím jiný.")
    if slot.free() < len(data.participants):
        raise BookingError(f"Na vybraný termín zbývá jen {slot.free()} míst. "
                           f"Vyberte prosím jiný termín, nebo nás kontaktujte.")
    offers = list(Offer.objects.filter(pk__in=data.offer_ids, organization=org, is_active=True))
    if not offers:
        raise BookingError("Vyberte prosím aspoň jeden test nebo balíček.")
    if not data.consent_testing:
        raise BookingError("Bez souhlasu s testováním a zpracováním údajů objednávku nelze přijmout.")
    if has_minors(data.participants, slot.start.date()) and not data.consent_guardian:
        raise BookingError("Mezi účastníky je nezletilý – je potřeba souhlas zákonného zástupce.")

    request = BookingRequest(
        organization=org, kind=data.kind, slot=slot,
        status=(BookingRequest.Status.VERIFY if settings.BOOKING_VERIFY_EMAIL
                else BookingRequest.Status.NEW),
        price_total=sum(o.price for o in offers) * len(data.participants),
        team_name=data.team_name, sport_name=data.sport_name, category=data.category,
        goal=data.goal, goal_note=data.goal_note, level=data.level,
        season_phase=data.season_phase, consent_testing=data.consent_testing,
        consent_handover=data.consent_handover, consent_guardian=data.consent_guardian,
    )
    request.set_contact(data.contact_name, data.email, data.phone)
    if request.status == BookingRequest.Status.NEW:
        request.verified_at = timezone.now()
    request.save()
    request.offers.set(offers)
    for p in data.participants:
        participant = Participant(request=request, sex=p.sex or "X")
        participant.set_data(p.first_name, p.last_name, p.birth_date, p.injury)
        participant.save()
    return request


def verify(request: BookingRequest) -> bool:
    """Klient klikl na odkaz v e-mailu. Teprve teď žádost uvidí laboratoř."""
    if request.status != BookingRequest.Status.VERIFY:
        return False
    with transaction.atomic():
        slot = Slot.objects.select_for_update().get(pk=request.slot_id)
        if slot.free() < request.participants.count():
            raise BookingError("Termín se mezitím zaplnil. Kontaktujte nás prosím, "
                               "domluvíme jiný.")
        request.status = BookingRequest.Status.NEW
        request.verified_at = timezone.now()
        request.save(update_fields=["status", "verified_at"])
    return True


# --- schválení -------------------------------------------------------------

MATCH_ORDER = [
    (SubjectExternalId.System.NAME_BIRTH, "jméno a datum narození"),
    (SubjectExternalId.System.NAME, "jméno"),
]


def match(participant: Participant, org) -> tuple[Subject | None, str]:
    """Existující sportovec k účastníkovi. Shoda jen podle jména platí, jen když je jediná."""
    ids = identity_ids(participant.full_name, participant.birth_date)
    for system, label in MATCH_ORDER:
        if not ids.get(system):
            continue
        found = list(Subject.objects.filter(organization=org, external_ids__system=system,
                                            external_ids__value=ids[system]).distinct()[:2])
        if len(found) == 1:
            return found[0], label
    return None, ""


def _sport(org, name: str):
    name = (name or "").strip()
    if not name:
        return None
    sport = Sport.objects.filter(organization=org, name__iexact=name).first()
    if sport:
        return sport
    code = slugify(name)[:32] or "sport"
    base, n = code, 2
    while Sport.objects.filter(organization=org, code=code).exists():
        code, n = f"{base[:29]}-{n}", n + 1
    return Sport.objects.create(organization=org, name=name, code=code)


def _new_subject(request, participant, sport) -> Subject:
    from apps.ingest.services import _next_subject_code

    subject = Subject.objects.create(
        organization=request.organization, code=_next_subject_code(request.organization),
        sport=sport, sex=participant.sex, birth_year=participant.birth_date.year,
        category=request.category, level=request.level,
        note=f"Založeno z objednávky {request.number}",
    )
    identity = SubjectIdentity(subject=subject)
    identity.set_names(participant.first_name, participant.last_name)
    if request.kind == BookingRequest.Kind.INDIVIDUAL:
        from apps.subjects import crypto

        identity.email_enc = crypto.encrypt(request.email)
        identity.phone_enc = crypto.encrypt(request.phone)
    identity.save()
    return subject


def _session_note(request, participant) -> str:
    parts = [f"Objednávka {request.number}: {request.get_goal_display().lower()}"]
    if request.goal_note:
        parts.append(request.goal_note)
    if injury := participant.injury:
        parts.append(f"Zranění (uvedl klient): {injury}")
    return ". ".join(parts)


@transaction.atomic
def approve(request: BookingRequest, user, *, note: str = "") -> list[Participant]:
    """Založí sportovce, souhlasy a testovací dny. Vrací účastníky s vazbami."""
    if request.status != BookingRequest.Status.NEW:
        raise BookingError("Schválit lze jen novou žádost.")
    org = request.organization
    sport = _sport(org, request.sport_name)
    protocols = request.protocols()
    day = timezone.localtime(request.slot.start).date()
    today = timezone.localdate()

    participants = list(request.participants.all())
    for participant in participants:
        subject, _ = match(participant, org)
        if subject is None:
            subject = _new_subject(request, participant, sport)
        for system, value in identity_ids(participant.full_name, participant.birth_date).items():
            SubjectExternalId.objects.get_or_create(subject=subject, system=system, value=value)

        scopes = [Consent.Scope.TESTING]
        if request.consent_handover:
            scopes.append(Consent.Scope.REPORT_HANDOVER)
        for scope in scopes:
            if not Consent.has(subject, scope):
                Consent.objects.create(subject=subject, scope=scope, granted_on=today,
                                       note=f"Objednávka {request.number}")

        session, created = TestSession.objects.get_or_create(
            organization=org, subject=subject, date=day,
            defaults={"location": request.slot.location, "season_phase": request.season_phase,
                      "note": _session_note(request, participant)})
        if not created and not session.note:
            session.note = _session_note(request, participant)
            session.save(update_fields=["note"])
        planning.ensure_runs(session, protocols)

        participant.subject, participant.session = subject, session
        participant.save(update_fields=["subject", "session"])

    request.status = BookingRequest.Status.APPROVED
    request.decided_at, request.decided_by = timezone.now(), user
    request.decision_note = note
    request.save(update_fields=["status", "decided_at", "decided_by", "decision_note"])
    return participants


@transaction.atomic
def reject(request: BookingRequest, user, *, note: str = ""):
    if request.status not in (BookingRequest.Status.NEW, BookingRequest.Status.VERIFY):
        raise BookingError("Zamítnout lze jen nevyřízenou žádost.")
    request.status = BookingRequest.Status.REJECTED
    request.decided_at, request.decided_by = timezone.now(), user
    request.decision_note = note
    request.save(update_fields=["status", "decided_at", "decided_by", "decision_note"])


# --- e-maily ---------------------------------------------------------------

def _absolute(http_request, name, *args) -> str:
    return http_request.build_absolute_uri(reverse(name, args=args))


def notify(http_request, request: BookingRequest, event: str) -> bool:
    """
    E-mail klientovi. Když se nepodaří (není nastavený server), objednávka
    tím nepadá – vrací False a aplikace to řekne laborantovi.
    """
    slot = timezone.localtime(request.slot.start)
    when = f"{slot:%d.%m.%Y v %H:%M}{', ' + request.slot.location if request.slot.location else ''}"
    status_url = _absolute(http_request, "booking_status", request.token)
    texts = {
        "overit": (
            "Potvrďte prosím objednávku testování",
            f"Dobrý den,\n\ndostali jsme objednávku testování na termín {when}.\n"
            f"Potvrďte ji prosím kliknutím na odkaz:\n"
            f"{_absolute(http_request, 'booking_verify', request.token)}\n\n"
            f"Pokud jste objednávku neodeslali vy, e-mail ignorujte."),
        "prijata": (
            f"Objednávka {request.number} přijata",
            f"Dobrý den,\n\nděkujeme za objednávku testování na termín {when}.\n"
            f"Laboratoř ji zkontroluje a potvrdí. Stav objednávky: {status_url}"),
        "schvalena": (
            f"Objednávka {request.number} potvrzena",
            f"Dobrý den,\n\nvaše testování je potvrzené na termín {when}.\n"
            + (f"\n{request.decision_note}\n" if request.decision_note else "")
            + f"\nStav objednávky: {status_url}"),
        "zamitnuta": (
            f"Objednávka {request.number}",
            f"Dobrý den,\n\nobjednávku na termín {when} bohužel nemůžeme potvrdit.\n"
            + (f"\n{request.decision_note}\n" if request.decision_note else "")
            + "\nNapište nám prosím, domluvíme jiný termín."),
    }
    subject, body = texts[event]
    try:
        send_mail(subject, body + "\n\nLaboratoř funkční diagnostiky FTVS UK",
                  None, [request.email])
        return True
    except Exception:  # SMTP nedostupné, špatná adresa – objednávka platí dál
        return False
