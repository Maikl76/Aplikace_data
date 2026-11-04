"""Genetika a měření: měření před genotypem, scénáře s měřením, pokus s kofeinem, genetický kontext ve zprávě z měření."""

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.catalog.models import Direction, MetricDef, Norm, Protocol, ProtocolMetric, TestFamily
from apps.genetics import report as genetics_report
from apps.genetics import seed, services
from apps.genetics.models import ContextScenario, Domain, ScenarioText
from apps.measurements import questionnaires
from apps.measurements.models import Measurement, ProtocolRun, TestSession, Trial
from apps.reports import services as report_services
from apps.reports.models import Audience, Report
from apps.reports.results import _conditions_text
from tests.test_genetika_zprava import laborator, org  # noqa: F401


def _session(subject, days_ago, protocol, metric, value, *, conditions=None, fatigue=None):
    session, _ = TestSession.objects.get_or_create(
        organization=subject.organization, subject=subject,
        date=timezone.localdate() - timedelta(days=days_ago))
    if fatigue is not None:
        session.fatigue_rating = fatigue
        session.save()
    run = ProtocolRun.objects.create(session=session, protocol=protocol, is_primary=True,
                                     conditions=conditions or {})
    trial = Trial.objects.create(protocol_run=run, number=1)
    Measurement.objects.create(trial=trial, metric=metric, side="B", value=value)
    return session, run


def test_seed_doplni_ukazatele_oblasti_jen_kdyz_chybi(laborator):
    vykon = Domain.objects.get(code="vykon")
    assert vykon.metrics.count() == 0          # katalog vznikl až po oblastech
    cmj = MetricDef.objects.create(code="cmj_height", name="Výška výskoku",
                                   family=TestFamily.FORCE_PLATE, unit="cm")
    assert seed.seed_domains() == 0
    assert set(vykon.metrics.all()) == {cmj, MetricDef.objects.get(code="vo2max")}
    assert Domain.objects.get(code="regenerace").uses_fatigue
    vykon.metrics.clear()
    other = MetricDef.objects.create(code="sprint_30m", name="Sprint 30 m",
                                     family=TestFamily.FIELD, unit="s")
    vykon.metrics.add(other)
    seed.seed_domains()
    assert list(vykon.metrics.all()) == [other]   # vlastní výběr se nepřepisuje


def test_mereni_mluvi_prvni(laborator):
    L = laborator
    subject, vo2 = L["subject"], MetricDef.objects.get(code="vo2max")
    vo2.direction = Direction.HIGHER
    vo2.mdc = 2.0
    vo2.save()
    vykon = Domain.objects.get(code="vykon")
    vykon.metrics.add(vo2)
    vykon.uses_fatigue = True
    vykon.save()
    Norm.objects.create(metric=vo2, mean=45.0, sd=5.0, source_citation="Norma 2020")
    older, _ = _session(subject, 200, L["spiro"], vo2, 48.0, fatigue=4)
    latest = TestSession.objects.get(subject=subject, date=timezone.localdate() - timedelta(days=40))
    latest.fatigue_rating = 6
    latest.save()
    rpe = questionnaires.questionnaire("rpe")
    if rpe is None:
        from apps.catalog.management.commands.seed_catalog import Command

        Command().handle(only_missing=True)
        rpe = questionnaires.questionnaire("rpe")
    questionnaires.save(latest, rpe, {rpe.questions.first(): 7}, source="operator",
                        run=latest.protocol_runs.first())

    content = genetics_report.compose(L["sample"], L["response"], audience=Audience.ATHLETE)
    (area,) = content["oblasti"]
    (row,) = area["mereni"]
    assert row["ukazatel"] == "VO2max" and row["hodnota"] == "52,3 ml/kg/min"
    assert row["norma"] == "nad normou (příznivě)"
    assert row["zmena"].startswith("zlepšení (minule 48,0 ml/kg/min") and row["zmena_kod"] == "better"
    assert area["unava"] == [{"datum": latest.date.strftime("%d.%m.%Y"), "unava": 6, "rpe": ["7"]},
                             {"datum": older.date.strftime("%d.%m.%Y"), "unava": 4, "rpe": []}]
    assert content["mereni_poznamka"].startswith("Měření popisuje")
    facts = genetics_report.facts(content)
    assert facts["oblasti"][0]["mereni"] == [
        f"VO2max: 52,3 ml/kg/min ({latest.date.strftime('%d.%m.%Y')}), nad normou (příznivě), "
        f"zlepšení (minule 48,0 ml/kg/min, {older.date.strftime('%d.%m.%Y')})"]
    assert facts["poznamka_k_mereni"] == genetics_report.MEASUREMENT_NOTE
    # Čísla z měření smí model použít; cizí ne.
    assert genetics_report.verify_summary("VO2max 52,3 je nad normou.", content) == []
    assert "číslo 60" in genetics_report.verify_summary("VO2max 60.", content)
    # Vypnuté měření v oblasti.
    vykon.show_measurements = False
    vykon.save()
    content = genetics_report.compose(L["sample"], L["response"], audience=Audience.ATHLETE)
    assert content["oblasti"][0]["mereni"] == []
    html = report_services.render_html(
        genetics_report.build_draft(L["sample"], user=L["lab"], audience=Audience.ATHLETE))
    assert "V každé oblasti je nejdřív to, co se změřilo" in html


