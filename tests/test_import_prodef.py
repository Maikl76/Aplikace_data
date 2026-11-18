"""
Import studie PRODEF ze sešitu pro spoluautory.

Sešit se v testu skládá ze smyšlených hodnot se stejnou strukturou listů
a sloupců jako skutečný sešit – skutečná data studie do repozitáře nepatří.
"""

from datetime import date
from io import StringIO

import openpyxl
import pytest
from django.core.management import CommandError, call_command

from apps.analytics import readiness
from apps.catalog.models import Questionnaire, TestBattery
from apps.core.models import AuditLog, Organization
from apps.ingest import prodef
from apps.measurements.models import Measurement, ProtocolRun, TestSession
from apps.reports.results import protocol_results
from apps.subjects.models import Sport, Subject, Team

COMMON = ["pid", "skupina", "blok", "blok_termin", "vek_let", "vyska_cm", "hmotnost_ct_kg"]
DAYS = {2: (date(2026, 7, 3), "Den 2 – pátek (baseline)"),
        3: (date(2026, 7, 4), "Den 3 – sobota (SMOS)"),
        4: (date(2026, 7, 5), "Den 4 – neděle (SMOS)")}
POSITIONS = {1: "baseline (před 1. zátěžovým blokem)", 2: "po zátěžovém bloku 1"}


def _sheet(wb, name, header, rows, *, title="smyšlená data"):
    ws = wb.create_sheet(name)
    ws.append([title])
    ws.append([])
    ws.append(header)
    for row in rows:
        ws.append(row)


def _person(pid, arm):
    return [pid, arm, 1, "2.–6. 7.", 22, 180, 80.0]


