"""Výzkumný export: anonymizovaně, jen se souhlasem s výzkumem i genetikou, od pěti osob; vlastní frekvence."""

import csv
import io
import zipfile
from datetime import date, timedelta

import pytest
from cryptography.fernet import Fernet
from django.core.management import CommandError, call_command
from django.test import Client
from django.utils import timezone

from apps.catalog.models import MetricDef, Protocol, ProtocolMetric, TestFamily
from apps.core import access
from apps.core.models import AuditLog, Organization, Role, User
from apps.genetics import research, seed, services
from apps.genetics.models import Domain, GenePanel, GeneVariant, PanelItem
from apps.measurements import questionnaires
from apps.measurements.models import Measurement, ProtocolRun, TestSession, Trial
from apps.subjects.models import Consent, Subject, SubjectIdentity


@pytest.fixture
def org(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.GENETICS_ENCRYPTION_KEY = Fernet.generate_key().decode()
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


@pytest.fixture
def populace(org):
    """Sedm dospělých s ověřeným vzorkem; pět má souhlas s výzkumem, jeden je neplatný, jeden bez."""
    lab, _ = _user(org, Role.LAB, "laborant")
    panel = GenePanel.objects.create(organization=org, code="p", name="Panel")
    actn3 = GeneVariant.objects.create(organization=org, gene="ACTN3", rsid="rs1815739",
                                       domain=Domain.objects.get(code="vykon"), order=1,
                                       genotypes=["CC", "CT", "TT"],
                                       genotype_aliases={"CC": "RR", "CT": "RX", "TT": "XX"})
    off = GeneVariant.objects.create(organization=org, gene="FTO", rsid="rs9939609",
                                     domain=Domain.objects.get(code="hmotnost"), order=2,
                                     genotypes=["TT", "AT", "AA"], is_active=False)
    PanelItem.objects.create(panel=panel, variant=actn3, order=1)
    PanelItem.objects.create(panel=panel, variant=off, order=2)
    cmj = Protocol.objects.create(code="cmj", name="CMJ", family=TestFamily.FORCE_PLATE,
                                  default_trials=3)
    height = MetricDef.objects.create(code="cmj_height", name="Výška výskoku",
                                      family=TestFamily.FORCE_PLATE, unit="cm", decimals=1)
    ProtocolMetric.objects.create(protocol=cmj, metric=height, is_primary=True, sides=["B"])
    q = questionnaires.questionnaire("genetika")
    subjects = []
    genotypes = ["CC", "CT", "CT", "TT", "CT", "CC", "TT"]
    for i in range(7):
        subject = Subject.objects.create(organization=org, code=f"FTVS-{i + 1:04d}", sex="M",
                                         level="trained")
        identity = SubjectIdentity(subject=subject)
        identity.set_names("Jan", f"Novák{i}")
        identity.set_birth_date(date(1990 + i, 1, 1))
        identity.save()
        services.grant_consent(subject, by=lab)
        if i < 5:
            Consent.objects.create(subject=subject, scope=Consent.Scope.RESEARCH,
                                   granted_on=timezone.localdate())
        elif i == 5:
            Consent.objects.create(subject=subject, scope=Consent.Scope.RESEARCH,
                                   granted_on=timezone.localdate() - timedelta(days=30),
                                   revoked_on=timezone.localdate() - timedelta(days=1))
        sample = services.record_sample(subject, panel, by=lab, data={},
                                        genotypes={actn3.pk: genotypes[i], off.pk: "AA"})
        services.verify_sample(sample, by=lab)
        session = TestSession.objects.create(organization=org, subject=subject,
                                             date=date(2026, 9, 10 + i), fatigue_rating=3)
        run = ProtocolRun.objects.create(session=session, protocol=cmj, is_primary=True)
        trial = Trial.objects.create(protocol_run=run, number=1)
        Measurement.objects.create(trial=trial, metric=height, side="B", value=30 + i)
        values = questionnaires.parse_answers(q, {"q_hlavni_sport": "Tajný klub Kobylisy",
                                                  "q_cil": "vytrvalost", "q_unava": "4",
                                                  "q_zmena_objemu__stav": "unknown"})
        questionnaires.save_standalone(subject, q, values, source="sportovec")
        subjects.append(subject)
    return {"org": org, "lab": lab, "subjects": subjects, "actn3": actn3}


def test_export_jen_se_souhlasem_a_bez_identifikace(populace):
    P = populace
    eligible = research.eligible_subjects(P["org"])
    assert [s.code for s in eligible] == [f"FTVS-000{i}" for i in range(1, 6)]
    content, count = research.build_export(P["org"])
    assert count == 5
    archive = zipfile.ZipFile(io.BytesIO(content))
    names = set(archive.namelist())
    assert names == {"README.txt", "sportovci.csv", "genotypy.csv", "mereni.csv", "dotaznik.csv"}
    text = "".join(archive.read(n).decode() for n in names)
    for forbidden in ("FTVS-", "Novák", "Jan", "Kobylisy", "1990", "2026-09-1"):
        assert forbidden not in text, forbidden

    def rows(name):
        return list(csv.DictReader(io.StringIO(archive.read(name).decode()), delimiter=";"))

    people = rows("sportovci.csv")
    assert len(people) == 5 and {p["pohlavi"] for p in people} == {"M"}
    assert {p["vek_pasmo"] for p in people} <= {"25–34", "35–44"}   # ročníky 1990–1994
    assert all(len(p["id"]) == 12 for p in people)
    ids = {p["id"] for p in people}
    genotypes = rows("genotypy.csv")
    assert len(genotypes) == 5 and {g["rsid"] for g in genotypes} == {"rs1815739"}   # FTO vypnuta
    assert sorted(g["genotyp"] for g in genotypes) == ["CC", "CT", "CT", "CT", "TT"]
    assert {g["id"] for g in genotypes} == ids
    measurements = rows("mereni.csv")
    assert {m["mesic"] for m in measurements} == {"2026-09"}
    assert sorted(m["ukazatel"] for m in measurements) == ["cmj_height"] * 5 + ["subjektivni_unava"] * 5
    assert {m["hodnota"] for m in measurements if m["ukazatel"] == "cmj_height"} == {"30.0", "31.0", "32.0", "33.0", "34.0"}
    answers = rows("dotaznik.csv")
    assert {a["otazka"] for a in answers} == {"cil", "unava", "zmena_objemu"}          # bez textu
    assert {(a["otazka"], a["odpoved"]) for a in answers} >= {("cil", "vytrvalost"), ("unava", "4"),
                                                               ("zmena_objemu", "unknown")}
    # Stálý identifikátor: stejná osoba má stejné id při každém exportu, ale ne kód.
    again, _ = research.build_export(P["org"])
    assert {p["id"] for p in csv.DictReader(io.StringIO(
        zipfile.ZipFile(io.BytesIO(again)).read("sportovci.csv").decode()), delimiter=";")} == ids
    assert research.research_id(P["subjects"][0]) in ids


def test_pod_minimem_se_export_nevyda(populace):
    P = populace
    for subject in P["subjects"][3:5]:
        services.revoke_consent(subject, by=P["lab"])
    assert len(research.eligible_subjects(P["org"])) == 3
    with pytest.raises(ValueError, match="od 5 sportovců"):
        research.build_export(P["org"])
    with pytest.raises(CommandError, match="od 5"):
        call_command("vyzkumny_export")


def test_stazeni_prikaz_a_frekvence(populace, tmp_path, settings):
    P = populace
    _, lab_client = _user(P["org"], Role.LAB, "laborant2")
    response = lab_client.get("/genetika/vyzkum/export/")
    assert response.status_code == 200 and response["Content-Type"] == "application/zip"
    assert "vyzkum-genetika-" in response["Content-Disposition"]
    assert AuditLog.objects.filter(action=AuditLog.Action.EXPORT, detail__vyzkum="genetika",
                                   detail__osob=5).exists()
    researcher, r_client = _user(P["org"], Role.RESEARCHER, "vyzkum")
    assert r_client.get("/genetika/vyzkum/export/").status_code == 403   # bez exportů jen čte
    access.grant(researcher, exports=True)                              # zapnul správce
    assert r_client.get("/genetika/vyzkum/export/").status_code == 200
    coach, coach_client = _user(P["org"], Role.COACH, "trener")
    assert coach_client.get("/genetika/vyzkum/export/").url == "/trener/"

    target = tmp_path / "vyzkum.zip"
    call_command("vyzkumny_export", cil=str(target))
    assert zipfile.ZipFile(target).namelist()[0] == "README.txt"

    page = lab_client.get("/genetika/").content.decode()
    assert "5 osob se souhlasem" in page and "Anonymizovaný export (ZIP)" in page
    assert "Frekvence genotypů v populaci laboratoře" in page
    freq = research.frequencies(P["org"])
    (row,) = freq
    assert row["variant"] == P["actn3"] and row["n"] == 5 and row["enough"]
    assert [(g["genotyp"], g["pocet"], g["procent"]) for g in row["genotypes"]] == [
        ("CC (RR)", 1, 20), ("CT (RX)", 3, 60), ("TT (XX)", 1, 20)]
    assert "CT (RX) 60 % (3)" in page
    # Pod minimem jen poznámka, bez čísel.
    services.revoke_consent(P["subjects"][0], by=P["lab"])
    page = lab_client.get("/genetika/").content.decode()
    assert "zatím málo výsledků" in page and "Export se vydá od 5 osob" in page
    # Bez klíče stránka nespadne a export odmítne.
    settings.GENETICS_ENCRYPTION_KEY = ""
    assert lab_client.get("/genetika/").status_code == 200
    assert lab_client.get("/genetika/vyzkum/export/").url == "/genetika/"