def test_scenar_s_merenim_a_kontrola_podminky(laborator):
    L = laborator
    vo2 = MetricDef.objects.get(code="vo2max")
    Norm.objects.create(metric=vo2, mean=45.0, sd=5.0, source_citation="Norma 2020")
    scenario = ContextScenario(card=L["card_actn3"], kind="measurement",
                               statement="Nadprůměrná aerobní kapacita v laboratorním testu.",
                               condition={"z": "vo2max", "op": ">", "value": 1.0}, is_active=True)
    scenario.full_clean()
    scenario.save()
    ScenarioText.objects.create(scenario=scenario, genotype="CT",
                                text="Změřená aerobní kapacita je uvedena vedle genotypu.")
    content = genetics_report.compose(L["sample"], L["response"], audience=Audience.ATHLETE)
    context = content["oblasti"][0]["polozky"][0]["kontext"]
    assert [c["zdroj"] for c in context] == [
        "z dotazníku", "z měření " + (timezone.localdate() - timedelta(days=40)).strftime("%d.%m.%Y")]
    assert context[1]["text"].startswith("Změřená aerobní kapacita")
    # Nesedící podmínka nic nepřidá; špatně zapsaná podmínka se neuloží.
    scenario.condition = {"z": "vo2max", "op": ">", "value": 5.0}
    scenario.save()
    content = genetics_report.compose(L["sample"], L["response"], audience=Audience.ATHLETE)
    assert len(content["oblasti"][0]["polozky"][0]["kontext"]) == 1
    with pytest.raises(ValidationError) as exc:
        ContextScenario(card=L["card_actn3"], kind="measurement", statement="x",
                        condition={"z": "neexistuje", "op": ">", "value": 1}).full_clean()
    assert "condition" in exc.value.message_dict
    with pytest.raises(ValidationError) as exc:
        ContextScenario(card=L["card_actn3"], kind="questionnaire", statement="x",
                        is_active=True).full_clean()
    assert "is_active" in exc.value.message_dict
    with pytest.raises(ValidationError):
        ContextScenario(card=L["card_actn3"], kind="questionnaire", statement="x",
                        answer_match={"foo": 1}).full_clean()


