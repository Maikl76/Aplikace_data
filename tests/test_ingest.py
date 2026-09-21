"""
Testy importní pipeline na Excelu ve formátu původní aplikace.

Těžiště: rozklad sloupců s režimem a rychlostí v názvu na kvalifikátory,
pseudonymizace při zakládání sportovců a spárování opakovaného importu.
"""

import io

import pandas as pd
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.catalog.models import MetricDef
from apps.core.models import Organization, Role, User
from apps.ingest import services
from apps.ingest.adapters.legacy_excel import LegacyExcelAdapter
from apps.ingest.models import ImportBatch, StagedMeasurement
from apps.measurements.models import Measurement, Mode, Side, TestSession
from apps.subjects.models import Subject

LEGACY_ROW = {
    "Jmeno": "Jan", "Prijmeni": "Novák", "Narozen": "1998-03-12",
    "Vek": 27, "Vyska": 186, "Hmotnost": 79.5, "DatumMereni": "2024-03-12",
    "Vnitrni rotace koncentricka (210°/s)": 52.3,
    "Vnejsi rotace koncentricka (210°/s)": 38.1,
    "Vnitrni rotace excentricka (210°/s)": 58.9,
    "Vnejsi rotace excentricka (210°/s)": 44.2,
    "Vnitrni rotace koncentricka (300°/s)": 47.1,
    "Vnejsi rotace koncentricka (300°/s)": 35.6,
    "Vnitrni rotace excentricka (300°/s)": 55.0,
    "Vnejsi rotace excentricka (300°/s)": 41.8,
    "IR/ER (210°/s)": 1.37,
    "IR/ER (300°/s)": 1.32,
    "Sila uchopu": 54.0,
    "Rychlost podani": 187,
    "Dominantni paze": 5.2,
    "Dominantni paze - beztukova": 4.6,
    "Beztukova hmota": 66.1,
    "Telesny tuk": 12.4,
}


def _legacy_bytes(rows=None) -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame(rows or [LEGACY_ROW]).to_excel(buffer, sheet_name="data", index=False)
    return buffer.getvalue()


def _legacy_excel(rows=None, name="historicka_data.xlsx") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, _legacy_bytes(rows))


@pytest.fixture
def prostredi(db):
    from django.core.management import call_command

    call_command("seed_catalog", verbosity=0)
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    user = User.objects.create(username="laborant", organization=org, role=Role.LAB)
    return org, user


# --- adaptér ---------------------------------------------------------------

def test_rotace_se_rozlozi_na_kvalifikatory(db):
    """Osm sloupců -> dvě metriky x dva režimy x dvě rychlosti."""
    rows = list(LegacyExcelAdapter().parse(_legacy_excel()))
    rotace = [r for r in rows if r.metric_code.startswith("shoulder_")]

    assert len(rotace) == 8
    assert {r.metric_code for r in rotace} == {"shoulder_ir_torque", "shoulder_er_torque"}
    assert {r.mode for r in rotace} == {"con", "ecc"}
    assert {r.speed for r in rotace} == {210.0, 300.0}

    jedna = next(r for r in rotace
                 if r.metric_code == "shoulder_ir_torque" and r.mode == "ecc" and r.speed == 300.0)
    assert jedna.value == 55.0
    assert jedna.extra["source_column"] == "Vnitrni rotace excentricka (300°/s)"


def test_segmenty_sdileji_metriku(db):
    rows = list(LegacyExcelAdapter().parse(_legacy_excel()))
    segmentove = [r for r in rows if r.segment]
    assert {r.segment for r in segmentove} == {"paze"}
    assert all(r.side == "D" for r in segmentove)


def test_adapter_nevraci_jmeno_v_klici(db):
    """subject_key je hash – jméno se do databáze nedostane."""
    row = next(iter(LegacyExcelAdapter().parse(_legacy_excel())))
    assert len(row.subject_key) == 64
    assert "Novák" not in row.subject_key


def test_sniff_pozna_format(db):
    assert LegacyExcelAdapter().sniff(_legacy_excel()) is True


# --- pipeline --------------------------------------------------------------

def test_staging_nic_neulozi(prostredi):
    org, user = prostredi
    batch = services.stage_file(uploaded_file=_legacy_excel(), user=user,
                                organization=org, adapter_code="legacy_excel")

    assert batch.status == ImportBatch.Status.PARSED
    assert batch.staged.count() > 0
    assert Measurement.objects.count() == 0
    assert Subject.objects.count() == 0
    assert batch.summary["novych_sportovcu"] == 1


def test_commit_zalozi_sportovce_bez_jmena(prostredi):
    org, user = prostredi
    batch = services.stage_file(uploaded_file=_legacy_excel(), user=user,
                                organization=org, adapter_code="legacy_excel")
    vysledek = services.commit_batch(batch, user=user)

    assert vysledek["sportovci"] == 1
    subject = Subject.objects.get()
    assert subject.code == "FTVS-0001"
    assert subject.birth_year == 1998
    assert len(subject.source_key) == 64

    ulozeno = " ".join(str(v) for v in Subject.objects.values_list(flat=False).first())
    assert "Novák" not in ulozeno

    # staging se po uložení maže – držel identifikaci ze zdroje
    assert StagedMeasurement.objects.filter(batch=batch).count() == 0


