"""AI zprávy: varianty pro čtenáře, upravitelné pokyny, vzory, kontext, hodnocení, zkušební sada."""

from datetime import date, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from apps.core.models import Role, User
from apps.measurements.models import Measurement, ProtocolRun, TestSession, Trial
from apps.reports import facts, prompts, services
from apps.reports.models import Audience, ModelTrial, Report, ReportStyle
from apps.subjects.models import Consent
from tests.test_llm import mereni, model  # noqa: F401  (fixtury)

VERNY = "Poměr IR/ER 0,85 je pod 1,00."


def _system(fake, index=0):
    return fake.requests[index]["body"]["messages"][0]["content"]


def _second_session(session, value=0.9, days=60):
    other = TestSession.objects.create(organization=session.organization, subject=session.subject,
                                       date=session.date - timedelta(days=days))
    run = ProtocolRun.objects.create(session=other, protocol=session.protocol_runs.first().protocol)
    trial = Trial.objects.create(protocol_run=run, number=1)
    metric = session.protocol_runs.first().trials.first().measurements.first().metric
    Measurement.objects.create(trial=trial, metric=metric, value=value)
    return other


def _released(session, user, *, audience=Audience.COACH, summary=VERNY, example=False):
    report = services.build_draft(session, user=user, audience=audience)
    report.summary = summary
    report.status = Report.Status.RELEASED
    report.released_at = timezone.now()
    report.is_example = example
    report.save()
    return report


def test_varianta_urci_pokyny_nadpis_i_fakta(mereni, model):  # noqa: F811
    user, session = mereni
    model.reply = VERNY
    report = services.build_draft(session, user=user, audience=Audience.ATHLETE)
    assert report.audience == "sportovec" and report.audience_for == "pro sportovce"
    system = _system(model)
    assert "Čtenář: sportovec" in system and "Používej výhradně čísla" in system
    assert '"ctenar": "sportovec"' in model.requests[0]["body"]["messages"][1]["content"]
    # Nová verze drží variantu.
    report.status = Report.Status.RELEASED
    report.save()
    assert services.supersede(report, user=user).audience == "sportovec"


def test_upravene_pokyny_pouzije_pevna_pravidla_zustanou(mereni, model):  # noqa: F811
    user, session = mereni
    model.reply = VERNY
    ReportStyle.objects.create(organization=session.organization, audience=Audience.COACH,
                               instructions="Piš jako zkušený kondiční trenér, max 120 slov.")
    services.build_draft(session, user=user)
    system = _system(model)
    assert "kondiční trenér" in system and "Používej výhradně čísla" in system
    assert prompts.DEFAULT_STYLES[Audience.COACH] not in system


def test_vzor_se_prida_jen_ke_stejne_variante(mereni, model):  # noqa: F811
    user, session = mereni
    model.reply = VERNY
    earlier = _second_session(session)
    _released(earlier, user, summary="Vzorový souhrn pro trenéra.", example=True)
    model.requests.clear()
    services.build_draft(session, user=user, audience=Audience.COACH)
    assert "Vzorový souhrn pro trenéra." in _system(model)
    model.requests.clear()
    services.build_draft(session, user=user, audience=Audience.CLINICIAN)
    assert "Vzorový souhrn" not in _system(model)


def test_cislo_opsane_ze_vzoru_text_neprojde(mereni, model):  # noqa: F811
    user, session = mereni
    earlier = _second_session(session)
    model.reply = VERNY
    _released(earlier, user, summary="Výška výskoku 47,3 cm je výborná.", example=True)
    model.reply = "Výška výskoku 47,3 cm je výborná."
    report = services.build_draft(session, user=user)
    assert report.llm_model == "šablona" and "47,3" in report.generation_note


def test_zprava_pro_lekare_jen_se_souhlasem(mereni, settings):  # noqa: F811
    user, session = mereni
    report = services.build_draft(session, user=user, audience=Audience.CLINICIAN)
    with pytest.raises(services.ReportError, match="souhlasem"):
        services.release(report, user=user)
    Consent.objects.create(subject=session.subject, scope=Consent.Scope.REPORT_HANDOVER,
                           granted_on=date(2026, 1, 1))
    assert services.release(report, user=user).status == Report.Status.RELEASED


def test_kontext_z_objednavky_a_vyvoj(mereni, settings):  # noqa: F811
    from apps.booking.models import BookingRequest, Participant, Slot

    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    user, session = mereni
    slot = Slot.objects.create(organization=session.organization,
                               start=timezone.make_aware(datetime(2026, 3, 1, 9)))
    request = BookingRequest.objects.create(
        organization=session.organization, slot=slot, goal=BookingRequest.Goal.RETURN,
        goal_note="Chce se vrátit do zápasů", season_phase="rtp")
    participant = Participant(request=request, session=session, subject=session.subject)
    participant.set_data("Eva", "Testovací", date(2001, 5, 5), injury="vymknutý kotník")
    participant.save()
    _second_session(session, value=0.8, days=120)
    _second_session(session, value=0.82, days=60)

    data = facts.build(session, [], [], audience=Audience.CLINICIAN)
    assert data["ctenar"] == "lékař / fyzioterapeut"
    assert data["kontext"] == {"cil_testovani": "návrat po zranění",
                               "cil_upresneni": "Chce se vrátit do zápasů",
                               "treninkove_obdobi": "návrat po zranění",
                               "zraneni_uvedene_klientem": "vymknutý kotník"}
    trend = data["vyvoj"][0]
    assert [p["hodnota"] for p in trend["mereni"]] == [0.8, 0.82, 0.85]
    assert "Eva" not in str(data) and "Testovací" not in str(data)


