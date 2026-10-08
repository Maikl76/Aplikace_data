"""
AI návrh u článku: hlavní zjištění, omezení, úroveň evidence a populace
z nahraného PDF nebo z abstraktu. Návrh platí až po uložení kurátorem.
"""

import io
import json
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from apps.core.models import Role, User
from apps.evidence import ai_draft
from apps.evidence.models import Article
from apps.subjects.models import Sport
from tests.test_llm import mereni, model  # noqa: F401  (fixtury)

ODPOVED = {
    "hlavni_zjisteni": "Síla vnitřní rotace ramene souvisela s rychlostí podání (r = 0,67).",
    "omezeni": "Jen 12 juniorů; korelační design. Autoři doporučují 99 % úsilí.",
    "uroven_dukazu": "cross",
    "populace": {"sport": "tenis", "pohlavi": "M", "vek_od": None, "vek_do": None,
                 "uroven": "výkonnostní junioři", "velikost_vzorku": 12},
}

TEXT = ["Twelve male competitive tennis players volunteered (age 17.2 years).",
        "Serve velocity correlated with shoulder internal rotation (r = 0.67).",
        "Limitations: small sample, isometric testing only."] * 6


def make_pdf(lines) -> bytes:
    """Nejmenší PDF s textovou vrstvou (Helvetica) – stačí pro pypdf."""
    def esc(line):
        return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    content = "BT /F1 9 Tf 40 800 Td 11 TL " + " ".join(f"({esc(x)}) '" for x in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n"
              f"%%EOF".encode())
    return out.getvalue()


def _pdf(lines=None, name="baiget.pdf"):
    return SimpleUploadedFile(name, make_pdf(lines or TEXT + ["References", "Smith J 2001"]),
                              content_type="application/pdf")


@pytest.fixture
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def _admin(session):
    client = Client()
    client.force_login(User.objects.create(username="sp", organization=session.organization,
                                           role=Role.ADMIN))
    return client


def _form(article, **extra):
    data = {"title": article.title, "status": article.status, "abstract": article.abstract,
            "key_finding": article.key_finding}
    data.update(extra)
    return data


def test_navrh_z_pdf_az_po_ulozeni(mereni, model, media):  # noqa: F811
    _, session = mereni
    tenis = Sport.objects.create(organization=session.organization, code="tenis",
                                 name="Tenis")
    article = Article.objects.create(title="Isometric strength and serve velocity",
                                     status=Article.Status.APPROVED,
                                     key_finding="Původní zjištění.")
    admin = _admin(session)
    model.reply = "```json\n" + json.dumps(ODPOVED, ensure_ascii=False) + "\n```"
    response = admin.post(f"/sporty/clanky/{article.pk}/", _form(
        article, akce="ai", pdf_soubor=_pdf(), ulozit_pdf="1"))
    assert response.url == f"/sporty/clanky/{article.pk}/"

    sent = model.requests[-1]["body"]["messages"]
    assert "kurátor knihovny" in sent[0]["content"]
    assert "internal rotation (r = 0.67)" in sent[1]["content"]
    assert "Smith J 2001" not in sent[1]["content"]          # bez seznamu literatury
    assert model.requests[-1]["body"]["temperature"] == 0.2

    article.refresh_from_db()
    assert article.pdf and not article.ai_writing
    draft = article.ai_draft
    assert draft["zdroj"] == ai_draft.SOURCE_PDF and draft["model"] == "testovaci-model"
    assert draft["cisla_k_overeni"] == ["99"]                # 0,67 a 12 v textu jsou
    # Zprávy zatím vidí původní text.
    assert article.key_finding == "Původní zjištění."

    page = admin.get(f"/sporty/clanky/{article.pk}/")
    html = page.content.decode()
    assert "Návrh od modelu testovaci-model" in html and "<strong>99</strong>" in html
    initial = page.context["form"].initial
    assert initial["key_finding"].startswith("Síla vnitřní rotace")
    assert initial["evidence_level"] == "cross" and initial["sample_size"] == 12
    assert initial["sports"] == [tenis.pk] and initial["population_sex"] == "M"
    assert initial["population_age_min"] is None          # průměr ± SD → věk nevyplní

    pdf = admin.get(f"/sporty/clanky/{article.pk}/pdf/")
    assert pdf["Content-Type"] == "application/pdf"

    admin.post(f"/sporty/clanky/{article.pk}/", _form(
        article, key_finding=initial["key_finding"] + " Ověřeno.", sports=[tenis.pk]))
    article.refresh_from_db()
    assert article.ai_draft is None and article.key_finding.endswith("Ověřeno.")
    assert list(article.sports.all()) == [tenis]


