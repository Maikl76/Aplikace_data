"""
Výchozí měření, semafor připravenosti a MDC z vlastních dat.

Všechna data v testech jsou vymyšlená.
"""

from datetime import date, timedelta

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.analytics import baseline, readiness, reliability
from apps.analytics.compare import compare
from apps.analytics.team import columns_for, team_table
from apps.catalog.models import (
    BatteryItem,
    MetricDef,
    Protocol,
    Question,
    Questionnaire,
    TestBattery,
)
from apps.core.models import AuditLog, Organization, Role, User
from apps.measurements import questionnaires
from apps.measurements.models import Measurement, ProtocolRun, TestSession, Trial
from apps.rules import engine
from apps.rules.engine import RuleError, validate_condition
from apps.rules.models import Rule
from apps.subjects.models import Sport, Subject, Team

D1, D2, D3, D4 = date(2026, 7, 9), date(2026, 7, 10), date(2026, 7, 11), date(2026, 7, 12)


@pytest.fixture
def lab(db, client):
    call_command("seed_catalog", verbosity=0)
    from apps.core import access

    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    user = User.objects.create(username="lab", organization=org, role=Role.ADMIN)
    access.grant(user, exports=True)
    sport = Sport.objects.create(organization=org, code="vojaci", name="Vojáci")
    battery = TestBattery.objects.create(organization=org, sport=sport)
    for order, code in enumerate(["cmj", "imtp"], start=1):
        BatteryItem.objects.create(battery=battery, protocol=Protocol.objects.get(code=code),
                                   order=order)
    MetricDef.objects.filter(code="cmj_height").update(mdc=3.0)
    MetricDef.objects.filter(code="imtp_peak_force").update(mdc=250.0)
    subjects = [Subject.objects.create(organization=org, code=f"P{i:02d}", sport=sport)
                for i in range(1, 6)]
    client.force_login(user)
    return org, battery, subjects, client


def zmer(subject, day, code, values, *, protocol="cmj", side="B", primary=True):
    session, _ = TestSession.objects.get_or_create(organization=subject.organization,
                                                   subject=subject, date=day)
    run = ProtocolRun.objects.filter(session=session, protocol__code=protocol,
                                     is_primary=primary).first()
    if run is None:
        run = ProtocolRun.objects.create(session=session, is_primary=primary,
                                         protocol=Protocol.objects.get(code=protocol))
    metric = MetricDef.objects.get(code=code)
    for number, value in enumerate(values, start=1):
        trial, _ = Trial.objects.get_or_create(protocol_run=run, number=number)
        Measurement.objects.create(trial=trial, metric=metric, side=side, value=value)
    return session


def ranni(session, **answers):
    q = questionnaires.questionnaire("ranni", session.organization)
    values = {q.questions.get(code=code): value for code, value in answers.items()}
    return questionnaires.save(session, q, values, source="operator")


# --- výchozí měření -----------------------------------------------------------------------

def test_srovnani_proti_vychozimu_meri_proti_mdc(lab):
    metric = MetricDef.objects.get(code="cmj_height")
    points = [(D1, 40.0), (D2, 39.0), (D3, 35.5)]
    out = compare(metric, points, baseline_date=D1, baseline_label="začátek studie")
    b = out["baseline"]
    assert b["delta_txt"] == "−4,5" and b["pct_txt"] == "−11 %"
    assert (b["verdict"], b["kind"]) == ("zhoršení", "worse") and b["count"] == 3
    assert b["label"] == "začátek studie" and not b["is_baseline"]
    # v pásmu chyby
    assert compare(metric, [(D1, 40.0), (D2, 38.0)], baseline_date=D1)["baseline"]["kind"] == "noise"
    # den sám výchozí, výchozí den bez měření, výchozí den až po řadě
    assert compare(metric, [(D1, 40.0)], baseline_date=D1)["baseline"]["is_baseline"]
    assert compare(metric, points, baseline_date=date(2026, 7, 1))["baseline"] is None
    assert compare(metric, points, baseline_date=date(2026, 8, 1))["baseline"] is None
    assert compare(metric, points)["baseline"] is None


