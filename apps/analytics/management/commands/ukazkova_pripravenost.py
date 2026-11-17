"""
Ukázkové výchozí měření a ranní dotazník pro zkušební provoz.

Prvním sportovcům (podle kódu), kteří mají aspoň tři měřené testovací dny,
nastaví výchozí měření na první z nich a k poslednímu dni vyplní ranní
dotazník připravenosti s fiktivními odpověďmi – jeden sportovec vychází
v semaforu červeně, jeden oranžově, ostatní zeleně. Na kartě sportovce, ve
zprávě, v týmovém přehledu a u testovacího dne je pak vidět, co výchozí
měření a semafor dělají.

Kdo výchozí měření nebo ranní dotazník k tomu dni už má, zůstane beze
změny. Běží sám při aktualizaci zkušebního provozu (DEMO_MODE); mimo ukázku
jen pro vyjmenované sportovce (--kody), aby fiktivní odpovědi nikdy nevznikly
u skutečného sportovce omylem.
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from apps.analytics import baseline
from apps.core.models import Organization
from apps.measurements import questionnaires
from apps.subjects.models import Subject

LABEL = "ukázka – první měření"
# spánek (h), ospalost KSS 1–9, únava 0–10, bolest svalů 1–5
ANSWERS = [
    {"spanek_h": 4.5, "kss": 8, "unava": 8, "bolest_svalu": 4},   # červená
    {"spanek_h": 5.5, "kss": 7, "unava": 5, "bolest_svalu": 2},   # oranžová
    {"spanek_h": 7.5, "kss": 3, "unava": 2, "bolest_svalu": 1},   # zelená
]


class Command(BaseCommand):
    help = ("Ukázkové výchozí měření a ranní dotazník připravenosti (fiktivní odpovědi) "
            "prvním sportovcům; jen při DEMO_MODE, jinde jen pro --kody.")

    def add_arguments(self, parser):
        parser.add_argument("--pocet", type=int, default=5, help="Kolika sportovcům.")
        parser.add_argument("--kody", nargs="+", default=None,
                            help="Kódy sportovců; mimo DEMO_MODE povinné.")

    def handle(self, *args, pocet=5, kody=None, **options):
        if not settings.DEMO_MODE and not kody:
            self.stdout.write("Jen v ukázce (DEMO_MODE=True) – nic se nezměnilo. Mimo ukázku "
                              "zadejte sportovce: --kody FTVS-0001 FTVS-0003")
            return
        org = Organization.objects.order_by("pk").first()
        questionnaire = questionnaires.questionnaire("ranni", org)
        if org is None or questionnaire is None:
            self.stdout.write("Chybí pracoviště nebo ranní dotazník (seed_catalog) – nic se "
                              "nezměnilo.")
            return
        questions = {q.code: q for q in questionnaire.questions.all()}
        subjects = (Subject.objects.filter(organization=org, is_active=True)
                    .annotate(dnu=Count("sessions", distinct=True,
                                        filter=Q(sessions__protocol_runs__trials__measurements__isnull=False)))
                    .filter(dnu__gte=3).order_by("code"))
        if kody:
            subjects = subjects.filter(code__in=kody)
            pocet = len(kody)
        set_baselines = filled = 0
        for index, subject in enumerate(subjects[:pocet]):
            days = baseline.measured_days(subject)        # od nejnovějšího
            if subject.baseline_date is None:
                baseline.set_baseline(subject, days[-1], LABEL)
                set_baselines += 1
            last = subject.sessions.get(date=days[0])
            if last.responses.filter(questionnaire__code="ranni").exists():
                self.stdout.write(f"{subject.code}: ranní dotazník k {last.date:%d.%m.%Y} už je.")
                continue
            answers = ANSWERS[min(index, len(ANSWERS) - 1)]
            questionnaires.save(last, questionnaire,
                                {questions[code]: value for code, value in answers.items()
                                 if code in questions},
                                source="sportovec")
            filled += 1
            self.stdout.write(f"{subject.code}: výchozí měření {subject.baseline_date:%d.%m.%Y}, "
                              f"ranní dotazník k {last.date:%d.%m.%Y}.")
        self.stdout.write(f"Ukázková připravenost: výchozích měření {set_baselines}, "
                          f"vyplněných ranních dotazníků {filled}.")
