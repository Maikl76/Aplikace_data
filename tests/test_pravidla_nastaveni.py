"""
Nastavení, dávka 3a: pravidla v aplikaci – přehled s kroky (aktivní,
zápis, zdroje, zkouška), formulář pravidla se stavitelem podmínky, texty
kontrolované proti polím podmínky, verze při změně, články, zkouška na
posledních testovacích dnech s důvodem, proč pravidlo nesedlo; kroky
norem a Nastavení vedou sem.
"""

from datetime import date

import pytest
from cryptography.fernet import Fernet
from django.test import Client
from django.urls import reverse

from apps.catalog.models import MetricDef, Norm, Protocol, TestFamily
from apps.catalog.steps import norm_steps
from apps.core.models import Organization, Role, User
from apps.evidence.models import Article
from apps.measurements.models import Measurement, ProtocolRun, TestSession, Trial
from apps.rules import engine
from apps.rules.models import Rule
from apps.rules.setup_views import condition_from_rows, rows_from_condition
from apps.rules.steps import describe
from apps.subjects.models import Sport, Subject


@pytest.fixture
def org(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    return Organization.objects.create(name="FTVS", short_name="ftvs")


def _user(org, role, username):
    user = User.objects.create(username=username, organization=org, role=role,
                               is_staff=role == Role.ADMIN)
    client = Client()
    client.force_login(user)
    return user, client


def _catalog(org):
    sport = Sport.objects.create(organization=org, name="Florbal", code="florbal")
    protocol = Protocol.objects.create(organization=org, code="iso", name="Izokinetika",
                                       family=TestFamily.DYNAMOMETRY)
    ratio = MetricDef.objects.create(organization=org, code="ir_er_pomer", name="Poměr IR/ER",
                                     family=TestFamily.DYNAMOMETRY, unit="", decimals=2)
    height = MetricDef.objects.create(organization=org, code="cmj_vyska", name="Výška výskoku",
                                      family=TestFamily.FORCE_PLATE, unit="cm", decimals=1)
    return sport, protocol, ratio, height


def _measure(org, subject, protocol, day, metric, value, **kv):
    session, _ = TestSession.objects.get_or_create(organization=org, subject=subject, date=day)
    run, _ = ProtocolRun.objects.get_or_create(session=session, protocol=protocol)
    trial, _ = Trial.objects.get_or_create(protocol_run=run, number=1)
    Measurement.objects.create(trial=trial, metric=metric, value=value, side=kv.get("side", ""),
                               mode=kv.get("mode", ""), speed=kv.get("speed"))
    return session


def _form(**extra):
    data = {"name": "Poměr IR/ER pod doporučenou hodnotou", "code": "", "sport": "",
            "severity": "medium", "is_active": "", "load_restriction": "on", "group": "all",
            "row_count": "1", "r0_kind": "metric", "r0_metric": "ir_er_pomer", "r0_op": "<",
            "r0_value": "1,0", "r0_side": "", "r0_mode": "", "r0_speed": "210", "r0_segment": "",
            "finding_template": "Poměr IR/ER {value_txt} při {speed_txt} °/s je pod {threshold_txt}.",
            "recommendation_template": "Posílit zevní rotátory.", "nra_count": "1",
            "nra0_article": "", "nra0_note": ""}
    data.update(extra)
    return data


def test_stavitel_podminky_tam_a_zpet():
    rows, group = rows_from_condition({"metric": "ir_er_ratio", "op": "<", "value": 1.0,
                                       "where": {"speed": 210, "side": "L"}})
    assert group == "all" and rows[0]["value"] == "1" and rows[0]["speed"] == "210"
    assert rows[0]["side"] == "L"
    condition, errors = condition_from_rows(rows, "all")
    assert not errors
    assert condition == {"metric": "ir_er_ratio", "op": "<", "value": 1,
                         "where": {"speed": 210, "side": "L"}}
    # složená podmínka a změna s MDC
    rows, group = rows_from_condition({"any": [
        {"change": "cmj_height", "op": "<", "value": -2.5, "require_mdc": False},
        {"asymmetry": "*", "op": ">", "value": 10}]})
    assert group == "any" and rows[0]["mdc"] is False and rows[1]["metric"] == "*"
    condition, errors = condition_from_rows(rows, "any")
    assert condition["any"][0] == {"change": "cmj_height", "op": "<", "value": -2.5,
                                   "require_mdc": False}
    # vnořené skupiny stavitel neumí
    assert rows_from_condition({"all": [{"any": [{"z": "x", "op": "<", "value": -1}]}]}) is None
    # chyby zápisu řádků
    _, errors = condition_from_rows([{"kind": "metric", "metric": "*", "op": "<", "value": "x",
                                      "side": "", "mode": "", "speed": "", "segment": "",
                                      "mdc": True}], "all")
    assert "práh musí být číslo" in " ".join(errors) and "jen u asymetrie" in " ".join(errors)


def test_podminka_slovy(org):
    _, _, ratio, height = _catalog(org)
    metrics = {ratio.code: ratio, height.code: height}
    assert describe({"metric": "ir_er_pomer", "op": "<", "value": 1.0,
                     "where": {"speed": 210, "side": "L", "mode": "con"}}, metrics) == (
        "Poměr IR/ER < 1 (levá, koncentricky, při 210 °/s)")
    assert describe({"change": "cmj_vyska", "op": "<", "value": -2.5}, metrics) == (
        "změna Výška výskoku proti minulému měření < -2,5 cm (jen nad MDC)")
    assert describe({"any": [{"asymmetry": "*", "op": ">", "value": 10},
                             {"z": "cmj_vyska", "op": "<", "value": -1}]}, metrics) == (
        "asymetrie všech ukazatelů > 10 % nebo z-skóre Výška výskoku vůči normě < -1")
    assert describe({"nesmysl": 1}, metrics) == "podmínku nejde přečíst"


def test_prehled_pravidel_s_kroky(org):
    _, client = _user(org, Role.ADMIN, "spravce")
    _, lab = _user(org, Role.LAB, "laborant")
    _, _, ratio, height = _catalog(org)
    url = reverse("rules_settings")
    page = client.get(url)
    assert page.status_code == 200
    text = page.content.decode()
    assert "Nové pravidlo" in text and "Zatím žádné pravidlo" in text
    steps = {s["title"]: s for s in page.context["steps"]}
    assert not steps["Aktivní pravidla"]["done"] and steps["Aktivní pravidla"]["url"] == reverse("rule_new")
    assert steps["Zápis"]["done"] and steps["Zdroje"]["done"]
    assert steps["Zkouška na datech"]["optional"] and steps["Zkouška na datech"]["url"] == reverse("rules_test")
    text = lab.get(url).content.decode()
    assert "Nové pravidlo" not in text and "Pravidla pracoviště" in text
    # kroky norem a Nastavení vedou sem místo do administrace
    assert norm_steps(page.context["request"].user)[3]["url"] == url
    sections = {s["title"]: s for s in client.get(reverse("workplace")).context["sections"]}
    assert ("Pravidla", url) in sections["Normy a pravidla"]["links"]
    assert sections["Dotazníky"]["url"] == reverse("questionnaires_settings")
    assert "/admin/rules/" not in client.get(reverse("workplace")).content.decode()
    assert "/admin/catalog/questionnaire/" not in client.get(reverse("workplace")).content.decode()

    # špatně zapsané pravidlo, aktivní bez zdroje a změna bez MDC se v přehledu označí
    Rule.objects.create(organization=org, code="spatne", name="Špatné", is_active=True,
                        condition={"metric": "neexistuje", "op": "<", "value": 1},
                        finding_template="x")
    Rule.objects.create(organization=org, code="zmena", name="Pokles výšky", is_active=True,
                        condition={"change": "cmj_vyska", "op": "<", "value": 0},
                        finding_template="Pokles {delta_txt} {unit}.")
    page = client.get(url)
    text = page.content.decode()
    assert "špatný zápis" in text and "nikdy nesedne" in text and "nemá MDC" in text
    steps = {s["title"]: s for s in page.context["steps"]}
    assert steps["Aktivní pravidla"]["done"] and steps["Aktivní pravidla"]["url"] == "#pravidla"
    assert not steps["Zápis"]["done"] and steps["Zápis"]["count"] == 1
    assert not steps["Zdroje"]["done"] and steps["Zdroje"]["count"] == 2


def test_pravidlo_se_zalozi_upravi_vyzkousi_a_smaze(org):
    _, client = _user(org, Role.ADMIN, "spravce")
    _, lab = _user(org, Role.LAB, "laborant")
    sport, protocol, ratio, height = _catalog(org)
    article = Article.objects.create(title="Shoulder rotation ratios", authors="Novák J.",
                                     journal="J Sports Sci", year=2021, doi="10.1234/abcd",
                                     status=Article.Status.APPROVED)
    url = reverse("rule_new")
    assert lab.get(url).status_code == 403
    page = client.get(url)
    assert page.status_code == 200
    text = page.content.decode()
    assert "Přidat podmínku" in text and "{value_txt}" in text and "Shoulder rotation" in text

    # texty smí používat jen pole, která podmínka nabídne; chybějící ukazatel neprojde
    text = client.post(url, _form(finding_template="Pokles {delta_txt}.", r0_metric=""),
                       follow=True).content.decode()
    assert "vyberte ukazatel" in text and not Rule.objects.exists()
    text = client.post(url, _form(finding_template="Pokles {delta_txt}."),
                       follow=True).content.decode()
    assert "nenabízí: {delta_txt}" in text and not Rule.objects.exists()

    # založení: kód z názvu, podmínka s rychlostí ve „where“, kontraindikace, článek
    resp = client.post(url, _form(**{"nra0_article": str(article.pk),
                                     "nra0_note": "stejný test"}))
    rule = Rule.objects.get()
    assert resp.status_code == 302 and resp.url.endswith(f"#pravidlo-{rule.pk}")
    assert rule.code == "pomer_ir_er_pod_doporucenou_hodnotou" and rule.version == 1
    assert rule.condition == {"metric": "ir_er_pomer", "op": "<", "value": 1,
                              "where": {"speed": 210}}
    assert rule.contraindication == {"load_restriction": True} and not rule.is_active
    assert rule.organization == org
    assert list(rule.rule_articles.values_list("article", "relevance_note")) == [
        (article.pk, "stejný test")]
    text = client.get(reverse("rules_settings")).content.decode()
    assert "Poměr IR/ER &lt; 1 (při 210 °/s)" in text and "vypnuté" in text
    # stejný kód podruhé neprojde
    text = client.post(url, _form(code="pomer_ir_er_pod_doporucenou_hodnotou"),
                       follow=True).content.decode()
    assert "už existuje" in text and Rule.objects.count() == 1

    # úprava: zapnutí nemění verzi, změna prahu ano; formulář ukazuje uloženou podmínku
    edit = reverse("rule_edit", args=[rule.pk])
    page = client.get(edit)
    assert page.status_code == 200 and page.context["data"]["rows"][0]["speed"] == "210"
    assert 'name="code"' not in page.content.decode()
    client.post(edit, _form(is_active="on", code="jiny", **{f"ra{rule.rule_articles.get().pk}_note": "stejný test a sport"}))
    rule.refresh_from_db()
    assert rule.is_active and rule.version == 1 and rule.code != "jiny"
    assert rule.rule_articles.get().relevance_note == "stejný test a sport"
    text = client.post(edit, _form(is_active="on", r0_value="1,1"), follow=True).content.decode()
    rule.refresh_from_db()
    assert rule.version == 2 and rule.condition["value"] == 1.1 and "jako verze 2" in text
    assert lab.post(edit, _form()).status_code == 403

    # zkouška na datech: nález, nesplněná podmínka s hodnotami, neměřený ukazatel
    subject = Subject.objects.create(organization=org, code="FTVS-0001", sport=sport, sex="M")
    _measure(org, subject, protocol, date(2026, 3, 1), ratio, 0.85, speed=210)
    _measure(org, subject, protocol, date(2026, 4, 1), ratio, 1.25, speed=210)
    _measure(org, subject, protocol, date(2026, 5, 1), height, 30)
    test = reverse("rule_test", args=[rule.pk])
    assert lab.get(test).status_code == 403
    page = client.get(test)
    assert page.status_code == 200 and page.context["hits"] == 1
    rows = {r["session"].date.isoformat(): r for r in page.context["rows"]}
    assert rows["2026-03-01"]["findings"][0].text == "Poměr IR/ER 0,85 při 210 °/s je pod 1,10."
    assert rows["2026-04-01"]["why"] == "hodnoty podmínku nesplnily: Poměr IR/ER 1,25 (210 °/s)"
    assert rows["2026-05-01"]["why"] == "ten den se neměřil ukazatel Poměr IR/ER"
    assert "FTVS-0001" in page.content.decode()
    # zkouška nic neuložila; zkouška všech aktivních pravidel jde také
    assert not rule.findings.exists()
    assert client.get(reverse("rules_test")).context["hits"] == 1
    steps = {s["title"]: s for s in client.get(reverse("rules_settings")).context["steps"]}
    assert steps["Zdroje"]["done"] and not steps["Zkouška na datech"]["done"]

    # pravidlo s nálezy ve zprávách nejde smazat, bez nich ano
    session = TestSession.objects.get(date=date(2026, 3, 1))
    engine.evaluate_session(session)
    assert rule.findings.count() == 1
    text = client.post(reverse("rule_delete", args=[rule.pk]), follow=True).content.decode()
    assert "nejde smazat" in text and Rule.objects.filter(pk=rule.pk).exists()
    rule.findings.all().delete()
    assert lab.post(reverse("rule_delete", args=[rule.pk])).status_code == 403
    text = client.post(reverse("rule_delete", args=[rule.pk]), follow=True).content.decode()
    assert "je smazané" in text and not Rule.objects.exists()


def test_zkouska_vysvetli_chybejici_minule_mereni_a_normu(org):
    _, client = _user(org, Role.ADMIN, "spravce")
    sport, protocol, ratio, height = _catalog(org)
    height.mdc = 1.0
    height.save()
    subject = Subject.objects.create(organization=org, code="FTVS-0001", sport=sport, sex="M")
    _measure(org, subject, protocol, date(2026, 3, 1), height, 30)
    change = Rule.objects.create(organization=org, code="pokles", name="Pokles", is_active=True,
                                 condition={"change": "cmj_vyska", "op": "<", "value": 0},
                                 finding_template="Pokles o {delta_txt} {unit}.")
    z = Rule.objects.create(organization=org, code="pod_normou", name="Pod normou",
                            condition={"z": "cmj_vyska", "op": "<", "value": -1},
                            finding_template="z {z}.")
    Norm.objects.create(organization=org, metric=height, mean=35, sd=2, sex="F",
                        source_citation="Novák J. (2021). Výskok. Čes. kinantropologie.")
    rows = client.get(reverse("rule_test", args=[change.pk])).context["rows"]
    assert rows[0]["why"].startswith("bez dřívějšího měření")
    rows = client.get(reverse("rule_test", args=[z.pk])).context["rows"]
    assert rows[0]["why"].startswith("na sportovce nesedí žádná norma")
    # druhý den: pokles nad MDC sedí, norma pro ženy na muže ne
    _measure(org, subject, protocol, date(2026, 4, 1), height, 27)
    rows = client.get(reverse("rule_test", args=[change.pk])).context["rows"]
    assert rows[0]["findings"][0].text == "Pokles o −3,0 cm."
    # „where“ zúží i změnu a z-skóre
    change.condition = {"change": "cmj_vyska", "op": "<", "value": 0, "where": {"side": "L"}}
    change.save()
    assert client.get(reverse("rule_test", args=[change.pk])).context["hits"] == 0