def test_hodnoceni_vzor_a_sada_v_aplikaci(mereni, model):  # noqa: F811
    user, session = mereni
    model.reply = VERNY
    report = services.build_draft(session, user=user)
    lab = Client()
    lab.force_login(user)
    lab.post(f"/zpravy/{report.pk}/hodnoceni/", {"hodnoceni": "pouzitelny",
                                                 "poznamka": "moc dlouhé"})
    report.refresh_from_db()
    assert (report.ai_rating, report.ai_rating_note) == ("pouzitelny", "moc dlouhé")
    # Laborant vzor neoznačí; správce ano, ale jen u vydané zprávy.
    lab.post(f"/zpravy/{report.pk}/hodnoceni/", {"vzor": "1"})
    report.refresh_from_db()
    assert not report.is_example
    admin = Client()
    admin.force_login(User.objects.create(username="sp", organization=session.organization,
                                          role=Role.ADMIN))
    admin.post(f"/zpravy/{report.pk}/hodnoceni/", {"vzor": "1"})
    report.refresh_from_db()
    assert not report.is_example
    report.status = Report.Status.RELEASED
    report.save()
    admin.post(f"/zpravy/{report.pk}/hodnoceni/", {"vzor": "1"})
    admin.post(f"/zpravy/{report.pk}/hodnoceni/", {"sada": "1"})
    report.refresh_from_db()
    assert report.is_example and report.in_test_set


def test_zkusebni_sada_a_statistika(mereni, model):  # noqa: F811
    user, session = mereni
    model.reply = VERNY
    report = _released(session, user, summary="Poměr IR/ER 0,85 je pod hranicí 1,00.")
    report.in_test_set = True
    report.ai_rating = "dobry"
    report.save()
    admin = Client()
    admin.force_login(User.objects.create(username="sp", organization=session.organization,
                                          role=Role.ADMIN))
    model.reply = "Poměr 0,85 a k tomu 99 bodů."
    model.replies = ["Poměr 0,85 a k tomu 99 bodů."] * 2
    response = admin.post(f"/zpravy/{report.pk}/zkusit-model/", {"model": "jiny-model"},
                          HTTP_HX_REQUEST="true")
    trial = ModelTrial.objects.get()
    assert trial.problems == ["99"] and "99" in response.content.decode()
    assert model.requests[-1]["body"]["model"] == "jiny-model"

    for tab in ("pokyny", "kvalita", "sada"):
        page = admin.get(f"/zpravy/ai/?tab={tab}").content.decode()
        assert "AI zprávy" in page
    stats = services.quality_stats(session.organization)
    row = stats["rows"][0]
    assert row["model"] == "testovaci-model" and row["prepis_pct"] > 0
    assert row["hodnoceni"][0][0] == 1

    lab = Client()
    lab.force_login(user)
    assert lab.get("/zpravy/ai/").url == "/zpravy/"

    call_command("porovnat_modely", "--model", "dalsi-model", verbosity=0)
    assert ModelTrial.objects.filter(model="dalsi-model").exists()


def test_pokyny_se_upravi_vrati_a_prenesou(mereni):  # noqa: F811
    from apps.catalog.transfer import export_catalog, import_catalog

    user, session = mereni
    admin = Client()
    admin.force_login(User.objects.create(username="sp", organization=session.organization,
                                          role=Role.ADMIN))
    admin.post("/zpravy/ai/", {"akce": "pokyny", "audience": "lekar",
                               "instructions": "Jen odborně."})
    assert prompts.style_for(session.organization, "lekar") == "Jen odborně."
    data = export_catalog()
    ReportStyle.objects.all().delete()
    import_catalog(data)
    assert prompts.style_for(session.organization, "lekar") == "Jen odborně."
    admin.post("/zpravy/ai/", {"akce": "pokyny", "audience": "lekar",
                               "instructions": "x", "vychozi": "1"})
    assert prompts.style_for(session.organization, "lekar") == prompts.DEFAULT_STYLES["lekar"]


def test_vytvoreni_zpravy_pro_vybraneho_ctenare(mereni):  # noqa: F811
    user, session = mereni
    client = Client()
    client.force_login(user)
    response = client.post(f"/zpravy/z-mereni/{session.pk}/", {"pro": "sportovec"})
    report = Report.objects.get()
    assert response.url == f"/zpravy/{report.pk}/" and report.audience == "sportovec"
    page = client.get(f"/zpravy/{report.pk}/").content.decode()
    assert "pro sportovce" in page and "Další varianty" in page
