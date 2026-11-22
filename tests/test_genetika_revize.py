"""
Revize a schválení karet krok za krokem: jedna fronta úkolů (značky k ověření,
revizní záznamy, chybějící texty), jeden úkol na obrazovce s odůvodněním,
záznam do historie, souhrn karty a schválení garantem ze souhrnu.
"""

import pytest
from cryptography.fernet import Fernet
from django.urls import reverse

from apps.core.models import Organization, Role
from apps.genetics import review
from apps.genetics.models import (
    CardEvidence,
    CardRevision,
    CardSource,
    GeneCard,
    GenotypeText,
    Recommendation,
)
from apps.genetics.seed import seed_domains
from tests.test_genetika import _card, _user, _variant


@pytest.fixture
def org(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.GENETICS_ENCRYPTION_KEY = Fernet.generate_key().decode()
    seed_domains()
    return Organization.objects.create(name="FTVS", short_name="ftvs")


@pytest.fixture
def karta(org):
    """Návrh v2 s původním zněním v1, značkami, revizními záznamy a chybějícím textem."""
    variant = _variant(org)
    v1 = _card(variant, version=1, status=GeneCard.Status.ORIGINAL)
    v1.genotype_texts.filter(genotype="CC").update(client_text="Máte rychlá vlákna.")
    v2 = _card(variant, version=2, supersedes=v1,
               limitations="Z genotypu nelze určit výkon [S1, OVĚŘIT formulaci].")
    v2.biology_client = "Gen souvisí s bílkovinou svalu. Podíl vláken určuje [DOPLNIT zdroj]."
    v2.save()
    GenotypeText.objects.filter(card=v2, genotype="CC").update(
        client_text="Studie popisují malý rozdíl mezi skupinami [S1, OVĚŘIT velikost efektu]. "
                    "Z výsledku nelze určit Vaši výkonnost.")
    GenotypeText.objects.filter(card=v2, genotype="TT").update(client_text="")
    CardEvidence.objects.create(card=v2, code="E01", trait="síla",
                                basis_text="Metaanalýza [OVĚŘIT OR]")
    CardSource.objects.create(card=v2, label="S1", title="Metaanalýza",
                              citation="Autor A et al. (2013). Metaanalýza ACTN3. Journal, 1, 1-9.")
    ab = CardRevision.objects.create(card=v2, part="Interpretace genotypu CT",
                                     original="Zjištěn genotyp CT.",
                                     proposal="Byl zjištěn genotyp CT (RX).", reason="v0.2")
    task = CardRevision.objects.create(card=v2, part="Frekvence genotypů",
                                       reason="Doplnit se souborem a zdrojem, nebo nechat prázdné.")
    return {"variant": variant, "v1": v1, "card": v2, "ab": ab, "task": task}


def test_fronta_uloh_v_poradi_blokujici_prvni(karta):
    card = karta["card"]
    tasks = review.tasks_for(card)
    keys = [t.key for t in tasks]
    blocking = [t for t in tasks if t.blocking]
    assert [t.title for t in blocking] == [
        "Vysvětlení biologické funkce pro klienta", "Omezení interpretace",
        "Text pro genotyp CC (RR)", "Text pro genotyp TT (XX)",
        "Interpretace genotypu CT", "Frekvence genotypů"]
    assert tasks[-1].title == "Řádek důkazů E01 – podklad a omezení" and not tasks[-1].blocking
    assert keys.index("chybi:genotyp:TT") > keys.index(f"text:genotyp:{_text(card, 'CC').pk}:client_text")
    cc = review.find(tasks, f"text:genotyp:{_text(card, 'CC').pk}:client_text")
    assert cc.verifiable and cc.markers == ["[S1, OVĚŘIT velikost efektu]"]
    assert not review.find(tasks, "text:karta:biology_client").verifiable   # DOPLNIT
    progress = review.progress(card, tasks)
    assert progress == {"blocking": 6, "optional": 1, "done": 0, "total": 7, "open": 7,
                        "percent": 0}


def _text(card, genotype):
    return card.genotype_texts.get(genotype=genotype)


def test_akce_textoveho_ukolu_se_zapisi_do_historie(karta, org):
    card = karta["card"]
    user, _ = _user(org, Role.LAB, "laborant")
    key = f"text:genotyp:{_text(card, 'CC').pk}:client_text"
    message = review.act(card, review.find(review.tasks_for(card), key), "overeno", user=user)
    assert message.endswith("vyřešeno.")
    assert _text(card, "CC").client_text == ("Studie popisují malý rozdíl mezi skupinami [S1]. "
                                             "Z výsledku nelze určit Vaši výkonnost.")
    rec = card.revisions.get(part="Text pro genotyp CC (RR)")
    assert rec.decision == "accepted" and rec.decision_note == "Ověřeno ve zdroji karty."
    assert "[S1, OVĚŘIT velikost efektu]" in rec.original and rec.decided_by == user
    assert review.find(review.tasks_for(card), key) is None

    # vyřadit větu s DOPLNIT; zbytek textu zůstane
    task = review.find(review.tasks_for(card), "text:karta:biology_client")
    with pytest.raises(review.ActionError, match="ověření jde jen"):
        review.act(card, task, "overeno", user=user)
    review.act(card, task, "vyradit", user=user)
    card.refresh_from_db()
    assert card.biology_client == "Gen souvisí s bílkovinou svalu."
    assert card.revisions.get(part="Vysvětlení biologické funkce pro klienta").decision == "removed"

    # ruční úprava: bez odůvodnění neprojde; se značkou dál zůstane úkolem
    task = review.find(review.tasks_for(card), "text:karta:limitations")
    with pytest.raises(review.ActionError, match="odůvodnění"):
        review.act(card, task, "ulozit", user=user, text="Nový text.")
    message = review.act(card, task, "ulozit", user=user, text="Výkon nejde určit [OVĚŘIT].",
                         note="Zkráceno.")
    assert "ještě obsahuje značka k ověření" in message
    # chybějící text pro genotyp
    task = review.find(review.tasks_for(card), "chybi:genotyp:TT")
    with pytest.raises(review.ActionError, match="Napište text"):
        review.act(card, task, "ulozit", user=user, note="x")
    review.act(card, task, "ulozit", user=user, text="Byl zjištěn genotyp TT.",
               note="Napsáno podle zdrojů karty.")
    assert _text(card, "TT").client_text == "Byl zjištěn genotyp TT."


def test_rozhodnuti_revizniho_zaznamu_s_odvodnenim(karta, org):
    card, ab = karta["card"], karta["ab"]
    user, _ = _user(org, Role.LAB, "laborant")
    _text(card, "CT")
    GenotypeText.objects.filter(card=card, genotype="CT").update(client_text="Zjištěn genotyp CT.")
    task = review.find(review.tasks_for(card), f"revize:{ab.pk}")
    assert task.is_ab and task.current == "Zjištěn genotyp CT."
    with pytest.raises(review.ActionError, match="odůvodnění"):
        review.act(card, task, "accepted", user=user)
    message = review.act(card, task, "accepted", user=user, note="Návrh odpovídá zdrojům karty.")
    assert "text karty upraven" in message
    assert _text(card, "CT").client_text == "Byl zjištěn genotyp CT (RX)."
    # rozhodnutý záznam bez odůvodnění (ze starší verze) je úkol „doplnit odůvodnění“
    CardRevision.objects.filter(pk=karta["task"].pk).update(decision="rejected")
    task = review.find(review.tasks_for(card), f"revize:{karta['task'].pk}")
    assert task.problems == ["rozhodnuto bez odůvodnění"]
    review.act(card, task, "oduvodnit", user=user, note="Frekvence bez souboru se neuvádějí.")
    assert review.find(review.tasks_for(card), f"revize:{karta['task'].pk}") is None


def test_obrazovky_revize_a_schvaleni_garantem(karta, org):
    card = karta["card"]
    lab, client = _user(org, Role.LAB, "laborant")
    garant, g_client = _user(org, Role.LAB, "garant")
    card.variant.domain.guarantors.add(garant)
    _, researcher = _user(org, Role.RESEARCHER, "vyzkumnik")
    assert researcher.get(reverse("genetics_review")).status_code == 403

    page = client.get(reverse("genetics_review")).content.decode()
    assert "Revize a schválení karet" in page and "6 blokujících" in page
    url = reverse("genetics_review_task", args=[card.pk])
    page = client.get(url)
    text = page.content.decode()
    assert page.context["task"].title == "Vysvětlení biologické funkce pro klienta"
    assert "Úkol 1 z 7" in text and "<mark" in text and "Vyřadit věty se značkou" in text
    assert "Ověřeno ve zdroji – ponechat text" not in text           # DOPLNIT nejde jen potvrdit

    # úkol CC: potvrdit ověření → přesměruje na další úkol
    key = f"text:genotyp:{_text(card, 'CC').pk}:client_text"
    page = client.get(url + f"?ukol={key}")
    assert "Ověřeno ve zdroji – ponechat text" in page.content.decode()
    assert "Máte rychlá vlákna." in page.content.decode()              # původní znění v1
    assert "S1" in page.content.decode() and "Metaanalýza ACTN3" in page.content.decode()
    task = page.context["task"]
    response = client.post(url, {"ukol": key, "base": task.base, "akce": "overeno"})
    assert response.status_code == 302 and "?ukol=" in response.url
    # změněný text mezitím: akce neprojde
    task = review.find(review.tasks_for(card), "text:karta:limitations")
    response = client.post(url, {"ukol": task.key, "base": "jiny", "akce": "vyradit"}, follow=True)
    assert "se mezitím změnil" in response.content.decode()

    # souhrn: blokující úkoly brání poslat garantovi
    summary = reverse("genetics_review_summary", args=[card.pk])
    text = client.get(summary).content.decode()
    assert "Zbývá 5 blokujících úkolů" in text and "Jak to uvidí sportovec" in text
    assert "Text pro genotyp CC (RR)" in text and "Ověřeno ve zdroji karty." in text
    client.post(summary, {"akce": "k_revizi"})
    card.refresh_from_db()
    assert card.status == "draft"

    # vyřešit zbytek přes obrazovky
    for _ in range(10):
        card.refresh_from_db()
        tasks = [t for t in review.tasks_for(card) if t.blocking]
        if not tasks:
            break
        t = tasks[0]
        data = {"ukol": t.key, "base": t.base}
        if t.kind == review.REVISION:
            data.update(akce="rejected", duvod="Původní znění je přesnější.")
        elif t.kind == review.MISSING:
            data.update(akce="ulozit", text="Byl zjištěn genotyp TT.", duvod="Podle zdrojů.")
        else:
            data.update(akce="vyradit")
        last = client.post(url, data)
    assert last.url == summary                     # po posledním blokujícím úkolu souhrn
    text = client.get(summary).content.decode()
    assert "Všechny blokující úkoly jsou vyřešené" in text and "Zbývá 1 úkolů k doplnění" in text
    client.post(summary, {"akce": "k_revizi"})
    card.refresh_from_db()
    assert card.status == "review"

    # garant: souhrn ke schválení; připravující schválit nesmí
    assert "Souhrn ke schválení" in g_client.get(reverse("genetics_home")).content.decode()
    assert client.post(summary, {"akce": "schvalit"}).status_code == 403
    text = g_client.get(summary).content.decode()
    assert "Schválit kartu" in text and "Vrátit k úpravě" in text
    # vrátit s připomínkou → úkol pro připravujícího
    g_client.post(summary, {"akce": "vratit", "pripominka": ""})
    card.refresh_from_db()
    assert card.status == "review"
    g_client.post(summary, {"akce": "vratit", "pripominka": "Zkraťte text pro TT."})
    card.refresh_from_db()
    assert card.status == "draft"
    remark = review.find(review.tasks_for(card), f"revize:{card.revisions.get(part='Připomínka garanta').pk}")
    assert remark is not None and remark.revision.reason == "Zkraťte text pro TT."
    client.post(url, {"ukol": remark.key, "base": remark.base, "akce": "accepted",
                      "duvod": "Text zkrácen."})
    client.post(summary, {"akce": "k_revizi"})
    response = g_client.post(summary, {"akce": "schvalit"})
    card.refresh_from_db()
    assert response.status_code == 302 and card.status == "approved"
    assert client.get(url).status_code == 302                     # schválenou kartu jen číst


def test_prehled_a_odkazy_z_karty(karta, org):
    card = karta["card"]
    _, client = _user(org, Role.ADMIN, "spravce")
    url = reverse("genetics_review_task", args=[card.pk])
    assert url in client.get(reverse("genetics_card", args=[card.pk])).content.decode()
    assert url in client.get(reverse("genetics_card_edit", args=[card.pk])).content.decode()
    steps = client.get(reverse("genetics_home")).context["steps"]
    assert steps[3]["url"] == reverse("genetics_review") and steps[3]["button"] == "Revize"
    Recommendation.objects.create(card=card, kind="training", basis="general",
                                  text="Dávka [DOPLNIT rozmezí].")
    page = client.get(reverse("genetics_review")).content.decode()
    assert "7 blokujících" in page and "Pokračovat" in page


def test_vyrazeni_vety_se_znackou_obsahujici_zkratku(karta):
    """Značka s tečkou uvnitř („např.“) zůstane celá; po zkratce věta nekončí."""
    card = karta["card"]
    text = ("Spánek platí pro všechny genotypy [DOPLNIT zdroj, např. konsenzus ke spánku]. "
            "Podle Ma et al. 2013 je rozdíl malý [S1]. Výsledek výkon neurčuje.")
    assert review.without_flagged(card, text, client=True) == (
        "Podle Ma et al. 2013 je rozdíl malý [S1]. Výsledek výkon neurčuje.")
    assert review.sentences("První tj. stále první. Druhá.") == ["První tj. stále první.", "Druhá."]


def test_pokracovat_nabidne_kartu_s_blokujicimi_ukoly(karta, org):
    card = karta["card"]
    _, client = _user(org, Role.LAB, "laborant")
    resume = client.get(reverse("genetics_review")).context["resume"]
    assert resume["card"] == card and resume["progress"]["blocking"] == 6
    GeneCard.objects.filter(pk=card.pk).update(status=GeneCard.Status.REVIEW)
    assert client.get(reverse("genetics_review")).context["resume"] is None