def test_vychozi_mereni_u_sportovce_dlazdice_zprava_a_graf(lab):
    org, _, subjects, client = lab
    p = subjects[0]
    zmer(p, D1, "cmj_height", [40.0, 40.0])
    zmer(p, D2, "cmj_height", [39.5])
    last = zmer(p, D3, "cmj_height", [35.0])
    TestSession.objects.create(organization=org, subject=p, date=D4)   # jen naplánovaný

    url = reverse("subject_baseline", args=[p.pk])
    text = client.post(url, {"datum": D4.isoformat()}, follow=True).content.decode()
    assert "jen testovací den, kdy se něco naměřilo" in text
    client.post(url, {"datum": D1.isoformat(), "popis": "začátek studie"})
    p.refresh_from_db()
    assert p.baseline_date == D1 and p.baseline_label == "začátek studie"
    assert AuditLog.objects.filter(detail__vychozi_mereni=D1.isoformat()).exists()
    assert baseline.describe(p) == "výchozí měření 9. 7. 2026 (začátek studie)"

    karta = client.get(reverse("subject_detail", args=[p.pk])).content.decode()
    assert "Výchozí měření 9. 7. 2026 (začátek studie)" in karta
    assert "proti výchozímu" in karta and "−5,0" in karta and "výchozí ± MDC" in karta

    den = client.get(reverse("session_detail", args=[last.pk])).content.decode()
    assert "Nastavit tento den jako výchozí měření" in den
    assert "Srovnává se proti výchozímu měření 9. 7. 2026 (začátek studie)." in den
    prvni = client.get(reverse("session_detail", args=[p.sessions.get(date=D1).pk])).content.decode()
    assert "výchozí měření</span>" in prvni and "Nastavit tento den" not in prvni

    from apps.reports import facts as facts_module
    from apps.reports.models import Audience, Report
    from apps.reports.services import report_context

    report = Report.objects.create(organization=org, subject=p, session=last,
                                   audience=Audience.COACH, report_number="T-1")
    context = report_context(report)
    assert context["baseline_shown"] and "9. 7. 2026" in context["baseline_text"]
    metriky = facts_module.build(last, [], [])["klicove_metriky"]
    cmj = next(m for m in metriky if m["metrika"].startswith("Výška"))
    assert cmj["proti_vychozimu_mereni"] == {
        "vychozi_mereni": "09. 07. 2026", "popis": "začátek studie", "hodnota": 40.0,
        "zmena": -5.0, "procent": -12, "posouzeni": "zhoršení přesahující chybu měření"}

    client.post(url, {"akce": "zrusit"})
    p.refresh_from_db()
    assert p.baseline_date is None and p.baseline_label == ""


def test_tymovy_prehled_proti_vychozimu_a_hromadne_nastaveni(lab):
    _, battery, subjects, client = lab
    a, b, c = subjects[:3]
    zmer(a, D1, "cmj_height", [40.0])
    zmer(a, D2, "cmj_height", [39.0])
    zmer(a, D3, "cmj_height", [36.0])
    zmer(b, D2, "cmj_height", [30.0])     # jiný blok: začíná až druhý den
    zmer(b, D3, "cmj_height", [30.5])

    url = reverse("team_baseline")
    client.post(url, {"baterie": battery.pk, "od": D1.isoformat(), "popis": "začátek"})
    a.refresh_from_db(), b.refresh_from_db(), c.refresh_from_db()
    assert (a.baseline_date, b.baseline_date, c.baseline_date) == (D1, D2, None)
    assert a.baseline_label == "začátek"

    cols = columns_for(battery.protocols())
    rows = {r["subject"].code: r for r in team_table(subjects, cols, today=D4,
                                                      against="vychozi")["rows"]}
    cell = rows["P01"]["cells"][0]
    assert cell["verdict"]["delta_txt"] == "−4,0" and cell["verdict"]["kind"] == "worse"
    assert cell["verdict"]["previous_date"] == D1 and rows["P01"]["worse"] == 1
    assert rows["P02"]["cells"][0]["verdict"]["kind"] == "noise"
    # proti minule je to jinak: −3 je pořád nad MDC, ale srovnává se s 10. 7.
    minule = team_table(subjects, cols, today=D4)["rows"][0]["cells"][0]["verdict"]
    assert minule["previous_date"] == D2

    html = client.get(reverse("team") + f"?baterie={battery.pk}&srovnani=vychozi").content.decode()
    assert "změna proti výchozímu měření" in html and "Výchozí měření skupiny" in html
    csv = client.get(reverse("team") + f"?baterie={battery.pk}&srovnani=vychozi&format=csv")
    text = csv.content.decode("utf-8-sig")
    assert "změna proti výchozímu" in text.splitlines()[0]
    assert "P01;36,0;11.07.2026;−4,0;zhoršení" in text

    client.post(url, {"baterie": battery.pk, "akce": "zrusit"})
    assert not Subject.objects.filter(baseline_date__isnull=False).exists()


