"""
AI návrh u článku, krok 5 „Kdy se článek použije“: model vybere z katalogu
pracoviště ukazatele, testy a pravidla. Návrh se zaškrtne k dosavadnímu výběru
(nic se neodškrtne) a platí až po uložení kurátorem.
"""

import json
from datetime import timedelta

from django.utils import timezone

from apps.catalog.models import MetricDef, Protocol, TestFamily
from apps.core.models import Organization
from apps.evidence import ai_draft
from apps.evidence.models import Article
from apps.rules.models import Rule
from tests.test_clanky_ai import _admin, _form
from tests.test_llm import mereni, model  # noqa: F401  (fixtury)

NAVRH = {
    "ukazatele": [{"kod": "ir_er_ratio", "proc": "Studie měří poměr vnitřní a zevní rotace."},
                  {"kod": "neexistuje", "proc": "smyšlený kód"}],
    "testy": [{"kod": "ISO", "proc": "Izokinetika ramene."}, {"kod": "tajny"}],
    "pravidla": ["ir_er"],
}


def test_navrh_ukazatelu_testu_a_pravidel(mereni, model):  # noqa: F811
    _, session = mereni
    cizi = Organization.objects.create(name="Jiná laboratoř", short_name="jina")
    Protocol.objects.create(organization=cizi, code="tajny", name="Cizí test",
                            family=TestFamily.OTHER)
    grip = MetricDef.objects.create(code="grip_max", name="Síla stisku",
                                    family=TestFamily.DYNAMOMETRY, unit="kg")
    article = Article.objects.create(
        title="Shoulder rotation ratio in tennis",
        abstract="Isokinetic IR/ER ratio below 1.0 was linked to shoulder pain.",
        key_finding="Poměr IR/ER pod 1,0 souvisel s bolestí ramene.",
        ai_draft={"hlavni_zjisteni": "Starý nezkontrolovaný návrh."})
    article.metrics.add(grip)
    admin = _admin(session)
    model.reply = "```json\n" + json.dumps(NAVRH, ensure_ascii=False) + "\n```"
    response = admin.post(f"/clanky/{article.pk}/", _form(article, akce="ai_temata",
                                                           metrics=[grip.pk]))
    assert response.url == f"/clanky/{article.pk}/"

    body = model.requests[-1]["body"]
    system, user = body["messages"][0]["content"], body["messages"][1]["content"]
    assert "vybereš, u kterých ukazatelů, testů" in system
    assert "ir_er_ratio – Poměr IR/ER (testy: Izokinetika)" in user
    assert "iso – Izokinetika" in user and "tajny" not in user          # cizí pracoviště ne
    assert "ir_er – Poměr IR/ER: Poměr IR/ER < 1" in user              # podmínka slovy
    assert "Hlavní zjištění (od kurátora)" in user and "Abstrakt:" in user
    assert body["temperature"] == 0.2 and "max_tokens" not in body

    article.refresh_from_db()
    topics = article.ai_draft[ai_draft.PART_TOPICS]
    assert set(article.ai_draft) == {"temata"}               # starý návrh uložením padl
    assert [i["kod"] for i in topics["ukazatele"]] == ["ir_er_ratio"]
    assert [i["kod"] for i in topics["testy"]] == ["iso"]      # kód bez ohledu na velikost
    assert [i["kod"] for i in topics["pravidla"]] == ["ir_er"]
    assert topics["nezname"] == ["neexistuje", "tajny"]
    assert topics["zdroj"] == ai_draft.SOURCE_ABSTRACT and not article.ai_writing
    assert list(article.metrics.all()) == [grip]               # zatím nic neplatí

    page = admin.get(f"/clanky/{article.pk}/")
    initial = page.context["form"].initial
    ratio = MetricDef.objects.get(code="ir_er_ratio")
    iso = Protocol.objects.get(code="iso")
    rule = Rule.objects.get(code="ir_er")
    assert initial["metrics"] == sorted([grip.pk, ratio.pk])    # k původnímu výběru
    assert initial["protocols"] == [iso.pk] and initial["rules"] == [rule.pk]
    html = page.content.decode()
    assert "Návrh od modelu testovaci-model" in html and "ukazatele 1, testy 1, pravidla 1" in html
    assert 'title="Navrhl model: Studie měří poměr vnitřní a zevní rotace."' in html
    assert "vynechané: neexistuje, tajny" in html
    assert "Návrh od AI se nepovedl" not in html and "Starý nezkontrolovaný" not in html

    admin.post(f"/clanky/{article.pk}/", _form(article, metrics=initial["metrics"],
                                                protocols=initial["protocols"],
                                                rules=initial["rules"]))
    article.refresh_from_db()
    assert article.ai_draft is None
    assert set(article.metrics.values_list("code", flat=True)) == {"grip_max", "ir_er_ratio"}
    assert list(article.protocols.all()) == [iso]
    assert article.rule_articles.filter(rule=rule).exists()


def test_navrh_temat_chyba_druhy_pokus_a_nic_nesedi(mereni, model):  # noqa: F811
    _, session = mereni
    admin = _admin(session)
    article = Article.objects.create(title="Bez ničeho")
    response = admin.post(f"/clanky/{article.pk}/", _form(article, akce="ai_temata"),
                          follow=True)
    assert "nemá z čeho vycházet" in response.content.decode() and not model.requests

    article.abstract = "Some abstract."
    article.save()
    model.replies = ["Tady JSON není.", "Pořád ne."]
    admin.post(f"/clanky/{article.pk}/", _form(article, akce="ai_temata"))
    article.refresh_from_db()
    assert len(model.requests) == 2 and "POUZE platným" in str(model.requests[1]["body"])
    assert "chyba" in article.ai_draft["temata"] and article.ai_writing_part == ""
    html = admin.get(f"/clanky/{article.pk}/").content.decode()
    assert "Návrh ukazatelů, testů a pravidel se nepovedl" in html
    assert "Návrh od AI se nepovedl" not in html                 # krok 3 je v pořádku

    model.reply = json.dumps({"ukazatele": [], "testy": [], "pravidla": []})
    admin.post(f"/clanky/{article.pk}/", _form(article, akce="ai_temata"))
    html = admin.get(f"/clanky/{article.pk}/").content.decode()
    assert "nenašel nic, k čemu by článek patřil" in html
    admin.post(f"/clanky/{article.pk}/", {"akce": "zahodit"})
    article.refresh_from_db()
    assert article.ai_draft is None


def test_nedokonceny_navrh_temat(mereni):  # noqa: F811
    article = Article.objects.create(
        title="Visí", ai_writing_model="m", ai_writing_part=ai_draft.PART_TOPICS,
        ai_writing_started_at=timezone.now() - timedelta(hours=3))
    assert ai_draft.clear_stalled(article)
    article.refresh_from_db()
    assert "nedokončilo" in article.ai_draft["temata"]["chyba"]
    assert not article.ai_writing and article.ai_writing_part == ""
