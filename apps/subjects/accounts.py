"""
Účty sportovců a zákonných zástupců, pozvánky a sdílení s trenérem.

Účet vzniká jen z pozvánky, kterou vystaví laboratoř (jinak by se kdokoli
mohl zaregistrovat „jako“ sportovec). Sdílení s trenérem potvrzuje
sportovec nebo zástupce ve svém účtu; laboratoř i trenér o něj mohou
jen požádat.
"""

import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.models import Role, User

from .models import AccountInvitation, Consent, Guardian, Sharing, SubjectIdentity

INVITATION_DAYS = 30


class AccountError(Exception):
    """Srozumitelná chyba pro uživatele."""


# --- pozvánky ----------------------------------------------------------------

def create_invitation(subject, kind: str, *, user) -> AccountInvitation:
    return AccountInvitation.objects.create(
        subject=subject, kind=kind, token=secrets.token_urlsafe(32), created_by=user,
        expires_at=timezone.now() + timedelta(days=INVITATION_DAYS))


def valid_invitation(token: str):
    invitation = (AccountInvitation.objects.filter(token=token)
                  .select_related("subject", "subject__organization").first())
    return invitation if invitation is not None and invitation.is_valid else None


@transaction.atomic
def accept_invitation(invitation, user):
    """Připojí účet k sportovci podle druhu pozvánky a pozvánku spotřebuje."""
    if user.role != Role.ATHLETE:
        raise AccountError("Pozvánku může přijmout jen účet sportovce nebo zákonného zástupce.")
    identity, _ = SubjectIdentity.objects.get_or_create(subject=invitation.subject)
    if invitation.kind == AccountInvitation.Kind.ATHLETE:
        if identity.user_id and identity.user_id != user.pk:
            raise AccountError("Tento sportovec už svůj účet má.")
        identity.user = user
        identity.save(update_fields=["user", "updated_at"])
    else:
        Guardian.objects.get_or_create(identity=identity, user=user)
    invitation.used_at, invitation.used_by = timezone.now(), user
    invitation.save(update_fields=["used_at", "used_by", "updated_at"])
    return invitation.subject


@transaction.atomic
def register(invitation, *, email: str, password: str) -> User:
    """Nový účet z pozvánky. Přihlašovací jméno je e‑mail."""
    email = email.strip().lower()
    if User.objects.filter(username__iexact=email).exists():
        raise AccountError("Účet s tímto e‑mailem už existuje. Přihlaste se do něj "
                           "a pozvánku otevřete znovu – připojí se k němu.")
    user = User(username=email, email=email, role=Role.ATHLETE,
                organization=invitation.subject.organization)
    user.set_password(password)
    user.save()
    accept_invitation(invitation, user)
    return user


def send_invitation(invitation, url: str, email: str = "") -> bool:
    """E‑mail s odkazem na uložený kontakt sportovce. Bez nastaveného serveru nic."""
    if not settings.EMAIL_HOST:
        return False
    if not email:
        identity = SubjectIdentity.objects.filter(subject=invitation.subject).first()
        email = identity.email if identity is not None else ""
    if not email:
        return False
    from django.core.mail import send_mail

    send_mail(
        "Přístup k výsledkům funkčního testování",
        "Dobrý den,\n\nlaboratoř FTVS UK vám zřizuje přístup k výsledkům testování. "
        f"Účet si založíte tímto odkazem (platí {INVITATION_DAYS} dní):\n\n{url}\n\n"
        "Laboratoř funkční diagnostiky FTVS UK",
        None, [email])
    return True


# --- přihlášení odkazem na e‑mail ------------------------------------------------

LINK_SALT = "prihlaseni-odkazem"
LINK_MAX_AGE = 30 * 60


def identities_with_email(email: str) -> list:
    """Identity s tímto uloženým e‑mailem (šifrovaný, porovnává se v paměti)."""
    email = email.strip().lower()
    if not email or not settings.IDENTITY_ENCRYPTION_KEY:
        return []
    found = []
    for identity in (SubjectIdentity.objects.exclude(email_enc="")
                     .select_related("subject").filter(subject__is_active=True)):
        try:
            if identity.email.strip().lower() == email:
                found.append(identity)
        except Exception:   # jiný klíč, poškozený záznam
            continue
    return found


def login_link_token(user) -> str:
    """Podepsaný odkaz; změna hesla ho zneplatní (nese kousek otisku hesla)."""
    from django.core import signing

    return signing.dumps({"u": user.pk, "h": user.password[-12:]}, salt=LINK_SALT)


def user_from_login_link(token: str):
    from django.core import signing

    try:
        data = signing.loads(token, salt=LINK_SALT, max_age=LINK_MAX_AGE)
    except signing.BadSignature:
        return None
    user = User.objects.filter(pk=data.get("u"), role=Role.ATHLETE, is_active=True).first()
    if user is None or user.password[-12:] != data.get("h"):
        return None
    return user


