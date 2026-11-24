"""
Vyplněnost testu: jedna hodnota ještě není hotový test. Přehled dne, krok
Hodnoty, seznam dnů i koncept zprávy, který vzniká sám, počítají s tím,
kolik ukazatelů je vyplněno z kolika (hodnota z neplatného pokusu se nepočítá).
"""

import pytest
from cryptography.fernet import Fernet
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import MetricDef, Protocol, ProtocolMetric, TestFamily
from apps.core.models import Organization, Role, User
from apps.measurements import completeness
from apps.measurements.models import ProtocolRun, TestSession
from apps.reports.models import Report
from apps.subjects.models import Subject


@pytest.fixture
def den(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    org = Organization.objects.create(name="FTVS", short_name="ftvs", auto_draft=True)
    user = User.objects.create(username="laborant", organization=org, role=Role.LAB)
    client = Client()
    client.force_login(user)
    protocol = Protocol.objects.create(organization=org, code="slozeni", name="Složení těla",
                                       family=TestFamily.BODY_COMPOSITION)
    pms = []
    for code, name in (("hmotnost", "Tělesná hmotnost"), ("tuk", "Podíl tuku")):
        metric = MetricDef.objects.create(organization=org, code=code, name=name,
                                          family=TestFamily.BODY_COMPOSITION, unit="kg")
        pms.append(ProtocolMetric.objects.create(protocol=protocol, metric=metric,
                                                 is_primary=code == "hmotnost"))
    subject = Subject.objects.create(organization=org, code="FTVS-0001")
    session = TestSession.objects.create(organization=org, subject=subject,
                                         date=timezone.localdate())
    run = ProtocolRun.objects.create(session=session, protocol=protocol)
    return {"org": org, "client": client, "session": session, "run": run, "pms": pms}


def test_jedna_hodnota_neni_hotovy_test(den):
    client, session, run, (hmotnost, tuk) = den["client"], den["session"], den["run"], den["pms"]
    detail = reverse("session_detail", args=[session.pk])
    page = client.get(detail).content.decode()
    assert "zadat hodnoty · 2" in page

    client.post(reverse("run_entry", args=[run.pk]), {f"v|{hmotnost.pk}|||||1": "88"})
    (annotated,) = completeness.annotate([run])
    assert (annotated.stav, annotated.vyplneno, annotated.ukazatelu, annotated.zbyva) == (
        "rozpracovany", 1, 2, 1)
    page = client.get(detail)
    text = page.content.decode()
    assert "vyplněno 1 z 2 · zbývá 1" in text and 'title="Chybí: Podíl tuku"' in text
    assert "hotovo" not in text.split("Testy</h2>")[1].split("</ul>")[0]
    steps = {s["title"]: s for s in page.context["steps"]}
    assert not steps["Hodnoty"]["done"] and steps["Hodnoty"]["button"] == "Doplnit hodnoty"
    assert "1 rozpracovaný (Složení těla: zbývá 1 z 2)" in steps["Hodnoty"]["text"]
    assert not Report.objects.exists()            # koncept vznikne až po vyplnění všeho
    assert "0/1" in client.get(reverse("session_list")).content.decode()

    # hodnota z neplatného pokusu se nepočítá (podíl tuku jen ve 2. pokusu, ten je neplatný)
    from apps.measurements.models import Measurement, Trial

    invalid = Trial.objects.create(protocol_run=run, number=2, is_valid=False)
    Measurement.objects.create(trial=invalid, metric=tuk.metric, value=14)
    assert completeness.annotate([run])[0].stav == "rozpracovany"
    invalid.delete()

    client.post(reverse("run_entry", args=[run.pk]),
                {f"v|{hmotnost.pk}|||||1": "88", f"v|{tuk.pk}|||||1": "14"})
    text = client.get(detail).content.decode()
    assert "hotovo · 2 z 2" in text
    steps = {s["title"]: s for s in client.get(detail).context["steps"]}
    assert steps["Hodnoty"]["done"] and "Všechny testy mají všechny hodnoty." in steps["Hodnoty"]["text"]
    assert Report.objects.filter(auto_created=True).count() == 1
    assert "1/1" in client.get(reverse("session_list")).content.decode()


def test_dva_testy_cekaji_spravne_cesky(den):
    session, org = den["session"], den["org"]
    other = Protocol.objects.create(organization=org, code="sj", name="Squat jump",
                                    family=TestFamily.FORCE_PLATE)
    metric = MetricDef.objects.create(organization=org, code="sj_h", name="Výška",
                                      family=TestFamily.FORCE_PLATE, unit="cm")
    ProtocolMetric.objects.create(protocol=other, metric=metric)
    ProtocolRun.objects.create(session=session, protocol=other)
    steps = {s["title"]: s for s in den["client"].get(
        reverse("session_detail", args=[session.pk])).context["steps"]}
    assert steps["Hodnoty"]["text"].startswith("2 testy čekají na hodnoty")
    assert steps["Hodnoty"]["count"] == 2


def test_bez_strany_je_oboustranne_a_stary_format_se_nepocita(den):
    """Import, který uloží oboustrannou hodnotu bez strany, test vyplní; starý formát ne."""
    from apps.measurements.models import Measurement, Trial

    org, session = den["org"], den["session"]
    protocol = Protocol.objects.create(organization=org, code="stisk", name="Síla stisku",
                                       family=TestFamily.DYNAMOMETRY)
    vyska = MetricDef.objects.create(organization=org, code="vyska_v", name="Výška výskoku",
                                     family=TestFamily.DYNAMOMETRY, unit="cm")
    sila = MetricDef.objects.create(organization=org, code="sila_s", name="Síla",
                                    family=TestFamily.DYNAMOMETRY, unit="N")
    ProtocolMetric.objects.create(protocol=protocol, metric=vyska, sides=["B"])
    ProtocolMetric.objects.create(protocol=protocol, metric=sila, sides=["L", "R"])
    run = ProtocolRun.objects.create(session=session, protocol=protocol)
    trial = Trial.objects.create(protocol_run=run, number=1)
    Measurement.objects.create(trial=trial, metric=vyska, side="", value=40)
    (r,) = completeness.annotate([run])
    assert (r.stav, r.vyplneno, r.ukazatelu, r.mimo) == ("rozpracovany", 1, 3, 0)
    assert r.chybi_text == "Chybí: Síla (levá), Síla (pravá)"

    # starý formát: síla bez strany u testu s levou a pravou – do žádného řádku nepatří
    Measurement.objects.create(trial=trial, metric=sila, side="", value=500)
    (r,) = completeness.annotate([run])
    assert (r.vyplneno, r.mimo) == (1, 1)
    assert r.chybi_text.endswith(
        ". 1 hodnota je mimo řádky tabulky (např. bez rozlišení strany) a nepočítá se")

    for side in ("L", "R"):
        Measurement.objects.create(trial=trial, metric=sila, side=side, value=500)
    (r,) = completeness.annotate([run])
    assert (r.stav, r.vyplneno, r.zbyva) == ("hotovy", 3, 0)

    # jen hodnota mimo řádky: rozpracovaný (něco uloženo je), vyplněno 0
    jiny = ProtocolRun.objects.create(session=session, protocol=protocol)
    Measurement.objects.create(trial=Trial.objects.create(protocol_run=jiny, number=1),
                               metric=sila, side="", value=480)
    (r,) = completeness.annotate([jiny])
    assert (r.stav, r.vyplneno, r.mimo) == ("rozpracovany", 0, 1)


def test_volitelny_ukazatel_se_do_vyplnenosti_nepocita(den):
    """Test je hotový i bez volitelného ukazatele; koncept vznikne; tabulka ho označí."""
    client, session, run, (hmotnost, tuk) = den["client"], den["session"], den["run"], den["pms"]
    tuk.is_optional = True
    tuk.save(update_fields=["is_optional"])
    detail = reverse("session_detail", args=[session.pk])
    assert "zadat hodnoty · 1" in client.get(detail).content.decode()
    entry = client.get(reverse("run_entry", args=[run.pk])).content.decode()
    assert entry.count(">volitelné</span>") == 1

    client.post(reverse("run_entry", args=[run.pk]), {f"v|{hmotnost.pk}|||||1": "88"})
    (r,) = completeness.annotate([run])
    assert (r.stav, r.vyplneno, r.ukazatelu, r.volitelne_chybi) == ("hotovy", 1, 1, ["Podíl tuku"])
    text = client.get(detail).content.decode()
    assert "hotovo · 1 z 1" in text
    assert 'title="Povinné ukazatele mají hodnotu. Volitelné bez hodnoty: Podíl tuku"' in text
    assert Report.objects.filter(auto_created=True).count() == 1

    # jen volitelná hodnota: něco zadané je, ale povinné chybí
    jiny = ProtocolRun.objects.create(session=session, protocol=run.protocol)
    client.post(reverse("run_entry", args=[jiny.pk]), {f"v|{tuk.pk}|||||1": "14"})
    (r,) = completeness.annotate([jiny])
    assert (r.stav, r.vyplneno, r.ukazatelu, r.chybi_text) == (
        "rozpracovany", 0, 1, "Chybí: Tělesná hmotnost")
