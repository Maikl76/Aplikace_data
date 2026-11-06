"""
Nastavení: stav pracoviště (nastavovací kroky všech částí na jednom místě)
a kategorie nastavení jako dlaždice. Odpovědný člověk tu vidí, co ještě
chybí, a každý krok ho vede přímo tam. Administrace Djanga je jen zadní
vrátka „pro pokročilé“.
"""

from django.conf import settings
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .steps import step


def workplace_steps(user) -> list[dict]:
    from apps.booking.models import Offer, Slot
    from apps.catalog.models import DeviceFormat
    from apps.catalog.steps import catalog_status
    from apps.genetics import crypto as genetics_crypto
    from apps.genetics.setup_views import setup_steps as genetics_steps
    from apps.ingest.models import ImportBatch
    from apps.reports import llm

    from .models import User
    from .roles import COLLEAGUE_ROLES

    org = user.organization
    shared = Q(organization__isnull=True) | Q(organization=org)

    colleagues = (User.objects.filter(organization=org, role__in=COLLEAGUE_ROLES, is_active=True)
                  .exclude(pk=user.pk).count())

    c = catalog_status(user)
    sports, sports_without = c["sports"], c["sports_without"]
    protocols, no_metrics, no_key = c["protocols"], c["no_metrics"], c["no_key"]
    key_metrics, no_mdc = c["key_metrics"], c["no_mdc"]

    devices = DeviceFormat.objects.filter(shared, is_active=True).count()
    imported = ImportBatch.objects.for_user(user).filter(status=ImportBatch.Status.COMMITTED).exists()
    norms, rules = c["norms"], c["rules"]
    offers = Offer.objects.for_user(user).filter(is_active=True).exists()
    slots = Slot.objects.for_user(user).filter(is_active=True, start__gte=timezone.now()).exists()
    genetics = [g for g in genetics_steps(user) if not g.get("optional")]
    genetics_done = sum(1 for g in genetics if g["done"])
    keys_ok = bool(settings.IDENTITY_ENCRYPTION_KEY) and genetics_crypto.configured()
    model = llm.describe()
    model_text = (model["blocked"] if model["blocked"] else
                  f"Jazykový model: cloudový ({model['host']}), jen pro zkušební provoz "
                  "se smyšlenými daty." if model["remote"] and model["enabled"] else
                  "Jazykový model je zapnutý (lokální)." if model["enabled"] else
                  "Jazykový model je vypnutý, souhrny píše šablona.")

    return [
        step(1, "Kolegové", colleagues > 0,
             (f"{colleagues} účtů kolegů." if colleagues else
              "Zatím jen vy. Každý kolega má mít vlastní účet s rolí."),
             url=reverse("colleagues"), button="Kolegové", admin_only=True),
        step(2, "Sporty a baterie", bool(sports) and not sports_without,
             (f"{len(sports) - len(sports_without)} z {len(sports)} sportů má baterii testů."
              + (" Bez baterie se testovací den nepředvyplní." if sports_without else "")
              if sports else "Založte sport a jeho baterii: které testy se měří a v jakém pořadí."),
             url=reverse("sport_list"), button="Sporty a testy"),
        step(3, "Testy a klíčové ukazatele", bool(protocols) and not no_metrics and not no_key,
             (" ".join(filter(None, [
                 f"{len(no_metrics)} testů bez ukazatelů." if no_metrics else "",
                 f"{len(no_key)} testů bez klíčového ukazatele – ten jde na kartu sportovce "
                 "a do týmového přehledu." if no_key else ""]))
              or (f"{len(protocols)} testů v bateriích, každý má klíčový ukazatel."
                  if protocols else "Testy přibudou s bateriemi.")),
             url=reverse("test_list"), button="Testy"),
        step(4, "MDC u klíčových ukazatelů", bool(key_metrics) and not no_mdc,
             (f"{len(no_mdc)} z {len(key_metrics)} klíčových ukazatelů nemá MDC – bez něj zpráva "
              "neřekne „zlepšení“, jen že změnu nelze odlišit od chyby měření."
              if no_mdc else (f"Všech {len(key_metrics)} klíčových ukazatelů má MDC."
                              if key_metrics else "Nejdřív klíčové ukazatele.")),
             url=reverse("mdc_settings"), button="Doplnit MDC", admin_only=True),
        step(5, "Přístroje a import", devices > 0 or imported,
             (f"{devices} přístrojů s profilem" + (", import už proběhl." if imported else ".")
              if devices or imported else
              "Exporty z VALD aplikace pozná sama; další přístroj přidáte průvodcem v Importu."),
             url=reverse("import_list"), button="Import", optional=True),
        step(6, "Normy a pravidla", norms > 0 or rules > 0,
             (f"{norms} norem, {rules} aktivních pravidel." if norms or rules else
              "Bez norem zpráva neukáže postavení vůči referenci; pravidla dávají nálezy "
              "a doporučení. Zapíná je ten, kdo za práh ručí."),
             url=reverse("norms_settings"), button="Normy a pravidla", optional=True),
        step(7, "Objednávky", offers and slots,
             ("Nabídka i volné termíny jsou vypsané." if offers and slots else
              "Klienti se objednávají sami, když je nabídka a volné termíny."),
             url=reverse("booking_offers"), button="Nabídka a termíny", optional=True),
        step(8, "Genetika", genetics_done == len(genetics),
             f"{genetics_done} z {len(genetics)} kroků nastavení hotových.",
             url=reverse("genetics_home"), button="Genetika", optional=True),
        step(9, "Klíče a model", keys_ok and not model["blocked"],
             (("Šifrovací klíče jsou nastavené. " if keys_ok else
               "Chybí šifrovací klíč – jména nebo genotypy se neuloží. ") + model_text),
             url=reverse("about") + "#technika", button="Jak nastavit", admin_only=True),
    ]