def workbook(path, *, excluded=True, extra_controls=0, without_data=()):
    """
    Dva probandi (stres, kontrola), dny 2–4, dva měřicí body, dva pokusy.
    ``extra_controls`` přidá další kontrolní probandy s malým rozptylem mezi dny
    (aby šla z kontrolní skupiny spočítat MDC).
    """
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    people = [(7, "Stres"), (9, "Kontrola")] + [(11 + i, "Kontrola")
                                                for i in range(extra_controls)]
    probandi = [_person(pid, arm) + ["ANO"] for pid, arm in people]
    probandi += [_person(pid, "Kontrola") + ["ANO"] for pid in without_data]
    if excluded:
        probandi.append(_person(31, "Stres") + ["NE"])
    _sheet(wb, "Probandi", COMMON + ["zarazen_do_analyzy"], probandi)

    master, cmj, imtp, sls, dotazniky = [], [], [], [], []
    for pid, arm in people:
        noise = {day: ((pid * 7 + day * 3) % 5 - 2) * 0.3 if pid > 10 else 0.0 for day in DAYS}
        drop = {2: 0.0, 3: -4.0 if arm == "Stres" else -0.5,
                4: -6.0 if arm == "Stres" else 0.3}
        drop = {day: value + noise[day] for day, value in drop.items()}
        for day, (when, name) in DAYS.items():
            for point in (1, 2):
                master.append(_person(pid, arm) + [day, point, when, POSITIONS[point]])
                fatigue = -1.0 if point == 2 else 0.0
                for trial in (1, 2):
                    height = 35.0 + drop[day] + fatigue + (0.2 if trial == 2 else -0.2)
                    cmj.append(_person(pid, arm) + [
                        day, name, when, f"1{point}:0{trial}:00", point, f"Trial {trial}",
                        "ANO" if (pid, day, point, trial) == (7, 4, 2, 2) else None,
                        "Z1" if (pid, day, point, trial) == (9, 3, 1, 1) else None,
                        height, 0.45 + drop[day] / 100, 2000.0, 1000.0, 1000.0, 80.0])
                    imtp.append(_person(pid, arm) + [
                        day, name, when, f"1{point}:1{trial}:00", point, f"Trial {trial}",
                        None, None, 2500.0 + 20 * drop[day] + 10 * trial])
                sls.append(_person(pid, arm) + [
                    day, name, when, f"1{point}:20:00", point, "Left (1)", None, None,
                    900.0 + 50 * noise[day]])
                sls.append(_person(pid, arm) + [
                    day, name, when, f"1{point}:21:00", point, "Right (1)", None, None,
                    950.0 - 40 * noise[day]])
            stres = arm == "Stres" and day >= 3
            for nastroj, polozka, value in (
                    ("Noční formulář", "hodin spánku tuto noc", 4.0 if stres else 7.5),
                    ("KSS", "Karolinska Sleepiness Scale (1–9)", 8 if stres else 3),
                    ("VAS (0–100)", "unava", 75 if stres else 20),
                    ("VAS (0–100)", "hlad", 90),     # jiná položka se nenačte
                    ("Ranní dotazník (1–5)", "jak_velkou_svalovou", 4 if stres else 1)):
                dotazniky.append(_person(pid, arm) + [day, when, nastroj, 1, "07:30",
                                                      polozka, value])
    _sheet(wb, "MASTER", COMMON + ["den", "mericí_bod", "datum", "pozice"], master)
    _sheet(wb, "VALD_CMJ", COMMON + [
        "den", "den_nazev", "datum", "cas", "mericí_bod", "Trial", "CMJ_kontrola", "kod_opravy",
        "Jump Height (Imp-Mom) [cm]", "RSI-modified (Imp-Mom) [m/s]",
        "Concentric Peak Force [N]", "Concentric Peak Force (Left) [N]",
        "Concentric Peak Force (Right) [N]", "Body Weight [kg]"], cmj)
    _sheet(wb, "VALD_IMTP", COMMON + [
        "den", "den_nazev", "datum", "cas", "mericí_bod", "Trial", "IMTP_kontrola_kategorie",
        "kod_opravy", "Peak Vertical Force [N]"], imtp)
    _sheet(wb, "VALD_SLS", COMMON + [
        "den", "den_nazev", "datum", "cas", "mericí_bod", "Trial", "SLS_kontrola_kategorie",
        "kod_opravy", "Area of CoP Ellipse [mm sq]"], sls)
    _sheet(wb, "Dotazníky_skóry", COMMON + [
        "den", "datum", "nastroj", "casovy_bod", "cas_vyplneni", "polozka", "hodnota"], dotazniky)
    ws = wb.create_sheet("Prostředí")
    ws.append(["klima"])
    ws.append([])
    ws.append(["blok", "blok_termin", "den", "den_nazev", "datum", "misto", "stav",
               "teplota_C", "vlhkost_pct"])
    ws.append([1, "2.–6. 7.", 3, "Den 3", date(2026, 7, 4), "Střelnice", "naměřeno", 30.0, 60])
    ws.append([1, "2.–6. 7.", 3, "Den 3", date(2026, 7, 4), "Posilovna", "naměřeno", 22.5, 40])
    _sheet(wb, "CIQ", COMMON + ["Farm_Léky"], [_person(7, "Stres") + ["něco citlivého"]])
    wb.save(path)
    return path


@pytest.fixture
def lab(db, settings):
    call_command("seed_catalog", verbosity=0)
    settings.DEMO_MODE = False
    return Organization.objects.create(name="FTVS", short_name="ftvs")


def run(*args):
    out = StringIO()
    call_command("import_prodef", *args, stdout=out)
    return out.getvalue()