def test_hromadne_vychozi_jen_s_opravnenim(lab):
    from apps.core import access

    org, battery, _, client = lab
    host = User.objects.create(username="host", organization=org, role=Role.LAB)
    access.grant(host, subjects_edit=False)
    client.force_login(host)
    response = client.post(reverse("team_baseline"), {"baterie": battery.pk, "od": "2026-07-01"})
    assert response.status_code == 403


# --- semafor připravenosti ----------------------------------------------------------------

def test_semafor_z_dotazniku_a_vykonu(lab):
    _, _, subjects, client = lab
    p = subjects[0]
    zmer(p, D1, "cmj_height", [40.0])
    zmer(p, D1, "imtp_peak_force", [2500.0], protocol="imtp")
    p.baseline_date = D1
    p.save()
    day = zmer(p, D3, "cmj_height", [35.0])                       # −5 cm > MDC 3
    zmer(p, D3, "imtp_peak_force", [2400.0], protocol="imtp")     # −100 N < MDC 250
    ranni(day, spanek_h=4.0, kss=8, unava=8, bolest_svalu=2)

    state = readiness.for_session(day)
    assert state["against"] == "výchozímu měření"
    assert state["against_text"] == "výchozímu měření 9. 7. 2026"
    assert state["subjective"][0]["value_txt"] == "4 h"
    assert [s["label"] for s in state["signals"]] == ["málo spánku", "ospalost", "únava",
                                                      "Výška výskoku (CMJ)"]
    assert (state["count"], state["evaluated"], state["level"]) == (4, 6, "cervena")
    assert state["label"] == "snížená připravenost"
    imtp = next(i for i in state["performance"] if i["metric"].code == "imtp_peak_force")
    assert imtp["evaluated"] and not imtp["signal"] and imtp["delta_txt"] == "−100 N"

    html = client.get(reverse("session_detail", args=[day.pk])).content.decode()
    assert "Připravenost: snížená připravenost" in html and "4 signály z 6 posouzených" in html

    # méně signálů: oranžová, zelená
    ranni(day, spanek_h=7.5, kss=8, unava=3, bolest_svalu=2)
    state = readiness.for_session(day)
    assert state["level"] == "oranzova" and state["subjective"][0]["value_txt"] == "7,5 h"
    ranni(day, spanek_h=7.5, kss=3, unava=3, bolest_svalu=2)
    assert readiness.for_session(day)["level"] == "zelena"


def test_semafor_bez_mdc_a_bez_odpovedi_nepocita(lab):
    _, _, subjects, _ = lab
    p = subjects[1]
    MetricDef.objects.filter(code="cmj_height").update(mdc=None)
    zmer(p, D1, "cmj_height", [40.0])
    day = zmer(p, D2, "cmj_height", [30.0])
    assert readiness.for_session(day) is None          # nic k posouzení
    # „nevím“ se nepočítá: tři posouzené ukazatele na semafor nestačí (nemohl by být červený)
    ranni(day, spanek_h={"state": "unknown"}, kss=5, unava=2, bolest_svalu=1)
    assert readiness.for_session(day) is None
    ranni(day, spanek_h=8, kss=5, unava=2, bolest_svalu=1)
    state = readiness.for_session(day)
    assert (state["count"], state["evaluated"], state["level"]) == (0, 4, "zelena")
    cmj = state["performance"][0]
    assert not cmj["evaluated"] and cmj["verdict"] == "nelze posoudit (chybí MDC)"
    assert state["against"] == "minulému měření" and state["against_text"] == "minulému měření"


def test_semafor_v_tymovem_prehledu(lab):
    _, battery, subjects, client = lab
    p = subjects[0]
    day = zmer(p, D2, "cmj_height", [40.0])
    ranni(day, spanek_h=5.0, kss=7, unava=2, bolest_svalu=1)
    html = client.get(reverse("team") + f"?baterie={battery.pk}").content.decode()
    assert "Připravenost" in html and "semafor-oranzova" in html
    assert reverse("session_detail", args=[day.pk]) + "#pripravenost" in html


