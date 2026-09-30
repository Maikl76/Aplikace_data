"""Ukázková zpráva od AI: uložení na laboratorním PC a načtení ve veřejné ukázce."""

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.core.models import Organization, Role, User
from apps.reports import demo_reports
from apps.reports.models import Report
from apps.subjects.models import Subject, SubjectIdentity


@pytest.fixture
def slozka(tmp_path, monkeypatch):
    monkeypatch.setattr(demo_reports, "DIRECTORY", tmp_path)
    return tmp_path


def zprava(org, *, code="FTVS-0021", model="google/gemma-4-e4b", status="released"):
    subject = Subject.objects.create(organization=org, code=code)
    return Report.objects.create(
        organization=org, subject=subject, report_number=f"FT-2026-{code[-4:]}", status=status,
        summary="Výška výskoku se zlepšila o 2,1 cm nad MDC.", llm_model=model,
        rendered_html="<html><body>Zpráva od modelu</body></html>",
        released_at=timezone.now() if status == "released" else None)


def test_ulozeni_a_nacteni_v_ukazce(db, slozka, settings, client):
    lab = Organization.objects.create(name="FTVS", short_name="ftvs")
    report = zprava(lab)
    call_command("ulozit_ukazku_zpravy", verbosity=0)
    assert (slozka / f"{report.report_number}.json").exists()

    # „jiná instalace“: ukázka na PythonAnywhere
    Report.objects.all().delete()
    Subject.objects.all().delete()
    settings.DEMO_MODE = True
    call_command("nacist_ukazky_zprav", verbosity=0)
    call_command("nacist_ukazky_zprav", verbosity=0)          # podruhé nic nezdvojí
    ukazka = Report.objects.get()
    assert ukazka.report_number == "AI-FT-2026-0021" and ukazka.status == "released"
    assert ukazka.subject.code == "FTVS-0021-AI"
    assert "google/gemma-4-e4b" in ukazka.generation_note

    client.force_login(User.objects.create(username="a", organization=lab, role=Role.ADMIN))
    assert "Zpráva od modelu" in client.get(f"/zpravy/{ukazka.pk}/nahled/").content.decode()
    assert "Výška výskoku se zlepšila" in client.get(f"/zpravy/{ukazka.pk}/").content.decode()


def test_do_ukazky_nesmi_skutecny_clovek_sablona_ani_koncept(db, slozka, settings):
    from cryptography.fernet import Fernet

    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    skutecny = zprava(org, code="FTVS-0001")
    identity = SubjectIdentity(subject=skutecny.subject)
    identity.set_names("Jan", "Skutečný")
    identity.save()
    with pytest.raises(CommandError, match="uložené jméno"):
        call_command("ulozit_ukazku_zpravy", skutecny.report_number)
    with pytest.raises(CommandError, match="šablona"):
        call_command("ulozit_ukazku_zpravy", zprava(org, code="FTVS-0002",
                                                    model="šablona").report_number)
    with pytest.raises(CommandError, match="neexistuje"):
        call_command("ulozit_ukazku_zpravy", zprava(org, code="FTVS-0003",
                                                    status="draft").report_number)
    assert not list(slozka.glob("*.json"))


def test_mimo_ukazku_se_nenacita(db, slozka, settings):
    settings.DEMO_MODE = False
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    (slozka / "x.json").write_text('{"report_number": "X"}', encoding="utf-8")
    call_command("nacist_ukazky_zprav", verbosity=0)
    assert not Report.objects.filter(organization=org).exists()
