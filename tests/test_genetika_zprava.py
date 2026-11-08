"""Genetická zpráva: sestavení ze schválených karet, slučování, co změřit, vydání a kdo ji vidí."""

import json
from datetime import date, timedelta

import pytest
from cryptography.fernet import Fernet
from django.test import Client
from django.utils import timezone

from apps.catalog.models import MetricDef, Protocol, ProtocolMetric, Question, TestFamily
from apps.core.models import Organization, Role, User
from apps.genetics import report as genetics_report
from apps.genetics import seed, services
from apps.genetics.models import (
    CardSource,
    ContextScenario,
    Domain,
    ForbiddenStatement,
    GeneCard,
    GenePanel,
    GeneVariant,
    GenotypeText,
    PanelItem,
    Recommendation,
    ScenarioText,
)
from apps.measurements import questionnaires
from apps.measurements.models import Measurement, ProtocolRun, TestSession, Trial
from apps.reports import services as report_services
from apps.reports.models import Audience, Report
from apps.subjects.models import Consent, Sharing, Subject, SubjectIdentity


@pytest.fixture
def org(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.GENETICS_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.EMAIL_HOST = ""
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
    subject = Subject.objects.create(organization=org, code=code, sport=None)
    identity = SubjectIdentity(subject=subject)
    identity.set_names("Jana", "Nová")
    identity.set_birth_date(date(1990, 5, 1))
    identity.save()
    return subject


def _approved_card(variant, guarantor, texts: dict, **extra):
    card = GeneCard.objects.create(organization=variant.organization, variant=variant,
                                   version=1, status=GeneCard.Status.REVIEW,
                                   biology_client=f"Gen {variant.gene} – biologie pro klienta.",
                                   biology_expert=f"Gen {variant.gene} – odborně.", **extra)
    for g, text in texts.items():
        GenotypeText.objects.create(card=card, genotype=g, client_text=text,
                                    expert_text=f"Odborně: {text}")
    CardSource.objects.create(card=card, citation=f"Autor et al. (2020). Studie {variant.gene}. "
                                                  f"Journal, 1(1), 1-10.")
    return card


@pytest.fixture
def laborator(org):
    """Panel se třemi aktivními variantami a jednou vypnutou, dvě schválené karty, vzorek."""
    lab, client = _user(org, Role.LAB, "laborant")
    guarantor, _ = _user(org, Role.LAB, "metodik")
    for domain in Domain.objects.all():
        domain.guarantors.add(guarantor)
    vykon = Domain.objects.get(code="vykon")
    actn3 = GeneVariant.objects.create(organization=org, gene="ACTN3", rsid="rs1815739",
                                       domain=vykon, order=1, genotypes=["CC", "CT", "TT"],
                                       genotype_aliases={"CC": "RR", "CT": "RX", "TT": "XX"})
    ace = GeneVariant.objects.create(organization=org, gene="ACE", rsid="rs1799752",
                                     domain=vykon, order=2, genotypes=["II", "ID", "DD"])
    col5a1 = GeneVariant.objects.create(organization=org, gene="COL5A1", rsid="rs12722",
                                        domain=Domain.objects.get(code="pohybovy_aparat"),
                                        order=3, genotypes=["CC", "CT", "TT"])
    fto = GeneVariant.objects.create(organization=org, gene="FTO", rsid="rs9939609",
                                     domain=Domain.objects.get(code="hmotnost"), order=4,
                                     genotypes=["TT", "AT", "AA"], is_active=False)
    spiro = Protocol.objects.create(code="spiro", name="Spiroergometrie",
                                    family=TestFamily.SPIROERGOMETRY, default_trials=1)
    vo2 = MetricDef.objects.create(code="vo2max", name="VO2max", family=TestFamily.SPIROERGOMETRY,
                                   unit="ml/kg/min", decimals=1)
    ProtocolMetric.objects.create(protocol=spiro, metric=vo2, is_primary=True, sides=["B"])

    card_actn3 = _approved_card(actn3, guarantor, {
        "CC": "Byl zjištěn genotyp CC (RR).", "CT": "Byl zjištěn genotyp CT (RX).",
        "TT": "Byl zjištěn genotyp TT (XX)."}, limitations="Z výsledku nelze určit sílu.")
    Recommendation.objects.create(card=card_actn3, kind="training", text="Zařaďte plyometrii.",
                                  merge_key="plyometrie", basis="general", order=1)
    Recommendation.objects.create(card=card_actn3, genotype="CT", kind="risk",
                                  text="Regeneraci není třeba hlídat víc než obvykle.",
                                  merge_key="regenerace", basis="variant", order=2)
    Recommendation.objects.create(card=card_actn3, kind="other", basis="measurement",
                                  text="Aerobní kapacitu posoudí spiroergometrie.",
                                  protocol=spiro, order=3)
    Recommendation.objects.create(card=card_actn3, genotype="TT", kind="sport",
                                  text="Jen pro TT.", basis="variant", order=4)
    question = Question.objects.get(questionnaire__code="genetika", code="vykonovy_profil")
    active = ContextScenario.objects.create(card=card_actn3, kind="questionnaire",
                                            statement="Dosahuji velmi dobrých výsledků ve sprintech.",
                                            question=question, answer_match={"choices": ["sila"]},
                                            is_active=True)
    ScenarioText.objects.create(scenario=active, genotype="CT",
                                text="Vaše zkušenost se silovým výkonem je uvedena vedle genotypu.")
    inactive = ContextScenario.objects.create(card=card_actn3, kind="questionnaire",
                                              statement="Neaktivní scénář.", question=question,
                                              answer_match={"choices": ["sila"]}, is_active=False)
    ScenarioText.objects.create(scenario=inactive, genotype="CT", text="NESMÍ SE OBJEVIT")
    card_ace = _approved_card(ace, guarantor, {
        "II": "Byl zjištěn genotyp II.", "ID": "Byl zjištěn genotyp ID.",
        "DD": "Byl zjištěn genotyp DD."})
    Recommendation.objects.create(card=card_ace, kind="training", text="Zařaďte plyometrii.",
                                  merge_key="plyometrie", basis="variant", order=1)
    Recommendation.objects.create(card=card_ace, kind="risk", text="Hlídejte regeneraci.",
                                  merge_key="regenerace", basis="variant", order=2)
    for card in (card_actn3, card_ace):
        services.approve(card, by=guarantor)
    GeneCard.objects.create(organization=org, variant=col5a1, version=1,
                            status=GeneCard.Status.DRAFT)      # neschválená karta
    ForbiddenStatement.objects.create(card=None, text="jste univerzální typ")

    panel = GenePanel.objects.create(organization=org, code="p10", name="Panel", provider="Lab")
    for order, variant in enumerate((actn3, ace, col5a1, fto), start=1):
        PanelItem.objects.create(panel=panel, variant=variant, order=order)
    subject = _adult(org)
    services.grant_consent(subject, by=lab)
    sample = services.record_sample(subject, panel, by=lab, data={"reported_on": date(2026, 10, 20)},
                                    genotypes={actn3.pk: "rx", ace.pk: "II", col5a1.pk: "CT",
                                               fto.pk: "AA"})
    services.verify_sample(sample, by=lab)

    session = TestSession.objects.create(organization=org, subject=subject,
                                         date=timezone.localdate() - timedelta(days=40))
    run = ProtocolRun.objects.create(session=session, protocol=spiro, is_primary=True)
    trial = Trial.objects.create(protocol_run=run, number=1)
    Measurement.objects.create(trial=trial, metric=vo2, side="B", value=52.34)

    q = questionnaires.questionnaire("genetika")
    values = questionnaires.parse_answers(q, {"q_hlavni_sport": "atletika", "q_cil": "sila_rychlost",
                                              "q_vykonovy_profil": "sila", "q_unava": "6"})
    response = questionnaires.save_standalone(subject, q, values, source="sportovec")
    return {"org": org, "lab": lab, "client": client, "guarantor": guarantor, "subject": subject,
            "sample": sample, "response": response, "actn3": actn3, "ace": ace,
            "card_actn3": card_actn3, "card_ace": card_ace, "spiro": spiro}


def test_sestaveni_obsahu_ze_schvalenych_karet(laborator):
    L = laborator
    content = genetics_report.compose(L["sample"], L["response"], audience=Audience.ATHLETE)
    assert [g["gen"] for g in content["genotypy"]] == ["ACTN3", "ACE", "COL5A1"]   # FTO vypnuta
    assert content["genotypy"][0]["genotyp_txt"] == "CT (RX)" and content["genotypy"][0]["karta"] == "v1"
    assert content["cil"] == {"sport": "atletika", "cil": "síla, rychlost, výbušnost"}
    assert content["dotaznik"]["oddily"][0]["odpovedi"][0] == {"otazka": "Hlavní sport nebo disciplína",
                                                               "odpoved": "atletika"}
    (area,) = content["oblasti"]
    assert area["nazev"] == "Výkon a trénink" and [e["gen"] for e in area["polozky"]] == ["ACTN3", "ACE"]
    actn3 = area["polozky"][0]
    assert actn3["text"] == "Byl zjištěn genotyp CT (RX)." and actn3["biologie"].startswith("Gen ACTN3 – biologie")
    assert actn3["ucinek"] == "" and actn3["dukazy"] == []
    assert [k["text"] for k in actn3["kontext"]] == ["Vaše zkušenost se silovým výkonem je uvedena vedle genotypu."]
    assert actn3["kontext"][0]["odpoved"].startswith("Dosahuji velmi dobrých")
    assert "NESMÍ" not in json.dumps(content, ensure_ascii=False)
    # Doporučení jen pro zjištěný genotyp (TT ne), bez „budoucího měření“ (to je v části Co doplnit).
    assert [r["text"] for r in actn3["doporuceni"]] == ["Zařaďte plyometrii.",
                                                       "Regeneraci není třeba hlídat víc než obvykle."]
    # Sloučení podle klíče: stejný text → jedno doporučení se dvěma důvody; různý text → k posouzení.
    (merged,) = content["doporuceni"]
    assert merged["text"] == "Zařaďte plyometrii." and merged["slouceno"] == 2
    assert merged["varianty"] == ["ACE / rs1799752", "ACTN3 / rs1815739"] and len(merged["duvody"]) == 2
    (conflict,) = content["k_posouzeni"]
    assert conflict["klic"] == "regenerace" and len(conflict["moznosti"]) == 2
    # Co změřit: test a výsledek z posledního roku, bez výkladu.
    (measure,) = content["co_doplnit"]
    assert measure["test"] == "Spiroergometrie" and measure["k_dispozici"]["values"] == ["VO2max 52,3 ml/kg/min"]
    assert (COL := content["neinterpretovano"][0])["gen"] == "COL5A1" and "není schválená" in COL["duvod"]
    assert "Z výsledku nelze určit sílu." in content["omezeni"] and len(content["omezeni"]) == 5
    assert [z["cislo"] for z in content["zdroje"]] == [1, 2]
    assert content["versions"]["karty"] == {"rs1799752": 1, "rs1815739": 1}
    assert content["versions"]["karty_text"] == "rs1799752@v1,rs1815739@v1"
    assert content["nepripustne_vyroky"] == []
    # Pro lékaře odborné texty a důkazy.
    expert = genetics_report.compose(L["sample"], L["response"], audience=Audience.CLINICIAN)
    assert expert["oblasti"][0]["polozky"][0]["text"] == "Odborně: Byl zjištěn genotyp CT (RX)."
    assert expert["oblasti"][0]["polozky"][0]["biologie"] == "Gen ACTN3 – odborně."
    # Bez dotazníku: žádný kontext, cíl prázdný.
    bare = genetics_report.compose(L["sample"], None, audience=Audience.ATHLETE)
    assert bare["cil"] == {} and bare["dotaznik"] is None and bare["oblasti"][0]["polozky"][0]["kontext"] == []
    summary = genetics_report.template_summary(content)
    assert "3 variant" in summary and "• Výkon a trénink: ACTN3 CT (RX), ACE II." in summary


def test_koncept_vydani_a_snimek(laborator):
    L = laborator
    client, sample, subject = L["client"], L["sample"], L["subject"]
    with pytest.raises(genetics_report.GeneticsReportError, match="trenér"):
        genetics_report.build_draft(sample, user=L["lab"], audience=Audience.COACH)
    response = client.post(f"/genetika/sportovec/{subject.pk}/zprava/",
                           {"vzorek": sample.pk, "pro": Audience.ATHLETE})
    report = Report.objects.get(kind=Report.Kind.GENETICS)
    assert response.url == f"/zpravy/{report.pk}/"
    assert report.report_number == f"FTG-{timezone.localdate().year}-0001"
    assert report.genetic_sample == sample and report.questionnaire_response == L["response"]
    assert report.session is None and report.llm_model == "šablona"
    assert report.rules_version == "rs1799752@v1,rs1815739@v1" and report.title.startswith("Zpráva z genetického")
    assert "Výkon a trénink" in report.summary and report.disclaimer.startswith("Výsledek genetického")

    page = client.get(f"/zpravy/{report.pk}/").content.decode()
    assert "Genotypy (3)" in page and "K odbornému posouzení" in page and "z dotazníku" in page
    assert "Byl zjištěn genotyp CT (RX)." in page and "Navrhnout doporučení" not in page
    assert '<option value="lekar">' in page and '<option value="trener">' not in page
    preview = client.get(f"/zpravy/{report.pk}/nahled/").content.decode()
    assert "1. Cíl klienta a dostupné podklady" in preview and "VO2max 52,3 ml/kg/min" in preview
    assert "6. Omezení interpretace a použité zdroje" in preview and "[1]" in preview

    # Nepřípustný výrok v textu diagnostika: upozornění při uložení, vydání se odmítne.
    client.post(f"/zpravy/{report.pk}/", {"summary": report.summary,
                                           "custom_note": "Podle výsledku jste univerzální typ."})
    report.refresh_from_db()
    response = client.get(f"/zpravy/{report.pk}/")
    assert "nepřípustný výrok" in response.content.decode()
    with pytest.raises(report_services.ReportError, match="nepřípustný výrok"):
        report_services.release(report, user=L["lab"])
    client.post(f"/zpravy/{report.pk}/", {"summary": report.summary, "custom_note": "Doplňte spánek."})
    report.refresh_from_db()
    report_services.release(report, user=L["lab"])
    assert report.status == Report.Status.RELEASED and "genetika" in report.snapshot
    assert "Byl zjištěn genotyp CT (RX)." in report.rendered_html and "Doplňte spánek." in report.rendered_html
    data = json.loads(report.data_json.read().decode())
    assert data["druh"] == "geneticke_vysetreni" and data["verze_karet"] == {"rs1799752": 1, "rs1815739": 1}
    assert data["genotypy"][0] == {"gen": "ACTN3", "rsid": "rs1815739", "genotyp": "CT",
                                   "kvalita": "V pořádku", "karta": "v1"}

    # Nová verze karty vydanou zprávu nemění; nový koncept už bere novou verzi.
    new = services.new_version(L["card_actn3"], by=L["lab"])
    new.genotype_texts.filter(genotype="CT").update(client_text="Nové znění pro CT.")
    services.submit_for_review(new)
    services.approve(new, by=L["guarantor"])
    context = report_services.report_context(report)
    assert context["content"]["oblasti"][0]["polozky"][0]["text"] == "Byl zjištěn genotyp CT (RX)."
    assert "Nové znění" not in report_services.render_html(report)
    newer = report_services.supersede(report, user=L["lab"])
    assert newer.version == 2 and newer.kind == Report.Kind.GENETICS and newer.supersedes == report
    assert "rs1815739@v2" in newer.rules_version
    assert report_services.report_context(newer)["content"]["oblasti"][0]["polozky"][0]["text"] == "Nové znění pro CT."

    # Sportovec vydanou zprávu vidí v portálu; trenér nikdy (ani se sdílením).
    athlete, athlete_client = _user(L["org"], Role.ATHLETE, "jana@example.cz")
    identity = subject.identity
    identity.user = athlete
    identity.save()
    page = athlete_client.get(f"/muj/{subject.pk}/").content.decode()
    assert report.report_number in page and "genetické vyšetření" in page
    assert "Zpráva z genetického vyšetření" in athlete_client.get(
        f"/muj/{subject.pk}/zprava/{report.pk}/").content.decode()
    coach, coach_client = _user(L["org"], Role.COACH, "trener")
    Sharing.objects.create(subject=subject, coach=coach, status=Sharing.Status.ACTIVE)
    assert coach_client.get(f"/trener/{subject.pk}/zprava/{report.pk}/").status_code == 404
    assert report.report_number not in coach_client.get(f"/trener/{subject.pk}/").content.decode()

    # Odvolaný souhlas: vydaná zpráva zůstává, nový koncept nejde.
    services.revoke_consent(subject, by=L["lab"])
    assert Report.objects.get(pk=report.pk).status == Report.Status.RELEASED
    with pytest.raises(genetics_report.GeneticsReportError, match="souhlas"):
        genetics_report.build_draft(sample, user=L["lab"], audience=Audience.ATHLETE)


def test_lekar_potrebuje_souhlas_s_predanim_a_neovereny_vzorek_nejde(laborator):
    L = laborator
    report = genetics_report.build_draft(L["sample"], user=L["lab"], audience=Audience.CLINICIAN)
    assert "Odborně: Byl zjištěn genotyp CT (RX)." in report_services.render_html(report)
    with pytest.raises(report_services.ReportError, match="předáním"):
        report_services.release(report, user=L["lab"])
    Consent.objects.create(subject=L["subject"], scope=Consent.Scope.REPORT_HANDOVER,
                           granted_on=timezone.localdate())
    report_services.release(report, user=L["lab"])
    assert report.status == Report.Status.RELEASED
    other = services.record_sample(L["subject"], L["sample"].panel, by=L["lab"], data={},
                                   genotypes={L["actn3"].pk: "CC"})
    with pytest.raises(genetics_report.GeneticsReportError, match="ověřeného"):
        genetics_report.build_draft(other, user=L["lab"], audience=Audience.ATHLETE)
    response = L["client"].post(f"/genetika/sportovec/{L['subject'].pk}/zprava/",
                                {"vzorek": other.pk, "pro": Audience.ATHLETE}, follow=True)
    assert "ověřeného vzorku" in response.content.decode()
    assert "Zprávu lze sestavit až z ověřeného vzorku" not in response.content.decode()


def test_kontrola_souhrnu_od_modelu(laborator):
    L = laborator
    content = genetics_report.compose(L["sample"], L["response"], audience=Audience.ATHLETE)
    ok = "Zpráva vychází z panelu a dotazníku. • Výkon a trénink: ACTN3 a ACE."
    assert genetics_report.verify_summary(ok, content) == []
    bad = "Jste univerzální typ a máte 7 z 10 bodů únavy; VO2max 60."
    problems = genetics_report.verify_summary(bad, content)
    assert any("univerzální typ" in p for p in problems)
    # Model dostává jen schválené texty a cíl – čísla z dotazníku ani měření v nich nejsou.
    assert {"číslo 7", "číslo 10", "číslo 60"} <= set(problems)
    facts = genetics_report.facts(content)
    assert facts["oblasti"][0]["varianty"][0]["text_karty"] == "Byl zjištěn genotyp CT (RX)."
    assert facts["doporuceni_sloucena"] == ["Zařaďte plyometrii."] and facts["k_odbornemu_posouzeni"] == ["regenerace"]


def test_dvoji_kliknuti_nezalozi_druhy_koncept(laborator):
    """Tlačítko se po kliknutí zamkne a server druhý stejný požadavek do dvou minut odkáže na hotový koncept."""
    L = laborator
    client, sample, subject = L["client"], L["sample"], L["subject"]
    page = client.get(f"/genetika/sportovec/{subject.pk}/").content.decode()
    assert 'data-jednou="Sestavuji koncept…"' in page and "data-jednou-poznamka" in page
    assert 'form[data-jednou]' in page                      # společný zámek v base.html
    data = {"vzorek": sample.pk, "pro": Audience.ATHLETE}
    first = client.post(f"/genetika/sportovec/{subject.pk}/zprava/", data)
    second = client.post(f"/genetika/sportovec/{subject.pk}/zprava/", data)
    assert Report.objects.filter(kind=Report.Kind.GENETICS).count() == 1
    assert first.url == second.url
    # jiný čtenář je jiná zpráva
    client.post(f"/genetika/sportovec/{subject.pk}/zprava/", {"vzorek": sample.pk, "pro": Audience.CLINICIAN})
    assert Report.objects.filter(kind=Report.Kind.GENETICS).count() == 2