# --- pravidla -----------------------------------------------------------------------------

def _rule(org, code, condition, template):
    return Rule.objects.create(organization=org, code=code, name=code, condition=condition,
                               finding_template=template, is_active=True, severity="medium")


def test_pravidla_odpoved_semafor_a_zmena_proti_vychozimu(lab):
    org, _, subjects, _ = lab
    p = subjects[0]
    zmer(p, D1, "cmj_height", [40.0])
    zmer(p, D2, "cmj_height", [37.0])
    day = zmer(p, D3, "cmj_height", [36.0])       # proti minule −1 (šum), proti výchozímu −4
    ranni(day, spanek_h=5.5, kss=8, unava=8, bolest_svalu=4)
    rules = [
        _rule(org, "spanek", {"answer": "ranni.spanek_h", "op": "<", "value": 6},
              "Spánek {value_txt} h je pod {threshold_txt} h ({otazka})."),
        _rule(org, "semafor", {"readiness": "*", "op": ">=", "value": 4},
              "Semafor: {pocet} signálů ({signaly}), {barva}."),
        _rule(org, "pokles", {"change": "cmj_height", "op": "<", "value": 0,
                              "against": "vychozi"},
              "Proti {proti} {srovnani_datum}: {delta_txt} cm ({delta_pct_txt})."),
        _rule(org, "pokles_minule", {"change": "cmj_height", "op": "<", "value": 0},
              "Proti {proti}: {delta_txt} cm."),
    ]
    # bez výchozího měření pravidlo proti výchozímu nesedí
    texts = {f.rule.code: f.text for f in engine.evaluate_session(day, rules=rules, persist=False)}
    assert "pokles" not in texts and "pokles_minule" not in texts   # −1 < MDC 3
    p.baseline_date = D1
    p.save()
    day.refresh_from_db()
    texts = {f.rule.code: f.text for f in engine.evaluate_session(day, rules=rules, persist=False)}
    assert texts["spanek"] == "Spánek 5,5 h je pod 6 h (Kolik hodin jste dnes v noci spali?)."
    # proti výchozímu je i výška výskoku signál (−4 cm > MDC), proti minule nebyla
    assert texts["semafor"] == ("Semafor: 5 signálů (málo spánku, ospalost, únava, bolest svalů, "
                                "Výška výskoku (CMJ)), červená.")
    assert texts["pokles"] == "Proti výchozímu měření 09. 07. 2026: −4,0 cm (−10 %)."
    assert "pokles_minule" not in texts


def test_kontrola_novych_druhu_podminek():
    validate_condition({"answer": "ranni.kss", "op": ">=", "value": 7})
    validate_condition({"readiness": "*", "op": ">=", "value": 4})
    validate_condition({"change": "cmj_height", "op": "<", "value": 0, "against": "vychozi"},
                       metrics={"cmj_height"})
    for bad, hint in [
        ({"readiness": "cmj", "op": ">=", "value": 4}, "je „readiness“ vždy"),
        ({"answer": "a.b.c", "op": ">=", "value": 4}, "kód otázky"),
        ({"change": "cmj_height", "op": "<", "value": 0, "against": "sezona"}, "vychozi"),
        ({"answer": "ranni.kss", "op": ">=", "value": 7, "where": {"side": "L"}}, "Neznámé klíče"),
    ]:
        with pytest.raises(RuleError, match=hint):
            validate_condition(bad, metrics={"cmj_height"})
    assert "pocet" in engine.template_fields({"readiness": "*", "op": ">=", "value": 4})


