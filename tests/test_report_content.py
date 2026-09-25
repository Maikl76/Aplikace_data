"""
Obsah zprávy: všechny výsledky, grafy vývoje a stranových rozdílů,
doporučení ve vlastní části a vydaná zpráva zamrzlá ve stavu při vydání.
"""

from datetime import date

import pytest

from apps.catalog.models import Direction, MetricDef, Protocol, ProtocolMetric, TestFamily
from apps.core.models import Organization, Role, User
from apps.measurements.models import Measurement, ProtocolRun, Side, TestSession, Trial
from apps.reports import narrative, results, services, svg
from apps.rules.models import Rule, Severity
from apps.subjects.models import Sex, Subject


@pytest.fixture
def lab(db):
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    user = User.objects.create(username="laborant", organization=org, role=Role.LAB)
    subject = Subject.objects.create(organization=org, code="FTVS-0001",
                                     sex=Sex.FEMALE, birth_year=1994)
    skok = MetricDef.objects.create(code="cmj_height", name="Výška výskoku",
                                    family=TestFamily.FORCE_PLATE, unit="cm", decimals=1,
                                    mdc=2.0, direction=Direction.HIGHER)
    stisk = MetricDef.objects.create(code="grip", name="Síla stisku",
                                     family=TestFamily.DYNAMOMETRY, unit="kg", decimals=1)
    protocol = Protocol.objects.create(code="cmj", name="Výskok z podřepu",
                                       family=TestFamily.FORCE_PLATE)
    ProtocolMetric.objects.create(protocol=protocol, metric=skok, is_primary=True, order=1)
    ProtocolMetric.objects.create(protocol=protocol, metric=stisk, order=2)
    return {"org": org, "user": user, "subject": subject, "skok": skok, "stisk": stisk,
            "protocol": protocol}


def mereni(lab, day, skoky, stisk=None):
    session = TestSession.objects.create(organization=lab["org"], subject=lab["subject"],
                                         date=day)
    run = ProtocolRun.objects.create(session=session, protocol=lab["protocol"])
    for number, value in enumerate(skoky, start=1):
        trial = Trial.objects.create(protocol_run=run, number=number)
        Measurement.objects.create(trial=trial, metric=lab["skok"], value=value)
        if stisk and number == 1:
            Measurement.objects.create(trial=trial, metric=lab["stisk"],
                                       value=stisk[0], side=Side.LEFT)
            Measurement.objects.create(trial=trial, metric=lab["stisk"],
                                       value=stisk[1], side=Side.RIGHT)
    return session


def test_tabulka_nese_vsechny_vysledky_i_pokusy(lab):
    session = mereni(lab, date(2026, 3, 1), [38.0, 39.0], stisk=(40.0, 30.0))
    bloky = results.protocol_results(session)

    assert [b["protocol"].name for b in bloky] == ["Výskok z podřepu"]
    radky = bloky[0]["rows"]
    # klíčová metrika napřed (pořadí z katalogu), pak obě strany stisku
    assert [r["metric"].code for r in radky] == ["cmj_height", "grip", "grip"]
    assert radky[0]["value_txt"] == "38,5"
    assert radky[0]["trials_txt"] == "38,0 · 39,0"
    assert radky[0]["verdict"] == ""          # první měření


def test_zmena_se_posuzuje_proti_mdc(lab):
    mereni(lab, date(2026, 1, 10), [38.0])
    session = mereni(lab, date(2026, 3, 1), [41.0])
    radek = results.protocol_results(session)[0]["rows"][0]

    assert radek["previous_txt"] == "38,0"
    assert radek["delta_txt"] == "+3,0"
    assert radek["verdict"] == "zlepšení"


def test_zmena_pod_mdc_je_v_pasmu_chyby(lab):
    mereni(lab, date(2026, 1, 10), [38.0])
    session = mereni(lab, date(2026, 3, 1), [39.0])
    radek = results.protocol_results(session)[0]["rows"][0]
    assert radek["verdict"] == "v pásmu chyby měření"


def test_zprava_obsahuje_vysledky_grafy_a_asymetrii(lab):
    mereni(lab, date(2026, 1, 10), [38.0])
    session = mereni(lab, date(2026, 3, 1), [41.0], stisk=(40.0, 30.0))
    report = services.build_draft(session, user=lab["user"])
    html = services.render_html(report)

    assert "2. Výsledky testů" in html
    assert "Výskok z podřepu" in html
    assert "41,0" in html
    assert "<svg" in html                     # graf vývoje i asymetrie
    assert "vyšší vlevo" in html
    assert "25,0 % ▲" in html                 # (40 − 30) / 40 = 25 % nad tolerancí


def test_prvni_mereni_nema_graf_vyvoje(lab):
    session = mereni(lab, date(2026, 3, 1), [41.0])
    context = services.report_context(services.build_draft(session, user=lab["user"]))
    assert context["trends"] == []
    assert "zatím není starší měření" in services.render_html(context["report"])


