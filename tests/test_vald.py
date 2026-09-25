"""
Import exportů z VALD (ForceDecks, HumanTrak).

Soubory se tu skládají uměle se stejnou stavbou jako skutečné exporty –
se sedmi řádky popisu nad hlavičkou, jedním řádkem na pokus, sloupci
„(Left)“/„(Right)“. Jména jsou vymyšlená; skutečné exporty do repozitáře
nepatří.
"""

import io
from datetime import datetime

import openpyxl
import pytest
from cryptography.fernet import Fernet
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone

from apps.analytics import queries
from apps.catalog.models import ImportColumn, ImportProfile, MetricDef
from apps.core.models import Organization, Role, User
from apps.ingest import services
from apps.ingest.adapters import detect_adapter, get_adapter
from apps.ingest.models import ImportBatch
from apps.measurements.models import Measurement, ProtocolRun, TestSession
from apps.reports import results
from apps.subjects.models import Subject, SubjectExternalId, SubjectIdentity

CMJ_COLUMNS = ["Jump Height (Imp-Mom) [cm]", "RSI-modified (Imp-Mom) [m/s]",
               "Concentric Peak Force [N]", "Concentric Peak Force (Left) [N]",
               "Concentric Peak Force (Right) [N]", "Countermovement Depth [cm]",
               "Body Weight [kg]", "Flight Time [ms]"]
HEAD = ["Athlete", "Athlete Id", "ExtId", "Date of Birth", "Gender", "Athlete Notes",
        "Test Type", "Test Date", "Test Notes", "Test Parameters", "Test Tags"]


