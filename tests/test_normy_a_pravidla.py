"""Normy podle strany a úrovně, kontrola tvaru pravidel, omezení zátěže."""

from datetime import date, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from apps.analytics.services import find_norm
from apps.catalog.models import MetricDef, Norm, Protocol
from apps.core.models import Organization, Role, User
from apps.external.models import ExternalExam
from apps.measurements.models import Measurement, ProtocolRun, TestSession, Trial
from apps.rules import engine
from apps.rules.models import Rule
from apps.subjects.models import Sport, Subject


@pytest.fixture
def lab(db, client):
    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    user = User.objects.create(username="lab", organization=org, role=Role.LAB)
    sport = Sport.objects.create(organization=org, code="tenis", name="Tenis")
    subject = Subject.objects.create(organization=org, code="FTVS-0001", sport=sport,
                                     level=Subject.Level.RECREATIONAL, sex="M")
    client.force_login(user)
    return org, subject, client


# --- normy ------------------------------------------------------------------

def test_norma_pro_uroven_a_stranu_se_nepouzije_jinde(lab):
    org, subject, _ = lab
    metric = MetricDef.objects.get(code="ir_er_ratio")
    obecna = Norm.objects.create(organization=org, metric=metric, mean=0.8, sd=0.1,
                                 source_citation="obecná")
    elitni_leva = Norm.objects.create(organization=org, metric=metric, mean=1.0, sd=0.1,
                                      level=Subject.Level.INTERNATIONAL, side="L",
                                      source_citation="elitní levá")

    # Rekreační sportovec, pravá strana: elitní norma pro levou nesedí.
    assert find_norm(metric, subject, side="R") == obecna
    subject.level = Subject.Level.INTERNATIONAL
    assert find_norm(metric, subject, side="R") == obecna
    assert find_norm(metric, subject, side="L") == elitni_leva
    # Sportovec bez vyplněné úrovně na normu s úrovní nemá nárok.
    subject.level = ""
    assert find_norm(metric, subject, side="L") == obecna


def test_oboustranna_hodnota_bez_strany_sedi_na_normu_oboustranne(lab):
    org, subject, _ = lab
    metric = MetricDef.objects.get(code="cmj_height")
    obou = Norm.objects.create(organization=org, metric=metric, mean=30, sd=3, side="B",
                               source_citation="B")
    assert find_norm(metric, subject, side="") == obou
    assert find_norm(metric, subject, side="B") == obou
    assert find_norm(metric, subject, side="L") is None


def test_prevod_volneho_textu_normy():
    from apps.catalog.norms import normalize_fields

    data = {"level": "Elite", "side": "Levá", "mode": "Concentric"}
    assert normalize_fields(data) == []
    assert data == {"level": "intl", "side": "L", "mode": "con"}
    data = {"level": "kdo ví", "side": "", "mode": "iso"}
    assert normalize_fields(data) == ["úroveň: kdo ví"]
    assert data == {"level": "", "side": "", "mode": "iso"}


@pytest.mark.django_db(transaction=True)
def test_migrace_prevede_normy_na_kody():
    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    metric = MetricDef.objects.get(code="ir_er_ratio").pk
    executor = MigrationExecutor(connection)
    executor.migrate([("catalog", "0008_vlastni_pristroje")])
    try:
        nodes = [n for n in executor.loader.graph.leaf_nodes() if n[0] != "catalog"]
        OldNorm = (executor.loader.project_state(nodes + [("catalog", "0008_vlastni_pristroje")])
                   .apps.get_model("catalog", "Norm"))
        OldNorm.objects.create(organization_id=org.pk, metric_id=metric, level="elite",
                               side="Levá", mode="con", mean=1.0, source_citation="x")
        OldNorm.objects.create(organization_id=org.pk, metric_id=metric, level="divná",
                               mean=1.0, source_citation="y", note="pozn.")
    finally:
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
    first, second = Norm.objects.order_by("pk")
    assert (first.level, first.side, first.mode) == ("intl", "L", "con")
    assert second.level == "" and "úroveň: divná" in second.note and second.note.startswith("pozn.")


# --- pravidla ---------------------------------------------------------------

def _rule(org, **kwargs):
    defaults = dict(organization=org, code="r1", name="Test", severity="medium",
                    condition={"metric": "ir_er_ratio", "op": "<", "value": 1.0,
                               "where": {"speed": 210}},
                    finding_template="Poměr {value_txt} při {speed_txt} °/s je pod {threshold_txt}.")
    defaults.update(kwargs)
    return Rule(**defaults)


