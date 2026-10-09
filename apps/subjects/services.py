"""
Ruční založení a úprava sportovce v aplikaci.

Jméno, datum narození a kontakt jdou do šifrované identity, provozní
záznam nese jen kód, sport, kategorii a rok narození. Navíc se uloží
otisky jména (a jména s datem narození), aby ho pozdější export z VALD
nebo jiného přístroje poznal a nezaložil podruhé.
"""

from django.db import transaction
from django.utils import timezone

from .models import Consent, Sport, Subject, SubjectExternalId, SubjectIdentity

# Souhlasy, které se nabízejí ve formuláři (genetika a mikrobiom se tu nesbírají).
FORM_CONSENTS = [Consent.Scope.TESTING, Consent.Scope.LONGITUDINAL,
                 Consent.Scope.REPORT_HANDOVER, Consent.Scope.RESEARCH]


def _tokens(text: str) -> frozenset:
    from apps.ingest.adapters.vald import normalize_name

    return frozenset(normalize_name(text).split())


def find_duplicates(organization, first_name, last_name, birth_date, *, exclude=None):
    """
    Sportovci se stejným jménem (pořadí slov a diakritika nehrají roli).

    Vrací (stejné jméno i datum narození, jen stejné jméno). U sportovce
    bez uloženého data narození se porovná aspoň rok.
    """
    wanted = _tokens(f"{first_name} {last_name}")
    exact, same_name = [], []
    identities = (SubjectIdentity.objects.filter(subject__organization=organization)
                  .select_related("subject"))
    if exclude is not None:
        identities = identities.exclude(subject=exclude)
    for identity in identities:
        try:
            if _tokens(identity.full_name) != wanted:
                continue
            birth = identity.birth_date
        except Exception:  # jiný klíč, poškozený záznam
            continue
        subject = identity.subject
        if birth == birth_date or (birth is None and subject.birth_year == birth_date.year):
            exact.append(subject)
        else:
            same_name.append(subject)
    return exact, same_name


def _sport(organization, data):
    if name := (data.get("new_sport") or "").strip():
        from django.utils.text import slugify

        sport = Sport.objects.filter(organization=organization, name__iexact=name).first()
        if sport:
            return sport
        code, base, n = slugify(name)[:32] or "sport", slugify(name)[:29] or "sport", 2
        while Sport.objects.filter(organization=organization, code=code).exists():
            code, n = f"{base}-{n}", n + 1
        return Sport.objects.create(organization=organization, name=name, code=code)
    return data.get("sport")


def _learn_name(subject, first_name, last_name, birth_date):
    from apps.ingest.adapters.vald import identity_ids

    for system, value in identity_ids(f"{first_name} {last_name}", birth_date).items():
        SubjectExternalId.objects.get_or_create(subject=subject, system=system, value=value)


def _consents(subject, wanted: set[str]):
    today = timezone.localdate()
    valid = {c.scope: c for c in subject.consents.all() if c.is_valid}
    for scope in FORM_CONSENTS:
        if scope in wanted and scope not in valid:
            Consent.objects.create(subject=subject, scope=scope, granted_on=today,
                                   note="zadáno v aplikaci")
        elif scope not in wanted and scope in valid:
            valid[scope].revoked_on = today
            valid[scope].save(update_fields=["revoked_on", "updated_at"])


def _apply(subject, identity, organization, data):
    subject.sport = _sport(organization, data)
    subject.sex = data["sex"]
    subject.birth_year = data["birth_date"].year
    subject.category = data.get("category", "").strip()
    subject.level = data["level"]
    subject.dominant_side = data.get("dominant_side", "")
    subject.note = data.get("note", "").strip()
    subject.save()

    from . import crypto

    identity.subject = subject
    identity.set_names(data["first_name"].strip(), data["last_name"].strip())
    identity.set_birth_date(data["birth_date"])
    identity.email_enc = crypto.encrypt(data.get("email", "").strip())
    identity.phone_enc = crypto.encrypt(data.get("phone", "").strip())
    identity.save()
    _learn_name(subject, data["first_name"].strip(), data["last_name"].strip(),
                data["birth_date"])
    _consents(subject, set(data.get("consents", [])))


@transaction.atomic
def create_subject(organization, data) -> Subject:
    from apps.ingest.services import _next_subject_code

    subject = Subject(organization=organization, code=_next_subject_code(organization))
    _apply(subject, SubjectIdentity(), organization, data)
    return subject


@transaction.atomic
def update_subject(subject, data) -> Subject:
    identity = SubjectIdentity.objects.filter(subject=subject).first() or SubjectIdentity()
    _apply(subject, identity, subject.organization, data)
    return subject


