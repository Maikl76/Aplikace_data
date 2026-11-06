"""
Dávka 7: srovnání se začátkem sezóny, osobním maximem a vývojem za 12
měsíců (dlaždice, zpráva, portál); cíle klíčových ukazatelů s postupem
(karta, portál, zpráva, graf); popisy ukazatelů a testů pro klienta
(nastavení, návrh modelem, portál, vysvětlivky zprávy); měsíc začátku
sezóny u sportu.
"""

from datetime import date

import pytest
from cryptography.fernet import Fernet
from django.test import Client
from django.urls import reverse

from apps.analytics import compare, overview
from apps.catalog.models import (
    Direction,
    MetricDef,
    Protocol,
    ProtocolMetric,
    TestBattery,
    TestFamily,
)
from apps.core.models import Organization, Role, User
from apps.measurements.models import Measurement, ProtocolRun, TestSession, Trial
from apps.reports import facts as report_facts
from apps.reports import llm, narrative
from apps.reports import services as report_services
from apps.reports.models import Audience
from apps.subjects import goals
from apps.subjects.models import Goal, Sharing, Sport, Subject, SubjectIdentity


@pytest.fixture
def org(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    return Organization.objects.create(name="FTVS", short_name="ftvs")


def _user(org, role, username, email=""):
    user = User.objects.create(username=username, organization=org, role=role, email=email,
                               is_staff=role == Role.ADMIN)
    client = Client()
    client.force_login(user)
    return user, client


def _catalog(org, *, mdc=1.0, direction=Direction.HIGHER):
    protocol = Protocol.objects.create(organization=org, code="cmj", name="CMJ",
                                       family=TestFamily.FORCE_PLATE, device="Deska")
    metric = MetricDef.objects.create(organization=org, code="cmj_vyska", name="Výška výskoku",
                                      family=TestFamily.FORCE_PLATE, unit="cm", mdc=mdc,
                                      decimals=1, direction=direction)
    ProtocolMetric.objects.create(protocol=protocol, metric=metric, is_primary=True)
    return protocol, metric


def _measure(org, subject, protocol, metric, day, value):
    session = TestSession.objects.create(organization=org, subject=subject, date=day)
    run = ProtocolRun.objects.create(session=session, protocol=protocol)
    trial = Trial.objects.create(protocol_run=run, number=1)
    Measurement.objects.create(trial=trial, metric=metric, value=value)
    return session


def _florbal(org):
    """Florbal se sezónou od září, baterie s CMJ, sportovkyně."""
    sport = Sport.objects.create(organization=org, name="Florbal", code="florbal",
                                 season_start_month=9)
    protocol, metric = _catalog(org)
    battery = TestBattery.objects.create(organization=org, sport=sport)
    battery.items.create(protocol=protocol, order=1)
    subject = Subject.objects.create(organization=org, code="FTVS-0001", sport=sport, sex="F")
    return sport, protocol, metric, subject


def _history(org, subject, protocol, metric):
    """Minulá sezóna 36,0; tato sezóna 35,0 → 38,0 (maximum) → 37,2 (poslední)."""
    for day, value in [(date(2025, 5, 10), 36.0), (date(2025, 10, 1), 35.0),
                       (date(2026, 1, 15), 38.0), (date(2026, 4, 20), 37.2)]:
        last = _measure(org, subject, protocol, metric, day, value)
    return last


def test_sezona_maximum_a_obdobi(org):
    sport, protocol, metric, subject = _florbal(org)
    assert compare.season_start(date(2026, 4, 20), sport) == date(2025, 9, 1)
    assert compare.season_start(date(2026, 9, 1), sport) == date(2026, 9, 1)
    assert compare.season_start(date(2026, 4, 20), None) == date(2026, 1, 1)
    assert compare.months_before(date(2026, 3, 31)) == date(2025, 3, 31)
    assert compare.months_before(date(2024, 2, 29)) == date(2023, 2, 28)
    assert compare.season_phrase(sport) == "od září" and compare.season_phrase(None, case="v") == "v lednu"

    _history(org, subject, protocol, metric)
    tile = overview.kpi_tiles(subject)[0]
    c = tile["compare"]
    assert c["season"]["from"] == date(2025, 9, 1) and c["season"]["date"] == date(2025, 10, 1)
    assert c["season"]["delta_txt"] == "+2,2" and c["season"]["verdict"] == "zlepšení"
    assert c["best"]["value"] == 38.0 and c["best"]["date"] == date(2026, 1, 15)
    assert not c["best"]["is_current"] and c["best"]["state"].startswith("na úrovni maxima")
    assert c["best"]["label"] == "osobní maximum"
    assert c["period"]["from"] == date(2025, 5, 10) and c["period"]["delta_txt"] == "+1,2"
    assert c["period"]["pct_txt"] == "+3 %" and c["period"]["count"] == 4
    assert tile["goal"] is None

    # nové osobní maximum; dál od maxima než MDC se píše „pod maximem“
    _measure(org, subject, protocol, metric, date(2026, 6, 1), 39.0)
    c = overview.kpi_tiles(subject)[0]["compare"]
    assert c["best"]["is_current"] and c["best"]["state"] == "nové osobní maximum"
    _measure(org, subject, protocol, metric, date(2026, 6, 20), 36.5)
    c = overview.kpi_tiles(subject)[0]["compare"]
    assert c["best"]["state"] == "o 2,5 cm pod maximem" and c["best"]["kind"] == "below"

    # jediné měření v sezóně: „první měření v sezóně“; u času je nejlepší nejnižší hodnota
    cas = MetricDef.objects.create(organization=org, code="sprint", name="Sprint 20 m",
                                   family=TestFamily.FIELD, unit="s", mdc=0.05, decimals=2,
                                   direction=Direction.LOWER)
    points = [(date(2025, 3, 1), 3.20), (date(2025, 11, 1), 3.05)]
    c = compare.compare(cas, points, sport=sport)
    assert c["season"] is None and c["season_first"]
    assert c["best"]["is_current"] and c["best"]["state"] == "nový osobní rekord"
    assert compare.compare(cas, points[:1])["best"] is None

    # grafy: čára cíle a začátek sezóny
    goals.create(subject, metric, 40.0)
    spec = overview.trend_specs(subject)[0]
    assert any(t.get("name") == "cíl" for t in spec.figure["data"])
    assert spec.figure["layout"]["shapes"][0]["x0"] == "2025-09-01"
    assert spec.figure["layout"]["yaxis"]["range"][1] > 40


def test_cil_postup_karta_a_kroky(org):
    lab, client = _user(org, Role.LAB, "laborant")
    sport, protocol, metric, subject = _florbal(org)
    _measure(org, subject, protocol, metric, date(2025, 10, 1), 35.0)
    _measure(org, subject, protocol, metric, date(2026, 1, 15), 38.0)
    url, detail = reverse("subject_goal", args=[subject.pk]), reverse("subject_detail", args=[subject.pk])

    page = client.get(detail)
    assert "Žádný cíl" in page.content.decode()
    steps = {s["title"]: s for s in page.context["steps"]}
    assert not steps["Cíle"]["done"] and steps["Cíle"]["optional"] and steps["Cíle"]["button"] == "Nastavit cíl"
    assert [m.code for m in page.context["goal_metrics"]][0] == "cmj_vyska"

    text = client.post(url, {"metrika": metric.pk, "cil": "40", "do": "2026-12-31",
                             "poznamka": "s trenérem"}, follow=True).content.decode()
    goal = Goal.objects.get()
    assert goal.start_value == 38.0 and goal.start_date == date(2026, 1, 15) and goal.set_by == lab
    assert "Cíl uložen: Výška výskoku 40,0 cm. Zbývá 2,0 cm" in text
    assert "s trenérem" in text and "cíl <span" in text   # dlaždice i sekce Cíle
    steps = {s["title"]: s for s in client.get(detail).context["steps"]}
    assert steps["Cíle"]["done"] and steps["Cíle"]["text"].startswith("1 cíl: Výška výskoku 40,0 cm (zbývá 2,0 cm)")
    p = goals.goals_for(subject)[0]
    assert p.status == "open" and p.percent == 0 and p.verdict() == "zbývá více než chyba měření"

    # blíž než MDC = v dosahu; nad cílem = splněno (a procenta postupu)
    _measure(org, subject, protocol, metric, date(2026, 3, 1), 39.5)
    p = goals.goals_for(subject)[0]
    assert p.status == "near" and p.percent == 75 and p.badge() == ("badge-accent", "v dosahu")
    assert "prakticky splněn" in p.text()
    _measure(org, subject, protocol, metric, date(2026, 4, 1), 40.3)
    p = goals.goals_for(subject)[0]
    assert p.status == "reached" and p.reached_on == date(2026, 4, 1) and p.percent == 100
    assert "splněno" in client.get(detail).content.decode()

    # druhý cíl téhož ukazatele a nesmysl se neuloží
    text = client.post(url, {"metrika": metric.pk, "cil": "42"}, follow=True).content.decode()
    assert "už cíl má" in text and Goal.objects.count() == 1
    text = client.post(url, {"metrika": metric.pk, "cil": "hodně"}, follow=True).content.decode()
    assert "jako číslo" in text
    # zrušení: zůstane neplatný, karta ho neukazuje
    client.post(reverse("subject_goal_delete", args=[subject.pk, goal.pk]))
    goal.refresh_from_db()
    assert not goal.is_active and "Žádný cíl" in client.get(detail).content.decode()

    # po termínu a bez měření
    overdue = goals.create(subject, metric, 45.0, due_date=date(2026, 1, 1))
    p = goals.Progress(overdue, goals.series_for(subject, metric), today=date(2026, 5, 1))
    assert p.status == "overdue" and p.badge() == ("badge-warn", "po termínu") and "Termín prošel" in p.text()
    jiny = MetricDef.objects.create(organization=org, code="imtp_sila", name="Síla IMTP",
                                    family=TestFamily.FORCE_PLATE, unit="N", decimals=0)
    ProtocolMetric.objects.create(protocol=Protocol.objects.create(
        organization=org, code="imtp", name="IMTP", family=TestFamily.FORCE_PLATE), metric=jiny,
        is_primary=True)
    p = goals.Progress(goals.create(subject, jiny, 3000), goals.series_for(subject, jiny))
    assert p.status == "nodata" and "zatím nebyl změřen" in p.text()


def test_portal_cile_popisy_a_slovnicek(org):
    sport, protocol, metric, subject = _florbal(org)
    metric.athlete_text = "Jak vysoko vyskočíte z místa – odráží výbušnou sílu nohou."
    metric.coach_text = "Výkon dolních končetin v SSC; citlivý na únavu."
    metric.save()
    protocol.athlete_text = "Stojíte na desce, podřepnete a vyskočíte co nejvýš, třikrát."
    protocol.save()
    _history(org, subject, protocol, metric)
    goals.create(subject, metric, 40.0, due_date=date(2026, 12, 31))

    identity = SubjectIdentity.objects.create(subject=subject)
    identity.set_names("Jana", "Nová")
    athlete = User.objects.create(username="jana", organization=org, role=Role.ATHLETE)
    identity.user = athlete
    identity.save()
    coach = User.objects.create(username="trener", organization=org, role=Role.COACH)
    Sharing.objects.create(subject=subject, coach=coach, status=Sharing.Status.ACTIVE)

    client = Client()
    client.force_login(athlete)
    text = client.get(reverse("portal_subject", args=[subject.pk])).content.decode()
    assert metric.athlete_text in text and metric.coach_text not in text
    assert "Jak testy probíhají" in text and protocol.athlete_text in text
    assert "Co znamenají pojmy" in text and "sezóna začíná v září" in text
    assert "od začátku sezóny" in text and "+2,2 cm" in text and "osobní maximum" in text
    assert "za 12 měsíců" in text and "+3 %" in text
    assert 'id="cile"' in text and "cíl <span" in text and "Zbývá 2,8 cm" in text

    client.force_login(coach)
    text = client.get(reverse("coach_subject", args=[subject.pk])).content.decode()
    assert metric.coach_text in text and metric.athlete_text not in text
    assert protocol.athlete_text in text and 'id="cile"' in text and "Co znamenají pojmy" in text


def test_zprava_fakta_text_a_vysvetlivky(org):
    lab, client = _user(org, Role.LAB, "laborant")
    sport, protocol, metric, subject = _florbal(org)
    metric.athlete_text = "Jak vysoko vyskočíte z místa."
    metric.save()
    session = _history(org, subject, protocol, metric)
    goals.create(subject, metric, 40.0, due_date=date(2026, 12, 31))

    facts = report_facts.build(session, [], [], audience=Audience.ATHLETE)
    m = facts["klicove_metriky"][0]
    assert m["od_zacatku_sezony"] == {"prvni_mereni": "01. 10. 2025", "hodnota": 35.0,
                                      "zmena": 2.2, "posouzeni": "zlepšení přesahující chybu měření"}
    assert m["osobni_maximum"]["hodnota"] == 38.0 and m["osobni_maximum"]["stav"].startswith("na úrovni")
    assert m["za_12_mesicu"]["procent"] == 3 and m["za_12_mesicu"]["pocet_mereni"] == 4
    assert facts["cile"] == [{"metrika": "Výška výskoku", "jednotka": "cm", "cil": 40.0,
                              "aktualni": 37.2, "zbyva": 2.8,
                              "posouzeni": "zbývá více než chyba měření", "do": "31. 12. 2026"}]
    text = narrative.compose(session, [], [], facts)
    assert "Od začátku sezóny:" in text and "+2,2 cm od prvního měření v sezóně 01. 10. 2025" in text
    assert "Cíle:" in text and "cíl 40 cm, do 31. 12. 2026, aktuálně 37,2 cm, zbývá 2,8 cm" in text
    assert narrative.verify_numbers(text, [], facts) == []

    # zpráva: tabulka dlouhodobého srovnání, cíle, čára cíle a sezóna v grafu, vysvětlivky
    report = report_services.build_draft(session, user=lab, audience=Audience.ATHLETE)
    html = report_services.render_html(report)
    assert "Od začátku sezóny" in html and "Osobní maximum" in html and "sezóna od září" in html
    assert ">Cíle<" in html and "zbývá více než chyba měření" in html
    assert "cíl 40,0 cm" in html and "začátek sezóny" in html
    assert "Co ukazatele znamenají" in html and metric.athlete_text in html
    # nové maximum vede k větě v souhrnu; lékař vysvětlivky pro laiky nedostane
    _measure(org, subject, protocol, metric, date(2026, 5, 20), 39.0)
    newest = TestSession.objects.get(date=date(2026, 5, 20))
    facts = report_facts.build(newest, [], [])
    assert "Nové osobní maximum: výška výskoku." in narrative.compose(newest, [], [], facts)
    doctor = report_services.build_draft(newest, user=lab, audience=Audience.CLINICIAN)
    assert "Co ukazatele znamenají" not in report_services.render_html(doctor)


def test_nastaveni_popisu_navrh_modelem_a_sezona(org, monkeypatch):
    admin, client = _user(org, Role.ADMIN, "spravce")
    sport, protocol, metric, subject = _florbal(org)
    bez = MetricDef.objects.create(organization=org, code="cmj_rsi", name="RSI",
                                   family=TestFamily.FORCE_PLATE, unit="-", decimals=2)
    ProtocolMetric.objects.create(protocol=protocol, metric=bez)
    url = reverse("client_texts")

    page = client.get(url)
    text = page.content.decode()
    assert "Popisy pro klienta" in text and f'name="s_{metric.pk}"' in text and f'name="p_{protocol.pk}"' in text
    assert "Jazykový model není zapnutý" in text
    steps = {s["title"]: s for s in page.context["steps"]}
    assert not steps["Popisy pro klienta"]["done"] and steps["Popisy pro klienta"]["count"] == 1
    from apps.core.workplace import settings_sections

    links = dict(next(s for s in settings_sections(admin) if s["title"] == "Testy a ukazatele")["links"])
    assert links["Popisy pro klienta"] == url

    text = client.post(url, {"akce": "ulozit", f"s_{metric.pk}": "Jak vysoko vyskočíte.",
                             f"t_{metric.pk}": "Výkon nohou.", f"p_{protocol.pk}": "Vyskočíte třikrát."},
                       follow=True).content.decode()
    metric.refresh_from_db()
    protocol.refresh_from_db()
    assert metric.athlete_text == "Jak vysoko vyskočíte." and metric.coach_text == "Výkon nohou."
    assert protocol.athlete_text == "Vyskočíte třikrát." and "3 popisů změněno" in text
    steps = {s["title"]: s for s in client.get(url).context["steps"]}
    assert steps["Popisy pro klienta"]["done"]

    # návrh modelem: jen chybějící, předvyplněný a neuložený, dokud se neuloží
    asked = []

    def fake_chat(messages, *, model=None, temperature=None, timeout=None):
        asked.append(messages[-1]["content"])
        return llm.LLMReply(text='{"ukazatele": {"cmj_rsi": {"sportovec": "Jak rychle se odrazíte.", '
                                 '"trener": "Reaktivní síla."}}, "testy": {}}', model="test", seconds=1)

    monkeypatch.setattr(llm, "blocked_reason", lambda: "")
    monkeypatch.setattr(llm, "is_enabled", lambda: True)
    monkeypatch.setattr(llm, "chat", fake_chat)
    text = client.post(url, {"akce": "navrhnout"}).content.decode()
    assert "Jak rychle se odrazíte." in text and "návrh modelu" in text and "neuložené" in text
    assert "cmj_rsi" in asked[0] and "cmj_vyska" not in asked[0] and "FTVS-0001" not in asked[0]
    bez.refresh_from_db()
    assert bez.athlete_text == ""
    client.post(url, {"akce": "ulozit", f"s_{metric.pk}": metric.athlete_text,
                      f"t_{metric.pk}": metric.coach_text, f"p_{protocol.pk}": protocol.athlete_text,
                      f"s_{bez.pk}": "Jak rychle se odrazíte.", f"t_{bez.pk}": "Reaktivní síla."})
    bez.refresh_from_db()
    assert bez.athlete_text == "Jak rychle se odrazíte."
    text = client.post(url, {"akce": "navrhnout"}, follow=True).content.decode()
    assert "už popis mají" in text

    def broken(messages, **kwargs):
        raise llm.LLMError("model neběží")

    bez.athlete_text = ""
    bez.save()
    monkeypatch.setattr(llm, "chat", broken)
    text = client.post(url, {"akce": "navrhnout"}, follow=True).content.decode()
    assert "Model popisy nenavrhl: model neběží" in text

    # laborant popisy jen čte
    _, lab = _user(org, Role.LAB, "laborant")
    assert lab.post(url, {"akce": "ulozit"}).status_code == 403

    # měsíc začátku sezóny u sportu
    text = client.post(reverse("sport_season", args=[sport.pk]), {"mesic": "11"}, follow=True).content.decode()
    sport.refresh_from_db()
    assert sport.season_start_month == 11 and "sezóna začíná v listopadu" in text
    client.post(reverse("sport_season", args=[sport.pk]), {"mesic": "13"})
    sport.refresh_from_db()
    assert sport.season_start_month == 11
    client.post(reverse("sport_season", args=[sport.pk]), {"mesic": ""})
    sport.refresh_from_db()
    assert sport.season_start_month is None
    assert 'value="11"' in client.get(reverse("sport_list")).content.decode()
