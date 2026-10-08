"""
Články ve zprávách a upravitelné pokyny pro návrh doporučení.

Článek se ke zprávě dostane přes pravidlo (nález) nebo přes téma (měřený
ukazatel či test). Model z něj dostane hlavní zjištění, omezení a populaci,
ne abstrakt. Čísla [n] zůstávají u konceptu stejná, i když se knihovna změní.
"""

from datetime import timedelta

from django.test import Client

from apps.catalog.models import MetricDef, Protocol
from apps.core.models import Role, User
from apps.evidence import lookup
from apps.evidence.models import Article
from apps.measurements.models import Measurement, ProtocolRun, TestSession, Trial
from apps.reports import facts, narrative, prompts, services
from apps.reports.models import Audience, Report, ReportStyle
from apps.rules import evidence
from apps.rules.models import Rule, RuleArticle
from tests.test_llm import mereni, model  # noqa: F401  (fixtury)

VERNY = "Poměr IR/ER 0,85 je pod 1,00."


def _admin(session):
    client = Client()
    client.force_login(User.objects.create(username="sp", organization=session.organization,
                                           role=Role.ADMIN))
    return client


def _article(title, *, status=Article.Status.APPROVED, metrics=(), year=2023, **fields):
    article = Article.objects.create(title=title, authors="Novák J, Svoboda K", year=year,
                                     status=status, **fields)
    article.metrics.set(MetricDef.objects.filter(code__in=metrics))
    return article


# --- B: pokyny pro návrh doporučení -----------------------------------------

def test_upravene_pokyny_pro_doporuceni(mereni, model):  # noqa: F811
    user, session = mereni
    model.reply = VERNY
    report = services.build_draft(session, user=user)
    admin = _admin(session)
    admin.post("/zpravy/ai/", {"akce": "pokyny", "audience": "trener", "kind": "doporuceni",
                               "instructions": "Navrhni 5–8 konkrétních bodů pro trenéra."})
    assert prompts.style_for(session.organization, "trener", "doporuceni").startswith("Navrhni")
    # Souhrn má pořád své výchozí pokyny.
    assert prompts.style_for(session.organization, "trener") == prompts.DEFAULT_STYLES["trener"]

    model.reply = "• Posílit zevní rotátory ramene."
    services.suggest_recommendations(report)
    system = model.requests[-1]["body"]["messages"][0]["content"]
    assert "Navrhni 5–8 konkrétních bodů" in system
    assert "Nestanovuj diagnózy" in system and "hlavni_zjisteni" in system   # pevná pravidla
    report.refresh_from_db()
    assert report.note_pending_review

    page = admin.get("/zpravy/ai/?tab=pokyny").content.decode()
    assert "Návrh doporučení" in page and "Navrhni 5–8" in page
    admin.post("/zpravy/ai/", {"akce": "pokyny", "audience": "trener", "kind": "doporuceni",
                               "instructions": "x", "vychozi": "1"})
    assert (prompts.style_for(session.organization, "trener", "doporuceni")
            == prompts.DEFAULT_RECOMMENDATION_STYLES["trener"])


def test_vychozi_pokyny_doporuceni_dle_ctenare(mereni):  # noqa: F811
    _, session = mereni
    org = session.organization
    assert "vykej" in prompts.recommendation_prompt(org, Audience.ATHLETE)
    lekar = prompts.recommendation_prompt(org, Audience.CLINICIAN)
    assert "dávkování vynech" in lekar and "navrhuj jen střídmě" not in lekar


# --- články pro model -------------------------------------------------------

def test_clanek_k_pravidlu_dostane_model_s_podstatou(mereni, model):  # noqa: F811
    user, session = mereni
    article = _article("Rotátory ramene u nadhazovačů", evidence_level="cohort",
                       key_finding="Poměr IR/ER pod 1,00 souvisel s bolestí ramene.",
                       limitations="Jen muži baseballisté.", population_sex="M",
                       population_sport="baseball", sample_size=120,
                       abstract="DLOUHÝ ABSTRAKT, KTERÝ MODEL NEDOSTANE")
    RuleArticle.objects.create(rule=Rule.objects.get(code="ir_er"), article=article,
                               relevance_note="Opora prahu 1,00")
    model.reply = "Poměr IR/ER 0,85 je pod 1,00 [1]; studie byla na jiné populaci."
    report = services.build_draft(session, user=user)
    assert report.llm_model == "testovaci-model"

    sent = model.requests[0]["body"]["messages"][1]["content"]
    assert "Poměr IR/ER pod 1,00 souvisel s bolestí ramene." in sent
    assert "DLOUHÝ ABSTRAKT" not in sent
    cit = facts.build(session, list(session.findings.all()),
                      evidence.report_citations(session, list(session.findings.all())))["citace"]
    assert cit == [{"cislo": 1, "zdroj": str(article), "proc_je_tu": "Opora prahu 1,00",
                    "uroven_dukazu": "kohortová studie",
                    "hlavni_zjisteni": "Poměr IR/ER pod 1,00 souvisel s bolestí ramene.",
                    "omezeni": "Jen muži baseballisté.",
                    "populace_studie": "baseball, muži, n = 120",
                    "populace_odpovida": False}]
    assert report.literature == [article.pk]