def forcedecks(rows, *, test_type="Countermovement Jump", columns=CMJ_COLUMNS) -> bytes:
    """rows: (jméno, id, datum narození, čas testu, pokus, {sloupec: hodnota})"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ForceDecks Test Results Export"])
    ws.append(["Export Date", datetime(2026, 9, 16, 10, 0)])
    ws.append(["Export Profile", "X"])
    ws.append(["Export Test Type", test_type])
    ws.append(["Export Trials", "Results from all trials within a test, one row/column per trial"])
    ws.append(["Key Result", "N/A"])
    ws.append([])
    ws.append(HEAD + ["Trial"] + columns)
    for name, athlete_id, birth, when, trial, values in rows:
        ws.append([name, athlete_id, "", birth, "Male", None, test_type, when, None,
                   values.pop("_params", None), None, trial]
                  + [values.get(c) for c in columns])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def cmj(value, left=900, right=880):
    return {"Jump Height (Imp-Mom) [cm]": value, "RSI-modified (Imp-Mom) [m/s]": 0.45,
            "Concentric Peak Force [N]": left + right, "Concentric Peak Force (Left) [N]": left,
            "Concentric Peak Force (Right) [N]": right, "Countermovement Depth [cm]": -31.5,
            "Body Weight [kg]": 80.2, "Flight Time [ms]": 500}


def humantrak(rows) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Name", "ExternalId", "Date", "Time", "Device", "Test", "Reps",
               "Box Weight[kg]", "Peak Trunk Extension[°]", "Spinal Flexion at Peak Knee "
               "Flexion During Lift[°]"])
    for name, day, clock, trunk, spine in rows:
        ws.append([name, "", day, clock, "", "Box Lift - Overhead", 3, 20, trunk, spine])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


T1 = datetime(2026, 8, 21, 11, 36, 56)
T2 = datetime(2026, 8, 21, 13, 6, 43)


@pytest.fixture
def lab(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    user = User.objects.create(username="laborant", organization=org, role=Role.LAB)
    return org, user


def nahraj(lab, data, name="export.xlsx"):
    org, user = lab
    batch = services.stage_file(uploaded_file=SimpleUploadedFile(name, data),
                                user=user, organization=org)
    assert batch.status == ImportBatch.Status.PARSED, batch.error
    return batch


def uloz(lab, data, name="export.xlsx"):
    batch = nahraj(lab, data, name)
    return services.commit_batch(batch, user=lab[1]), batch


# --- rozpoznání a čtení ----------------------------------------------------------

def test_format_se_pozna_podle_obsahu(lab):
    assert detect_adapter(io.BytesIO(forcedecks([]))) == "vald_forcedecks"
    assert detect_adapter(io.BytesIO(humantrak([]))) == "vald_humantrak"


def test_forcedecks_pokusy_strany_a_prevody(lab):
    data = forcedecks([("Petr Novák", "uuid-1", "19.05.2003", T1, "Trial 2", cmj(33.4))])
    adapter = get_adapter("vald_forcedecks")
    rows = list(adapter.parse(io.BytesIO(data)))

    by = {(r.metric_code, r.side): r for r in rows}
    assert by[("cmj_height", "B")].value == 33.4
    assert by[("cmj_peak_force", "L")].value == 900
    assert by[("cmj_peak_force", "R")].value == 880
    assert by[("cmj_depth", "B")].value == 31.5          # export ji má zápornou
    assert all(r.trial_number == 2 for r in rows)
    assert rows[0].run_started_at.hour == 11
    assert rows[0].subject_attrs["birth_year"] == 2003
    assert rows[0].subject_ids["vald"] == "uuid-1"
    # Flight Time v profilu není – neimportuje se, ale řekne se to
    assert any("další sloupec" in n for n in adapter.notes)


def test_stoj_na_jedne_noze_bere_stranu_z_pokusu(lab):
    columns = ["Area of CoP Ellipse [mm sq]", "Total Excursion [mm]", "Mean Velocity [mm/s]"]
    data = forcedecks([
        ("Petr Novák", "uuid-1", "19.05.2003", T1, "Left (1)",
         {"Area of CoP Ellipse [mm sq]": 1694, "_params": "Exercise Length: 30s"}),
        ("Petr Novák", "uuid-1", "19.05.2003", T1, "Right (2)",
         {"Area of CoP Ellipse [mm sq]": 1013}),
    ], test_type="Single Leg Stand", columns=columns)
    rows = list(get_adapter("vald_forcedecks").parse(io.BytesIO(data)))
    assert [(r.side, r.trial_number, r.value) for r in rows] == [("L", 1, 1694), ("R", 2, 1013)]
    assert rows[0].run_conditions == {"parametry": "Exercise Length: 30s"}


def test_neznamy_typ_testu_se_ohlasi(lab):
    data = forcedecks([("Petr Novák", "uuid-1", "19.05.2003", T1, "Trial 1", cmj(30))],
                      test_type="Drop Jump")
    adapter = get_adapter("vald_forcedecks")
    assert list(adapter.parse(io.BytesIO(data))) == []
    assert any("Drop Jump" in n and "nemá profil" in n for n in adapter.notes)


# --- uložení ---------------------------------------------------------------------

def test_import_zalozi_sportovce_se_jmenem_a_testy(lab):
    result, batch = uloz(lab, forcedecks([
        ("Petr Novák", "uuid-1", "19.05.2003", T1, "Trial 1", cmj(33.0)),
        ("Petr Novák", "uuid-1", "19.05.2003", T1, "Trial 2", cmj(34.0)),
    ]))
    assert result["sportovci"] == 1 and result["testy"] == 1

    subject = Subject.objects.get()
    assert subject.birth_year == 2003 and subject.sex == "M"
    assert subject.identity.full_name == "Petr Novák"
    assert set(subject.external_ids.values_list("system", flat=True)) == {
        "vald", "hash_jmeno", "hash_jmeno_narozeni"}

    run = ProtocolRun.objects.get()
    assert run.external_ref.startswith("vald:uuid-1:Countermovement Jump:")
    assert timezone.localtime(run.started_at).hour == 11 and run.is_primary
    assert run.trials.count() == 2

    # jména ani identifikátory nezůstávají v souhrnu importu
    batch.refresh_from_db()
    assert "Novák" not in str(batch.summary)
    assert "subjects" not in batch.summary


def test_bez_klice_se_jmeno_neulozi(lab, settings):
    settings.IDENTITY_ENCRYPTION_KEY = ""
    result, _ = uloz(lab, forcedecks([
        ("Petr Novák", "uuid-1", "19.05.2003", T1, "Trial 1", cmj(33.0))]))
    assert result["jmena_neulozena"] == 1
    assert not SubjectIdentity.objects.exists()


def test_dalsi_soubor_pozna_sportovce_podle_vald_id(lab):
    uloz(lab, forcedecks([("Petr Novák", "uuid-1", "19.05.2003", T1, "Trial 1", cmj(33))]))
    imtp = forcedecks([("P. Novák", "uuid-1", "19.05.2003", T1, "Trial 1",
                        {"Peak Vertical Force [N]": 2500})],
                      test_type="Isometric Mid-Thigh Pull", columns=["Peak Vertical Force [N]"])
    batch = nahraj(lab, imtp, "imtp.xlsx")
    assert batch.summary["novych_sportovcu"] == 0
    assert list(batch.summary["subjects"].values())[0]["shoda"] == "ID ve VALD"
    services.commit_batch(batch, user=lab[1])
    assert Subject.objects.count() == 1
    assert TestSession.objects.count() == 1     # stejný den = stejný testovací den


def test_humantrak_pozna_sportovce_podle_jmena_i_bez_diakritiky(lab):
    uloz(lab, forcedecks([("Petr Novák", "uuid-1", "19.05.2003", T1, "Trial 1", cmj(33))]))
    result, _ = uloz(lab, humantrak([("Petr Novak", datetime(2026, 8, 24), "14:28", "11.24",
                                      "36.45")]), "boxlift.xlsx")
    assert result["sportovci"] == 0
    run = ProtocolRun.objects.get(protocol__code="box_lift")
    assert run.conditions == {"opakovani": 3.0, "zatez_kg": 20.0}
    assert timezone.localtime(run.started_at).strftime("%H:%M") == "14:28"
    spine = Measurement.objects.get(metric__code="boxlift_spine_flex_lift")
    assert spine.value == 36.45


def test_dva_stejna_jmena_se_neparuji_naslepo(lab):
    uloz(lab, forcedecks([
        ("Jan Novák", "uuid-1", "01.01.2000", T1, "Trial 1", cmj(33)),
        ("Jan Novák", "uuid-2", "02.02.2002", T1, "Trial 1", cmj(35)),
    ]))
    batch = nahraj(lab, humantrak([("Jan Novák", datetime(2026, 8, 24), "14:28", "5", "30")]),
                   "boxlift.xlsx")
    info = list(batch.summary["subjects"].values())[0]
    assert info["kod"] is None
    assert "víc sportovcům" in info["upozorneni"]


def test_opakovany_import_nezdvoji_a_aktualizuje(lab):
    uloz(lab, forcedecks([("Petr Novák", "uuid-1", "19.05.2003", T1, "Trial 1", cmj(33.0))]))
    # VALD test přepočítal – jiný soubor, stejný test, jiná výška
    batch = nahraj(lab, forcedecks([
        ("Petr Novák", "uuid-1", "19.05.2003", T1, "Trial 1", cmj(33.6))]), "znovu.xlsx")
    assert batch.summary["existujici_testy"] == 1
    result = services.commit_batch(batch, user=lab[1])

    assert result["testy"] == 0 and result["aktualizovano"] == 1
    assert ProtocolRun.objects.count() == 1
    assert Measurement.objects.get(metric__code="cmj_height").value == 33.6


def test_stejny_soubor_podruhe_odmitne(lab):
    data = forcedecks([("Petr Novák", "uuid-1", "19.05.2003", T1, "Trial 1", cmj(33))])
    uloz(lab, data)
    with pytest.raises(services.ImportError_, match="načíst znovu"):
        services.stage_file(uploaded_file=SimpleUploadedFile("x.xlsx", data),
                            user=lab[1], organization=lab[0])


def test_nova_metrika_v_profilu_se_doplni_opetovnym_nactenim(lab):
    uloz(lab, forcedecks([("Petr Novák", "uuid-1", "19.05.2003", T1, "Trial 1", cmj(33))]))
    flight = MetricDef.objects.create(code="cmj_flight_time", name="Doba letu",
                                      family="force_plate", unit="ms", decimals=0)
    ImportColumn.objects.create(profile=ImportProfile.objects.get(test_type="Countermovement Jump"),
                                column="Flight Time [ms]", metric=flight, with_sides=False)

    batch = services.restage(ImportBatch.objects.get().raw_file, user=lab[1],
                             organization=lab[0])
    result = services.commit_batch(batch, user=lab[1])
    assert result["hodnoty"] == 1 and result["testy"] == 0
    assert Measurement.objects.get(metric=flight).value == 500


# --- opakované měření během dne -----------------------------------------------------

def test_opakovane_mereni_dne(lab):
    uloz(lab, forcedecks([
        ("Petr Novák", "uuid-1", "19.05.2003", T2, "Trial 1", cmj(30.0)),   # po zátěži
        ("Petr Novák", "uuid-1", "19.05.2003", T1, "Trial 1", cmj(34.0)),   # ráno
    ]))
    first, second = ProtocolRun.objects.order_by("started_at")
    assert first.is_primary and not second.is_primary

    session = TestSession.objects.get()
    values = queries.session_metric_values(session)
    height = next(v for k, v in values.items() if k[0] == "cmj_height")
    assert height["value"] == 34.0          # hodnota dne = první měření, ne průměr 32

    block = results.protocol_results(session)[0]
    assert block["time"] == "11:36"
    assert block["repeats"]["times"] == ["13:06"]
    row = next(r for r in block["repeats"]["rows"] if r["metric"].code == "cmj_height")
    assert row["first_txt"] == "34,0"
    assert row["cells"][0] == {"value_txt": "30,0", "delta_txt": "−4,0"}


# --- zbytek -------------------------------------------------------------------------

def test_nahrani_vice_souboru_najednou(lab, client):
    org, user = lab
    client.force_login(user)
    response = client.post("/import/nahrat/", {"adapter": "auto", "file": [
        SimpleUploadedFile("cmj.xlsx", forcedecks([
            ("Petr Novák", "uuid-1", "19.05.2003", T1, "Trial 1", cmj(33))])),
        SimpleUploadedFile("box.xlsx", humantrak([
            ("Petr Novák", datetime(2026, 8, 24), "14:28", "5", "30")])),
    ]})
    assert response.status_code == 302
    assert sorted(ImportBatch.objects.values_list("adapter", flat=True)) == [
        "vald_forcedecks", "vald_humantrak"]


def test_zajisti_klic_doplni_jednou_a_neprepise(tmp_path, settings):
    settings.BASE_DIR = tmp_path
    env = tmp_path / ".env"
    env.write_text("DJANGO_SECRET_KEY=x\n", encoding="utf-8")
    call_command("zajisti_klic")
    first = env.read_text(encoding="utf-8")
    assert "IDENTITY_ENCRYPTION_KEY=" in first
    call_command("zajisti_klic")
    assert env.read_text(encoding="utf-8") == first


def test_profily_importu_se_prenesou_s_katalogem(lab):
    from apps.catalog.transfer import export_catalog, import_catalog

    data = export_catalog()
    ImportProfile.objects.all().delete()
    import_catalog(data)
    profile = ImportProfile.objects.get(test_type="Isometric Mid-Thigh Pull")
    column = profile.columns.get(column="Start Time to Peak Force [s]")
    assert column.with_sides is False and profile.protocol.code == "imtp"
    assert SubjectExternalId.System.VALD == "vald"