def send_email_link(email: str, *, login_url, register_url, user=None) -> bool:
    """
    Druhá cesta k účtu, bez pozvánky od laboratoře. Komu patří e‑mail:
    - účet sportovce/zástupce → odkaz pro přihlášení (30 minut),
    - jen uložený kontakt sportovce → pozvánka k založení účtu (nezletilému
      pro zákonného zástupce),
    - nikomu → nic; stránka odpoví stejně, aby adresy nešlo zkoušet.
    """
    from django.core.mail import send_mail

    email = email.strip().lower()
    if not settings.EMAIL_HOST or not email:
        return False
    account = User.objects.filter(role=Role.ATHLETE, is_active=True, email__iexact=email).first()
    if account is not None:
        send_mail(
            "Přihlášení k výsledkům testování",
            "Dobrý den,\n\npřihlásíte se tímto odkazem (platí 30 minut):\n\n"
            f"{login_url(login_link_token(account))}\n\nPokud jste o odkaz nežádali, "
            "e-mail ignorujte.\n\nLaboratoř funkční diagnostiky FTVS UK",
            None, [email])
        return True

    identities = identities_with_email(email)
    if not identities:
        return False
    lines = []
    for identity in identities:
        subject = identity.subject
        valid = [i for i in subject.invitations.all() if i.is_valid]
        if valid:
            invitation = valid[0]
        else:
            age = subject.age_on()
            kind = (AccountInvitation.Kind.GUARDIAN if age is not None and age < 18
                    else AccountInvitation.Kind.ATHLETE)
            invitation = create_invitation(subject, kind, user=user)
        who = ("zákonný zástupce – " if invitation.kind == AccountInvitation.Kind.GUARDIAN
               else "") + (identity.full_name or subject.code)
        lines.append(f"- {who}: {register_url(invitation.token)}")
    send_mail(
        "Přístup k výsledkům funkčního testování",
        "Dobrý den,\n\nk tomuto e-mailu laboratoř FTVS UK eviduje testovaného sportovce. "
        f"Účet si založíte odkazem (platí {INVITATION_DAYS} dní, jde použít jednou):\n\n"
        + "\n".join(lines)
        + "\n\nPokud jste o přístup nežádali, e-mail ignorujte.\n\n"
        "Laboratoř funkční diagnostiky FTVS UK",
        None, [email])
    return True


# --- sdílení s trenérem --------------------------------------------------------

def coaches(organization):
    return (User.objects.filter(organization=organization, role=Role.COACH, is_active=True)
            .order_by("last_name", "first_name", "username"))


def coach_label(user) -> str:
    return user.get_full_name() or user.get_username()


def request_sharing(subject, coach, *, by) -> Sharing:
    """Žádost laboratoře nebo trenéra; platná bude až po potvrzení v účtu sportovce."""
    sharing, _ = Sharing.objects.get_or_create(subject=subject, coach=coach)
    if sharing.status == Sharing.Status.ACTIVE:
        return sharing
    sharing.status, sharing.requested_by = Sharing.Status.REQUESTED, by
    sharing.decided_by = sharing.decided_at = None
    sharing.save()
    return sharing


@transaction.atomic
def confirm_sharing(sharing, *, by) -> Sharing:
    """Potvrzení v účtu: vzniká souhlas se sdílením, který jde kdykoli odvolat."""
    today = timezone.localdate()
    sharing.consent = Consent.objects.create(
        subject=sharing.subject, scope=Consent.Scope.COACH, granted_on=today,
        note=f"trenér {coach_label(sharing.coach)}, potvrzeno v účtu ({by.get_username()})")
    sharing.status, sharing.decided_by, sharing.decided_at = (
        Sharing.Status.ACTIVE, by, timezone.now())
    sharing.save()
    return sharing


def start_sharing(subject, coach, *, by) -> Sharing:
    """Sdílení, které si sportovec zapne sám – je tím rovnou potvrzené."""
    sharing, _ = Sharing.objects.get_or_create(subject=subject, coach=coach,
                                               defaults={"requested_by": by})
    if sharing.status == Sharing.Status.ACTIVE:
        return sharing
    return confirm_sharing(sharing, by=by)


def decline_sharing(sharing, *, by) -> Sharing:
    sharing.status, sharing.decided_by, sharing.decided_at = (
        Sharing.Status.DECLINED, by, timezone.now())
    sharing.save()
    return sharing


@transaction.atomic
def revoke_sharing(sharing, *, by) -> Sharing:
    if sharing.consent_id and sharing.consent.revoked_on is None:
        sharing.consent.revoked_on = timezone.localdate()
        sharing.consent.save(update_fields=["revoked_on", "updated_at"])
    sharing.status, sharing.decided_by, sharing.decided_at = (
        Sharing.Status.REVOKED, by, timezone.now())
    sharing.save()
    return sharing


def accounts_of(subject) -> dict:
    """Kdo má k sportovci účet: vlastní účet a zákonní zástupci."""
    identity = SubjectIdentity.objects.filter(subject=subject).select_related("user").first()
    return {
        "athlete": identity.user if identity is not None else None,
        "guardians": [g.user for g in Guardian.objects.filter(identity=identity)
                      .select_related("user")] if identity is not None else [],
        "invitations": [i for i in subject.invitations.all() if i.is_valid],
    }


def deactivate_orphans(users) -> int:
    """Účty sportovce/zástupce, kterým nezbyl žádný sportovec, se vypnou."""
    from .access import subject_ids_for

    count = 0
    for user in users:
        if user is not None and user.role == Role.ATHLETE and not subject_ids_for(user):
            user.is_active = False
            user.save(update_fields=["is_active"])
            count += 1
    return count


def account_users(subject) -> list:
    identity = SubjectIdentity.objects.filter(subject=subject).select_related("user").first()
    if identity is None:
        return []
    return ([identity.user] if identity.user_id else []) + [
        g.user for g in Guardian.objects.filter(identity=identity).select_related("user")]