def test_clanek_k_tematu_a_seznam_zdroju(mereni, model):  # noqa: F811
    user, session = mereni
    tema = _article("IR/ER a prevence", metrics=["ir_er_ratio"], evidence_level="meta",
                    key_finding="Posilování zevních rotátorů zlepšilo poměr IR/ER.")
    _article("Navržený, neschválený", metrics=["ir_er_ratio"],
             status=Article.Status.SUGGESTED)
    _article("Jiný ukazatel", metrics=[])

    model.reply = VERNY
    report = services.build_draft(session, user=user)
    sent = model.requests[0]["body"]["messages"][1]["content"]
    assert "Posilování zevních rotátorů" in sent and "Navržený" not in sent
    assert "k měřenému ukazateli: Poměr IR/ER" in sent
    assert report.literature == [tema.pk]

    # Souhrn na článek k tématu neodkazuje → ve zprávě není.
    context = services.report_context(report)
    assert context["citations"] == []
    services.save_edits(report, summary=VERNY + " Doporučuje se posílení [1].", custom_note="")
    context = services.report_context(report)
    assert [c["article"] for c in context["citations"]] == [tema]
    html = services.render_html(report)
    assert "[1] Novák J, Svoboda K" in html


def test_cisla_zdroju_zustanou_u_konceptu(mereni, model):  # noqa: F811
    user, session = mereni
    first = _article("Starší kohorta", metrics=["ir_er_ratio"], evidence_level="cohort")
    model.reply = VERNY
    report = services.build_draft(session, user=user)
    assert report.literature == [first.pk]
    # Mezitím přibude silnější článek – u nového konceptu by byl první…
    meta = _article("Metaanalýza", metrics=["ir_er_ratio"], evidence_level="meta")
    fresh = evidence.report_citations(session, list(session.findings.all()))
    assert [c["article"] for c in fresh] == [meta, first]
    # …ale tahle zpráva drží svá čísla: [1] zůstává starší kohorta.
    _, data = narrative.report_facts(report)
    assert [(c["cislo"], c["zdroj"]) for c in data["citace"]] == [(1, str(first))]


def test_prednost_maji_ukazatele_se_zmenou(mereni):  # noqa: F811
    user, session = mereni
    metric = MetricDef.objects.get(code="ir_er_ratio")
    metric.mdc = 0.05
    metric.save()
    other = MetricDef.objects.create(code="peak_torque", name="Špičkový moment",
                                     family=metric.family, unit="Nm")
    run = session.protocol_runs.first()
    Measurement.objects.create(trial=run.trials.first(), metric=other, value=100)
    earlier = TestSession.objects.create(organization=session.organization,
                                         subject=session.subject,
                                         date=session.date - timedelta(days=60))
    trial = Trial.objects.create(protocol_run=ProtocolRun.objects.create(
        session=earlier, protocol=run.protocol), number=1)
    Measurement.objects.create(trial=trial, metric=metric, value=1.05)    # změna −0,20 > MDC
    Measurement.objects.create(trial=trial, metric=other, value=100)

    for i in range(evidence.MAX_TOPIC_ARTICLES + 2):
        _article(f"Moment {i}", metrics=["peak_torque"], evidence_level="meta")
    changed = _article("K poměru", metrics=["ir_er_ratio"], evidence_level="expert")
    topic = evidence.topic_articles(session)
    assert len(topic) == evidence.MAX_TOPIC_ARTICLES
    assert topic[0]["article"] == changed
    assert "změna přesahující chybu měření" in topic[0]["reason"]


def test_clanek_k_testu(mereni):  # noqa: F811
    _, session = mereni
    article = _article("O izokinetice")
    article.protocols.set(Protocol.objects.filter(code="iso"))
    topic = evidence.topic_articles(session)
    assert [t["article"] for t in topic] == [article]
    assert topic[0]["reason"] == "k testu: Izokinetika"


