"""
Návrhy AI k úkolům revize: model dostane jen obsah karty, knihovnu a kandidáty
z PubMedu; návrh projde kontrolou; přijímá ho člověk po jednom; nový zdroj
z PubMedu přijde jako zdroj karty a navržený článek v knihovně.
"""

import json

import pytest
from django.urls import reverse

from apps.core.models import Role
from apps.evidence import lookup
from apps.evidence.models import Article
from apps.genetics import review, review_ai
from apps.genetics.models import CardSource, ReviewProposal
from tests.test_genetika import _user
from tests.test_genetika_revize import karta, org  # noqa: F401  (fixtury)
from tests.test_llm import model  # noqa: F401  (falešný model)

CANDIDATE = {"pmid": "111", "title": "Kandidátní studie ACTN3 u sportovců",
             "authors": "Novak A, Svoboda B, Dvorak C", "journal": "J Sports Sci", "year": 2024,
             "doi": "10.1000/kandidat", "abstract": "Small differences between groups of athletes.",
             "url": "https://pubmed.ncbi.nlm.nih.gov/111/", "evidence_level": "meta"}


def _reply(**data):
    base = {"rozhodnuti": "", "text": "", "zduvodneni": "", "zdroje": [],
            "novy_zdroj_pmid": None, "jistota": "stredni", "overit": ""}
    return json.dumps({**base, **data}, ensure_ascii=False)


@pytest.fixture
def pubmed(monkeypatch):
    calls = []

    def search(term, retmax=8):
        calls.append(term)
        return ["111"]

    monkeypatch.setattr(lookup, "search_pubmed", search)
    monkeypatch.setattr(lookup, "fetch_pubmed_many", lambda ids: [CANDIDATE] if ids else [])
    return calls


def test_bez_modelu_navrhy_nejsou(karta, org, settings):  # noqa: F811
    settings.LLM_ENABLED = False
    _, client = _user(org, Role.LAB, "laborant")
    page = client.get(reverse("genetics_review_task", args=[karta["card"].pk]))
    assert "Návrh AI" not in page.content.decode()
    with pytest.raises(review.ActionError, match="není zapnutý"):
        review_ai.start(karta["card"])


