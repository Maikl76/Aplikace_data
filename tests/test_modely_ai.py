"""Volba jazykového modelu, přepsání souhrnu jiným modelem a psaní na pozadí."""

from datetime import timedelta

from django.test import Client
from django.utils import timezone

from apps.core.models import Role, User
from apps.reports import ai_models, llm, services
from apps.reports.models import AiModel, ModelTrial, Report
from tests.test_llm import mereni, model  # noqa: F401  (fixtury)

VERNY = "Poměr IR/ER 0,85 je pod 1,00."


def _admin(session):
    client = Client()
    client.force_login(User.objects.create(username="sp", organization=session.organization,
                                           role=Role.ADMIN))
    return client


def test_vychozi_model_a_cekani_z_aplikace(mereni, model, settings):  # noqa: F811
    _, session = mereni
    assert ai_models.default_model() == "testovaci-model"      # bez nastavení z .env
    admin = _admin(session)
    admin.post("/zpravy/ai/", {"akce": "model_pridat", "name": "LLM_MODEL=meta/muse-glimmer",
                               "timeout": "900"})
    admin.post("/zpravy/ai/", {"akce": "model_vychozi", "name": "meta/muse-glimmer"})
    glimmer = AiModel.objects.get(name="meta/muse-glimmer")
    assert glimmer.is_default and glimmer.timeout == 900
    assert ai_models.default_model() == "meta/muse-glimmer"
    assert ai_models.timeout_for("meta/muse-glimmer") == 900
    model.reply = VERNY
    llm.chat([{"role": "user", "content": "x"}])
    assert model.requests[-1]["body"]["model"] == "meta/muse-glimmer"
    page = admin.get("/zpravy/ai/?tab=modely").content.decode()
    assert "meta/muse-glimmer" in page and "google/gemma-3-4b" in page   # i ze serveru
    assert ai_models.choices()[0] == ("meta/muse-glimmer", "meta/muse-glimmer (výchozí)")


def test_zprava_vybranym_modelem(mereni, model):  # noqa: F811
    user, session = mereni
    AiModel.objects.create(name="meta/muse-glimmer", label="Glimmer")
    model.reply = VERNY
    client = Client()
    client.force_login(user)
    page = client.get(f"/mereni/{session.pk}/").content.decode()
    assert "Glimmer" in page and 'name="model"' in page
    client.post(f"/zpravy/z-mereni/{session.pk}/", {"pro": "trener", "model": "meta/muse-glimmer"})
    assert model.requests[-1]["body"]["model"] == "meta/muse-glimmer"
    # Model, který se nenabízí, se nepoužije (výchozí místo něj).
    client.post(f"/zpravy/z-mereni/{session.pk}/", {"pro": "trener", "model": "cizi-model"})
    assert model.requests[-1]["body"]["model"] == "testovaci-model"


def test_napsat_znovu_necha_puvodni_text_v_historii(mereni, model):  # noqa: F811
    user, session = mereni
    model.reply = VERNY
    report = services.build_draft(session, user=user)
    services.save_edits(report, summary=VERNY + " Upraveno.", custom_note="")
    model.reply = "Poměr IR/ER je 0,85, tedy pod 1,00."
    client = Client()
    client.force_login(user)
    client.post(f"/zpravy/{report.pk}/napsat-znovu/", {"model": "testovaci-model",
                                                       "summary": VERNY + " Upraveno."})
    report.refresh_from_db()
    assert report.summary == "Poměr IR/ER je 0,85, tedy pod 1,00." and not report.summary_edited
    old = ModelTrial.objects.get(report=report)
    assert old.text == VERNY + " Upraveno." and "upraveno" in old.model
    assert "dřívější texty souhrnu" in client.get(f"/zpravy/{report.pk}/").content.decode()


def test_nepovedene_prepsani_text_nezmeni(mereni, model):  # noqa: F811
    user, session = mereni
    model.reply = VERNY
    report = services.build_draft(session, user=user)
    model.reply = "Poměr 0,85 a 77 dalších věcí."
    services.rewrite_summary(report, model=None)
    report.refresh_from_db()
    assert report.summary == VERNY and "nepovedlo" in report.generation_note
    assert not ModelTrial.objects.exists() and not report.writing


def test_psani_na_pozadi(mereni, model, settings):  # noqa: F811
    """Zpráva vznikne hned ze šablony, model ji pak přepíše; mezitím ji nejde vydat."""
    user, session = mereni
    settings.LLM_BACKGROUND = True
    model.reply = VERNY
    calls = []
    orig = services._start_writing
    services._start_writing = lambda report, m, rewrite: calls.append((report.pk, m, rewrite))
    try:
        report = services.build_draft(session, user=user)
    finally:
        services._start_writing = orig
    assert report.is_writing and report.llm_model == "šablona" and "0,85" in report.summary
    assert calls == [(report.pk, None, False)] and not model.requests
    try:
        services.release(report, user=user)
        raise AssertionError("vydání mělo selhat")
    except services.ReportError as exc:
        assert "píše" in str(exc)
    client = Client()
    client.force_login(user)
    page = client.get(f"/zpravy/{report.pk}/").content.decode()
    assert "píše souhrn" in page and "Vydat</button>" not in page
    assert client.get(f"/zpravy/{report.pk}/pise/").content.decode().endswith(" s")

    services.write_summary(report.pk, None, rewrite=False)        # co udělá vlákno
    report.refresh_from_db()
    assert not report.is_writing and report.summary == VERNY
    assert report.llm_model == "testovaci-model"
    assert client.get(f"/zpravy/{report.pk}/pise/")["HX-Refresh"] == "true"


def test_prerusene_psani_zpravu_uvolni(mereni, settings):  # noqa: F811
    user, session = mereni
    report = services.build_draft(session, user=user)
    Report.objects.filter(pk=report.pk).update(
        writing=Report.Writing.RUNNING, writing_model="x",
        writing_started_at=timezone.now() - timedelta(hours=2))
    client = Client()
    client.force_login(user)
    page = client.get(f"/zpravy/{report.pk}/").content.decode()
    assert "nedokončilo" in page
    report.refresh_from_db()
    assert not report.writing
