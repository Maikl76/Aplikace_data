"""
Nastavení, dávka 3b: dotazníky v aplikaci – přehled s kroky (dotazníky,
otázky, vyplnění), dotazník (název, pokyn, aktivní, pořadí otázek,
náhled) a otázka (znění, druh, možnosti a škála z řádků, povinnost
a stavy); ochrana kódů a otázek s odpověďmi nebo scénáři; vlastní
dotazník se nabídne v testovacím dni operátorovi i sportovci přes QR.
"""

from datetime import date

import pytest
from cryptography.fernet import Fernet
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from apps.catalog.models import Question, Questionnaire
from apps.core.models import Organization, Role, User
from apps.genetics.models import ContextScenario, Domain, GeneCard, GeneVariant
from apps.measurements import questionnaires
from apps.measurements.models import Answer, QuestionnaireResponse, TestSession
from apps.subjects.models import Sport, Subject


@pytest.fixture
def org(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    call_command("seed_catalog", verbosity=0)
    return Organization.objects.create(name="FTVS", short_name="ftvs")


def _user(org, role, username):
    user = User.objects.create(username=username, organization=org, role=role,
                               is_staff=role == Role.ADMIN)
    client = Client()
    client.force_login(user)
    return user, client


def _question(**extra):
    data = {"code": "", "text": "Jak jste se poslední týden vyspali?", "help_text": "",
            "section": "Regenerace", "kind": "choice", "unit": "", "scale_min": "0",
            "scale_max": "10", "anchors": "", "required": "on",
            "options": "dobre = Dobře\nPřerušovaně\nspatne = Špatně", "action": "ulozit"}
    data.update(extra)
    return data


def test_prehled_dotazniku_s_kroky(org):
    _, client = _user(org, Role.ADMIN, "spravce")
    _, lab = _user(org, Role.LAB, "laborant")
    url = reverse("questionnaires_settings")
    page = client.get(url)
    assert page.status_code == 200
    text = page.content.decode()
    assert "Nový dotazník" in text and "RPE" in text and "po každém testu" in text
    assert "u sportovce v Genetice" in text
    steps = {s["title"]: s for s in page.context["steps"]}
    assert steps["Dotazníky"]["done"] and steps["Dotazníky"]["url"] == reverse("questionnaire_new")
    assert steps["Otázky"]["done"] and not steps["Vyplnění"]["done"] and steps["Vyplnění"]["optional"]
    text = lab.get(url).content.decode()
    assert "Nový dotazník" not in text and "Dotazníky pracoviště" in text
    assert lab.get(reverse("questionnaire_new")).status_code == 403

    # aktivní dotazník bez otázek a otázka s jednou možností = doplnit
    empty = Questionnaire.objects.create(organization=org, code="prazdny", name="Prázdný")
    page = client.get(url)
    assert "bez otázek" in page.content.decode()
    steps = {s["title"]: s for s in page.context["steps"]}
    assert not steps["Otázky"]["done"] and steps["Otázky"]["count"] == 1
    Question.objects.create(questionnaire=empty, code="x", text="Jedna?", kind="choice",
                            options=[{"code": "a", "label": "A"}])
    assert "méně než dvě možnosti" in client.get(url).content.decode()


def test_dotaznik_s_otazkami_se_zalozi_nabidne_v_testovacim_dni_a_chrani(org):
    _, client = _user(org, Role.ADMIN, "spravce")
    _, lab = _user(org, Role.LAB, "laborant")
    # založení dotazníku vede rovnou na novou otázku
    resp = client.post(reverse("questionnaire_new"), {"name": "Únava a spánek", "code": "",
                                                      "description": "Podle posledních 7 dnů.",
                                                      "is_active": "on"})
    q = Questionnaire.objects.get(code="unava_a_spanek")
    assert resp.status_code == 302 and resp.url == reverse("question_new", args=[q.pk])
    assert q.organization == org and q.is_active
    text = client.post(reverse("questionnaire_new"), {"name": "Únava a spánek"},
                       follow=True).content.decode()
    assert "už existuje" in text

    # otázka s možnostmi: kódy z řádků, chyby zápisu; náhled i po chybě
    new = reverse("question_new", args=[q.pk])
    page = client.get(new)
    assert page.status_code == 200 and "Druh odpovědi" in page.content.decode()
    text = client.post(new, _question(options="jen jedna"), follow=True).content.decode()
    assert "aspoň dvě možnosti" in text and not q.questions.exists()
    assert "Jak jste se poslední týden vyspali?" in text   # náhled z formuláře
    resp = client.post(new, _question(action="dalsi"))
    spanek = q.questions.get()
    assert resp.status_code == 302 and resp.url == new
    assert spanek.code == "jak_jste_se_posledni_tyden_vyspali" and spanek.section == "Regenerace"
    assert spanek.options == [{"code": "dobre", "label": "Dobře"},
                              {"code": "prerusovane", "label": "Přerušovaně"},
                              {"code": "spatne", "label": "Špatně"}]
    # škála s popisky; popisek mimo škálu neprojde
    text = client.post(new, _question(text="Jak moc jste unaveni?", kind="scale", scale_min="1",
                                      scale_max="5", anchors="1 = vůbec\n9 = úplně"),
                       follow=True).content.decode()
    assert "mimo škálu 1–5" in text
    client.post(new, _question(text="Jak moc jste unaveni?", kind="scale", scale_min="1",
                               scale_max="5", anchors="1 = vůbec\n5 = úplně", required="",
                               allow_unknown="on"))
    unava = q.questions.get(code="jak_moc_jste_unaveni")
    assert (unava.kind, unava.scale_min, unava.scale_max, unava.order) == ("scale", 1, 5, 2)
    assert unava.anchors == {"1": "vůbec", "5": "úplně"} and not unava.required
    assert unava.allow_unknown and unava.options == []
    # kód stejného znění dostane příponu
    client.post(new, _question(kind="yesno"))
    assert q.questions.filter(code="jak_jste_se_posledni_tyden_vyspali_2").exists()

    # dotazník: pořadí a náhled; kód se nemění
    edit = reverse("questionnaire_edit", args=[q.pk])
    page = client.get(edit)
    assert page.status_code == 200
    text = page.content.decode()
    assert 'name="code"' not in text and "Náhled" in text and 'name="q_jak_moc_jste_unaveni"' in text
    assert "Další dotazníky" in text or "pod Další dotazníky" in text
    client.post(edit, {"name": "Únava a spánek", "description": "Podle posledních 7 dnů.",
                       "is_active": "on", f"q{spanek.pk}_order": "5", f"q{unava.pk}_order": "1",
                       f"q{q.questions.get(code='jak_jste_se_posledni_tyden_vyspali_2').pk}_order": "3"})
    assert [x.code for x in q.questions.order_by("order")][0] == "jak_moc_jste_unaveni"

    # testovací den: dotazník se nabízí, operátor ho vyplní, sportovec přes QR i jiné druhy otázek
    sport = Sport.objects.create(organization=org, name="Florbal", code="florbal")
    subject = Subject.objects.create(organization=org, code="FTVS-0001", sport=sport, sex="M")
    session = TestSession.objects.create(organization=org, subject=subject, date=date(2026, 3, 1))
    assert [x.code for x in questionnaires.available(org)] == ["unava_a_spanek"]
    page = lab.get(reverse("session_detail", args=[session.pk]))
    text = page.content.decode()
    assert "Další dotazníky" in text and reverse("session_questionnaire_form",
                                                 args=[session.pk, q.code]) in text
    form = reverse("session_questionnaire_form", args=[session.pk, q.code])
    assert lab.get(form).status_code == 200
    text = lab.post(form, {"q_jak_moc_jste_unaveni__stav": "unknown"}, follow=True).content.decode()
    assert "Doplňte povinné otázky" in text
    resp = lab.post(form, {"q_jak_jste_se_posledni_tyden_vyspali": "spatne",
                           "q_jak_moc_jste_unaveni__stav": "unknown",
                           "q_jak_jste_se_posledni_tyden_vyspali_2": "1", "vyplnil": "sportovec"})
    assert resp.status_code == 302
    response = QuestionnaireResponse.objects.get(session=session, questionnaire=q)
    answers = response.answers_by_code()
    assert response.source == "sportovec" and answers["jak_jste_se_posledni_tyden_vyspali"].choices == ["spatne"]
    assert answers["jak_moc_jste_unaveni"].state == Answer.State.UNKNOWN
    text = lab.get(reverse("session_detail", args=[session.pk])).content.decode()
    assert "Špatně" in text and "nevím" in text
    token = questionnaires.make_token(session, q)
    fill = reverse("questionnaire_fill", args=[token])
    page = Client().get(fill)
    assert page.status_code == 200 and not page.context["simple"]
    assert 'name="q_jak_jste_se_posledni_tyden_vyspali"' in page.content.decode()
    page = Client().post(fill, {"q_jak_jste_se_posledni_tyden_vyspali": "dobre",
                                "q_jak_jste_se_posledni_tyden_vyspali_2": "0"})
    assert page.context["done"]
    assert response.answers.get(question=spanek).choices == ["dobre"]   # přepsáno, ne nové
    assert QuestionnaireResponse.objects.filter(session=session).count() == 1
    # nesprávný kód se v testovacím dni nenabízí; neaktivní zmizí z nabídky
    assert lab.get(reverse("session_questionnaire_form", args=[session.pk, "rpe"])).status_code == 302
    assert lab.post(reverse("questionnaire_delete", args=[q.pk])).status_code == 403

    # ochrana: otázka s odpověďmi a dotazník s vyplněním nejdou smazat, RPE nikdy
    text = client.post(reverse("question_delete", args=[q.pk, spanek.pk]), follow=True).content.decode()
    assert "nejde smazat" in text and Question.objects.filter(pk=spanek.pk).exists()
    text = client.post(reverse("questionnaire_delete", args=[q.pk]), follow=True).content.decode()
    assert "nejde smazat" in text and Questionnaire.objects.filter(pk=q.pk).exists()
    rpe = Questionnaire.objects.get(code="rpe", organization=None)
    text = client.post(reverse("questionnaire_delete", args=[rpe.pk]), follow=True).content.decode()
    assert "aplikace potřebuje" in text and Questionnaire.objects.filter(pk=rpe.pk).exists()
    # otázka bez odpovědí se smaže; vypnutý dotazník se v testovacím dni nenabízí
    yesno = q.questions.get(code="jak_jste_se_posledni_tyden_vyspali_2")
    yesno.answers.all().delete()
    client.post(reverse("question_delete", args=[q.pk, yesno.pk]))
    assert not Question.objects.filter(pk=yesno.pk).exists()
    client.post(edit, {"name": "Únava a spánek", "description": "", "is_active": "",
                       f"q{spanek.pk}_order": "5", f"q{unava.pk}_order": "1"})
    assert questionnaires.available(org) == []
    steps = {s["title"]: s for s in client.get(reverse("questionnaires_settings")).context["steps"]}
    assert steps["Vyplnění"]["done"]


def test_otazka_se_scenarem_genove_karty_drzi_kody_moznosti(org):
    _, client = _user(org, Role.ADMIN, "spravce")
    genetics = Questionnaire.objects.get(code="genetika", organization=None)
    profile = Question.objects.get(questionnaire=genetics, code="vykonovy_profil")
    variant = GeneVariant.objects.create(organization=org, gene="ACTN3", rsid="rs1815739",
                                         domain=Domain.objects.get(code="vykon"),
                                         genotypes=["RR", "RX", "XX"])
    card = GeneCard.objects.create(organization=org, variant=variant, version=1)
    ContextScenario.objects.create(card=card, kind=ContextScenario.Kind.QUESTIONNAIRE,
                                   statement="Vytrvalost", question=profile,
                                   answer_match={"choices": ["vytrvalost"]})
    edit = reverse("question_edit", args=[genetics.pk, profile.pk])
    page = client.get(edit)
    assert page.status_code == 200 and "scénáře genových karet" in page.content.decode()
    options = "\n".join(f"{o['code']} = {o['label']}" for o in profile.options
                        if o["code"] != "vytrvalost")
    text = client.post(edit, _question(text=profile.text, kind="choice", options=options),
                       follow=True).content.decode()
    assert "používá scénář genové karty" in text
    profile.refresh_from_db()
    assert profile.option_codes() == ["vytrvalost", "sila", "neutralni"]
    text = client.post(edit, _question(text=profile.text, kind="text"), follow=True).content.decode()
    assert "druh odpovědi se nemění" in text
    # popisek jde změnit, kódy zůstanou; smazat nejde
    options = "\n".join(f"{o['code']} = {o['label']}" for o in profile.options).replace(
        "= Dosahuji velmi dobrých", "= Jsem silový typ:")
    client.post(edit, _question(text=profile.text, kind="choice", options=options))
    profile.refresh_from_db()
    assert profile.option_label("sila").startswith("Jsem silový typ") and profile.kind == "choice"
    text = client.post(reverse("question_delete", args=[genetics.pk, profile.pk]),
                       follow=True).content.decode()
    assert "nejde smazat" in text and Question.objects.filter(pk=profile.pk).exists()