def test_import_zalozi_studii(lab, tmp_path):
    path = workbook(tmp_path / "sesit.xlsx")
    text = run(str(path))
    assert "Sešit: 2 probandů (Kontrola 1, Stres 1), 6 testovacích dnů" in text
    assert "Nenačtou se 1 probandi" in text and "Načteno do pracoviště ftvs" in text
    # souhrn před zápisem počítá pokusy stejně jako zápis: CMJ 2 + IMTP 2 + stoj na jedné
    # noze 1 (levá a pravá „(1)“ jsou jeden pokus) × 2 měřicí body × 3 dny × 2 probandi
    assert "36 provedení testů, 60 pokusů" in text and "pokusů 60, hodnot" in text

    sport = Sport.objects.get(organization=lab, code="prodef")
    assert set(Team.objects.filter(sport=sport).values_list("name", flat=True)) == {
        "PRODEF Stres", "PRODEF Kontrola"}
    battery = TestBattery.objects.get(sport=sport, category="Stres")
    assert [i.protocol.code for i in battery.items.order_by("order")] == ["cmj", "imtp", "sls"]

    stres = Subject.objects.get(code="PRODEF-P07")
    assert (stres.category, stres.team.name, stres.birth_year) == ("Stres", "PRODEF Stres", 2004)
    assert stres.baseline_date == date(2026, 7, 3) and stres.baseline_label.startswith("PRODEF")
    assert not Subject.objects.filter(code="PRODEF-P31").exists()     # nenastoupil
    assert not hasattr(stres, "identity") or stres.identity is None   # bez jména

    day = stres.sessions.get(date=date(2026, 7, 4))
    assert (day.temperature_c, day.humidity_pct) == (22.5, 40)        # posilovna
    assert day.location == "PRODEF, Den 3 – sobota (SMOS)"
    runs = list(day.protocol_runs.filter(protocol__code="cmj").order_by("started_at"))
    assert [(r.is_primary, r.conditions["pozice"]) for r in runs] == [
        (True, POSITIONS[1]), (False, POSITIONS[2])]
    first = runs[0]
    assert first.trials.count() == 2
    heights = Measurement.objects.filter(trial__protocol_run=first, metric__code="cmj_height")
    assert sorted(heights.values_list("value", flat=True)) == [30.8, 31.2]
    sides = set(Measurement.objects.filter(trial__protocol_run=first,
                                           metric__code="cmj_peak_force")
                .values_list("side", flat=True))
    assert sides == {"B", "L", "R"}
    sls = Measurement.objects.filter(trial__protocol_run__session=day,
                                     trial__protocol_run__is_primary=True,
                                     metric__code="sls_cop_area")
    assert sorted(sls.values_list("side", "value")) == [("L", 900.0), ("R", 950.0)]
    # oprava ze sešitu a pokus k ruční kontrole jsou u hodnoty vidět
    control = Subject.objects.get(code="PRODEF-P09")
    fixed = Measurement.objects.get(trial__protocol_run__session__subject=control,
                                    trial__protocol_run__session__date=date(2026, 7, 4),
                                    trial__protocol_run__is_primary=True, trial__number=1,
                                    metric__code="cmj_height")
    assert fixed.note == "oprava v sešitu: Z1"
    suspect = Measurement.objects.filter(quality=Measurement.Quality.SUSPECT)
    assert suspect.exists() and all(m.note.startswith("k ruční kontrole") for m in suspect)

    # ranní dotazník: vlastní dotazník studie, neaktivní, s prahy ze studie
    q = Questionnaire.objects.get(organization=lab, code="prodef_ranni")
    assert not q.is_active
    answers = {a.question.code: a.value for a in day.responses.get().answers.all()}
    assert answers == {"spanek_h": 4.0, "kss": 8, "vas_unava": 75, "svalova": 4}
    assert not Questionnaire.objects.filter(code="ciq").exists()

    # semafor: stres v sobotu červeně (4 odpovědi za prahem), kontrola zeleně
    assert readiness.for_session(day)["level"] == "cervena"
    assert readiness.for_session(control.sessions.get(date=date(2026, 7, 4)))["level"] == "zelena"
    assert AuditLog.objects.filter(object_type="ImportPRODEF").exists()


def test_opakovany_import_nic_nezdvoji(lab, tmp_path):
    path = workbook(tmp_path / "sesit.xlsx")
    run(str(path))
    counts = (TestSession.objects.count(), ProtocolRun.objects.count(), Measurement.objects.count())
    text = run(str(path))
    assert "nových sportovců 0, aktualizovaných 2" in text
    assert (TestSession.objects.count(), ProtocolRun.objects.count(),
            Measurement.objects.count()) == counts
    # ručně změněné výchozí měření import nepřepíše
    subject = Subject.objects.get(code="PRODEF-P07")
    subject.baseline_date, subject.baseline_label = date(2026, 7, 4), "moje volba"
    subject.save()
    run(str(path))
    subject.refresh_from_db()
    assert subject.baseline_label == "moje volba"


