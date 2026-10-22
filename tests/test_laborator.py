"""Práce v laboratoři: neplatný pokus z mřížky, mazání hodnot, opakovaný test, snímek vydané zprávy."""


from django.test import Client

from apps.analytics import queries
from apps.core.models import Role, User
from apps.measurements.forms import field_name
from apps.measurements.models import Measurement, ProtocolRun, Trial
from tests.test_entry import izokinetika, run  # noqa: F401  (fixtury)
from tests.test_reports import prostredi  # noqa: F401


def _client(run):  # noqa: F811
    client = Client()
    client.force_login(User.objects.create(username="lab", organization=run.session.organization,
                                           role=Role.LAB))
    return client


def _field(run, side, trial):  # noqa: F811
    pm = run.protocol.protocol_metrics.first()
    return field_name(pm, {"side": side, "mode": "con", "speed": 210.0, "segment": ""}, trial)


def test_neplatny_pokus_z_mrizky(run):  # noqa: F811
    client = _client(run)
    data = {_field(run, "L", 1): "50", _field(run, "L", 2): "90", "pokusy_stav": "1",
            "neplatny|2": "1", "duvod|2": "nedoskok"}
    response = client.post(f"/mereni/provedeni/{run.pk}/", data, follow=True)
    assert "Neplatný pokus: 2" in response.content.decode()
    trial = Trial.objects.get(protocol_run=run, number=2)
    assert not trial.is_valid and trial.invalid_reason == "nedoskok"
    key = ("ir", "L", "con", 210.0, "")
    assert queries.session_metric_values(run.session)[key]["value"] == 50     # bez pokusu 2

    page = client.get(f"/mereni/provedeni/{run.pk}/").content.decode()
    assert 'name="neplatny|2" value="1" x-model="neplatny" checked' in page
    assert 'value="nedoskok"' in page

    # Odškrtnutí pokus zase započítá.
    client.post(f"/mereni/provedeni/{run.pk}/", {"pokusy_stav": "1"})
    trial.refresh_from_db()
    assert trial.is_valid and trial.invalid_reason == ""
    assert queries.session_metric_values(run.session)[key]["value"] == 70


def test_vymazane_pole_hodnotu_smaze(run):  # noqa: F811
    client = _client(run)
    client.post(f"/mereni/provedeni/{run.pk}/", {_field(run, "L", 1): "50",
                                                 _field(run, "R", 1): "52"})
    assert Measurement.objects.count() == 2
    response = client.post(f"/mereni/provedeni/{run.pk}/", {_field(run, "L", 1): "",
                                                            _field(run, "R", 1): "53"},
                           follow=True)
    assert "Smazáno 1" in response.content.decode()
    assert list(Measurement.objects.values_list("side", "value")) == [("R", 53.0)]


def test_opakovane_mereni_tehoz_testu(run):  # noqa: F811
    client = _client(run)
    session, protocol = run.session, run.protocol
    # Bez zaškrtnutí se vrátí existující provedení.
    response = client.post(f"/mereni/{session.pk}/protokol/", {"protocol": protocol.pk})
    assert response.url == f"/mereni/provedeni/{run.pk}/"
    assert ProtocolRun.objects.count() == 1
    # Se zaškrtnutím vznikne opakované měření s časem; hlavní zůstává první.
    response = client.post(f"/mereni/{session.pk}/protokol/", {"protocol": protocol.pk,
                                                               "repeat": "1"}, follow=True)
    assert ProtocolRun.objects.count() == 2
    repeat = ProtocolRun.objects.exclude(pk=run.pk).get()
    assert not repeat.is_primary and repeat.started_at is not None
    html = response.content.decode()
    assert "opakované měření" in html and "založeno opakované měření" in html
    run.refresh_from_db()
    assert run.is_primary
    assert "opakované měření" in client.get(f"/mereni/{session.pk}/").content.decode()


def test_vydana_zprava_ukazuje_snimek(prostredi):  # noqa: F811
    from apps.reports import services
    from apps.rules.models import Finding, Rule

    org, user, subject, session = prostredi
    client = Client()
    client.force_login(user)
    report = services.release(services.build_draft(session, user=user), user=user)
    assert report.snapshot["findings"][0]["rule_code"] == "ir_er"
    assert "Posílit zevní rotátory" in report.snapshot["recommendations"][0]

    # Svět se změní: nálezy zmizí, pravidlo se vypne. Vydaná zpráva říká dál totéž.
    Finding.objects.filter(session=session).delete()
    Rule.objects.update(is_active=False, recommendation_template="")
    context = services.report_context(report)
    assert [f.text for f in context["findings"]] == [report.snapshot["findings"][0]["text"]]
    assert context["recommendations"] == report.snapshot["recommendations"]
    page = client.get(f"/zpravy/{report.pk}/").content.decode()
    assert "0,85" in page and "Posílit zevní rotátory" in page
    assert "jak byly při vydání" in page

    # Koncept dál počítá živě – teď bez nálezů.
    draft = services.build_draft(session, user=user)
    assert services.report_context(draft)["findings"] == []
    assert "jak byly při vydání" not in client.get(f"/zpravy/{draft.pk}/").content.decode()
