"""
Návrhy karet ze souboru (katalog/karty/*.json): karta připravená mimo
aplikaci vznikne jako původní znění + návrh, přidá se do panelu a dál ji
vede průvodce kartou. Značky [OVĚŘIT] / [DOPLNIT] schválení zastaví.
"""

import json
from io import StringIO
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from django.conf import settings
from django.core.management import CommandError, call_command
from django.urls import reverse

from apps.core.models import Organization, Role
from apps.genetics import services
from apps.genetics.card_steps import card_steps
from apps.genetics.models import (
    CardEvidence,
    GeneCard,
    GenePanel,
    GeneVariant,
    GenotypeText,
    Recommendation,
)
from apps.genetics.seed import seed_domains
from tests.test_genetika import _card, _user, _variant

FILE = Path(settings.BASE_DIR) / "katalog" / "karty" / "cyp1a2.json"


@pytest.fixture
def org(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.GENETICS_ENCRYPTION_KEY = Fernet.generate_key().decode()
    seed_domains()
    return Organization.objects.create(name="FTVS", short_name="ftvs")


def _load(*paths) -> str:
    out = StringIO()
    call_command("nacist_navrhy_karet", *paths, stdout=out)
    return out.getvalue()


def test_navrh_cyp1a2_se_nacte_a_pruvodce_ho_vede(org):
    call_command("seed_catalog", verbosity=0)  # test z katalogu pro budoucí měření
    text = _load()
    assert "CYP1A2 / rs762551: založeno (v1 původní znění (jen ke čtení), v2 návrh)" in text
    variant = GeneVariant.objects.get(rsid="rs762551")
    assert variant.organization is None and variant.domain.code == "kofein"
    assert variant.genotypes == ["AA", "AC", "CC"] and variant.frequency_source.startswith("https://")
    v1, v2 = variant.cards.get(version=1), variant.cards.get(version=2)
    assert v1.status == GeneCard.Status.ORIGINAL and v2.status == GeneCard.Status.DRAFT
    assert v2.supersedes == v1 and v2.review_priorities.startswith("Neurčovat bezpečnou dávku")
    assert GenePanel.objects.get().items.filter(variant=variant).exists()

    # původní znění zůstává celé: texty, doporučení podle genotypu, čtyři scénáře, literatura
    assert v1.genotype_texts.count() == 3 and v1.recommendations.count() == 9
    assert v1.scenarios.count() == 4 and v1.sources.count() == 8
    # návrh: čtyři obecná doporučení, poslední jako budoucí měření s testem z katalogu
    recs = list(v2.recommendations.order_by("order"))
    assert [r.basis for r in recs] == ["general"] * 3 + ["measurement"]
    assert all(r.genotype == "" for r in recs) and recs[-1].protocol.code == "spiro_ramp"
    # scénáře napojené na otázku o kofeinu, vypnuté, stejný text pro všechny genotypy
    scenarios = list(v2.scenarios.order_by("order"))
    assert [s.question.code for s in scenarios] == ["kofein_ucinek"] * 2
    assert {s.answer_match["choices"][0] for s in scenarios} == {"pozitivni", "negativni"}
    assert not any(s.is_active for s in scenarios)
    assert all(len({t.text for t in s.texts.all()}) == 1 and s.texts.count() == 3 for s in scenarios)
    assert v2.forbidden_statements.count() == 8 and v2.evidence.count() == 5
    assert list(v2.sources.values_list("label", flat=True)) == [f"S{i}" for i in range(1, 9)]
    assert v2.revisions.filter(decision="open").count() == 6

    # průvodce: kroky 1–7 hotové, schválení blokují jen značky k ověření
    assert [s["done"] for s in card_steps(v2)] == [True] * 7 + [False]
    check = services.checklist(v2)
    assert len(check.blocking) == 4 and all("značku k ověření" in i.text for i in check.blocking)
    assert any("E03 má značku" in w.text for w in check.warnings)

    # podruhé se nic nepřepíše
    assert "už v katalogu, nechávám být" in _load() and variant.cards.count() == 2

    # v aplikaci: přehled kroků i původní znění vedle pole
    _, client = _user(org, Role.LAB, "laborant")
    page = client.get(reverse("genetics_card_edit", args=[v2.pk]))
    assert page.status_code == 200 and "původní znění z podkladů" in page.content.decode().lower()
    text = client.get(reverse("genetics_card_step", args=[v2.pk, "genotypy"])).content.decode()
    assert "Váš genetický profil odpovídá rychlejšímu metabolismu kofeinu" in text  # v1
    assert "Byl zjištěn genotyp AA varianty CYP1A2" in text  # návrh
    text = client.get(reverse("genetics_card_step", args=[v2.pk, "kontrola"])).content.decode()
    assert "Důkaz E03 – Guest 2018" in text and "Blokuje schválení" in text


def test_navrh_z_vlastniho_souboru_nese_test_a_otazku(org, tmp_path):
    call_command("seed_catalog", verbosity=0)
    data = {
        "format": "navrh-karty/1",
        "varianty": [{"organizace": None, "oblast": "vykon", "gene": "ACTN3", "rsid": "rs1815739",
                      "full_name": "", "notation": "", "subtitle": "", "genotypes": ["CC", "CT", "TT"],
                      "genotype_aliases": {"CC": "RR", "CT": "RX", "TT": "XX"}, "strand_note": "",
                      "frequency_source": "", "order": 1, "is_active": True}],
        "karty": [{
            "organizace": None, "varianta": "rs1815739", "nahrazuje": None, "version": 1,
            "status": "draft", "review_priorities": "", "biology_expert": "",
            "biology_client": "Gen souvisí s bílkovinou svalu.", "effect": "", "limitations": "",
            "frequency_note": "", "related_areas": [], "import_note": "", "change_summary": "",
            "approved_at": None,
            "texty": [{"genotype": g, "client_text": f"Genotyp {g}.", "expert_text": "",
                       "frequency": "", "order": i} for i, g in enumerate(["CC", "CT", "TT"])],
            "doporuceni": [{"genotype": "", "kind": "training", "text": "Změřit Wingate.",
                            "basis": "measurement", "merge_key": "", "order": 0,
                            "protokol": "wingate"}],
            "dukazy": [], "zdroje": [], "nepripustne": [],
            "scenare": [{"kind": "questionnaire", "title": "", "statement": "Lépe zvládám zátěž.",
                         "answer_match": {"choices": ["vytrvalost"]}, "condition": {},
                         "is_active": True, "order": 0, "otazka": "vykonovy_profil",
                         "texty": [{"genotype": "CC", "text": "Text CC."}]}],
            "revize": [],
        }],
    }
    path = tmp_path / "actn3.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert "ACTN3 / rs1815739: založeno (v1 návrh)" in _load(str(path))
    card = GeneVariant.objects.get(rsid="rs1815739").cards.get()
    assert card.recommendations.get().protocol.code == "wingate"
    scenario = card.scenarios.get()
    assert scenario.question.code == "vykonovy_profil" and scenario.is_active
    assert GenePanel.objects.get().items.get(variant=card.variant).genotype_map == {
        "RR": "CC", "RX": "CT", "XX": "TT"}
    assert services.checklist(card).ok

    # cizí formát a neexistující soubor se hlásí
    bad = tmp_path / "cizi.json"
    bad.write_text('{"format": "neco"}', encoding="utf-8")
    with pytest.raises(CommandError, match="formát"):
        _load(str(bad))
    with pytest.raises(CommandError, match="neexistuje"):
        _load(str(tmp_path / "nic.json"))


FILES = sorted(p.name for p in FILE.parent.glob("*.json"))


def test_vsechny_navrhy_v_repozitari_se_nactou_a_jsou_po_sedmy_krok_hotove(org):
    """Každý soubor v katalog/karty: varianta v panelu, kroky 1–7 hotové, blokují jen značky."""
    call_command("seed_catalog", verbosity=0)
    text = _load()
    assert len(FILES) == 10 and all(f"{name}: " in text for name in FILES)
    panel = GenePanel.objects.get()
    for variant in GeneVariant.objects.all():
        assert panel.items.filter(variant=variant).exists(), variant
        card = variant.cards.filter(status=GeneCard.Status.DRAFT).get()
        steps = card_steps(card)
        assert [s["done"] for s in steps[:7]] == [True] * 7, (variant.label, [s["text"] for s in steps])
        check = services.checklist(card)
        assert all("značku k ověření" in i.text for i in check.blocking), (variant.label, check.blocking)
        assert card.revisions.filter(decision="open").exists() and card.change_summary
        assert card.limitations and card.forbidden_statements.count() >= 5
        assert all(r.basis for r in card.recommendations.all()) and card.sources.exists()
        for scenario in card.scenarios.all():  # scénáře jen z dotazníku, napojené, vypnuté
            assert scenario.question_id and scenario.answer_match and not scenario.is_active
            assert scenario.texts.count() == len(variant.genotypes)
    # původní znění z Wordu zůstává u sedmi plných karet; tři nové karty jsou jen návrh
    originals = GeneCard.objects.filter(status=GeneCard.Status.ORIGINAL)
    assert originals.count() == 7
    assert {c.variant.gene for c in GeneCard.objects.filter(version=1, status="draft")} == {
        "SLC16A1", "FTO", "TCF7L2"}
    # MCM6/LCT: scénáře k whey nově napojené na otázku o whey
    lct = GeneVariant.objects.get(rsid="rs4988235").cards.get(version=2)
    assert sorted(lct.scenarios.values_list("question__code", flat=True)) == [
        "mleko_obtize", "mleko_obtize", "whey_obtize", "whey_obtize"]
    # ACTN3: revidované texty v0.2 a důkazy zůstávají, nic neblokuje
    actn3 = GeneVariant.objects.get(rsid="rs1815739").cards.get(version=2)
    assert services.checklist(actn3).ok and actn3.evidence.count() == 5
    assert actn3.genotype_texts.get(genotype="TT").client_text.startswith("Byl zjištěn genotyp TT (XX)")


def test_znacky_k_overeni_zastavi_schvaleni(org):
    card = _card(_variant(org))
    GenotypeText.objects.filter(card=card, genotype="CC").update(
        client_text="Ve studiích bývá spojován s rychlejším odbouráváním [S3, OVĚŘIT].")
    Recommendation.objects.create(card=card, kind="nutrition", basis="general",
                                  text="Dávka [DOPLNIT rozmezí].")
    CardEvidence.objects.create(card=card, code="E01", trait="znak",
                                basis_text="dbSNP [OVĚŘIT souřadnice]")
    check = services.checklist(card)
    assert [i.text for i in check.blocking] == [
        "Interpretace genotypu CC obsahuje značku k ověření [OVĚŘIT].",
        "Doporučení „Dávka [DOPLNIT rozmezí].…“ obsahuje značku k ověření [DOPLNIT].",
    ]
    assert any("E01 má značku k ověření [OVĚŘIT]" in w.text for w in check.warnings)
    assert card_steps(card)[7]["count"] == 2

    GenotypeText.objects.filter(card=card, genotype="CC").update(
        client_text="Ve studiích bývá spojován s rychlejším odbouráváním [S3].")
    Recommendation.objects.filter(card=card).update(text="Dávka 3 mg/kg [S4].")
    assert services.checklist(card).ok