def test_nanecisto_nic_nezapise(lab, tmp_path):
    text = run(str(workbook(tmp_path / "sesit.xlsx")), "--nanecisto")
    assert "Nanečisto – nic se nezapsalo." in text
    assert not Subject.objects.exists() and not Sport.objects.filter(code="prodef").exists()


def test_zkusebni_provoz_jen_se_souhlasem(lab, tmp_path, settings):
    settings.DEMO_MODE = True
    path = workbook(tmp_path / "sesit.xlsx")
    with pytest.raises(CommandError, match="souhlasem vedoucího projektu"):
        run(str(path))
    assert not Subject.objects.exists()
    run(str(path), "--souhlas-vedouciho")
    assert Subject.objects.filter(code__startswith="PRODEF-P").count() == 2


def test_smazani_odebere_jen_studii(lab, tmp_path):
    other = Subject.objects.create(organization=lab, code="FTVS-0001")
    run(str(workbook(tmp_path / "sesit.xlsx")))
    text = run("--smazat", "--ano")
    assert "Smazáno: 2 probandů, 6 testovacích dnů, 0 zpráv." in text
    assert list(Subject.objects.values_list("code", flat=True)) == [other.code]
    assert not Sport.objects.filter(code="prodef").exists()
    assert not Questionnaire.objects.filter(code="prodef_ranni").exists()
    assert "Žádní probandi PRODEF tu nejsou." in run("--smazat", "--ano")


def test_opakovani_dne_proti_mdc_a_mdc_z_kontroly(lab, tmp_path):
    from apps.catalog.models import MetricDef

    run(str(workbook(tmp_path / "sesit.xlsx")))
    MetricDef.objects.filter(code="cmj_height").update(mdc=0.8)
    sunday = Subject.objects.get(code="PRODEF-P07").sessions.get(date=date(2026, 7, 5))
    block = next(b for b in protocol_results(sunday) if b["protocol"].code == "cmj")
    repeats = block["repeats"]
    assert repeats["first_conditions"] == POSITIONS[1]
    assert repeats["headers"][0]["conditions"] == POSITIONS[2]
    height = next(r for r in repeats["rows"] if r["metric"].code == "cmj_height")
    cell = height["cells"][0]
    assert (cell["delta_txt"], cell["verdict"], cell["real"]) == ("−1,0", "zhoršení", True)
    assert repeats["any_real"]

    # MDC z kontrolní skupiny (jeden člověk = málo dat → nic se neuloží)
    assert prodef.control_mdc(lab, save=True) == []
    text = run("--mdc-z-kontroly")
    assert "MDC se nespočítala" in text


def test_zaheslovany_sesit_bez_hesla(lab, tmp_path):
    path = tmp_path / "zaheslovany.xlsx"
    path.write_bytes(prodef.OLE_MAGIC + b"\x00" * 64)
    with pytest.raises(CommandError, match="zaheslovaný"):
        run(str(path))
    bad = tmp_path / "neni.xlsx"
    bad.write_bytes(b"hello")
    with pytest.raises(CommandError, match="není sešit Excelu"):
        run(str(bad))


def test_sesit_bez_listu_probandi(lab, tmp_path):
    wb = openpyxl.Workbook()
    wb.save(tmp_path / "prazdny.xlsx")
    with pytest.raises(CommandError, match="chybí list Probandi"):
        run(str(tmp_path / "prazdny.xlsx"))


def test_zeptat_pred_zapisem(lab, tmp_path, monkeypatch):
    path = str(workbook(tmp_path / "sesit.xlsx"))
    monkeypatch.setattr("builtins.input", lambda prompt="": "ne")
    assert "Nic se nenačetlo." in run(path, "--zeptat")
    assert not Subject.objects.exists()
    monkeypatch.setattr("builtins.input", lambda prompt="": "ANO")
    assert "Načteno do pracoviště ftvs" in run(path, "--zeptat")


