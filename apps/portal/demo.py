"""Ukázkové účty portálu pro veřejnou ukázku (sportovec, rodič, trenér)."""

from django.conf import settings

from apps.core.models import Role, User

USERNAMES = ("sportovec", "rodic", "trener")


def create_demo_accounts(org, password) -> list[str]:
    """
    Účty se stejným heslem jako admin: sportovec (FTVS-0001), rodič
    (zástupce FTVS-0002) a trenér (sdílení s 0001 a 0003, žádost u 0002).
    Jména jsou vymyšlená; bez šifrovacího klíče zůstanou jen kódy.

    Zakládá jen chybějící účty a na existující nesahá – jde pouštět při
    každé aktualizaci ukázky. Vrací jména nově založených účtů.
    """
    from apps.subjects import accounts
    from apps.subjects.models import Guardian, Subject, SubjectIdentity

    subjects = {s.code: s for s in Subject.objects.filter(
        organization=org, code__in=["FTVS-0001", "FTVS-0002", "FTVS-0003"])}
    if len(subjects) < 3:
        return []
    names = {"FTVS-0001": ("Jana", "Ukázková"), "FTVS-0002": ("Tomáš", "Ukázkový"),
             "FTVS-0003": ("Petra", "Vzorová")}
    for code, (first, last) in names.items():
        identity, _ = SubjectIdentity.objects.get_or_create(subject=subjects[code])
        if settings.IDENTITY_ENCRYPTION_KEY and not identity.first_name_enc:
            identity.set_names(first, last)
            identity.save()

    created = []

    def make(username, role, **extra):
        if User.objects.filter(username=username).exists():
            return None
        user = User(username=username, email=f"{username}@example.cz", organization=org,
                    role=role, **extra)
        user.set_password(password)
        user.save()
        created.append(username)
        return user

    if athlete := make("sportovec", Role.ATHLETE):
        identity = SubjectIdentity.objects.get(subject=subjects["FTVS-0001"])
        if identity.user_id is None:
            identity.user = athlete
            identity.save(update_fields=["user"])
    if parent := make("rodic", Role.ATHLETE):
        Guardian.objects.get_or_create(
            identity=SubjectIdentity.objects.get(subject=subjects["FTVS-0002"]), user=parent)
    if coach := make("trener", Role.COACH, first_name="Karel", last_name="Ukázkový"):
        by = User.objects.filter(username="sportovec").first() or coach
        for code in ("FTVS-0001", "FTVS-0003"):
            accounts.start_sharing(subjects[code], coach, by=by)
        accounts.request_sharing(subjects["FTVS-0002"], coach, by=coach)
    return created