def test_rychlost_mimo_where_se_neulozi(lab):
    org, *_ = lab
    rule = _rule(org, condition={"metric": "ir_er_ratio", "op": "<", "value": 1.0, "speed": 210})
    with pytest.raises(ValidationError) as info:
        rule.full_clean()
    message = info.value.message_dict["condition"][0]
    assert "speed" in message and '"where": {"speed": 210}' in message

    for condition, hint in [
        ({"metric": "ir_er_ratoi", "op": "<", "value": 1.0}, "v katalogu není"),
        ({"metric": "ir_er_ratio", "op": "<>", "value": 1.0}, "operátor"),
        ({"metric": "ir_er_ratio", "op": "<", "value": "1"}, "číslo"),
        ({"metric": "ir_er_ratio", "op": "<", "value": 1, "where": {"rychlost": 210}}, "where"),
        ({"all": [], "x": 1}, "all"),
        ({"asymetrie": "*", "op": ">", "value": 10}, "právě jeden"),
        ({}, "neprázdný"),
    ]:
        with pytest.raises(ValidationError, match=hint):
            _rule(org, condition=condition).full_clean()
    with pytest.raises(ValidationError, match="load_restriction"):
        _rule(org, contraindication={"external_exam": "load_restriction"}).full_clean()
    _rule(org).full_clean()
    _rule(org, condition={"asymmetry": "*", "op": ">", "value": 10},
          finding_template="{metric}: {index_txt} %").full_clean()


def test_sablona_smi_pouzit_jen_nabizena_pole(lab):
    org, *_ = lab
    with pytest.raises(ValidationError) as info:
        _rule(org, finding_template="Delta {delta_txt}").full_clean()
    assert "{delta_txt}" in info.value.message_dict["finding_template"][0]
    with pytest.raises(ValidationError, match="Nepovolený"):
        _rule(org, recommendation_template="{value.__class__}").full_clean()
    # „any“: jisté je jen to, co mají všechny části.
    condition = {"any": [{"metric": "ir_er_ratio", "op": "<", "value": 1},
                         {"change": "cmj_height", "op": "<", "value": 0}]}
    _rule(org, condition=condition, finding_template="{value_txt}").full_clean()
    with pytest.raises(ValidationError):
        _rule(org, condition=condition, finding_template="{delta_txt}").full_clean()


def test_vzorova_pravidla_z_katalogu_projdou_kontrolou(lab):
    for rule in Rule.objects.all():
        rule.full_clean()


def test_where_omezi_i_asymetrii(lab):
    org, subject, _ = lab
    session = TestSession.objects.create(organization=org, subject=subject, date=date(2026, 3, 1))
    run = ProtocolRun.objects.create(session=session, protocol=Protocol.objects.get(code="cmj"))
    trial = Trial.objects.create(protocol_run=run, number=1)
    metric = MetricDef.objects.get(code="cmj_peak_force")
    Measurement.objects.create(trial=trial, metric=metric, side="L", value=1000)
    Measurement.objects.create(trial=trial, metric=metric, side="R", value=800)
    context = engine._build_context(session)
    assert engine._evaluate({"asymmetry": "*", "op": ">", "value": 10}, context)
    assert not engine._evaluate({"asymmetry": "*", "op": ">", "value": 10,
                                 "where": {"speed": 60}}, context)


# --- omezení zátěže ---------------------------------------------------------

def test_novejsi_bez_omezeni_zrusi_starsi_omezeni(lab):
    org, subject, client = lab
    today = timezone.localdate()
    full = ExternalExam.objects.create(subject=subject, exam_type="medical",
                                       date=today - timedelta(days=30),
                                       load_restriction=ExternalExam.Restriction.FULL)
    assert ExternalExam.active_restriction_for(subject) == full
    page = client.get(f"/sportovci/{subject.pk}/").content.decode()
    assert "Platné omezení zátěže" in page

    ExternalExam.objects.create(subject=subject, exam_type="medical", date=today,
                                load_restriction=ExternalExam.Restriction.NONE)
    assert ExternalExam.active_restriction_for(subject) is None
    assert "Platné omezení zátěže" not in client.get(f"/sportovci/{subject.pk}/").content.decode()

    # „Neuvedeno“ nic nemění; nové plné omezení zase platí.
    ExternalExam.objects.create(subject=subject, exam_type="lab", date=today,
                                load_restriction=ExternalExam.Restriction.UNKNOWN)
    assert ExternalExam.active_restriction_for(subject) is None
    partial = ExternalExam.objects.create(subject=subject, exam_type="imaging",
                                          date=today + timedelta(days=1),
                                          load_restriction=ExternalExam.Restriction.PARTIAL)
    assert ExternalExam.active_restriction_for(subject) == partial