def test_zaheslovany_sesit_s_heslem(lab, tmp_path, monkeypatch):
    msoffcrypto = pytest.importorskip("msoffcrypto")
    from msoffcrypto.format.ooxml import OOXMLFile

    plain = workbook(tmp_path / "sesit.xlsx")
    secret = tmp_path / "zaheslovany.xlsx"
    with open(plain, "rb") as source, open(secret, "wb") as target:
        OOXMLFile(source).encrypt("tajne-heslo-z-testu", target)
    assert prodef.is_encrypted(secret.read_bytes()[:8])
    monkeypatch.setenv("XLSX_HESLO", "spatne")
    with pytest.raises(CommandError, match="heslo nesedí"):
        run(str(secret))
    monkeypatch.setenv("XLSX_HESLO", "tajne-heslo-z-testu")
    assert "Načteno do pracoviště ftvs" in run(str(secret))
    assert msoffcrypto is not None


def test_vic_pracovist_vyber_cislem(lab, tmp_path, monkeypatch):
    """Přetažením sešitu na nacist-prodef.bat se --pracoviste zadat nedá – s --zeptat
    se pracoviště vybere číslem."""
    other = Organization.objects.create(name="Jiné pracoviště", short_name="jine")
    path = str(workbook(tmp_path / "sesit.xlsx"))
    with pytest.raises(CommandError, match="Pracovišť je víc"):
        run(path)
    monkeypatch.setattr("builtins.input", lambda prompt="": "7")
    with pytest.raises(CommandError, match="Pracoviště nevybráno"):
        run(path, "--zeptat")
    answers = iter(["2", "ANO"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    text = run(path, "--zeptat")
    assert "  2  Jiné pracoviště (jine)" in text
    assert "Načteno do pracoviště jine" in text
    assert set(Subject.objects.values_list("organization", flat=True)) == {other.pk}


def test_upozorneni_na_nejlepsi_pokus_imtp_jen_kdyz_je_potreba(lab, tmp_path):
    from apps.catalog.models import MetricDef

    path = str(workbook(tmp_path / "sesit.xlsx"))
    assert "Hodnota dne z pokusů: Nejlepší pokus" in run(path)
    MetricDef.objects.filter(code="imtp_peak_force").update(trial_rule=MetricDef.TrialRule.BEST)
    assert prodef.imtp_rule_note(lab) == ""
    assert "list MASTER" not in run(path)


def test_mdc_z_kontroly_ulozi_a_puvodni_hodnoty_jsou_v_auditu(lab, tmp_path):
    from apps.catalog.models import MetricDef

    MetricDef.objects.filter(code="cmj_height").update(typical_error=0.9, mdc=2.1)
    run(str(workbook(tmp_path / "sesit.xlsx", extra_controls=2)))
    text = run("--mdc-z-kontroly")
    assert "uloženo" in text and "Původní TE a MDC jsou v auditu" in text
    metric = MetricDef.objects.get(code="cmj_height", organization__isnull=True)
    assert metric.mdc != 2.1 and "PRODEF, kontrolní skupina" in metric.mdc_source
    entry = AuditLog.objects.filter(object_id="prodef-mdc").latest("pk")
    assert "cmj_height" in entry.detail["ukazatele"]
    assert entry.detail["puvodne"]["cmj_height"] == {"te": 0.9, "mdc": 2.1}


def test_proband_bez_mereni_se_nenacte(lab, tmp_path):
    """Zařazený do analýzy, ale v sešitu bez jediného pokusu VALD: v týmu by byl
    prázdný řádek – nenačte se a souhrn ho jmenuje."""
    text = run(str(workbook(tmp_path / "sesit.xlsx", without_data=(29,))))
    assert "Bez jediného měření VALD v sešitu, nenačtou se: PRODEF-P29." in text
    assert "Sešit: 2 probandů" in text
    assert not Subject.objects.filter(code="PRODEF-P29").exists()
    assert prodef.imported_subjects(lab).count() == 2