def test_navrhy_kontrola_a_prijeti_po_jednom(karta, org, model, pubmed):  # noqa: F811
    card = karta["card"]
    lab, client = _user(org, Role.LAB, "laborant")
    model.replies = [
        _reply(rozhodnuti="vyradit", zduvodneni="Podíl vláken zdroje karty nedokládají."),
        _reply(rozhodnuti="overeno", zduvodneni="S1 formulaci dokládá.", zdroje=["S1"]),
        _reply(rozhodnuti="upravit", text="Studie popisují malý rozdíl mezi skupinami "
                                          "[NOVÝ ZDROJ]. Z výsledku nelze určit Vaši výkonnost.",
               zduvodneni="Kandidátní studie popisuje malé rozdíly.", novy_zdroj_pmid="111",
               overit="Zda studie zahrnuje genotyp CC."),
        _reply(rozhodnuti="upravit", text="Rozdíl činí 25 % [S7].", zduvodneni="Podle S7."),
        _reply(rozhodnuti="upravit_podle_navrhu", zduvodneni="Návrh je přesnější a odpovídá S1."),
        _reply(rozhodnuti="upravit_podle_navrhu", zduvodneni="Frekvence doplněny."),
        "Tohle není JSON.",
        _reply(rozhodnuti="upravit", text="Metaanalýza malých rozdílů [NOVÝ ZDROJ].",
               zduvodneni="Kandidát to dokládá.", novy_zdroj_pmid="111"),
    ]
    url = reverse("genetics_review_task", args=[card.pk])
    client.post(url, {"akce": "ai_karta"})
    proposals = {p.task_key: p for p in card.review_proposals.all()}
    assert len(proposals) == 7 and {p.status for p in proposals.values()} == {"ready"}
    assert pubmed == ["rs1815739[All Fields] AND (exercise[All Fields] OR athlete*[All Fields] "
                      "OR sport*[All Fields] OR training[All Fields] OR performance[All Fields])"]
    sent = model.requests[0]["body"]["messages"]
    facts = json.loads(sent[1]["content"])
    assert facts["kandidati_pubmed"][0]["pmid"] == "111" and facts["zdroje_karty"][0]["stitek"] == "S1"
    assert facts["ukol"]["povolena_rozhodnuti"] == ["upravit", "vyradit"]       # DOPLNIT: ne „overeno“
    assert set(facts) == {"karta", "zdroje_karty", "kandidati_pubmed", "nepripustne_vyroky",
                          "ukol"}                                          # jen obsah karty
    cc_key = f"text:genotyp:{card.genotype_texts.get(genotype='CC').pk}:client_text"
    assert proposals[cc_key].new_source["pmid"] == "111" and proposals[cc_key].issues == []
    tt = proposals["chybi:genotyp:TT"]
    assert any("S7" in i for i in tt.issues) and any("25" in i for i in tt.issues)
    task_rev = proposals[f"revize:{karta['task'].pk}"]
    assert any("nejde" in i for i in task_rev.issues)        # u úkolu jen ponechat / vyřadit
    assert proposals["text:dukaz:" + str(card.evidence.get().pk) + ":basis_text"].issues == []

    # obrazovka úkolu ukáže návrh, nový zdroj a „Přijmout návrh“
    page = client.get(url + f"?ukol={cc_key}").content.decode()
    assert "Přijmout návrh" in page and "nový zdroj z PubMedu – k ověření" in page
    assert "PMID 111" in page and "Zda studie zahrnuje genotyp CC." in page

    # přijetí s novým zdrojem: S2 v kartě, navržený článek v knihovně, záznam „Návrh AI … přijat“
    task = review.find(review.tasks_for(card), cc_key)
    client.post(url, {"ukol": cc_key, "base": task.base, "akce": "navrh"})
    source = CardSource.objects.get(card=card, label="S2")
    assert source.article.pmid == "111" and source.article.status == Article.Status.SUGGESTED
    assert "k ověření" in source.title and source.url == "https://doi.org/10.1000/kandidat"
    assert card.genotype_texts.get(genotype="CC").client_text.startswith(
        "Studie popisují malý rozdíl mezi skupinami [S2].")
    rec = card.revisions.get(part="Text pro genotyp CC (RR)")
    assert rec.decision_note.startswith("Návrh AI (testovaci-model) přijat: Kandidátní studie")
    assert rec.decided_by == lab and "PMID 111" in rec.source
    assert ReviewProposal.objects.get(task_key=cc_key).status == "used"

    # návrh s výhradou kontroly jedním klikem neprojde
    card.refresh_from_db()
    task = review.find(review.tasks_for(card), "chybi:genotyp:TT")
    text = client.post(url, {"ukol": task.key, "base": task.base, "akce": "navrh"},
                       follow=True).content.decode()
    assert "výhrady kontroly" in text and card.genotype_texts.get(genotype="TT").client_text == ""

    # revizní záznam A/B: přijetí = rozhodnutí s odůvodněním z návrhu (náhled = navržené znění)
    ab_key = f"revize:{karta['ab'].pk}"
    assert "Byl zjištěn genotyp CT (RX)." in client.get(url + f"?ukol={ab_key}").content.decode()
    task = review.find(review.tasks_for(card), ab_key)
    client.post(url, {"ukol": ab_key, "base": task.base, "akce": "navrh"})
    karta["ab"].refresh_from_db()
    assert karta["ab"].decision == "accepted"
    assert karta["ab"].decision_note.endswith("Návrh je přesnější a odpovídá S1.")

    # odmítnutý návrh se při další přípravě pro kartu nevrátí; zastaralý se nepřijme
    task = review.find(review.tasks_for(card), "text:karta:biology_client")
    client.post(url, {"ukol": task.key, "base": task.base, "akce": "navrh_odmitnout"})
    assert ReviewProposal.objects.get(task_key=task.key).status == "dismissed"
    assert review_ai.start(card) == 0
    card.refresh_from_db()
    card.limitations = "Z genotypu nelze určit výkon [S1, OVĚŘIT jinak]."
    card.save()
    task = review.find(review.tasks_for(card), "text:karta:limitations")
    text = client.get(url + f"?ukol={task.key}").content.decode()
    assert "ke staršímu znění" in text and "Připravit návrh znovu" in text
    with pytest.raises(review.ActionError, match="staršímu znění"):
        review_ai.accept(card, task, review_ai.proposal_for(card, task), user=lab)

    # upravený návrh s [NOVÝ ZDROJ]: zdroj se přidá (stejný článek = stejný štítek S2)
    ev_key = "text:dukaz:" + str(card.evidence.get().pk) + ":basis_text"
    task = review.find(review.tasks_for(card), ev_key)
    client.post(url, {"ukol": ev_key, "base": task.base, "akce": "ulozit",
                      "text": "Metaanalýza malých rozdílů, upraveno [NOVÝ ZDROJ].",
                      "duvod": "Upravený návrh AI."})
    assert card.evidence.get().basis_text == "Metaanalýza malých rozdílů, upraveno [S2]."
    assert CardSource.objects.filter(card=card).count() == 2

    # přehled: sloupec Návrhy AI; souhrn označí rozhodnutí z návrhu AI
    page = client.get(reverse("genetics_review")).content.decode()
    assert "Návrhy AI" in page and "připraveno" in page
    summary = client.get(reverse("genetics_review_summary", args=[card.pk])).content.decode()
    assert summary.count(">návrh AI<") == 2
