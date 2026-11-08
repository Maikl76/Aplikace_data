"""Dotazník genetiky: druhy otázek, stavy nevím / netýká se, vyplnění v laboratoři i v portálu."""

from datetime import date

import pytest
from cryptography.fernet import Fernet
from django.test import Client

from apps.catalog.models import Question, Questionnaire
from apps.core.models import Organization, Role, User
from apps.genetics import seed, services
from apps.genetics.models import ContextScenario, Domain, GeneCard, GeneVariant
from apps.measurements import questionnaires
from apps.measurements.models import Answer, QuestionnaireResponse, TestSession
from apps.subjects.models import Subject, SubjectIdentity


@pytest.fixture
def org(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.GENETICS_ENCRYPTION_KEY = Fernet.generate_key().decode()
    seed.seed_genetics()
    return Organization.objects.create(name="FTVS", short_name="ftvs")


def _user(org, role, username):
    from apps.core import access

    user = User.objects.create(username=username, organization=org, role=role)
    if role == Role.LAB:
        # laborant genetiky: genetiku, vydávání a exporty mu zapne správce (Kolegové → Přístup)
        access.grant(user, genetics=True, reports_release=True, exports=True)
    client = Client()
    client.force_login(user)
    return user, client


def _adult(org, code="FTVS-0001"):
    subject = Subject.objects.create(organization=org, code=code)
    identity = SubjectIdentity(subject=subject)
    identity.set_names("Jana", "Nová")
    identity.set_birth_date(date(1990, 5, 1))
    identity.save()
    return subject


def test_seed_dotazniku_a_druhy_otazek(org):
    q = questionnaires.questionnaire("genetika")
    assert q is not None and q.questions.count() == len(seed.QUESTIONNAIRE["questions"])
    sections = [s["name"] for s in questionnaires.sections(q)]
    assert sections[0] == "Profil a cíle" and "Kofein" in sections and len(sections) == 8
    profile = Question.objects.get(questionnaire=q, code="vykonovy_profil")
    assert profile.kind == "choice" and profile.allow_unknown and not profile.allow_na
    assert profile.option_codes() == ["vytrvalost", "sila", "neutralni"]
    assert profile.option_label("sila").startswith("Dosahuji velmi dobrých")
    # Opakovaný seed nic nepřepíše.
    profile.text = "Upraveno v administraci"
    profile.save()
    seed.seed_genetics()
    assert Question.objects.get(pk=profile.pk).text == "Upraveno v administraci"
    assert Questionnaire.objects.filter(code="genetika").count() == 1


def test_odpovedi_podle_druhu_a_stavy(org):
    q = questionnaires.questionnaire("genetika")
    data = {
        "q_hlavni_sport": "  běh  ", "q_zamereni": "vykonnostni", "q_cil": "neexistuje",
        "q_praxe_let": "12,5", "q_jednotek_tydne": "x", "q_zmena_objemu__stav": "unknown",
        "q_zmena_objemu": "zvysil", "q_vykonovy_profil": "sila", "q_obtize_nyni": "0",
        "q_unava": "11", "q_stres": "4", "q_kofein_davky__stav": "na",
        "q_mleko_obtize__stav": "unknown", "q_bezlaktozove__stav": "na",
        "q_hmotnost_zamer": "udrzet",
    }

    class Data(dict):
        def getlist(self, key):
            return {"q_slozka": ["silova", "neexistuje"], "q_kofein_zdroje": []}.get(key, [])

    values = questionnaires.parse_answers(q, Data(data))
    by_code = {question.code: value for question, value in values.items()}
    assert by_code["hlavni_sport"] == {"text": "běh"}
    assert by_code["zamereni"] == {"choices": ["vykonnostni"]}
    assert "cil" not in by_code and "jednotek_tydne" not in by_code and "unava" not in by_code
    assert by_code["praxe_let"] == {"value": 12.5}
    assert by_code["zmena_objemu"] == {"state": "unknown"}           # stav má přednost
    assert by_code["slozka"] == {"choices": ["silova"]} and "kofein_zdroje" not in by_code
    assert by_code["obtize_nyni"] == {"value": 0.0} and by_code["stres"] == {"value": 4}
    assert by_code["kofein_davky"] == {"state": "na"}
    assert by_code["bezlaktozove"] == {"state": "na"}
    missing = [m.code for m in questionnaires.missing_required(q, values)]
    assert "cil" in missing and "jednotek_tydne" in missing and "cil_upresneni" not in missing

    subject = _adult(org)
    response = questionnaires.save_standalone(subject, q, values,
                                              source=QuestionnaireResponse.Source.SUBJECT)
    assert response.session is None and response.subject == subject
    answers = response.answers_by_code()
    assert answers["zmena_objemu"].state == "unknown" and answers["zmena_objemu"].display() == "nevím"
    assert answers["kofein_davky"].display() == "netýká se"
    assert answers["cil"].state == "missing" and answers["cil"].display() == "bez odpovědi"
    assert answers["praxe_let"].display() == "12.5 let" and answers["obtize_nyni"].display() == "ne"
    assert answers["slozka"].display() == "silová"
    assert answers["stres"].display() == "4"
    assert questionnaires.latest(subject, "genetika") == response
    # Další vyplnění je nový záznam; nejnovější vyhrává.
    second = questionnaires.save_standalone(subject, q, {}, source="operator")
    assert questionnaires.latest(subject, "genetika") == second
    assert QuestionnaireResponse.objects.filter(subject=subject).count() == 2


def test_rpe_k_testovacimu_dni_zustava_a_nese_sportovce(org):
    from apps.catalog.management.commands.seed_catalog import Command

    Command().handle(only_missing=True)
    subject = _adult(org)
    session = TestSession.objects.create(organization=org, subject=subject, date=date(2026, 5, 1))
    rpe = questionnaires.questionnaire("rpe", org)
    question = rpe.questions.first()
    response = questionnaires.save(session, rpe, {question: 7}, source="operator")
    assert response.subject == subject and response.answers.get().value == 7
    assert questionnaires.parse_answers(rpe, {"q_rpe": "7"}) == {question: {"value": 7}}
    assert questionnaires.summary(session)[0]["answers"][0]["value_txt"] == "7"
    assert questionnaires.latest(subject, "rpe") is None    # patří k testovacímu dni


def test_vyplneni_v_laboratori_a_v_portalu(org):
    lab, lab_client = _user(org, Role.LAB, "laborant")
    subject = _adult(org)
    page = lab_client.get(f"/genetika/sportovec/{subject.pk}/dotaznik/").content.decode()
    assert "Dotazník ke genetickému vyšetření" in page and "netýká se" in page
    assert 'name="q_vykonovy_profil"' in page and 'name="q_slozka"' in page
    data = {"q_hlavni_sport": "tenis", "q_zamereni": "rekreacni"}
    response = lab_client.post(f"/genetika/sportovec/{subject.pk}/dotaznik/", data)
    assert response.status_code == 200 and "Chybí odpověď na povinné otázky" in response.content.decode()
    assert QuestionnaireResponse.objects.count() == 0
    required = [q for q in questionnaires.questionnaire("genetika").questions.all() if q.required]
    data = {}
    for q in required:
        if q.kind == "choice":
            data[f"q_{q.code}"] = q.option_codes()[0]
        elif q.kind == "multi":
            data[f"q_{q.code}"] = q.option_codes()[0]
        elif q.kind in ("number", "scale"):
            data[f"q_{q.code}"] = "3"
        elif q.kind == "yesno":
            data[f"q_{q.code}"] = "1"
        else:
            data[f"q_{q.code}"] = "text"
    data["vyplnil"] = "sportovec"
    response = lab_client.post(f"/genetika/sportovec/{subject.pk}/dotaznik/", data)
    assert response.status_code == 302
    saved = questionnaires.latest(subject, "genetika")
    assert saved.source == "sportovec" and saved.answers.filter(state="answered").count() == len(required)
    page = lab_client.get(f"/genetika/sportovec/{subject.pk}/").content.decode()
    assert "Vyplněno" in page and "Vyplnit znovu" in page and "tenis" not in page

    # V portálu až po souhlasu; formulář je předvyplněný.
    athlete, athlete_client = _user(org, Role.ATHLETE, "jana@example.cz")
    identity = subject.identity
    identity.user = athlete
    identity.save()
    response = athlete_client.get(f"/muj/{subject.pk}/dotaznik/genetika/")
    assert response.url == f"/muj/{subject.pk}/souhlasy/"
    services.grant_consent(subject, by=athlete)
    page = athlete_client.get(f"/muj/{subject.pk}/dotaznik/genetika/").content.decode()
    assert "Naposledy vyplněno" in page and 'value="3"' in page
    page = athlete_client.get(f"/muj/{subject.pk}/souhlasy/").content.decode()
    assert "Upravit dotazník" in page and "dotazník vyplněn" in page
    data["q_hlavni_sport"] = "běh"
    assert athlete_client.post(f"/muj/{subject.pk}/dotaznik/genetika/", data).status_code == 302
    latest = questionnaires.latest(subject, "genetika")
    assert latest != saved and latest.source == "sportovec"
    assert latest.answers_by_code()["hlavni_sport"].text == "běh"
    # Trenér ani výzkumník dotazník genetiky neotevřou.
    coach, coach_client = _user(org, Role.COACH, "trener")
    assert coach_client.get(f"/genetika/sportovec/{subject.pk}/dotaznik/").url == "/trener/"
    researcher, r_client = _user(org, Role.RESEARCHER, "vyzkum")
    assert r_client.get(f"/genetika/sportovec/{subject.pk}/dotaznik/").status_code == 403


def test_scenare_se_napoji_na_otazky_a_shoda_odpovedi(org):
    variant = GeneVariant.objects.create(organization=org, gene="ACE", rsid="rs1799752",
                                         domain=Domain.objects.get(code="vykon"),
                                         genotypes=["II", "ID", "DD"])
    card = GeneCard.objects.create(organization=org, variant=variant, version=1)
    linked = ContextScenario.objects.create(
        card=card, kind="questionnaire",
        statement="Lépe zvládám delší souvislou zátěž a vytrvalostní trénink než krátké maximální výkony.")
    other = ContextScenario.objects.create(card=card, kind="questionnaire",
                                           statement="Něco, co v dotazníku není.")
    measured = ContextScenario.objects.create(card=card, kind="measurement",
                                              statement="V laboratorním testu dosahuji nadprůměrných hodnot VO2max.")
    assert seed.link_scenarios() == 1
    linked.refresh_from_db()
    assert linked.question.code == "vykonovy_profil" and linked.answer_match == {"choices": ["vytrvalost"]}
    assert not linked.is_active
    other.refresh_from_db()
    measured.refresh_from_db()
    assert other.question is None and measured.question is None

    q = linked.question
    yes = Answer(question=q, choices=["vytrvalost"], state="answered")
    no = Answer(question=q, choices=["sila"], state="answered")
    unknown = Answer(question=q, choices=["vytrvalost"], state="unknown")
    assert linked.matches(yes) and not linked.matches(no) and not linked.matches(unknown)
    assert not linked.matches(None)
    scale = ContextScenario(answer_match={"min": 7})
    scale_q = Question(kind="scale")
    assert scale.matches(Answer(question=scale_q, value=8, state="answered"))
    assert not scale.matches(Answer(question=scale_q, value=3, state="answered"))
    yesno = ContextScenario(answer_match={"value": 1})
    assert yesno.matches(Answer(question=scale_q, value=1.0, state="answered"))
    assert not yesno.matches(Answer(question=scale_q, value=0.0, state="answered"))


def test_po_chybe_zustanou_vyplnene_odpovedi(org):
    """Zapomenutá povinná otázka nesmí smazat, co už je vyplněné (laboratoř i portál)."""
    _, lab_client = _user(org, Role.LAB, "laborant")
    subject = _adult(org)
    url = f"/genetika/sportovec/{subject.pk}/dotaznik/"
    data = {"q_hlavni_sport": "tenis", "q_zamereni": "rekreacni", "q_praxe_let": "12,5",
            "q_stres": "4", "q_kofein_davky__stav": "na", "q_slozka": ["silova"]}
    response = lab_client.post(url, data)
    page = response.content.decode()
    assert response.status_code == 200 and QuestionnaireResponse.objects.count() == 0
    assert ">tenis</textarea>" in page                                       # text
    assert 'name="q_zamereni" value="rekreacni" class="mt-1" checked' in page  # volba
    assert 'name="q_praxe_let" class="input w-32 text-sm py-1.5" value="12.5"' in page  # číslo
    assert 'name="q_stres" value="4" checked' in page                         # škála
    assert 'name="q_kofein_davky__stav" value="na" checked' in page           # stav
    assert 'name="q_slozka" value="silova" class="mt-1" checked' in page      # více možností
    assert 'id="q-cil"' in page and 'href="#q-cil"' in page and "chybí odpověď" in page
    assert "Co už je vyplněné, zůstalo" in page

    # portál: totéž pro sportovce
    athlete, athlete_client = _user(org, Role.ATHLETE, "jana@example.cz")
    identity = subject.identity
    identity.user = athlete
    identity.save()
    services.grant_consent(subject, by=athlete)
    page = athlete_client.post(f"/muj/{subject.pk}/dotaznik/genetika/", data).content.decode()
    assert ">tenis</textarea>" in page and 'name="q_stres" value="4" checked' in page
    assert QuestionnaireResponse.objects.count() == 0
