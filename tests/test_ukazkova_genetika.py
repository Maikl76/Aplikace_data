"""Ukázkové genetické vzorky ve zkušebním provozu: jen dospělí, jen jednou, mimo ukázku jen --kody."""

from io import StringIO

import pytest
from cryptography.fernet import Fernet
from django.core.management import call_command
from django.utils import timezone

from apps.core.models import Organization
from apps.genetics.models import GeneticSample, Genotype
from apps.genetics.seed import seed_domains
from apps.subjects.models import Sport, Subject

AGES = (("FTVS-0001", 24), ("FTVS-0002", 17), ("FTVS-0003", 30), ("FTVS-0004", 19),
        ("FTVS-0005", 22))


@pytest.fixture
def ukazka(db, settings):
    settings.DEMO_MODE = True
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.GENETICS_ENCRYPTION_KEY = Fernet.generate_key().decode()
    seed_domains()
    call_command("nacist_navrhy_karet", verbosity=0)        # varianty a panel z repozitáře
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    sport = Sport.objects.create(organization=org, code="florbal", name="Florbal")
    year = timezone.localdate().year
    for code, age in AGES:
        Subject.objects.create(organization=org, code=code, sport=sport, birth_year=year - age)
    return org


def _run(**opts):
    out = StringIO()
    call_command("ukazkova_genetika", stdout=out, **opts)
    return out.getvalue()


def test_vzorky_dostanou_prvni_tri_dospeli(ukazka):
    text = _run()
    codes = sorted(GeneticSample.objects.values_list("subject__code", flat=True))
    assert codes == ["FTVS-0001", "FTVS-0003", "FTVS-0004"]   # 0002 je nezletilý
    assert "FTVS-0002: přeskočeno" in text and "dospěl" in text
    sample = GeneticSample.objects.get(subject__code="FTVS-0001")
    assert sample.status == GeneticSample.Status.RECEIVED      # ověření zůstává na diagnostikovi
    assert sample.consent is not None and "Fiktivní" in sample.note
    items = list(sample.panel.active_items())
    assert items and sample.genotypes.count() == len(items)
    for g in sample.genotypes.all():
        assert g.quality == Genotype.Quality.OK and g.value in g.variant.genotypes
    assert any(g.raw != g.value for g in sample.genotypes.all())  # i zápis v notaci laboratoře
    rows = {s.subject.code: tuple(g.value for g in s.genotypes.order_by("variant__rsid"))
            for s in GeneticSample.objects.all()}
    assert len(set(rows.values())) == 3                         # sportovci se liší

    again = _run()
    assert "nových vzorků 0" in again and GeneticSample.objects.count() == 3


def test_mimo_ukazku_jen_pro_vyjmenovane(ukazka, settings):
    settings.DEMO_MODE = False
    assert "Jen v ukázce" in _run() and not GeneticSample.objects.exists()
    text = _run(kody=["FTVS-0005", "FTVS-0002"])
    assert GeneticSample.objects.filter(subject__code="FTVS-0005").exists()
    assert not GeneticSample.objects.filter(subject__code="FTVS-0002").exists()
    assert "FTVS-0002: přeskočeno" in text and GeneticSample.objects.count() == 1
