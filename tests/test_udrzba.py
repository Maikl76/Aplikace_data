"""Údržba: normy jedním dotazem, strana B = bez strany, otisk pravidel, opakované nahrání souboru."""

from datetime import date
from types import SimpleNamespace

from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.catalog.models import MetricDef, Norm, Protocol
from apps.core.models import Organization, Role, User
from apps.measurements.models import Measurement, ProtocolRun, TestSession, Trial
from apps.reports import services
from apps.rules import engine
from apps.subjects.models import Sport, Subject
from tests.test_hodnota_dne import veslar, zmer  # noqa: F401  (fixtura a pomocník)


def test_normy_se_nactou_jednou_pro_celou_zpravu(veslar):  # noqa: F811
    org = veslar.organization
    for code in ("cmj_height", "body_mass"):
        Norm.objects.create(organization=org, metric=MetricDef.objects.get(code=code),
                            mean=30, sd=3, source_citation="x")
    zmer(veslar, date(2026, 3, 1), "cmj", "cmj_height", [30.0, 31.0])
    zmer(veslar, date(2026, 3, 1), "cmj", "body_mass", [73.0, 73.1])
    session = zmer(veslar, date(2026, 3, 1), "bodycomp", "body_mass", [72.9])
    user = User.objects.create(username="lab2", organization=org, role=Role.LAB)
    report = services.build_draft(session, user=user)

    with CaptureQueriesContext(connection) as ctx:
        context = services.report_context(report)
    norm_queries = [q["sql"] for q in ctx.captured_queries if "catalog_norm" in q["sql"]]
    assert len(norm_queries) == 1
    assert any(r["norm_txt"] for b in context["results"] for r in b["rows"])


def test_strana_b_a_bez_strany_je_totez(db):
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    sport = Sport.objects.create(organization=org, code="tenis", name="Tenis")
    subject = Subject.objects.create(organization=org, code="FTVS-0001", sport=sport)
    metric = MetricDef.objects.create(code="vo2max", name="VO2max", family="spiro", unit="ml",
                                      decimals=1)
    protocol = Protocol.objects.create(code="sj", name="Spiro", family="spiro")
    for day, side, value in [(date(2026, 1, 1), "B", 50.0), (date(2026, 6, 1), "", 53.0)]:
        session = TestSession.objects.create(organization=org, subject=subject, date=day)
        trial = Trial.objects.create(protocol_run=ProtocolRun.objects.create(
            session=session, protocol=protocol), number=1)
        Measurement.objects.create(trial=trial, metric=metric, side=side, value=value)

    rows = services.results.protocol_results(session)[0]["rows"]
    assert rows[0]["previous_txt"] == "50,0" and rows[0]["delta_txt"] == "+3,0"
    context = engine._build_context(session)
    assert engine._evaluate({"metric": "vo2max", "op": ">", "value": 52,
                             "where": {"side": "B"}}, context)
    assert engine._evaluate({"metric": "vo2max", "op": ">", "value": 52,
                             "where": {"side": ""}}, context)


def test_otisk_pravidel_se_neusekne():
    findings = [SimpleNamespace(rule=SimpleNamespace(code=f"pravidlo_{i:02d}"), rule_version=1)
                for i in range(12)]
    otisk = services._rules_fingerprint(findings)
    assert len(otisk) > 40 and otisk.endswith("pravidlo_11@1")


def test_zruseny_import_jde_nahrat_znovu(db, settings):
    from cryptography.fernet import Fernet
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.core.management import call_command

    from apps.ingest import services as ingest
    from apps.ingest.models import ImportBatch
    from apps.measurements.models import RawFile
    from tests.test_vald import T1, cmj, forcedecks

    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    user = User.objects.create(username="lab", organization=org, role=Role.LAB)
    data = forcedecks([("Petr Novák", "uuid-1", "19.05.2003", T1, "Trial 1", cmj(34.0))])
    batch = ingest.stage_file(uploaded_file=SimpleUploadedFile("e.xlsx", data), user=user,
                              organization=org)
    assert batch.status == ImportBatch.Status.PARSED
    batch.status = ImportBatch.Status.CANCELLED
    batch.save()

    znovu = ingest.stage_file(uploaded_file=SimpleUploadedFile("e.xlsx", data), user=user,
                              organization=org)
    assert znovu.pk != batch.pk and znovu.status == ImportBatch.Status.PARSED
    assert not ImportBatch.objects.filter(pk=batch.pk).exists()
    assert RawFile.objects.count() == 1
