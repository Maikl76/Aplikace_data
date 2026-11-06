"""
Dávka 9: souhrnná zpráva za období (víc testovacích dnů v jedné zprávě:
první a poslední hodnota, nejlepší v období, hodnoty po měřeních, grafy,
cíle, doporučení z období) a uzavřená smyčka doporučení (plnění doporučení
z minulé zprávy posouzené při dalším dni, navázání v nové zprávě, portál).
"""

from datetime import date

import pytest
from cryptography.fernet import Fernet
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from apps.catalog.models import MetricDef, Protocol, ProtocolMetric, TestBattery, TestFamily
from apps.core.models import Organization, Role, User
from apps.measurements.models import Measurement, ProtocolRun, TestSession, Trial
from apps.reports import facts as report_facts
from apps.reports import followup, narrative, notify, period
from apps.reports import services as report_services
from apps.reports.models import Audience, RecommendationReview, Report
from apps.subjects import goals
from apps.subjects.models import Sharing, Sport, Subject, SubjectIdentity


@pytest.fixture
def org(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    call_command("seed_roles", verbosity=0)
    return Organization.objects.create(name="FTVS", short_name="ftvs")


def _user(org, role, username):
    user = User.objects.create(username=username, organization=org, role=role)
    client = Client()
    client.force_login(user)
    return user, client


def _world(org):
    sport = Sport.objects.create(organization=org, name="Florbal", code="florbal",
                                 season_start_month=1)
    protocol = Protocol.objects.create(organization=org, code="cmj", name="CMJ",
                                       family=TestFamily.FORCE_PLATE)
    metric = MetricDef.objects.create(organization=org, code="cmj_vyska", name="Výška výskoku",
                                      family=TestFamily.FORCE_PLATE, unit="cm", mdc=1.0, decimals=1)
    ProtocolMetric.objects.create(protocol=protocol, metric=metric, is_primary=True)
    battery = TestBattery.objects.create(organization=org, sport=sport)
    battery.items.create(protocol=protocol, order=1)
    subject = Subject.objects.create(organization=org, code="FTVS-0001", sport=sport, sex="F")
    return sport, protocol, metric, subject


def _measure(org, subject, protocol, metric, day, value):
    session = TestSession.objects.create(organization=org, subject=subject, date=day)
    run = ProtocolRun.objects.create(session=session, protocol=protocol)
    Measurement.objects.create(trial=Trial.objects.create(protocol_run=run, number=1),
                               metric=metric, value=value)
    return session


def _released(session, user, *, note="", rules=(), audience=Audience.COACH):
    """Vydaná zpráva z měření s komentářem diagnostika a (dodatečně) doporučeními z pravidel."""
    report = report_services.build_draft(session, user=user, audience=audience)
    report.custom_note = note
    report.save(update_fields=["custom_note"])
    report_services.release(report, user=user)
    if rules:
        report.snapshot = {**(report.snapshot or {}), "recommendations": list(rules)}
        report.save(update_fields=["snapshot"])
    return report


def test_plneni_doporuceni_z_minule_zpravy(org):
    lab, client = _user(org, Role.LAB, "laborant")
    sport, protocol, metric, subject = _world(org)
    first = _measure(org, subject, protocol, metric, date(2026, 3, 1), 30.0)
    report = _released(first, lab, note="Posilovat lýtka 3× týdně.", rules=["Zařadit plyometrii."])
    assert [i["index"] for i in followup.items(report)] == [0, -1]

    second = _measure(org, subject, protocol, metric, date(2026, 5, 1), 32.0)
    assert followup.previous_report(second) == report
    assert followup.previous_report(first) is None
    detail = reverse("session_detail", args=[second.pk])
    page = client.get(detail)
    html = page.content.decode()
    assert "Doporučení z minulé zprávy" in html and "Zařadit plyometrii." in html
    assert "Posilovat lýtka 3× týdně." in html and 'name="stav_-1"' in html
    steps = {s["title"]: s for s in page.context["steps"]}
    assert not steps["Doporučení z minula"]["done"] and steps["Doporučení z minula"]["count"] == 2
    assert steps["Doporučení z minula"]["button"] == "Posoudit"
    # před první zprávou není co posuzovat
    steps = {s["title"]: s for s in client.get(reverse("session_detail", args=[first.pk])).context["steps"]}
    assert "není vydaná zpráva" in steps["Doporučení z minula"]["text"] and steps["Doporučení z minula"]["done"]

    text = client.post(reverse("session_followup", args=[second.pk]),
                       {"stav_0": "plnilo", "stav_-1": "castecne", "pozn_-1": "jen 2× týdně"},
                       follow=True).content.decode()
    assert f"Plnění doporučení z {report.report_number} uloženo (2 z 2 posouzeno)" in text
    reviews = {r.index: r for r in RecommendationReview.objects.filter(session=second)}
    assert reviews[0].status == "plnilo" and reviews[-1].note == "jen 2× týdně"
    assert reviews[-1].reviewed_by == lab and reviews[0].text == "Zařadit plyometrii."
    steps = {s["title"]: s for s in client.get(detail).context["steps"]}
    assert steps["Doporučení z minula"]["done"] and "2 z 2" in steps["Doporučení z minula"]["text"]
    # změna názoru přepíše, neposouzené zůstává neposouzené
    client.post(reverse("session_followup", args=[second.pk]), {"stav_0": "neplnilo", "stav_-1": ""})
    assert RecommendationReview.objects.get(session=second, index=0).status == "neplnilo"
    assert RecommendationReview.objects.get(session=second, index=-1).status == "castecne"

    # nová zpráva naváže: fakta, souhrn ze šablony, oddíl ve zprávě, detail
    facts = report_facts.build(second, [], [])
    assert facts["doporuceni_z_minula"] == [
        {"zprava": report.report_number, "vydano": "01. 03. 2026", "text": "Zařadit plyometrii.",
         "plneni": "neplnilo se"},
        {"zprava": report.report_number, "vydano": "01. 03. 2026", "text": "Posilovat lýtka 3× týdně.",
         "plneni": "částečně", "poznamka": "jen 2× týdně"}]
    summary = narrative.compose(second, [], [], facts)
    assert f"Doporučení z minulé zprávy {report.report_number} (01. 03. 2026) a jejich plnění:" in summary
    assert "• Zařadit plyometrii. – neplnilo se" in summary and "– částečně (jen 2× týdně)" in summary
    assert narrative.verify_numbers(summary, [], facts) == []
    new = report_services.build_draft(second, user=lab, audience=Audience.COACH)
    html = report_services.render_html(new)
    assert f"Plnění doporučení z minulé zprávy {report.report_number}" in html and "neplnilo se" in html
    html = client.get(reverse("report_detail", args=[new.pk])).content.decode()
    assert "Plnění doporučení z minulé zprávy" in html and "částečně" in html

    # portál: trenér i sportovec vidí doporučení z poslední zprávy pro sebe i plnění
    coach = User.objects.create(username="trener", organization=org, role=Role.COACH)
    Sharing.objects.create(subject=subject, coach=coach, status=Sharing.Status.ACTIVE)
    portal = Client()
    portal.force_login(coach)
    html = portal.get(reverse("coach_subject", args=[subject.pk])).content.decode()
    assert "Doporučení z poslední zprávy" in html and "Zařadit plyometrii." in html
    assert "neplnilo se" in html and "částečně" in html and "jen 2× týdně" in html
    identity = SubjectIdentity.objects.create(subject=subject)
    athlete = User.objects.create(username="jana", organization=org, role=Role.ATHLETE)
    identity.user = athlete
    identity.save()
    portal.force_login(athlete)
    html = portal.get(reverse("portal_subject", args=[subject.pk])).content.decode()
    assert "Doporučení z poslední zprávy" not in html   # pro sportovce zatím žádná vydaná zpráva
    _released(first, lab, note="Protahovat.", audience=Audience.ATHLETE)
    html = portal.get(reverse("portal_subject", args=[subject.pk])).content.decode()
    assert "Doporučení z poslední zprávy" in html and "Protahovat." in html and "zatím neposouzeno" in html


def test_souhrnna_zprava_za_obdobi(org, settings):
    settings.EMAIL_HOST = ""
    lab, client = _user(org, Role.LAB, "laborant")
    sport, protocol, metric, subject = _world(org)
    jan = _measure(org, subject, protocol, metric, date(2026, 1, 10), 30.0)
    mar = _measure(org, subject, protocol, metric, date(2026, 3, 10), 33.5)
    _measure(org, subject, protocol, metric, date(2026, 5, 10), 32.0)
    old = _released(jan, lab, note="Posilovat lýtka.", rules=["Zařadit plyometrii."])
    RecommendationReview.objects.create(session=mar, report=old, index=0, text="Zařadit plyometrii.",
                                        status="plnilo", reviewed_by=lab)
    goals.create(subject, metric, 35.0, due_date=date(2026, 12, 31))

    detail = reverse("subject_detail", args=[subject.pk])
    html = client.get(detail).content.decode()
    assert "Souhrnná zpráva za období" in html and 'name="od"' in html
    url = reverse("report_period_create", args=[subject.pk])
    text = client.post(url, {"od": "2026-04-01", "do": "2026-06-30", "pro": "trener"},
                       follow=True).content.decode()
    assert "má sportovec 1 měření s hodnotami" in text and not Report.objects.filter(kind="obdobi").exists()
    text = client.post(url, {"od": "2026-06-30", "do": "2026-01-01", "pro": "trener"}, follow=True).content.decode()
    assert "musí být před" in text

    response = client.post(url, {"od": "2026-01-01", "do": "2026-06-30", "pro": "trener"})
    report = Report.objects.get(kind=Report.Kind.PERIOD)
    assert response["Location"] == reverse("report_detail", args=[report.pk])
    assert report.period_from == date(2026, 1, 1) and report.period_to == date(2026, 6, 30)
    assert report.session is None and report.audience == Audience.COACH and report.is_period
    assert report.title == "Souhrnná zpráva za období pro trenéra" and report.llm_model == "šablona"
    assert "Souhrn za období od 01. 01. 2026 do 30. 06. 2026: 3 měření (CMJ)." in report.summary
    assert ("• Výška výskoku: 30 cm (10. 01. 2026) → 32 cm (10. 05. 2026), změna +2 cm – "
            "zlepšení přesahující chybu měření; nejlepší v období 33,5 cm (10. 03. 2026)") in report.summary
    assert "cíl 35 cm, do 31. 12. 2026, aktuálně 32 cm, zbývá 3 cm" in report.summary
    assert f"• {old.report_number} (10. 01. 2026): Zařadit plyometrii. – plnilo se" in report.summary
    assert "Posilovat lýtka. – neposouzeno" in report.summary
    data = period.facts(report)
    assert data["obdobi"]["pocet_mereni"] == 3 and data["klicove_ukazatele"][0]["nejlepsi"]["hodnota"] == 33.5
    assert narrative.verify_numbers(report.summary, [], data) == []

    page = client.get(reverse("report_detail", args=[report.pk]))
    html = page.content.decode()
    assert "souhrn za období 01.01.2026 – 30.06.2026" in html and "3 měření" in html
    assert "Klíčové ukazatele za období" in html and "Doporučení v období a jejich plnění" in html
    steps = {s["title"]: s for s in page.context["steps"]}
    assert "souhrn za období 01.01.2026 – 30.06.2026" in steps["Koncept"]["text"]
    html = report_services.render_html(report)
    assert "Souhrnná zpráva za období pro trenéra" in html and "Hodnoty po měřeních" in html
    assert "10.01.26" in html and "10.03.26" in html and "10.05.26" in html and "33,5" in html
    assert "cíl 35,0 cm" in html and "Zařadit plyometrii." in html and "plnilo se" in html
    assert "Vývoj v období" in html and "<svg" in html

    # vydání, upozornění, seznam, portál trenéra, nová verze
    report_services.release(report, user=lab)
    report.refresh_from_db()
    assert report.status == Report.Status.RELEASED and report.rendered_html
    assert "souhrn za období 01.01.2026 – 30.06.2026" in notify.message(report, "")[1]
    assert "období" in client.get(reverse("report_list")).content.decode()
    coach = User.objects.create(username="trener", organization=org, role=Role.COACH)
    Sharing.objects.create(subject=subject, coach=coach, status=Sharing.Status.ACTIVE)
    portal = Client()
    portal.force_login(coach)
    html = portal.get(reverse("coach_subject", args=[subject.pk])).content.decode()
    assert "souhrn za období 01.01.2026 – 30.06.2026" in html
    assert portal.get(reverse("coach_report", args=[subject.pk, report.pk])).status_code == 200
    newer = report_services.supersede(report, user=lab)
    assert newer.is_period and newer.version == 2 and newer.period_to == date(2026, 6, 30)
    # souhrn za období je i „minulá zpráva“ pro další den
    later = _measure(org, subject, protocol, metric, date(2026, 8, 1), 34.0)
    report.refresh_from_db()
    assert followup.previous_report(later) == old   # souhrn bez komentáře nemá co posoudit
    newer.custom_note = "Držet objem skoků."
    newer.save(update_fields=["custom_note"])
    report_services.release(newer, user=lab)
    assert followup.previous_report(later) == newer
    assert followup.facts(later)[0]["vydano"] == "30. 06. 2026"