def test_pokus_s_kofeinem(laborator):
    L = laborator
    subject = L["subject"]
    wingate = Protocol.objects.create(code="wingate", name="Wingate test",
                                      family=TestFamily.DYNAMOMETRY, default_trials=1)
    pmax = MetricDef.objects.create(code="wingate_pmax_th", name="Pmax/kg",
                                    family=TestFamily.DYNAMOMETRY, unit="W/kg", decimals=2,
                                    direction=Direction.HIGHER, mdc=0.3)
    ProtocolMetric.objects.create(protocol=wingate, metric=pmax, is_primary=True, sides=["B"])
    _session(subject, 20, wingate, pmax, 10.52)
    _, run = _session(subject, 12, wingate, pmax, 11.24, conditions={"kofein_mg_kg": 3})
    _session(subject, 5, wingate, pmax, 10.60)     # další bez kofeinu, dál od pokusu
    assert _conditions_text(run.conditions) == "kofein 3 mg/kg"

    content = genetics_report.compose(L["sample"], L["response"], audience=Audience.ATHLETE)
    (trial,) = content["kofein"]
    assert trial["test"] == "Wingate test" and trial["davka"] == 3.0
    assert trial["s_kofeinem"] == (timezone.localdate() - timedelta(days=12)).strftime("%d.%m.%Y")
    assert trial["bez"] == (timezone.localdate() - timedelta(days=5)).strftime("%d.%m.%Y")   # nejbližší
    (row,) = trial["rozdily"]
    assert row == {"ukazatel": "Pmax/kg", "s_kofeinem": "11,24 W/kg", "bez": "10,60 W/kg",
                   "rozdil": "+0,64 W/kg", "posouzeni": "zlepšení", "kod": "better"}
    facts = genetics_report.facts(content)
    assert facts["pokus_s_kofeinem"][0].startswith("Wingate test (3 mg/kg")
    html = report_services.render_html(
        genetics_report.build_draft(L["sample"], user=L["lab"], audience=Audience.ATHLETE))
    assert "Pokus s kofeinem" in html and "+0,64 W/kg" in html and "nevysvětluje ani nepotvrzuje" in html

    # Podmínky provedení se zadávají u testu; prázdná dávka klíč odstraní.
    client = L["client"]
    response = client.post(f"/mereni/provedeni/{run.pk}/podminky/",
                           {"kofein_mg_kg": "4,5", "poznamka": "ráno nalačno"})
    assert response.url == f"/mereni/provedeni/{run.pk}/"
    run.refresh_from_db()
    assert run.conditions == {"kofein_mg_kg": 4.5} and run.note == "ráno nalačno"
    page = client.get(f"/mereni/provedeni/{run.pk}/").content.decode()
    assert "kofein 4,5 mg/kg" in page and 'value="4.5"' in page
    client.post(f"/mereni/provedeni/{run.pk}/podminky/", {"kofein_mg_kg": "", "poznamka": ""})
    run.refresh_from_db()
    assert run.conditions == {} and run.note == ""


def test_geneticky_kontext_ve_zprave_z_mereni(laborator):
    L = laborator
    subject = L["subject"]
    session = TestSession.objects.get(subject=subject)
    # Bez vydané genetické zprávy nic.
    testing = report_services.build_draft(session, user=L["lab"], audience=Audience.ATHLETE)
    assert report_services.report_context(testing)["genetic_context"] is None
    genetic = genetics_report.build_draft(L["sample"], user=L["lab"], audience=Audience.ATHLETE)
    report_services.release(genetic, user=L["lab"])
    context = report_services.report_context(testing)["genetic_context"]
    assert context["cislo"] == genetic.report_number
    assert [g["gen"] for g in context["genotypy"]] == ["ACTN3", "ACE"]     # COL5A1 bez karty
    assert context["oblasti"] == ["Výkon a trénink"]
    html = report_services.render_html(testing)
    assert "7. Souvislost s genetickým vyšetřením" in html and "ACTN3 CT (RX) (výkon a trénink)" in html
    page = L["client"].get(f"/zpravy/{testing.pk}/").content.decode()
    assert "Souvislost s genetickým vyšetřením" in page and genetic.report_number in page
    # Trenér ani lékař (bez vlastní genetické zprávy) genetický kontext nedostanou.
    coach_report = report_services.build_draft(session, user=L["lab"], audience=Audience.COACH)
    assert report_services.report_context(coach_report)["genetic_context"] is None
    assert "genetick" not in report_services.render_html(coach_report)
    clinician = report_services.build_draft(session, user=L["lab"], audience=Audience.CLINICIAN)
    assert report_services.report_context(clinician)["genetic_context"] is None
    # Vydání zmrazí kontext do snímku; odvolaný souhlas ho z vydané zprávy nevezme.
    report_services.release(testing, user=L["lab"])
    assert testing.snapshot["genetic_context"]["cislo"] == genetic.report_number
    services.revoke_consent(subject, by=L["lab"])
    assert report_services.report_context(testing)["genetic_context"]["cislo"] == genetic.report_number
    fresh = report_services.build_draft(session, user=L["lab"], audience=Audience.ATHLETE)
    assert report_services.report_context(fresh)["genetic_context"] is None
    assert Report.objects.filter(kind=Report.Kind.TESTING).count() == 4