def test_graf_nezobrazi_pozdejsi_mereni(lab):
    """Zpráva z března nesmí ukazovat měření z května."""
    mereni(lab, date(2026, 1, 10), [38.0])
    brezen = mereni(lab, date(2026, 3, 1), [41.0])
    mereni(lab, date(2026, 5, 1), [45.0])

    serie = results.trend_series(brezen)
    assert len(serie) == 1
    assert [d for d, _ in serie[0]["points"]] == [date(2026, 1, 10), date(2026, 3, 1)]


def test_sablona_shrne_klicove_vysledky(lab):
    mereni(lab, date(2026, 1, 10), [38.0])
    session = mereni(lab, date(2026, 3, 1), [41.0])
    report = services.build_draft(session, user=lab["user"])

    assert "přesahují chybu měření" in report.summary
    assert "Výška výskoku: 41 cm; minule 38 cm, změna +3 cm – zlepšení" in report.summary
    assert narrative.verify_numbers(report.summary, []) != []   # bez faktů by neprošla
    assert report.llm_model == "šablona"


def test_doporuceni_ma_vlastni_cast(lab):
    session = mereni(lab, date(2026, 3, 1), [30.0])
    Rule.objects.create(
        code="nizky_skok", name="Nízký výskok", severity=Severity.MEDIUM,
        condition={"metric": "cmj_height", "op": "<", "value": 35},
        finding_template="Výška výskoku {value_txt} cm je pod {threshold_txt} cm.",
        recommendation_template="Zařadit plyometrický trénink.",
    )
    report = services.build_draft(session, user=lab["user"])
    html = services.render_html(report)

    assert "6. Doporučení" in html
    assert "Zařadit plyometrický trénink." in html
    assert "Zařadit plyometrický" not in report.summary
    assert services._machine_readable(
        services.release(report, user=lab["user"]))["doporuceni"] == [
            "Zařadit plyometrický trénink."]


def test_komentar_diagnostika_je_v_doporucenich(lab):
    session = mereni(lab, date(2026, 3, 1), [41.0])
    report = services.build_draft(session, user=lab["user"])
    report.custom_note = "Pokračovat v současném tréninku."
    html = services.render_html(report)
    assert html.index("6. Doporučení") < html.index("Pokračovat v současném tréninku.")


def test_vydana_zprava_se_uz_neprepocitava(lab):
    session = mereni(lab, date(2026, 3, 1), [41.0])
    report = services.release(services.build_draft(session, user=lab["user"]),
                              user=lab["user"])
    pred = services.render_html(report)
    assert "41,0" in pred

    Measurement.objects.filter(metric=lab["skok"]).update(value=20.0)
    report.refresh_from_db()
    assert services.render_html(report) == pred


def test_priloha_nese_namerene_hodnoty(lab):
    session = mereni(lab, date(2026, 3, 1), [38.0, 39.0])
    report = services.release(services.build_draft(session, user=lab["user"]),
                              user=lab["user"])
    data = services._machine_readable(report)
    hodnoty = data["vysledky"][0]["hodnoty"]
    assert hodnoty[0] == {"metrika": "cmj_height", "jednotka": "cm", "strana": "",
                          "rezim": "", "rychlost": None, "segment": "",
                          "hodnota": 38.5, "pocet_pokusu": 2}


@pytest.mark.parametrize("low, high, expected", [
    (0, 10, [0, 2.5, 5, 7.5, 10]),
    (36.2, 43.9, [38, 40, 42]),
    (0.8, 1.1, [0.8, 0.9, 1.0, 1.1]),
])
def test_osy_maji_kulate_hodnoty(low, high, expected):
    assert svg.nice_ticks(low, high) == pytest.approx(expected)


def test_minula_hodnota_je_z_posledniho_dne_kdy_se_metrika_merila(lab):
    """Mezi dvěma měřeními stisku proběhl jen výskok – stisk není „první měření“."""
    mereni(lab, date(2026, 1, 10), [38.0], stisk=(40.0, 38.0))
    mereni(lab, date(2026, 2, 10), [39.0])
    session = mereni(lab, date(2026, 3, 1), [41.0], stisk=(42.0, 39.0))

    radky = results.protocol_results(session)[0]["rows"]
    stisk_leva = next(r for r in radky if r["metric"].code == "grip"
                      and r["qualifiers"]["side"] == Side.LEFT)
    assert stisk_leva["previous_txt"] == "40,0"
    assert stisk_leva["previous_date"] == date(2026, 1, 10)
    skok = radky[0]
    assert skok["previous_date"] == date(2026, 2, 10)


def test_sablona_nevypisuje_zmeny_v_pasmu_chyby(lab):
    mereni(lab, date(2026, 1, 10), [38.0])
    session = mereni(lab, date(2026, 3, 1), [38.5])
    report = services.build_draft(session, user=lab["user"])
    assert "(výška výskoku) je změna v pásmu chyby měření" in report.summary
    assert "38,5" not in report.summary