def test_navrh_z_abstraktu_a_druhy_pokus(mereni, model):  # noqa: F811
    _, session = mereni
    article = Article.objects.create(title="T", abstract="Serve velocity r = 0.67 in 12 players.")
    model.replies = ["Tady je shrnutí bez JSON.", json.dumps(ODPOVED)]
    _admin(session).post(f"/sporty/clanky/{article.pk}/", _form(article, akce="ai"))
    article.refresh_from_db()
    assert article.ai_draft["zdroj"] == ai_draft.SOURCE_ABSTRACT
    assert len(model.requests) == 2 and "POUZE platným" in str(model.requests[1]["body"])
    assert not article.pdf


def test_bez_zdroje_a_chyba_modelu(mereni, model):  # noqa: F811
    _, session = mereni
    admin = _admin(session)
    article = Article.objects.create(title="Bez abstraktu")
    response = admin.post(f"/sporty/clanky/{article.pk}/", _form(article, akce="ai"),
                          follow=True)
    assert "nemá z čeho vycházet" in response.content.decode() and not model.requests

    article.abstract = "Some abstract."
    article.save()
    model.status = 500
    admin.post(f"/sporty/clanky/{article.pk}/", _form(article, akce="ai"))
    article.refresh_from_db()
    assert "chyba" in article.ai_draft and not article.ai_writing
    html = admin.get(f"/sporty/clanky/{article.pk}/").content.decode()
    assert "Návrh od AI se nepovedl" in html
    admin.post(f"/sporty/clanky/{article.pk}/", {"akce": "zahodit"})
    article.refresh_from_db()
    assert article.ai_draft is None


def test_pdf_jen_ulozit_bez_ai(mereni, media):  # noqa: F811
    _, session = mereni
    admin = _admin(session)
    response = admin.post("/sporty/clanky/novy/", {"title": "S PDF", "status": "suggested",
                                                   "pdf_soubor": _pdf(), "ulozit_pdf": "1"})
    assert response.url == "/sporty/clanky/"
    article = Article.objects.get()
    assert article.pdf.name.startswith("clanky/")
    admin.post(f"/sporty/clanky/{article.pk}/", _form(article, smazat_pdf="1"))
    article.refresh_from_db()
    assert not article.pdf
    # Bez zaškrtnutí se PDF neuloží.
    admin.post(f"/sporty/clanky/{article.pk}/", _form(article, pdf_soubor=_pdf()))
    article.refresh_from_db()
    assert not article.pdf
    bad = admin.post(f"/sporty/clanky/{article.pk}/", _form(
        article, pdf_soubor=SimpleUploadedFile("a.docx", b"x")))
    assert "jako PDF" in bad.content.decode()


