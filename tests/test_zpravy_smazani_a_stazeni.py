"""
Dávka 18: smazat jde jen koncept (zpráva, která nikdy nebyla vydaná) – jeho
číslo se už nepřidělí a den si smazání pamatuje, takže koncept sám znovu
nevznikne. Vydanou zprávu nesmaže nikdo; vydanou omylem lze stáhnout z oběhu:
zmizí z portálu sportovce i trenéra, v laboratoři zůstane v archivu s důvodem.
"""

from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from django.contrib import admin as django_admin
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import ProtocolMetric
from apps.core import access
from apps.core.models import AuditLog, Organization, Role, User
from apps.measurements.models import ProtocolRun, TestSession
from apps.reports import auto as report_auto
from apps.reports import notify, services
from apps.reports.models import Audience, Report, ReportSeries
from apps.reports.steps import report_steps
from apps.subjects.models import Sharing, Sport
from tests.test_koncept_a_doruceni import _account, _day, _measure, _user


@pytest.fixture
def org(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    return Organization.objects.create(name="FTVS", short_name="ftvs")


def _measured_day(org):
    d = _day(org)
    _measure(d["run_cmj"], d["cmj_m"], 30)
    _measure(d["run_imtp"], d["imtp_m"], 2000)
    return d


def _messages(response) -> str:
    return " | ".join(str(m) for m in response.context["messages"])


# --- smazání konceptu ---------------------------------------------------------------------

def test_koncept_jde_smazat_a_cislo_se_nepouzije(org):
    lab, client = _user(org, Role.LAB, "laborant")
    d = _measured_day(org)
    draft = services.build_draft(d["session"], user=lab, audience=Audience.ATHLETE)
    assert draft.report_number.endswith("0001") and draft.can_delete
    detail = reverse("report_detail", args=[draft.pk])
    delete = reverse("report_delete", args=[draft.pk])

    page = client.get(detail).content.decode()
    assert "Smazat koncept" in page and f'action="{delete}"' in page
    assert "Stáhnout z oběhu" not in page                   # koncept se nestahuje, maže se
    assert f'action="{delete}"' in client.get(reverse("report_list")).content.decode()
    assert client.get(delete).url == detail                 # GET nic nemaže
    assert Report.objects.filter(pk=draft.pk).exists()

    response = client.post(delete, follow=True)
    assert response.redirect_chain[0][0] == reverse("session_detail", args=[d["session"].pk]) + "#zpravy"
    assert not Report.objects.exists()
    text = _messages(response)
    assert f"Koncept {draft.report_number} je smazaný" in text and "Číslo se už nepoužije" in text
    log = AuditLog.objects.get(action=AuditLog.Action.DELETE, object_type="Report")
    assert log.object_id == str(draft.pk) and log.subject_code == "FTVS-0001"
    assert log.detail["cislo"] == draft.report_number and log.detail["pro"] == Audience.ATHLETE
    assert log.user == lab

    # číslo smazaného konceptu se už nepřidělí
    assert ReportSeries.objects.get(organization=org).last == 1
    second = services.build_draft(d["session"], user=lab, audience=Audience.ATHLETE)
    assert second.report_number.endswith("0002")
    # smazání staršího konceptu nechá mezeru, řada pokračuje od nejvyššího
    third = services.build_draft(d["session"], user=lab, audience=Audience.COACH)
    client.post(reverse("report_delete", args=[second.pk]))
    fourth = services.build_draft(d["session"], user=lab, audience=Audience.CLINICIAN)
    assert third.report_number.endswith("0003") and fourth.report_number.endswith("0004")
    # číslo mimo řadu se ignoruje
    services.burn_number(org.pk, "UKAZKA")
    services.burn_number(org.pk, "FT-2026-abc")
    assert ReportSeries.objects.filter(organization=org).count() == 1


def test_smazany_koncept_sam_znovu_nevznikne(org):
    lab, client = _user(org, Role.LAB, "laborant")
    d = _day(org)
    cmj_pm = ProtocolMetric.objects.get(protocol=d["cmj"])
    imtp_pm = ProtocolMetric.objects.get(protocol=d["imtp"])
    client.post(reverse("run_entry", args=[d["run_cmj"].pk]), {f"v|{cmj_pm.pk}|||||1": "30"})
    client.post(reverse("run_entry", args=[d["run_imtp"].pk]), {f"v|{imtp_pm.pk}|||||1": "2000"})
    draft = Report.objects.get()
    assert draft.auto_created

    # smazání ze seznamu vrátí do seznamu se stejným filtrem
    back = reverse("report_list") + "?stav=draft"
    response = client.post(reverse("report_delete", args=[draft.pk]), {"zpet": back}, follow=True)
    assert response.redirect_chain[0][0] == back and not Report.objects.exists()
    assert "koncept sám nevznikne" in _messages(response)
    d["session"].refresh_from_db()
    assert d["session"].draft_deleted

    # další hodnota ani přímé volání automatu koncept nezaloží
    client.post(reverse("run_entry", args=[d["run_cmj"].pk]), {f"v|{cmj_pm.pk}|||||2": "31"})
    assert not Report.objects.exists()
    assert report_auto.ensure_draft(d["session"], user=lab) is None
    page = client.get(reverse("session_detail", args=[d["session"].pk]))
    text = page.content.decode()
    assert "byl smazán ručně" in text and "Koncept vzniká sám" not in text
    steps = {s["title"]: s for s in page.context["steps"]}
    assert "byl smazán, sám už nevznikne" in steps["Zpráva"]["text"]

    # ručně založit jde dál – tlačítkem i hromadně z Dnešního testování
    assert report_auto.drafts_for([d["session"]], user=lab)["vytvoreno"] == 1
    manual = Report.objects.get()
    client.post(reverse("report_delete", args=[manual.pk]))
    response = client.post(reverse("report_create", args=[d["session"].pk]), {"pro": "sportovec"})
    assert response.status_code == 302 and Report.objects.count() == 1

    # zpět na jiné stránky než vlastní adresy se nepřesměruje
    again = Report.objects.get()
    response = client.post(reverse("report_delete", args=[again.pk]), {"zpet": "https://example.com/"})
    assert response.url == reverse("session_detail", args=[d["session"].pk]) + "#zpravy"


def test_vydanou_ani_psanou_zpravu_smazat_nejde(org):
    lab, client = _user(org, Role.LAB, "laborant")
    access.grant(lab, reports_release=True)
    d = _measured_day(org)
    released = services.release(services.build_draft(d["session"], user=lab,
                                                     audience=Audience.ATHLETE), user=lab)
    assert not released.can_delete
    response = client.post(reverse("report_delete", args=[released.pk]), follow=True)
    assert Report.objects.filter(pk=released.pk).exists()
    assert "Smazat lze jen koncept" in _messages(response)
    page = client.get(reverse("report_detail", args=[released.pk])).content.decode()
    assert "Smazat koncept" not in page and "Stáhnout z oběhu" in page
    assert reverse("report_delete", args=[released.pk]) not in client.get(reverse("report_list")).content.decode()
    with pytest.raises(services.ReportError, match="jen koncept"):
        services.delete_draft(released, user=lab)

    # koncept, který právě píše model, počká
    draft = services.build_draft(d["session"], user=lab, audience=Audience.COACH)
    Report.objects.filter(pk=draft.pk).update(writing=Report.Writing.RUNNING,
                                              writing_started_at=timezone.now())
    draft.refresh_from_db()
    assert draft.is_writing and not draft.can_delete
    response = client.post(reverse("report_delete", args=[draft.pk]), follow=True)
    assert Report.objects.filter(pk=draft.pk).exists() and "píše souhrn" in _messages(response)
    page = client.get(reverse("report_detail", args=[draft.pk])).content.decode()
    assert "Vydat nebo smazat koncept půjde, až model dopíše" in page
    assert not AuditLog.objects.filter(action=AuditLog.Action.DELETE).exists()

    # koncept, který je novou verzí: po smazání původní vydaná zpráva platí dál
    newer = services.supersede(released, user=lab)
    assert "Původní vydaná zpráva platí dál" in client.get(reverse("report_detail", args=[newer.pk])).content.decode()
    client.post(reverse("report_delete", args=[newer.pk]))
    released.refresh_from_db()
    assert released.status == Report.Status.RELEASED and not Report.objects.filter(pk=newer.pk).exists()


def test_mazat_a_stahovat_smi_jen_opravneny_ucet_ve_svem_rozsahu(org):
    lab, client = _user(org, Role.LAB, "laborant")              # koncepty ano, vydávání ne
    d = _measured_day(org)
    draft = services.build_draft(d["session"], user=lab, audience=Audience.ATHLETE)

    # účet bez oprávnění ke konceptům a výzkumník (jen čtení) nesmažou nic
    other, other_client = _user(org, Role.LAB, "bez-konceptu")
    access.grant(other, reports_draft=False)
    assert other_client.post(reverse("report_delete", args=[draft.pk])).status_code == 403
    assert "Smazat koncept" not in other_client.get(reverse("report_detail", args=[draft.pk])).content.decode()
    assert reverse("report_delete", args=[draft.pk]) not in other_client.get(reverse("report_list")).content.decode()
    _, researcher = _user(org, Role.RESEARCHER, "vyzkumnik")
    assert researcher.post(reverse("report_delete", args=[draft.pk])).status_code == 403
    assert Report.objects.filter(pk=draft.pk).exists()

    # účet s jiným rozsahem sportů zprávu vůbec nevidí
    hokej = Sport.objects.create(organization=org, name="Hokej", code="hokej")
    scoped, scoped_client = _user(org, Role.LAB, "jen-hokej")
    profile = access.grant(scoped, all_sports=False)
    profile.sports.set([hokej])
    access.forget(scoped)
    assert scoped_client.post(reverse("report_delete", args=[draft.pk])).status_code == 404
    assert Report.objects.filter(pk=draft.pk).exists()

    # stáhnout z oběhu smí jen účet, který smí vydávat
    admin_user, admin_client = _user(org, Role.ADMIN, "spravce")
    released = services.release(draft, user=admin_user)
    withdraw = reverse("report_withdraw", args=[released.pk])
    assert client.post(withdraw, {"duvod": "vydáno omylem"}).status_code == 403
    assert "Stáhnout z oběhu" not in client.get(reverse("report_detail", args=[released.pk])).content.decode()
    assert scoped_client.post(withdraw, {"duvod": "vydáno omylem"}).status_code in (403, 404)
    released.refresh_from_db()
    assert released.status == Report.Status.RELEASED
    assert admin_client.post(withdraw, {"duvod": "vydáno omylem"}).status_code == 302
    released.refresh_from_db()
    assert released.status == Report.Status.WITHDRAWN and released.withdrawn_by == admin_user


# --- stažení vydané zprávy z oběhu ----------------------------------------------------------

def test_stazeni_z_obehu_skryje_zpravu_v_portalu_a_necha_ji_v_archivu(org):
    lab, client = _user(org, Role.LAB, "laborant")
    access.grant(lab, reports_release=True)
    d = _measured_day(org)
    _, athlete = _account(d["subject"])
    coach = User.objects.create(username="trener", organization=org, role=Role.COACH)
    Sharing.objects.create(subject=d["subject"], coach=coach, status=Sharing.Status.ACTIVE)
    athlete_client, coach_client = Client(), Client()
    athlete_client.force_login(athlete)
    coach_client.force_login(coach)

    report = services.release(services.build_draft(d["session"], user=lab,
                                                   audience=Audience.ATHLETE), user=lab)
    coach_report = services.release(services.build_draft(d["session"], user=lab,
                                                         audience=Audience.COACH), user=lab)
    services.set_flags(report, example=True, test_set=True)
    portal = reverse("portal_subject", args=[d["subject"].pk])
    portal_report = reverse("portal_report", args=[d["subject"].pk, report.pk])
    assert report.report_number in athlete_client.get(portal).content.decode()
    assert athlete_client.get(portal_report).status_code == 200

    withdraw = reverse("report_withdraw", args=[report.pk])
    detail = reverse("report_detail", args=[report.pk])
    assert client.get(withdraw).url == detail                       # GET nic nestahuje
    # bez důvodu nejde
    response = client.post(withdraw, {"duvod": "  "}, follow=True)
    assert "Uveďte důvod stažení" in _messages(response)
    report.refresh_from_db()
    assert report.status == Report.Status.RELEASED

    response = client.post(withdraw, {"duvod": "  Vydáno   omylem – chybné hodnoty CMJ. "}, follow=True)
    report.refresh_from_db()
    assert report.status == Report.Status.WITHDRAWN and report.is_withdrawn
    assert report.withdrawn_by == lab and report.withdrawn_at
    assert report.withdrawn_reason == "Vydáno omylem – chybné hodnoty CMJ."
    assert not report.is_example and not report.in_test_set       # stažená není vzor pro model
    assert "je stažená z oběhu" in _messages(response)
    log = AuditLog.objects.filter(action=AuditLog.Action.UPDATE, object_id=str(report.pk)).latest("pk")
    assert log.detail["akce"] == "stazeni_z_obehu" and "chybné hodnoty" in log.detail["duvod"]

    # sportovec ji v portálu nevidí – seznam, zpráva ani PDF
    assert report.report_number not in athlete_client.get(portal).content.decode()
    assert athlete_client.get(portal_report).status_code == 404
    assert athlete_client.get(reverse("portal_report_pdf", args=[d["subject"].pk, report.pk])).status_code == 404
    # zpráva pro trenéra zůstala, dokud ji někdo nestáhne; pak zmizí i trenérovi
    coach_page = reverse("coach_subject", args=[d["subject"].pk])
    coach_view = reverse("coach_report", args=[d["subject"].pk, coach_report.pk])
    assert coach_report.report_number in coach_client.get(coach_page).content.decode()
    client.post(reverse("report_withdraw", args=[coach_report.pk]), {"duvod": "stejná chyba"})
    assert coach_report.report_number not in coach_client.get(coach_page).content.decode()
    assert coach_client.get(coach_view).status_code == 404
    assert coach_client.get(reverse("coach_report_pdf", args=[d["subject"].pk, coach_report.pk])).status_code == 404

    # v laboratoři zůstává v archivu: stránka, seznam, filtr, karta sportovce, testovací den
    page = client.get(detail)
    text = page.content.decode()
    assert "Zpráva je stažená z oběhu" in text and "chybné hodnoty CMJ" in text
    assert "Stažená zpráva se nepředává" in text and "Učení modelu" not in text
    assert f'action="{withdraw}"' not in text and "Smazat koncept" not in text
    assert "Vytvořit novou verzi" in text
    steps = {s["title"]: s for s in page.context["steps"]}
    assert "staženo z oběhu" in steps["Vydání"]["text"] and steps["Vydání"]["done"]
    assert steps["Předání"]["done"] and "nepředává" in steps["Předání"]["text"]
    assert "Další krok" not in text and "uzavřeno – stažena z oběhu" in text
    listing = client.get(reverse("report_list") + "?stav=withdrawn").content.decode()
    assert report.report_number in listing and "stažena z oběhu" in listing
    assert "Stažené z oběhu" in client.get(reverse("report_list")).content.decode()
    assert "Stažena z oběhu" in client.get(reverse("subject_detail", args=[d["subject"].pk])).content.decode()
    day = client.get(reverse("session_detail", args=[d["session"].pk]))
    assert "stažena z oběhu" in day.content.decode()
    day_steps = {s["title"]: s for s in day.context["steps"]}
    assert "je stažená z oběhu" in day_steps["Zpráva"]["text"] and not day_steps["Zpráva"]["done"]
    assert client.get(reverse("report_preview", args=[report.pk])).status_code == 200   # archiv jde otevřít

    # se staženou zprávou už nejde nic: smazat, znovu stáhnout, předat, upozornit, dát za vzor
    assert notify.notice(report) == ""
    for name, data, needle in (("report_delete", {}, "Smazat lze jen koncept"),
                               ("report_withdraw", {"duvod": "ještě jednou"}, "jen platnou vydanou"),
                               ("report_deliver", {"recipient": "AKESO"}, "Předat lze jen vydanou"),
                               ("report_notify", {}, "Upozornit jde jen u vydané")):
        response = client.post(reverse(name, args=[report.pk]), data, follow=True)
        assert needle in _messages(response), name
    with pytest.raises(services.ReportError, match="ne koncept ani zprávu staženou"):
        services.set_flags(report, example=True)
    report.refresh_from_db()
    assert report.status == Report.Status.WITHDRAWN and report.withdrawn_reason.startswith("Vydáno omylem")
    # automat ani hromadné koncepty den se staženou zprávou neřeší – rozhoduje člověk
    assert report_auto.ensure_draft(d["session"], user=lab) is None
    assert report_auto.drafts_for([d["session"]], user=lab)["uz_ma"] == 1

    # opravená zpráva vznikne jako nová verze; stažená zůstane staženou
    newer = services.supersede(report, user=lab)
    assert newer.version == 2 and newer.supersedes == report
    services.release(newer, user=lab)
    report.refresh_from_db()
    assert report.status == Report.Status.WITHDRAWN
    assert newer.report_number in athlete_client.get(portal).content.decode()
    assert report.report_number not in athlete_client.get(portal).content.decode()


def test_koncept_a_predana_zprava_pri_stazeni(org):
    from apps.subjects.models import Consent

    lab, client = _user(org, Role.LAB, "laborant")
    access.grant(lab, reports_release=True)
    d = _measured_day(org)
    draft = services.build_draft(d["session"], user=lab, audience=Audience.CLINICIAN)
    with pytest.raises(services.ReportError, match="můžete ho smazat"):
        services.withdraw(draft, user=lab, reason="omyl omyl")
    response = client.post(reverse("report_withdraw", args=[draft.pk]), {"duvod": "omyl omyl"}, follow=True)
    assert "můžete ho smazat" in _messages(response)

    # zpráva pro lékaře už předaná příjemci: stáhnout jde, ale laboratoř ví, že příjemce musí informovat
    Consent.objects.create(subject=d["subject"], scope=Consent.Scope.REPORT_HANDOVER,
                           granted_on=timezone.localdate() - timedelta(days=1))
    released = services.release(draft, user=lab)
    services.deliver(released, recipient="AKESO", channel="handover", user=lab)
    page = client.get(reverse("report_detail", args=[released.pk])).content.decode()
    assert "Zpráva už byla předána" in page
    response = client.post(reverse("report_withdraw", args=[released.pk]),
                           {"duvod": "záměna sportovce"}, follow=True)
    assert "Už byla předána (AKESO)" in _messages(response)
    text = response.content.decode()
    assert "Před stažením už byla předána" in text and "AKESO" in text
    steps = report_steps(Report.objects.get(pk=released.pk), has_consent=True)
    assert steps[5]["done"] and "Předáno: AKESO" in steps[5]["text"]


# --- administrace ---------------------------------------------------------------------------

def test_administrace_smaze_jen_koncept(org):
    admin_user = User.objects.create(username="spravce", organization=org, role=Role.ADMIN,
                                     is_staff=True, is_superuser=True)
    client = Client()
    client.force_login(admin_user)
    d = _measured_day(org)
    released = services.release(services.build_draft(d["session"], user=admin_user,
                                                     audience=Audience.ATHLETE), user=admin_user)
    withdrawn = services.withdraw(
        services.release(services.build_draft(d["session"], user=admin_user,
                                              audience=Audience.COACH), user=admin_user),
        user=admin_user, reason="vydáno omylem")
    draft = services.build_draft(d["session"], user=admin_user, audience=Audience.CLINICIAN)

    model_admin = django_admin.site._registry[Report]
    request = RequestFactory().get("/admin/")
    request.user = admin_user
    assert model_admin.has_delete_permission(request, draft)
    assert not model_admin.has_delete_permission(request, released)
    assert not model_admin.has_delete_permission(request, withdrawn)

    for report in (released, withdrawn):
        response = client.post(f"/admin/reports/report/{report.pk}/delete/", {"post": "yes"})
        assert response.status_code == 403 and Report.objects.filter(pk=report.pk).exists()
    # hromadné mazání vydanou zprávu také nesmaže
    client.post("/admin/reports/report/", {"action": "delete_selected", "post": "yes",
                                           "_selected_action": [released.pk, draft.pk]})
    assert Report.objects.filter(pk=released.pk).exists() and Report.objects.filter(pk=draft.pk).exists()

    # koncept smazat jde – stejnou cestou jako v aplikaci (číslo, paměť dne)
    response = client.post(f"/admin/reports/report/{draft.pk}/delete/", {"post": "yes"})
    assert response.status_code == 302 and not Report.objects.filter(pk=draft.pk).exists()
    d["session"].refresh_from_db()
    assert d["session"].draft_deleted
    assert ReportSeries.objects.get(organization=org).last == int(draft.report_number[-4:])
    again = services.build_draft(d["session"], user=admin_user, audience=Audience.CLINICIAN)
    assert int(again.report_number[-4:]) == int(draft.report_number[-4:]) + 1


# --- souhrn za období -----------------------------------------------------------------------

def test_koncept_souhrnu_za_obdobi_jde_smazat(org):
    from apps.reports import period

    lab, client = _user(org, Role.LAB, "laborant")
    d = _measured_day(org)
    older = TestSession.objects.create(organization=org, subject=d["subject"],
                                       date=timezone.localdate() - timedelta(days=40))
    _measure(ProtocolRun.objects.create(session=older, protocol=d["cmj"]), d["cmj_m"], 28)
    draft = period.build_draft(d["subject"], date_from=timezone.localdate() - timedelta(days=60),
                               date_to=timezone.localdate(), user=lab, audience=Audience.ATHLETE)
    assert draft.is_period and draft.session is None
    response = client.post(reverse("report_delete", args=[draft.pk]))
    assert response.url == reverse("subject_detail", args=[d["subject"].pk]) + "#zpravy"
    assert not Report.objects.exists()
    # souhrn za období není vázaný na jeden den – žádný den si smazání nepamatuje
    assert not TestSession.objects.filter(draft_deleted=True).exists()