def test_stavitel_pravidla_s_otazkou_a_vychozim(lab):
    _, _, _, client = lab
    response = client.post(reverse("rule_new"), {
        "name": "Málo spánku", "code": "malo_spanku", "severity": "low", "group": "all",
        "finding_template": "Spánek {value_txt} h.", "row_count": "2",
        "r0_kind": "answer", "r0_question": "ranni.spanek_h", "r0_op": "<", "r0_value": "6",
        "r1_kind": "change", "r1_metric": "cmj_height", "r1_op": "<", "r1_value": "0",
        "r1_mdc": "on", "r1_against": "vychozi",
    })
    assert response.status_code == 302, response.content.decode()[:500]
    rule = Rule.objects.get(code="malo_spanku")
    assert rule.condition == {"all": [
        {"answer": "ranni.spanek_h", "op": "<", "value": 6},
        {"change": "cmj_height", "op": "<", "value": 0, "require_mdc": True,
         "against": "vychozi"}]}
    form = client.get(reverse("rule_edit", args=[rule.pk])).content.decode()
    assert 'value="ranni.spanek_h" selected' in form and 'value="vychozi" checked' in form
    seznam = client.get(reverse("rules_settings")).content.decode()
    assert "odpověď na „Kolik hodin jste dnes v noci spali?“ &lt; 6" in seznam
    assert "proti výchozímu měření" in seznam


# --- MDC z vlastních dat ------------------------------------------------------------------

def _opakovane(subjects, base_values, noise, *, shift=0.0, start=D1, days=3):
    """Každý sportovec ``days`` dní po sobě: výchozí hodnota + posun skupiny + „šum“."""
    for i, (subject, base) in enumerate(zip(subjects, base_values, strict=True)):
        for k in range(days):
            zmer(subject, start + timedelta(days=k), "cmj_height",
                 [base + shift * k + noise[(i + k) % len(noise)]])


def test_odhad_te_a_mdc_z_opakovanych_mereni(lab):
    _, _, subjects, _ = lab
    metric = MetricDef.objects.get(code="cmj_height")
    _opakovane(subjects, [30, 35, 40, 45, 50], [0.0, 1.0, -1.0, 0.5, -0.5], shift=-2.0)
    result = reliability.estimate(metric, Subject.objects.all(), D1, D4)[0]
    assert result["ok"] and result["label"] == ""
    assert (result["n_subjects"], result["n_pairs"], result["df"]) == (5, 10, 8)
    # posun skupiny (−2 cm za den) se odečte: TE je jen z rozptylu rozdílů
    assert result["mean_changes"] == {0: pytest.approx(-2.0), 1: pytest.approx(-2.0)}
    # rozdíly „šumu“ v obou skupinách párů: (1, −2, 1,5, −1, 0,5) a (−2, 1,5, −1, 0,5, 1)
    # → součet čtverců 17, 8 stupňů volnosti, SD = √(17/8), TE = SD/√2
    assert result["te"] == pytest.approx((17 / 8) ** 0.5 / 2 ** 0.5)
    assert result["mdc90"] == pytest.approx(1.6449 * 2 ** 0.5 * result["te"])
    assert result["mdc95"] == pytest.approx(1.96 * 2 ** 0.5 * result["te"])
    assert result["ci_low"] < result["te"] < result["ci_high"]
    import statistics

    assert result["swc"] == pytest.approx(0.2 * statistics.stdev([30, 36, 39, 45.5, 49.5]))
    assert any("hrubý" in w for w in result["warnings"])
    # páry dál od sebe než povolený odstup se nepočítají
    assert not reliability.estimate(metric, Subject.objects.all(), D1, D4, max_gap=0)[0]["ok"]
    # chí-kvadrát: Wilson–Hilferty blízko tabulkových hodnot
    assert reliability.chi2_quantile(0.95, 8) == pytest.approx(15.507, abs=0.1)
    assert reliability.chi2_quantile(0.05, 8) == pytest.approx(2.733, abs=0.1)


def test_mdc_z_dat_ulozi_s_zdrojem(lab):
    org, _, subjects, client = lab
    team = Team.objects.create(organization=org, name="Kontrola", sport=subjects[0].sport)
    Subject.objects.filter(pk__in=[s.pk for s in subjects]).update(team=team)
    _opakovane(subjects, [30, 35, 40, 45, 50], [0.0, 1.0, -1.0, 0.5, -0.5])
    metric = MetricDef.objects.get(code="cmj_height")
    url = reverse("mdc_estimate", args=[metric.pk])
    params = {"skupina": f"tym-{team.pk}", "od": D1.isoformat(), "do": D4.isoformat(),
              "odstup": "3"}
    html = client.get(url, params).content.decode()
    assert "MDC z vlastních dat" in html and "5 sportovců · 10 párů" in html
    assert "Uložit jako MDC ukazatele" in html
    client.post(url, {**params, "kombinace": "", "uroven": "95", "swc": "1"})
    metric.refresh_from_db()
    te = (17 / 8) ** 0.5 / 2 ** 0.5
    assert metric.mdc == round(1.96 * 2 ** 0.5 * te, 2) == 2.86
    assert metric.typical_error == 1.03 and metric.swc is not None
    assert metric.mdc_source.startswith("Vlastní data: tým Kontrola, 09. 07. 2026–12. 07. 2026, "
                                        "5 osob, 10 párů; TE 1,03 cm")
    assert "MDC95 = 1,96·√2·TE" in metric.mdc_source
    assert AuditLog.objects.filter(detail__nastaveni="mdc_z_dat").exists()
    assert "spočítat z dat" in client.get(reverse("mdc_settings")).content.decode()