def initial(subject) -> dict:
    """Hodnoty pro formulář úprav (dešifrovaná identita)."""
    data = {"sport": subject.sport_id, "sex": subject.sex, "category": subject.category,
            "level": subject.level, "dominant_side": subject.dominant_side,
            "note": subject.note,
            "consents": [c.scope for c in subject.consents.all() if c.is_valid]}
    identity = SubjectIdentity.objects.filter(subject=subject).first()
    if identity is not None:
        data.update(first_name=identity.first_name, last_name=identity.last_name,
                    birth_date=identity.birth_date, email=identity.email, phone=identity.phone)
    return data


# ---------------------------------------------------------------------------
# Deaktivace, smazání a anonymizace
# ---------------------------------------------------------------------------

class SubjectError(Exception):
    """Akci se sportovcem nejde provést – uživatel se musí dozvědět proč."""


def has_data(subject) -> bool:
    """Má sportovec naměřená data nebo zprávy? Pak ho smazat nejde."""
    return subject.sessions.exists() or subject.reports.exists()


def set_active(subject, active: bool) -> None:
    subject.is_active = active
    subject.save(update_fields=["is_active"])


@transaction.atomic
def delete_subject(subject) -> None:
    """
    Smazání – jen sportovec bez měření a zpráv (třeba založený omylem).
    Longitudinální data se nesmí ztratit omylem; s daty jen deaktivace
    nebo anonymizace.
    """
    if has_data(subject):
        raise SubjectError(f"Sportovce {subject.code} nelze smazat – má naměřená data nebo "
                           f"zprávy. Použijte deaktivaci, nebo anonymizaci (výmaz osobních "
                           f"údajů podle GDPR).")
    for consent in subject.consents.all():
        if consent.document:
            consent.document.delete(save=False)
    subject.delete()


@transaction.atomic
def anonymize(subject) -> list[str]:
    """
    Výmaz osobních údajů (GDPR): jméno, datum narození, kontakt, údaje
    z objednávek, identifikátory v přístrojích a podepsané dokumenty. Měření
    a zprávy zůstanou pod pseudonymním kódem – už je k člověku nic nepřiřadí.
    Vrací, co se smazalo (pro záznam a hlášku).
    """
    from apps.booking.models import BookingRequest, Participant
    from apps.ingest.models import StagedMeasurement

    done = []
    if SubjectIdentity.objects.filter(subject=subject).delete()[0]:
        done.append("jméno, datum narození a kontakt")
    if subject.external_ids.all().delete()[0] or subject.source_key:
        done.append("identifikátory v přístrojích a otisky jména")
    participants = list(Participant.objects.filter(subject=subject))
    if participants:
        Participant.objects.filter(subject=subject).update(
            first_name_enc="", last_name_enc="", birth_date_enc="", injury_enc="")
        # Objednávka jen pro tohoto člověka: kontakt a poznámka patří jemu.
        alone = [p.request_id for p in participants
                 if not Participant.objects.filter(request_id=p.request_id)
                 .exclude(subject=subject).exists()]
        BookingRequest.objects.filter(pk__in=alone).update(
            contact_name_enc="", email_enc="", phone_enc="", goal_note="")
        done.append("údaje z objednávek")
    if StagedMeasurement.objects.filter(subject=subject).exclude(subject_hint="").update(
            subject_hint="", subject_key=""):
        done.append("jméno v rozpracovaných importech")
    documents = [c for c in subject.consents.all() if c.document]
    for consent in documents:
        consent.document.delete(save=False)
        consent.save(update_fields=["document"])
    if documents:
        done.append("podepsané dokumenty souhlasů")
    subject.source_key = ""
    raw = raw_files_with(subject)
    if raw:
        done.append(f"POZOR: {raw} původních souborů z přístrojů obsahuje jméno dál – "
                    f"nemění se (jsou v nich i další sportovci); je-li třeba, smažte je ručně")
    subject.note = f"Osobní údaje vymazány {timezone.localdate():%d.%m.%Y} (anonymizace)."
    subject.is_active = False
    subject.save(update_fields=["source_key", "note", "is_active"])
    return done


def raw_files_with(subject) -> int:
    """Původní exporty z přístrojů, ve kterých sportovec je (jméno v nich zůstává)."""
    from django.db.models import Q

    from apps.measurements.models import RawFile

    return (RawFile.objects.filter(Q(import_batches__staged__subject=subject)
                                   | Q(protocol_run__session__subject=subject))
            .distinct().count())