def pending_count(user) -> int:
    return sum(1 for s in workplace_steps(user) if not s["done"] and not s["optional"])


def settings_sections(user) -> list[dict]:
    """Kategorie nastavení: kam co patří, stav z dat a tlačítko přímo tam."""
    from apps.catalog.models import ImportProfile, Questionnaire
    from apps.catalog.steps import catalog_status
    from apps.evidence.models import Article
    from apps.genetics.setup_views import setup_steps as genetics_steps
    from apps.subjects.models import Team

    from .models import Remark, User
    from .roles import COLLEAGUE_ROLES

    org = user.organization
    shared = Q(organization__isnull=True) | Q(organization=org)
    c = catalog_status(user)
    colleagues = (User.objects.filter(organization=org, role__in=COLLEAGUE_ROLES, is_active=True)
                  .exclude(pk=user.pk).count())
    teams = Team.objects.filter(organization=org).count()
    profiles = ImportProfile.objects.filter(shared, is_active=True).count()
    questionnaires = Questionnaire.objects.filter(shared).count()
    articles = Article.objects.filter(status=Article.Status.APPROVED).count()
    remarks = Remark.objects.filter(organization=org, status=Remark.Status.OPEN).count()
    genetics = [g for g in genetics_steps(user) if not g.get("optional")]

    def section(title, text, *, url="", button="", admin_only=False, later="", links=()):
        return {"title": title, "text": text, "url": url, "button": button,
                "admin_only": admin_only, "later": later, "links": list(links)}

    return [
        section("Pracoviště a kolegové",
                f"{org.name if org else 'bez pracoviště'}; {colleagues} účtů kolegů, {teams} týmů.",
                url=reverse("workplace_org"), button="Pracoviště a týmy", admin_only=True,
                links=[("Kolegové a role", reverse("colleagues"))]),
        section("Sporty a baterie testů",
                f"{len(c['sports'])} sportů, {len(c['sports']) - len(c['sports_without'])} "
                "s baterií testů.",
                url=reverse("sport_list"), button="Sporty a baterie"),
        section("Testy a ukazatele",
                f"{len(c['protocols'])} testů v bateriích; {len(c['key_metrics']) - len(c['no_mdc'])} "
                f"z {len(c['key_metrics'])} klíčových ukazatelů má MDC.",
                url=reverse("test_list"), button="Testy",
                links=[("MDC u ukazatelů", reverse("mdc_settings")),
                       ("Popisy pro klienta", reverse("client_texts"))]),
        section("Přístroje a import",
                f"{profiles} profilů importu (které sloupce exportu jsou které ukazatele).",
                url=reverse("import_list"), button="Import a přístroje",
                links=[("Sloupce exportů", reverse("import_profiles"))]),
        section("Normy a pravidla",
                f"{c['norms']} norem, {c['rules']} aktivních pravidel. Bez norem zpráva neukáže "
                "postavení vůči referenci; pravidla dávají nálezy a doporučení.",
                url=reverse("norms_settings"), button="Normy",
                links=[("Pravidla", reverse("rules_settings"))]),
        section("Dotazníky",
                f"{questionnaires} dotazníků: RPE po testu, dotazník genetiky, vlastní dotazníky "
                "k testovacímu dni.",
                url=reverse("questionnaires_settings"), button="Dotazníky"),
        section("Objednávky", "Nabídka testování a volné termíny, podle nich se klienti objednávají.",
                url=reverse("booking_offers"), button="Nabídka a termíny"),
        section("Články", f"{articles} článků v knihovně; zdroje pro normy, pravidla a karty.",
                url=reverse("article_list"), button="Knihovna článků"),
        section("Genetika",
                f"{sum(1 for g in genetics if g['done'])} z {len(genetics)} kroků nastavení; "
                "karty vede průvodce.",
                url=reverse("genetics_home"), button="Genetika"),
        section("Připomínky", f"{remarks} nevyřízených připomínek kolegů.",
                url=reverse("remarks"), button="Připomínky", admin_only=True),
        section("Klíče a model",
                "Šifrovací klíče a jazykový model; nastavuje se v souboru .env.",
                url=reverse("about") + "#technika", button="Jak nastavit", admin_only=True),
    ]
