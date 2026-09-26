"""DSI, ODS u CMJ a kontrola rozptylu pokusů."""

from datetime import date

import pytest
from django.core.management import call_command

from apps.catalog.models import MetricDef, Protocol
from apps.core.models import Organization, Role, User
from apps.measurements.models import Measurement, ProtocolRun, TestSession, Trial
from apps.reports import facts, results, services
from apps.rules.models import Rule
from apps.subjects.models import Subject


@pytest.fixture
def lab(db):
    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    user = User.objects.create(username="lab", organization=org, role=Role.LAB)
    subject = Subject.objects.create(organization=org, code="FTVS-0001")
    return org, user, subject


def mereni(lab, day, protocol_code, values: dict, trials: int = 3):
    """values: {(metrika, strana): [pokusy]}"""
    org, _, subject = lab
    session, _ = TestSession.objects.get_or_create(organization=org, subject=subject, date=day)
    run = ProtocolRun.objects.create(session=session,
                                     protocol=Protocol.objects.get(code=protocol_code))
    for (code, side), vals in values.items():
        metric = MetricDef.objects.get(code=code)
        for number, value in enumerate(vals, start=1):
            trial, _ = Trial.objects.get_or_create(protocol_run=run, number=number)
            Measurement.objects.create(trial=trial, metric=metric, side=side, value=value)
    return session


def test_dsi_se_dopocita_z_cmj_a_imtp(lab):
    from apps.analytics.derived import recompute

    session = mereni(lab, date(2026, 3, 1), "cmj", {("cmj_peak_force", "B"): [1800, 1800]})
    mereni(lab, date(2026, 3, 1), "imtp", {("imtp_peak_force", "B"): [2500, 2500]})
    assert recompute(session) == 1
    dsi = Measurement.objects.get(metric__code="dsi")
    assert dsi.value == 0.72                            # 1800 / 2500
    assert dsi.trial.protocol_run.external_ref == "odvozeno:dsi"

    # druhý přepočet nic nezdvojí; bez IMTP odvozená hodnota zmizí
    recompute(session)
    assert Measurement.objects.filter(metric__code="dsi").count() == 1
    ProtocolRun.objects.filter(protocol__code="imtp").delete()
    recompute(session)
    assert not Measurement.objects.filter(metric__code="dsi").exists()


def test_pravidla_dsi_maji_literaturu_a_jsou_vypnuta(lab):
    rule = Rule.objects.get(code="dsi_nizky")
    assert rule.is_active is False
    assert rule.rule_articles.filter(article__doi="10.3390/sports5040072").exists()
    assert rule.rule_articles.first().article.status == "suggested"   # schválí člověk


def test_ods_vysvetli_zmenu_vysky_zmenou_strategie(lab):
    MetricDef.objects.filter(code="cmj_height").update(mdc=2.0)
    MetricDef.objects.filter(code="cmj_depth").update(mdc=3.0)
    MetricDef.objects.filter(code="cmj_peak_force").update(mdc=100)
    mereni(lab, date(2026, 1, 1), "cmj", {("cmj_height", "B"): [38, 38],
                                           ("cmj_depth", "B"): [30, 30],
                                           ("cmj_peak_force", "B"): [1800, 1800]})
    session = mereni(lab, date(2026, 3, 1), "cmj", {("cmj_height", "B"): [34, 34],
                                                     ("cmj_depth", "B"): [24, 24],
                                                     ("cmj_peak_force", "B"): [1790, 1790]})
    block = next(b for b in results.protocol_results(session) if b["ods"])
    roles = [g["role"] for g in block["ods"]["groups"]]
    assert roles == ["vysledek", "pricina", "strategie"]
    text = block["ods"]["text"]
    assert "Skutečná změna výsledku (výška výskoku)" in text
    assert "strategie skoku: hloubka protipohybu" in text
    assert "hnacích" not in text                       # síla se nezměnila nad MDC

    ods = facts._ods(session)
    assert ods["vysledek"][0]["zmena"] == -4.0
    assert ods["interpretace"] == text


def test_rozptyl_pokusu_se_ohlasi(lab):
    session = mereni(lab, date(2026, 3, 1), "cmj", {("cmj_height", "B"): [30, 38, 34]})
    block = results.protocol_results(session)[0]
    row = block["rows"][0]
    assert row["cv"] == pytest.approx(11.76, abs=0.01)
    assert row["cv_warn"] and block["unstable"] == [row]

    report = services.build_draft(session, user=lab[1])
    assert "rozptyl pokusů 11,8 % ▲" in services.render_html(report)


def test_stabilni_pokusy_bez_varovani(lab):
    session = mereni(lab, date(2026, 3, 1), "cmj", {("cmj_height", "B"): [34, 35, 34.5]})
    assert results.protocol_results(session)[0]["unstable"] == []


def test_import_ukaze_nestabilni_pokusy(lab):
    from datetime import datetime

    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.ingest import services as ingest
    from tests.test_vald import cmj, forcedecks

    org, user, _ = lab
    data = forcedecks([
        ("Petr Novák", "u-1", "19.05.2003", datetime(2026, 8, 21, 11, 0), "Trial 1", cmj(30.0)),
        ("Petr Novák", "u-1", "19.05.2003", datetime(2026, 8, 21, 11, 0), "Trial 2", cmj(38.0)),
    ])
    batch = ingest.stage_file(uploaded_file=SimpleUploadedFile("cmj.xlsx", data),
                              user=user, organization=org)
    assert batch.summary["nestabilnich_celkem"] == 1
    assert batch.summary["nestabilni_pokusy"][0]["metrika"] == "Výška výskoku (CMJ)"
    ingest.commit_batch(batch, user=user)
    batch.refresh_from_db()
    assert "nestabilni_pokusy" not in batch.summary     # jména pryč i odsud
