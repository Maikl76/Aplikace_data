"""
Nastavení, dávka 2: normy v aplikaci – přehled s kroky, formulář normy
v pěti částech (ukazatel, pro koho platí, hodnoty, zdroj, poznámka),
náhled kolika sportovcům sedí, smazání; kroky nastavení vedou sem.
"""

import pytest
from cryptography.fernet import Fernet
from django.test import Client
from django.urls import reverse

from apps.analytics.services import find_norm
from apps.catalog.models import MetricDef, Norm, Protocol, ProtocolMetric, TestBattery, TestFamily
from apps.catalog.steps import catalog_steps
from apps.core.models import Organization, Role, User
from apps.evidence.models import Article
from apps.subjects.models import Sport, Subject


@pytest.fixture
def org(db, settings):
    settings.IDENTITY_ENCRYPTION_KEY = Fernet.generate_key().decode()
    return Organization.objects.create(name="FTVS", short_name="ftvs")


def _user(org, role, username):
    user = User.objects.create(username=username, organization=org, role=role,
                               is_staff=role == Role.ADMIN)
    client = Client()
    client.force_login(user)
    return user, client


def _catalog(org):
    sport = Sport.objects.create(organization=org, name="Florbal", code="florbal")
    protocol = Protocol.objects.create(organization=org, code="cmj", name="CMJ",
                                       family=TestFamily.FORCE_PLATE)
    key = MetricDef.objects.create(organization=org, code="cmj_vyska", name="Výška výskoku",
                                   family=TestFamily.FORCE_PLATE, unit="cm")
    other = MetricDef.objects.create(organization=org, code="cmj_sila", name="Síla",
                                     family=TestFamily.FORCE_PLATE, unit="N")
    ProtocolMetric.objects.create(protocol=protocol, metric=key, is_primary=True)
    ProtocolMetric.objects.create(protocol=protocol, metric=other)
    TestBattery.objects.create(organization=org, sport=sport).items.create(protocol=protocol)
    return sport, key, other


def _norm_data(metric, **extra):
    data = {"metric": str(metric.pk), "sport": "", "sex": "", "age_min": "", "age_max": "",
            "level": "", "side": "", "mode": "", "speed": "", "mean": "30", "sd": "4",
            "sample_size": "120",
            "source_citation": "Novák J. et al. (2021). Výskok u florbalistů. Čes. kinantropologie.",
            "source_doi": "https://doi.org/10.1234/abcd", "note": ""}
    data.update(extra)
    return data


def test_prehled_norem_s_kroky(org):
    _, client = _user(org, Role.ADMIN, "spravce")
    _, lab = _user(org, Role.LAB, "laborant")
    _, key, other = _catalog(org)
    url = reverse("norms_settings")
    page = client.get(url)
    assert page.status_code == 200
    text = page.content.decode()
    assert "Nová norma" in text and "Zatím žádná norma" in text
    steps = {s["title"]: s for s in page.context["steps"]}
    assert not steps["Normy u klíčových ukazatelů"]["done"] and "0 z 1 klíčových" in steps["Normy u klíčových ukazatelů"]["text"]
    assert steps["Normy u klíčových ukazatelů"]["url"] == reverse("norm_new")
    assert steps["Hodnoty"]["done"] and steps["Zdroje"]["done"]  # nic k doplnění
    assert steps["Pravidla"]["optional"] and steps["Pravidla"]["admin_only"]
    text = lab.get(url).content.decode()
    assert "Nová norma" not in text and "Normy podle ukazatele" in text
    # kroky nastavení vedou sem místo do administrace
    assert catalog_steps(client.get(url).context["request"].user)[4]["url"] == url
    steps = {s["title"]: s for s in client.get(reverse("workplace")).context["steps"]}
    assert steps["Normy a pravidla"]["url"] == url
    sections = {s["title"]: s for s in client.get(reverse("workplace")).context["sections"]}
    assert sections["Normy a pravidla"]["url"] == url
    assert "/admin/catalog/norm/" not in client.get(reverse("workplace")).content.decode()

    # neúplná norma se v přehledu označí a kroky ji počítají
    Norm.objects.create(organization=org, metric=other, mean=100, source_citation="krátké")
    page = client.get(url)
    assert "doplnit" in page.content.decode()
    steps = {s["title"]: s for s in page.context["steps"]}
    assert not steps["Hodnoty"]["done"] and steps["Hodnoty"]["count"] == 1
    assert not steps["Zdroje"]["done"] and "neúplnou citací" in steps["Zdroje"]["text"]