def test_psani_na_pozadi_a_zaseknute(mereni, model, settings):  # noqa: F811
    _, session = mereni
    settings.LLM_BACKGROUND = True
    article = Article.objects.create(title="T", abstract="Abstract text.")
    calls = []
    orig = ai_draft.transaction.on_commit
    ai_draft.transaction.on_commit = lambda fn: calls.append(fn)
    try:
        ai_draft.start(article, model=None, text="x", source=ai_draft.SOURCE_ABSTRACT)
    finally:
        ai_draft.transaction.on_commit = orig
    article.refresh_from_db()
    assert article.ai_writing and calls and not model.requests
    admin = _admin(session)
    assert "píše návrh" in admin.get(f"/sporty/clanky/{article.pk}/").content.decode()
    assert admin.get(f"/sporty/clanky/{article.pk}/ai/").content.decode().endswith(" s")
    with pytest.raises(ai_draft.DraftError):
        ai_draft.start(article, model=None, text="x", source="x")

    Article.objects.filter(pk=article.pk).update(
        ai_writing_started_at=timezone.now() - timedelta(hours=2))
    assert admin.get(f"/sporty/clanky/{article.pk}/ai/")["HX-Refresh"] == "true"
    article.refresh_from_db()
    assert "nedokončilo" in article.ai_draft["chyba"]


def test_cteni_odpovedi_a_textu():
    data = ai_draft.parse_reply('Výsledek: {"hlavni_zjisteni": "X", "uroven_dukazu": "RCT", '
                                '"populace": {"pohlavi": "muži", "vek_od": "16", '
                                '"velikost_vzorku": "12,0"}}')
    assert data["uroven_dukazu"] == "rct" and data["populace"]["pohlavi"] == "M"
    assert data["populace"]["vek_od"] == 16 and data["populace"]["velikost_vzorku"] == 12
    for bad in ("nic", '{"omezeni": "jen omezení"}', "{rozbité"):
        with pytest.raises(ai_draft.DraftError):
            ai_draft.parse_reply(bad)
    text = ai_draft.clean_text("Úvod\n" + "text " * 200 + "\nReferences\nSmith 2001")
    assert "Smith" not in text and text.startswith("Úvod")
    assert ai_draft.unsupported_numbers("r = 0,67, n = 12, 55 %", "r = 0.67; 12 players") == ["55"]


def test_bez_modelu_jde_pdf_ulozit(mereni, settings):  # noqa: F811
    _, session = mereni
    settings.LLM_ENABLED = False
    article = Article.objects.create(title="T", abstract="A.")
    html = _admin(session).get(f"/sporty/clanky/{article.pk}/").content.decode()
    assert "Jazykový model není zapnutý" in html and 'name="pdf_soubor"' in html
    with pytest.raises(ai_draft.DraftError):
        ai_draft.start(article, model=None, text="x", source="x")


def test_export_katalogu_bez_pdf_a_navrhu(mereni, media):  # noqa: F811
    from apps.catalog.transfer import export_catalog

    article = Article.objects.create(title="T", ai_draft={"hlavni_zjisteni": "x"})
    article.pdf.save("a.pdf", _pdf())
    item = export_catalog()["clanky"][0]
    json.dumps(item)
    assert "pdf" not in item and "ai_draft" not in item


def test_dlouhe_jmeno_pdf(mereni, model, media):  # noqa: F811
    """Názvy souborů od vydavatelů bývají delší než 100 znaků (chyba na Windows)."""
    _, session = mereni
    name = ("Brito_et_al_tVCivYq._-_2024_-_The_Influence_of_Kinematics_on_Tennis_Serve_Speed_"
            "An_In-Depth_Analysis_Using_Xsens_MVN_Biomech_Link_Technology.pdf")
    model.reply = json.dumps(ODPOVED)
    response = _admin(session).post("/sporty/clanky/novy/", {
        "title": "Kinematics and serve speed", "status": "suggested", "akce": "ai",
        "pdf_soubor": _pdf(name=name), "ulozit_pdf": "1"})
    article = Article.objects.get()
    assert response.url == f"/sporty/clanky/{article.pk}/"
    assert article.pdf.name.startswith("clanky/brito_et_al_tvcivyq_-_2024_-_the_influence")
    assert len(article.pdf.name) < 100 and article.ai_draft["zdroj"] == ai_draft.SOURCE_PDF