def test_commit_ulozi_hodnoty_s_kvalifikatory(prostredi):
    org, user = prostredi
    batch = services.stage_file(uploaded_file=_legacy_excel(), user=user,
                                organization=org, adapter_code="legacy_excel")
    services.commit_batch(batch, user=user)

    session = TestSession.objects.get()
    assert session.date.isoformat() == "2024-03-12"

    ir = MetricDef.objects.get(code="shoulder_ir_torque")
    hodnoty = Measurement.objects.filter(metric=ir)
    assert hodnoty.count() == 4  # dva režimy x dvě rychlosti
    assert hodnoty.get(mode=Mode.ECCENTRIC, speed=300.0).value == 55.0


def test_opakovany_import_spari_tehoz_sportovce(prostredi):
    org, user = prostredi
    first = services.stage_file(uploaded_file=_legacy_excel(), user=user,
                                organization=org, adapter_code="legacy_excel")
    services.commit_batch(first, user=user)

    pozdeji = {**LEGACY_ROW, "DatumMereni": "2024-09-20", "Sila uchopu": 57.5}
    second = services.stage_file(uploaded_file=_legacy_excel([pozdeji], "druhe.xlsx"),
                                 user=user, organization=org, adapter_code="legacy_excel")
    vysledek = services.commit_batch(second, user=user)

    assert vysledek["sportovci"] == 0          # tatáž osoba, ne nová
    assert Subject.objects.count() == 1
    assert TestSession.objects.count() == 2    # dva testovací dny


def test_ulozeny_soubor_uz_podruhe_neprojde(prostredi):
    """
    Kontrola je na otisk OBSAHU, takže testujeme tytéž bajty. Dva exporty
    téhož měření z Excelu shodné nejsou – nesou v sobě čas vytvoření –
    a ochrana proti dvojímu uložení se o ně neopírá: duplicitní hodnoty
    zachytí až get_or_create nad kvalifikátory při ukládání.
    """
    org, user = prostredi
    data = _legacy_bytes()

    batch = services.stage_file(uploaded_file=SimpleUploadedFile("h.xlsx", data),
                                user=user, organization=org, adapter_code="legacy_excel")
    services.commit_batch(batch, user=user)

    with pytest.raises(services.ImportError_, match="už byl importován"):
        services.stage_file(uploaded_file=SimpleUploadedFile("h.xlsx", data),
                            user=user, organization=org, adapter_code="legacy_excel")


def test_nedokonceny_import_se_vrati_k_nahledu(prostredi):
    """Náhled bez uložení nesmí zablokovat pozdější uložení téhož souboru."""
    org, user = prostredi
    data = _legacy_bytes()
    first = services.stage_file(uploaded_file=SimpleUploadedFile("h.xlsx", data),
                                user=user, organization=org, adapter_code="legacy_excel")
    again = services.stage_file(uploaded_file=SimpleUploadedFile("h.xlsx", data),
                                user=user, organization=org, adapter_code="legacy_excel")

    assert again.pk == first.pk
    assert ImportBatch.objects.count() == 1


def test_nezmapovany_sloupec_se_ohlasi(prostredi):
    """Tiše zahozený sloupec je při migraci dat to nejhorší."""
    org, user = prostredi
    row = {**LEGACY_ROW, "Nejaky novy sloupec": 3.3}
    batch = services.stage_file(uploaded_file=_legacy_excel([row]), user=user,
                                organization=org, adapter_code="legacy_excel")

    assert batch.summary["nezmapovane_sloupce"] == ["Nejaky novy sloupec"]


def test_hodnota_mimo_rozsah_se_oznaci(prostredi):
    org, user = prostredi
    nesmysl = {**LEGACY_ROW, "Telesny tuk": 95.0}
    batch = services.stage_file(uploaded_file=_legacy_excel([nesmysl]), user=user,
                                organization=org, adapter_code="legacy_excel")

    assert batch.summary["mimo_rozsah"] == 1
    services.commit_batch(batch, user=user)

    tuk = Measurement.objects.get(metric__code="body_fat_pct")
    assert tuk.quality == Measurement.Quality.OUT_OF_RANGE
    assert tuk.value == 95.0     # neukládá se mlčky zahozené


def test_lze_nechat_nesmysly_stranou(prostredi):
    org, user = prostredi
    nesmysl = {**LEGACY_ROW, "Telesny tuk": 95.0}
    batch = services.stage_file(uploaded_file=_legacy_excel([nesmysl]), user=user,
                                organization=org, adapter_code="legacy_excel")
    services.commit_batch(batch, user=user, skip_out_of_range=True)

    assert Measurement.objects.filter(metric__code="body_fat_pct").count() == 0


def test_historicka_data_neumi_stranu(prostredi):
    """
    Původní formát stranu nerozlišoval. Import to nesmí předstírat –
    rotace se ukládají bez strany a asymetrii z nich spočítat nelze.
    """
    org, user = prostredi
    batch = services.stage_file(uploaded_file=_legacy_excel(), user=user,
                                organization=org, adapter_code="legacy_excel")
    services.commit_batch(batch, user=user)

    rotace = Measurement.objects.filter(metric__code__startswith="shoulder_")
    assert all(m.side == "" for m in rotace)
    assert not rotace.filter(side__in=[Side.LEFT, Side.RIGHT]).exists()