def test_odkazy_v_textu():
    assert evidence.cited_numbers("a [1] b [2, 4] c [5–7] d [rok 2020]", "[9]") == {
        1, 2, 4, 5, 6, 7, 9}


def test_sablona_pocita_jen_zdroje_k_nalezum(mereni):  # noqa: F811
    _, session = mereni
    _article("K tématu", metrics=["ir_er_ratio"])
    findings = list(session.findings.all())
    citations = evidence.report_citations(session, findings)
    assert len(citations) == 1
    assert "citovan" not in narrative.compose(session, findings, citations)


# --- dohledání podle DOI / PMID ---------------------------------------------

PUBMED_XML = b"""<?xml version="1.0" ?>
<PubmedArticleSet><PubmedArticle>
 <MedlineCitation Status="MEDLINE"><PMID Version="1">29910432</PMID>
  <Article PubModel="Electronic">
   <Journal><JournalIssue><Volume>5</Volume><PubDate><Year>2017</Year><Month>Sep</Month></PubDate>
    </JournalIssue><Title>Sports (Basel, Switzerland)</Title><ISOAbbreviation>Sports (Basel)</ISOAbbreviation></Journal>
   <ArticleTitle>Influence of <i>Dynamic Strength Index</i> on Countermovement Jump.</ArticleTitle>
   <ELocationID EIdType="doi" ValidYN="Y">10.3390/sports5040072</ELocationID>
   <Abstract><AbstractText Label="PURPOSE">To compare DSI.</AbstractText>
    <AbstractText Label="RESULTS">Low DSI had greater force.</AbstractText></Abstract>
   <AuthorList><Author><LastName>McMahon</LastName><ForeName>John J</ForeName><Initials>JJ</Initials></Author>
    <Author><LastName>Comfort</LastName><Initials>P</Initials></Author>
    <Author><CollectiveName>FTVS Group</CollectiveName></Author></AuthorList>
   <PublicationTypeList><PublicationType>Journal Article</PublicationType>
    <PublicationType>Randomized Controlled Trial</PublicationType></PublicationTypeList>
  </Article></MedlineCitation>
 <PubmedData><ArticleIdList><ArticleId IdType="pubmed">29910432</ArticleId>
  <ArticleId IdType="doi">10.3390/sports5040072</ArticleId></ArticleIdList></PubmedData>
</PubmedArticle></PubmedArticleSet>"""


def test_rozpozna_doi_a_pmid():
    assert lookup.parse_identifier("https://doi.org/10.3390/sports5040072") == (
        "doi", "10.3390/sports5040072")
    assert lookup.parse_identifier("PMID: 29910432") == ("pmid", "29910432")
    assert lookup.parse_identifier("https://pubmed.ncbi.nlm.nih.gov/29910432/") == (
        "pmid", "29910432")
    for bad in ("", "nějaký text"):
        try:
            lookup.parse_identifier(bad)
            raise AssertionError("mělo selhat")
        except lookup.LookupError_:
            pass


def test_precte_pubmed():
    data = lookup.parse_pubmed_xml(PUBMED_XML)
    assert data["title"] == "Influence of Dynamic Strength Index on Countermovement Jump"
    assert data["authors"] == "McMahon JJ, Comfort P, FTVS Group"
    assert (data["journal"], data["year"], data["doi"]) == ("Sports (Basel)", 2017,
                                                             "10.3390/sports5040072")
    assert data["abstract"] == "Purpose: To compare DSI.\n\nResults: Low DSI had greater force."
    assert data["evidence_level"] == "rct"
    assert data["url"] == "https://pubmed.ncbi.nlm.nih.gov/29910432/"


def test_precte_crossref():
    data = lookup.parse_crossref({"message": {
        "DOI": "10.1/x", "title": ["A  title"], "container-title": ["Journal"],
        "author": [{"family": "Novák", "given": "Jan Petr"}],
        "issued": {"date-parts": [[2021, 5]]},
        "abstract": "<jats:title>Abstract</jats:title><jats:p>Abstract text "
                    "<jats:i>here</jats:i>.</jats:p>"}})
    assert (data["title"], data["authors"], data["year"]) == ("A title", "Novák JP", 2021)
    assert data["abstract"] == "Abstract text here."


