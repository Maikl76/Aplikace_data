"""Průvodce „Nový přístroj“: návrhy, uložení nastavení a import souboru z přístroje."""

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from django.conf import settings as dj_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client

from apps.catalog.models import DeviceFormat, ImportProfile, MetricDef, Protocol
from apps.catalog.transfer import export_catalog, import_catalog
from apps.core.models import Organization, Role, User
from apps.ingest import device_setup as setup
from apps.ingest import services
from apps.measurements.models import Measurement
from apps.subjects.models import SubjectExternalId

EXPORT = Path(dj_settings.BASE_DIR) / setup.DEMO_EXPORT


@pytest.fixture
def lab(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    admin = User.objects.create(username="spravce", organization=org, role=Role.ADMIN)
    client = Client()
    client.force_login(admin)
    return org, admin, client


def _upload(name="dexa.csv", data=None):
    return SimpleUploadedFile(name, data if data is not None else EXPORT.read_bytes())


def _fields(client, pk) -> dict:
    """Formulář průvodce tak, jak ho odešle prohlížeč bez úprav (s návrhy)."""
    ctx = client.get(f"/import/pristroje/{pk}/").context
    data = {f: value for f, _, _, value in ctx["identity_fields"] if value}
    for c in ctx["columns"]:
        if c.get("metric"):
            data.update({f"c{c['i']}_metric": c["metric"], f"c{c['i']}_side": c.get("side", ""),
                         f"c{c['i']}_segment": c.get("segment", ""),
                         f"c{c['i']}_factor": c.get("factor", "1")})
    return data, {c["name"]: c["i"] for c in ctx["columns"]}


def _wizard(client, extra=None):
    response = client.post("/import/pristroje/novy/", {
        "name": "DEXA", "protocol": Protocol.objects.get(code="bodycomp").pk, "file": _upload()})
    device = DeviceFormat.objects.get(code="dexa")
    assert response.url == f"/import/pristroje/{device.pk}/"
    data, index = _fields(client, device.pk)
    for column, values in (extra or {}).items():
        data.update({f"c{index[column]}_{k}": v for k, v in values.items()})
    response = client.post(f"/import/pristroje/{device.pk}/", data)
    device.refresh_from_db()
    return device, response


def test_navrhy_poznaji_jmeno_datum_metriky_a_prevody(db):
    call_command("seed_catalog", verbosity=0)
    sample = setup.read_sample(EXPORT.open("rb"))
    assert sample.header_row == 3 and len(sample.rows) == setup.SAMPLE_ROWS
    identity = setup.suggest_identity(sample)
    assert identity == {"first_name_column": "First Name", "last_name_column": "Last Name",
                        "id_column": "Patient ID", "birth_column": "Birth Date",
                        "sex_column": "Sex", "date_column": "Scan Date"}
    protocol = Protocol.objects.get(code="bodycomp")
    metrics = [m for group in setup.metric_choices(protocol, None) for m in group]
    got = setup.suggest_columns(sample.header, protocol, metrics, set(identity.values()))
    assert got["Total Fat (%)"].metric.code == "body_fat_pct"
    assert (got["Total Lean (g)"].metric.code, got["Total Lean (g)"].factor) == ("lean_mass", 0.001)
    arm = got["Left Arm Lean (g)"]
    assert (arm.metric.code, arm.side, arm.segment) == ("segment_lean_mass", "L", "paze")
    assert got["Trunk Lean (g)"].segment == "trup" and got["Trunk Lean (g)"].side == ""
    # Tuk v gramech není beztuková hmota a BMD v katalogu není – raději nic než omyl.
    assert got["Total Fat (g)"].metric is None
    assert got["Total BMD (g/cm2)"].metric is None


def test_jmeno_v_jednom_sloupci_cesky():
    sample = setup.Sample(header_row=1, header=["Jméno", "Datum", "Čas", "Hmotnost (kg)"])
    assert setup.suggest_identity(sample) == {"name_column": "Jméno", "date_column": "Datum",
                                              "time_column": "Čas"}


def test_pruvodce_ulozi_pristroj_i_nove_metriky(lab):
    org, _, client = lab
    device, response = _wizard(client, {
        "Total Fat (g)": {"metric": "nova", "new_name": "Tuková hmota", "new_unit": "kg",
                          "new_dir": "neutral", "factor": "0,001"},
        "Total BMD (g/cm2)": {"metric": "nova", "new_name": "Kostní denzita",
                              "new_unit": "g/cm2", "new_dir": "higher"},
    })
    assert response.url == "/import/"
    assert device.is_active and device.date_column == "Scan Date"
    profile = ImportProfile.objects.get(device="vlastni:dexa")
    assert profile.columns.count() == 11
    fat = MetricDef.objects.get(name="Tuková hmota")
    assert fat.organization == org and fat.unit == "kg"
    assert profile.columns.get(column="Total Fat (g)").factor == 0.001
    bodycomp = Protocol.objects.get(code="bodycomp")
    assert bodycomp.protocol_metrics.filter(metric=fat).exists()
    assert "Kostní denzita" in str(list(bodycomp.protocol_metrics.values_list("metric__name")))


def test_bez_data_se_neulozi(lab):
    _, _, client = lab
    client.post("/import/pristroje/novy/", {
        "name": "DEXA", "protocol": Protocol.objects.get(code="bodycomp").pk, "file": _upload()})
    device = DeviceFormat.objects.get(code="dexa")
    data, _ = _fields(client, device.pk)
    data.pop("date_column")
    response = client.post(f"/import/pristroje/{device.pk}/", data)
    assert response.status_code == 200
    assert "datem měření" in response.content.decode()
    device.refresh_from_db()
    assert not device.is_active


def test_soubor_z_pristroje_se_pozna_a_importuje(lab):
    org, admin, client = lab
    _wizard(client)
    batch = services.stage_file(uploaded_file=_upload("sken-zari.csv"), user=admin,
                                organization=org)
    assert batch.adapter == "vlastni:dexa" and batch.adapter_label == "DEXA"
    staged = {(s.subject_hint, s.metric_code, s.side, s.segment): s.value
              for s in batch.staged.all()}
    assert staged[("Adam Testovací", "lean_mass", "B", "")] == pytest.approx(63.12)
    assert staged[("Bára Ukázková", "segment_lean_mass", "R", "noha")] == pytest.approx(7.91)
    assert batch.summary["sportovcu"] == 6 and batch.summary["datum_od"] == "2026-09-15"

    result = services.commit_batch(batch, user=admin)
    assert result["sportovci"] == 6
    assert Measurement.objects.filter(metric__code="body_fat_pct").count() == 6
    assert SubjectExternalId.objects.filter(system="pristroj", value="dexa:U001").exists()

    # Další export (jiný den, Adam s překlepem ve jméně) se spáruje podle ID z přístroje.
    text = EXPORT.read_text(encoding="utf-8").replace("15.09.2026", "15.12.2026")
    text = text.replace("Testovací;Adam", "Testovaci;Adamm")
    batch = services.stage_file(uploaded_file=_upload("sken-prosinec.csv", text.encode()),
                                user=admin, organization=org)
    assert batch.summary["novych_sportovcu"] == 0


def test_pristroj_bez_sloupcu_jmena_soubor_nepozna(lab):
    org, admin, client = lab
    _wizard(client)
    with pytest.raises(services.ImportError_, match="Přidat přístroj"):
        services.stage_file(uploaded_file=_upload("jiny.csv", b"a;b\n1;2\n"), user=admin,
                            organization=org)


def test_laborant_pristroj_nenastavuje(lab):
    org, _, _ = lab
    client = Client()
    client.force_login(User.objects.create(username="lab", organization=org, role=Role.LAB))
    assert client.get("/import/pristroje/novy/").url == "/import/"
    assert "Přidat přístroj" not in client.get("/import/").content.decode()


def test_pristroj_se_prenese_s_katalogem(lab):
    _, _, client = lab
    _wizard(client)
    data = export_catalog()
    assert [d["code"] for d in data["pristroje"]] == ["dexa"]
    ImportProfile.objects.filter(device="vlastni:dexa").delete()
    DeviceFormat.objects.all().delete()
    import_catalog(data)
    device = DeviceFormat.objects.get(code="dexa")
    assert device.is_active and device.profile().columns.count() == 9
    arm = device.profile().columns.get(column="Left Arm Lean (g)")
    assert (arm.side, arm.segment) == ("L", "paze")


def test_ukazka_ma_pristroj_ale_nenahrava(lab, settings):
    _, _, client = lab
    settings.DEMO_MODE = True
    call_command("ukazkovy_pristroj", verbosity=0)
    device = DeviceFormat.objects.get(code="dexa")
    assert device.is_active and device.profile().columns.count() == 9
    assert client.get(f"/import/pristroje/{device.pk}/").status_code == 200
    client.post("/import/pristroje/novy/", {
        "name": "Jiný", "protocol": device.protocol_id, "file": _upload()})
    assert DeviceFormat.objects.count() == 1