def test_mdc_z_dat_bez_opravneni_neulozi(lab):
    org, _, subjects, client = lab
    _opakovane(subjects, [30, 35, 40, 45, 50], [0.0, 1.0, -1.0, 0.5, -0.5])
    metric = MetricDef.objects.get(code="cmj_height")
    from apps.core import access

    host = User.objects.create(username="host2", organization=org, role=Role.LAB)
    access.grant(host, settings_tests=False)
    client.force_login(host)
    url = reverse("mdc_estimate", args=[metric.pk])
    assert client.get(url).status_code == 200            # číst může
    assert "Uložit jako MDC" not in client.get(url).content.decode()
    response = client.post(url, {"kombinace": "", "uroven": "90"})
    assert response.status_code == 403
    metric.refresh_from_db()
    assert metric.mdc == 3.0


# --- otázka s prahem signálu --------------------------------------------------------------

def test_otazka_s_prahem_signalu(lab):
    _, _, _, client = lab
    q = Questionnaire.objects.get(code="ranni", organization=None)
    spanek = q.questions.get(code="spanek_h")
    assert (spanek.kind, spanek.signal_op, spanek.signal_value) == ("number", "<", 6)
    assert spanek.signal_text() == "méně než 6 h" and spanek.is_signal(5.9)
    assert not spanek.is_signal(6) and not spanek.is_signal(None)
    kss = q.questions.get(code="kss")
    assert (kss.scale_min, kss.scale_max, kss.signal_text()) == (1, 9, "aspoň 7")

    url = reverse("question_edit", args=[q.pk, kss.pk])
    form = client.get(url).content.decode()
    assert "Signál do semaforu připravenosti" in form
    client.post(url, {"text": kss.text, "kind": "scale", "scale_min": "1", "scale_max": "9",
                      "anchors": "1 = bdělý\n9 = ospalý", "required": "on",
                      "signal_op": ">=", "signal_value": "6", "signal_label": "ospalost"})
    kss.refresh_from_db()
    assert (kss.signal_op, kss.signal_value, kss.signal_label) == (">=", 6.0, "ospalost")
    text = client.post(url, {"text": kss.text, "kind": "text", "signal_op": ">=",
                             "signal_value": "6"}, follow=True).content.decode()
    assert "jde jen u škály, čísla a ano/ne" in text
    assert Question.objects.get(pk=kss.pk).kind == "scale"


# --- zkušební provoz ----------------------------------------------------------------------

def test_ukazkova_pripravenost_jen_v_ukazce(lab, settings):
    from io import StringIO

    _, _, subjects, _ = lab
    for subject in subjects[:3]:
        for day in (D1, D2, D3):
            zmer(subject, day, "cmj_height", [40.0])
    out = StringIO()
    settings.DEMO_MODE = False
    call_command("ukazkova_pripravenost", stdout=out)
    assert "Jen v ukázce" in out.getvalue()
    assert not Subject.objects.filter(baseline_date__isnull=False).exists()

    settings.DEMO_MODE = True
    call_command("ukazkova_pripravenost", stdout=StringIO())
    first = Subject.objects.get(code="P01")
    assert first.baseline_date == D1 and first.baseline_label.startswith("ukázka")
    last = first.sessions.get(date=D3)
    assert readiness.for_session(last)["level"] == "cervena"      # 4,5 h, KSS 8, únava 8, bolest 4
    assert Subject.objects.filter(baseline_date__isnull=False).count() == 3
    # podruhé nic nového
    out = StringIO()
    call_command("ukazkova_pripravenost", stdout=out)
    assert "výchozích měření 0, vyplněných ranních dotazníků 0" in out.getvalue()