def test_bez_internetu_srozumitelna_chyba(monkeypatch):
    import urllib.error

    def offline(*args, **kwargs):
        raise urllib.error.URLError("no network")

    monkeypatch.setattr(lookup.urllib.request, "urlopen", offline)
    try:
        lookup.lookup("29910432")
        raise AssertionError("mělo selhat")
    except lookup.LookupError_ as exc:
        assert "internet" in str(exc)


# --- Katalog → Články --------------------------------------------------------

def test_pridani_clanku_v_aplikaci(mereni, monkeypatch):  # noqa: F811
    user, session = mereni
    admin = _admin(session)
    monkeypatch.setattr(lookup, "lookup", lambda text: lookup.parse_pubmed_xml(PUBMED_XML))
    page = admin.get("/sporty/clanky/novy/?hledat=29910432").content.decode()
    assert "Countermovement Jump" in page and "McMahon JJ" in page and "z PubMedu" in page

    metric = MetricDef.objects.get(code="ir_er_ratio")
    rule = Rule.objects.get(code="ir_er")
    response = admin.post("/sporty/clanky/novy/", {
        "title": "Influence of DSI", "authors": "McMahon JJ", "year": "2017",
        "doi": "https://doi.org/10.3390/sports5040072", "pmid": "29910432",
        "status": "suggested", "key_finding": "Nízké DSI → balistický trénink.",
        "metrics": [metric.pk], "rules": [rule.pk]})
    assert response.status_code == 302
    article = Article.objects.get()
    assert article.doi == "10.3390/sports5040072"
    assert list(article.metrics.all()) == [metric]
    assert RuleArticle.objects.filter(rule=rule, article=article).exists()

    # Stejný článek podruhé → odkaz na existující.
    again = admin.get("/sporty/clanky/novy/?hledat=29910432")
    assert again.url == f"/sporty/clanky/{article.pk}/"
    dup = admin.post("/sporty/clanky/novy/", {"title": "x", "doi": "10.3390/sports5040072",
                                              "status": "suggested"})
    assert "už v knihovně je" in dup.content.decode()

    page = admin.get("/sporty/clanky/").content.decode()
    assert "Influence of DSI" in page and "navrženo" in page and "Poměr IR/ER" in page
    admin.post(f"/sporty/clanky/{article.pk}/stav/", {"stav": "approved",
                                                       "next": "https://zle.example/"})
    article.refresh_from_db()
    assert article.status == Article.Status.APPROVED

    # Úprava: odebrat pravidlo.
    admin.post(f"/sporty/clanky/{article.pk}/", {"title": "Influence of DSI",
                                                  "status": "approved", "doi": article.doi})
    assert not RuleArticle.objects.exists() and not article.metrics.exists()

    lab = Client()
    lab.force_login(user)
    assert "Influence of DSI" in lab.get("/sporty/clanky/").content.decode()
    assert lab.get("/sporty/clanky/novy/").url == "/sporty/clanky/"
    lab.post(f"/sporty/clanky/{article.pk}/stav/", {"stav": "rejected"})
    article.refresh_from_db()
    assert article.status == Article.Status.APPROVED


def test_prenos_katalogu_s_tematy_a_pokyny(mereni):  # noqa: F811
    from apps.catalog.transfer import export_catalog, import_catalog

    _, session = mereni
    _article("Téma", metrics=["ir_er_ratio"], doi="10.1/tema", key_finding="Zjištění.")
    ReportStyle.objects.create(organization=session.organization, audience="trener",
                               kind="doporuceni", instructions="Odvážněji.")
    data = export_catalog()
    assert data["clanky"][0]["metriky"] == ["ir_er_ratio"]
    Article.objects.all().delete()
    ReportStyle.objects.all().delete()
    import_catalog(data)
    article = Article.objects.get()
    assert article.key_finding == "Zjištění."
    assert [m.code for m in article.metrics.all()] == ["ir_er_ratio"]
    assert prompts.style_for(session.organization, "trener", "doporuceni") == "Odvážněji."
    # Starší soubor bez druhu pokynů = pokyny pro souhrn.
    import_catalog({**data, "styly_zprav": [{"organizace": "ftvs", "audience": "lekar",
                                             "instructions": "Stručně."}]})
    assert prompts.style_for(session.organization, "lekar") == "Stručně."


def test_stara_zprava_bez_seznamu_literatury(mereni, model):  # noqa: F811
    user, session = mereni
    model.reply = VERNY
    report = services.build_draft(session, user=user)
    Report.objects.filter(pk=report.pk).update(literature=None)
    report.refresh_from_db()
    tema = _article("Téma", metrics=["ir_er_ratio"])
    _, data = narrative.report_facts(report)
    assert data["citace"][0]["zdroj"] == str(tema)