def test_norma_se_zalozi_se_zdrojem_upravi_a_smaze(org):
    _, client = _user(org, Role.ADMIN, "spravce")
    _, lab = _user(org, Role.LAB, "laborant")
    sport, key, other = _catalog(org)
    Subject.objects.create(organization=org, code="FTVS-0001", sport=sport, sex="F",
                           level=Subject.Level.NATIONAL)
    Subject.objects.create(organization=org, code="FTVS-0002", sport=sport, sex="M",
                           level=Subject.Level.TRAINED)
    Article.objects.create(title="Jump height norms in floorball", authors="Novák J., Svoboda P.",
                           journal="J Sports Sci", year=2021, doi="10.1234/abcd",
                           status=Article.Status.APPROVED)
    url = reverse("norm_new")
    assert lab.get(url).status_code == 403
    page = client.get(url + f"?ukazatel={key.pk}")
    assert page.status_code == 200
    text = page.content.decode()
    assert "Klíčové ukazatele" in text and f'value="{key.pk}" selected' in text
    assert 'data-citace="Novák J., Svoboda P. (2021). Jump height norms in floorball. J Sports Sci."' in text
    assert 'data-doi="10.1234/abcd"' in text

    # bez zdroje, s průměrem bez SD a s věkem naopak neprojde
    text = client.post(url, _norm_data(key, source_citation="x", sd="", age_min="18", age_max="15"),
                       follow=True).content.decode()
    assert "Doplňte zdroj" in text and "Průměr a SD patří k sobě" in text and "Věk od je větší" in text
    assert not Norm.objects.exists()
    text = client.post(url, _norm_data(key, mean="", sd="", p5="20", p50="30", p95="25"),
                       follow=True).content.decode()
    assert "Percentily musí růst" in text and not Norm.objects.exists()

    # založení: ženy, národní úroveň; sedí na jednu sportovkyni
    resp = client.post(url, _norm_data(key, sex="F", level="national", p10="24", p50="30", p90="36",
                                       mean="30,5", sd="4,2"))
    norm = Norm.objects.get()
    assert resp.status_code == 302 and resp.url.endswith(f"#ukazatel-{key.pk}")
    assert (norm.metric, norm.sex, norm.level, norm.mean, norm.sd, norm.sample_size) == (
        key, "F", "national", 30.5, 4.2, 120)
    assert norm.percentiles == {"10": 24.0, "50": 30.0, "90": 36.0}
    assert norm.source_doi == "10.1234/abcd" and norm.organization == org
    text = client.get(reverse("norms_settings")).content.decode()
    assert "sedí na 1" in text and "ženy, národní úroveň" in text and "30.5 ± 4.2" in text
    assert "percentily P10 24, P50 30, P90 36" in text
    # výběr normy ve zprávě: sedí na sportovkyni národní úrovně, ne na trénovaného muže
    woman, man = Subject.objects.order_by("code")
    assert find_norm(key, woman) == norm and find_norm(key, man) is None

    # úprava: rozšířit na všechny; ukazatel se nemění; náhled sedí na 2
    edit = reverse("norm_edit", args=[norm.pk])
    page = client.get(edit)
    assert page.status_code == 200 and page.context["fits"] == 1
    client.post(edit, _norm_data(other, sex="", level="", mean="31", sd="4"))
    norm.refresh_from_db()
    assert norm.metric == key and norm.sex == "" and norm.mean == 31.0 and norm.percentiles == {}
    assert client.get(edit).context["fits"] == 2
    assert lab.get(edit).status_code == 403
    steps = {s["title"]: s for s in client.get(reverse("norms_settings")).context["steps"]}
    assert steps["Normy u klíčových ukazatelů"]["done"]

    # smazání
    assert lab.post(reverse("norm_delete", args=[norm.pk])).status_code == 403
    resp = client.post(reverse("norm_delete", args=[norm.pk]), follow=True)
    assert not Norm.objects.exists() and "je smazaná" in resp.content.decode()