# --- filtry v knihovně -------------------------------------------------------

def test_filtry_clanku(mereni):  # noqa: F811
    from apps.subjects.models import Sport

    _, session = mereni
    org = session.organization
    tenis = Sport.objects.create(organization=org, code="tenis", name="Tenis")
    fotbal = Sport.objects.create(organization=org, code="fotbal", name="Fotbal")
    podani = _article("Podání a síla ramene", metrics=["ir_er_ratio"], evidence_level="cross",
                      population_sex="M", population_age_min=16, population_age_max=18,
                      key_finding="Vnitřní rotace souvisí s rychlostí podání.")
    podani.sports.set([tenis])
    podani.protocols.set(Protocol.objects.filter(code="iso"))
    zeny = _article("Fotbalistky", evidence_level="meta", population_sex="F",
                    population_age_min=20)
    zeny.sports.set([fotbal])
    baseball = _article("Nadhazovači", population_sport="baseball, tenis",
                        status=Article.Status.SUGGESTED)

    admin = _admin(session)

    def titles(**params):
        page = admin.get("/sporty/clanky/", params)
        return {a.title for a in page.context["articles"]}

    assert titles() == {"Podání a síla ramene", "Fotbalistky", "Nadhazovači"}
    assert titles(sport=tenis.pk) == {"Podání a síla ramene", "Nadhazovači"}
    assert titles(sport=tenis.pk, stav="approved") == {"Podání a síla ramene"}
    assert titles(pohlavi="F") == {"Fotbalistky", "Nadhazovači"}
    assert titles(vek=17) == {"Podání a síla ramene", "Nadhazovači"}
    assert titles(vek=25) == {"Fotbalistky", "Nadhazovači"}
    assert titles(test=Protocol.objects.get(code="iso").pk) == {"Podání a síla ramene"}
    assert titles(ukazatel=MetricDef.objects.get(code="ir_er_ratio").pk) == {
        "Podání a síla ramene"}
    assert titles(dukaz="meta") == {"Fotbalistky"}
    assert titles(chybi="zjisteni") == {"Fotbalistky", "Nadhazovači"}
    assert titles(chybi="vazba") == {"Fotbalistky", "Nadhazovači"}
    assert titles(q="rychlostí podání") == {"Podání a síla ramene"}
    page = admin.get("/sporty/clanky/", {"razeni": "dukaz"})
    assert [a.title for a in page.context["articles"]][0] == "Fotbalistky"
    html = admin.get("/sporty/clanky/", {"sport": tenis.pk}).content.decode()
    assert "Zrušit filtry (1)" in html and "2 články" in html
    assert baseball.population_text() == "baseball, tenis"


def test_sport_clanku_ma_prednost(mereni):  # noqa: F811
    from apps.subjects.models import Sport

    _, session = mereni
    tenis = Sport.objects.create(organization=session.organization, code="tenis",
                                 name="Tenis")
    subject = session.subject
    subject.sport = tenis
    subject.save()
    _article("Obecný", metrics=["ir_er_ratio"], evidence_level="meta", year=2024)
    tenisovy = _article("Tenisový", metrics=["ir_er_ratio"], evidence_level="cross")
    tenisovy.sports.set([tenis])
    topic = evidence.topic_articles(session)
    assert topic[0]["article"] == tenisovy
    assert "tenis" in tenisovy.population_text()


def test_sport_z_textu_do_katalogu(mereni):  # noqa: F811
    import importlib

    from django.apps import apps as django_apps

    from apps.subjects.models import Sport

    _, session = mereni
    tenis = Sport.objects.create(organization=session.organization, code="tenis",
                                 name="Tenis")
    article = _article("Starý záznam", population_sport="tenis, baseball")
    migration = importlib.import_module("apps.evidence.migrations.0003_sporty_clanku")
    migration.text_to_sports(django_apps, None)
    article.refresh_from_db()
    assert list(article.sports.all()) == [tenis] and article.population_sport == "baseball"


def test_prenos_sportu_clanku(mereni):  # noqa: F811
    from apps.catalog.transfer import export_catalog, import_catalog
    from apps.subjects.models import Sport

    _, session = mereni
    tenis = Sport.objects.create(organization=session.organization, code="tenis",
                                 name="Tenis")
    _article("Tenis", doi="10.1/tenis").sports.set([tenis])
    data = export_catalog()
    Article.objects.all().delete()
    import_catalog(data)
    assert [s.code for s in Article.objects.get().sports.all()] == ["tenis"]
