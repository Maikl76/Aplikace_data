"""
Testy napojení jazykového modelu.

Skutečný model v testech neběží – místo něj falešný server, který mluví
stejným protokolem jako Ollama (``/v1/chat/completions``). Ověřuje se
celá cesta včetně HTTP, a hlavně pojistky: když model napíše číslo, které
v datech není, nebo když neodpoví, zpráva vznikne ze šablony.
"""

import json
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from apps.catalog.models import MetricDef, Protocol, ProtocolMetric, TestFamily
from apps.core.models import Organization, Role, User
from apps.measurements.models import Measurement, ProtocolRun, TestSession, Trial
from apps.reports import facts, llm, narrative, services
from apps.rules.models import Rule, Severity
from apps.subjects.models import Sex, Subject


class FakeModel:
    """Falešný model: vrátí připravený text a zapamatuje si, co dostal."""

    def __init__(self):
        self.reply = "Výchozí odpověď."
        self.status = 200
        self.requests = []

    def handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append({"path": self.path, "body": body})
                payload = json.dumps({"choices": [{"message": {"content": fake.reply}}]})
                self.send_response(fake.status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload.encode())

            def log_message(self, *args):
                pass

        return Handler


@pytest.fixture
def model(settings):
    fake = FakeModel()
    server = ThreadingHTTPServer(("127.0.0.1", 0), fake.handler())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings.LLM_ENABLED = True
    settings.LLM_BASE_URL = f"http://127.0.0.1:{server.server_port}/v1"
    settings.LLM_MODEL = "testovaci-model"
    settings.LLM_TIMEOUT = 5
    yield fake
    server.shutdown()


@pytest.fixture
def mereni(db):
    org = Organization.objects.create(name="FTVS", short_name="ftvs")
    user = User.objects.create(username="laborant", organization=org, role=Role.LAB)
    subject = Subject.objects.create(organization=org, code="FTVS-0007",
                                     sex=Sex.FEMALE, birth_year=2001)
    metric = MetricDef.objects.create(code="ir_er_ratio", name="Poměr IR/ER",
                                      family=TestFamily.DYNAMOMETRY, unit="-", decimals=2)
    protocol = Protocol.objects.create(code="iso", name="Izokinetika",
                                       family=TestFamily.DYNAMOMETRY)
    ProtocolMetric.objects.create(protocol=protocol, metric=metric, is_primary=True)
    session = TestSession.objects.create(organization=org, subject=subject,
                                         date=date(2026, 3, 1))
    run = ProtocolRun.objects.create(session=session, protocol=protocol)
    trial = Trial.objects.create(protocol_run=run, number=1)
    Measurement.objects.create(trial=trial, metric=metric, value=0.85)
    Rule.objects.create(
        code="ir_er", name="Poměr IR/ER", severity=Severity.MEDIUM,
        condition={"metric": "ir_er_ratio", "op": "<", "value": 1.0},
        finding_template="Poměr IR/ER {value_txt} je pod {threshold_txt}.",
        recommendation_template="Posílit zevní rotátory ramene.",
    )
    return user, session


# --- klient ----------------------------------------------------------------

def test_klient_mluvi_protokolem_openai(model):
    model.reply = "Ahoj."
    odpoved = llm.chat([{"role": "user", "content": "test"}])

    assert odpoved.text == "Ahoj."
    assert odpoved.model == "testovaci-model"
    assert model.requests[0]["path"] == "/v1/chat/completions"
    assert model.requests[0]["body"]["model"] == "testovaci-model"
    assert model.requests[0]["body"]["stream"] is False


def test_premysleni_nahlas_se_odstrani(model):
    model.reply = "<think>Tady model přemýšlí o 42 věcech.</think>\n\nVýsledný text."
    assert llm.chat([{"role": "user", "content": "x"}]).text == "Výsledný text."


def test_nedostupny_model_rekne_proc(settings):
    settings.LLM_BASE_URL = "http://127.0.0.1:9/v1"   # port, kde nic neběží
    settings.LLM_TIMEOUT = 2
    with pytest.raises(llm.LLMError, match="není dostupný"):
        llm.chat([{"role": "user", "content": "x"}])


def test_chyba_serveru_se_ohlasi(model):
    model.status = 500
    with pytest.raises(llm.LLMError, match="chybou 500"):
        llm.chat([{"role": "user", "content": "x"}])


# --- fakta -----------------------------------------------------------------

def test_fakta_obsahuji_jen_pseudonym(mereni):
    user, session = mereni
    services.build_draft(session, user=user)  # vyhodnotí pravidla
    data = facts.build(session, list(session.findings.all()), [])

    assert data["sportovec"]["kod"] == "FTVS-0007"
    assert "jmeno" not in json.dumps(data)
    assert data["klicove_metriky"][0]["hodnota"] == 0.85
    assert data["doporuceni_z_pravidel"] == ["Posílit zevní rotátory ramene."]


# --- skládání zprávy -------------------------------------------------------

def test_vypnuty_model_pouzije_sablonu(mereni, settings):
    settings.LLM_ENABLED = False
    user, session = mereni
    report = services.build_draft(session, user=user)

    assert report.llm_model == "šablona"
    assert "0,85" in report.summary


def test_verny_text_od_modelu_se_pouzije(mereni, model):
    model.reply = ("Sportovkyně FTVS-0007 má poměr IR/ER 0,85, tedy pod hodnotou 1,00.\n\n"
                   "Zjištění:\n• Poměr IR/ER 0,85 je pod 1,00.\n\n"
                   "Doporučení:\n• Posílit zevní rotátory ramene.")
    user, session = mereni
    report = services.build_draft(session, user=user)

    assert report.llm_model == "testovaci-model"
    assert report.summary.startswith("Sportovkyně FTVS-0007")
    assert "sestavil model" in report.generation_note


def test_vymyslene_cislo_text_odmitne(mereni, model):
    """Nejdůležitější pojistka: číslo, které v datech není, zprávu neprojde."""
    model.reply = "Poměr IR/ER 0,85 je pod 1,00; doporučujeme 12 týdnů posilování."
    user, session = mereni
    report = services.build_draft(session, user=user)

    assert report.llm_model == "šablona"
    assert "12" not in report.summary
    assert "odmítnut" in report.generation_note
    assert "12" in report.generation_note


def test_nedostupny_model_zpravu_nezastavi(mereni, settings):
    settings.LLM_ENABLED = True
    settings.LLM_BASE_URL = "http://127.0.0.1:9/v1"
    settings.LLM_TIMEOUT = 2
    user, session = mereni
    report = services.build_draft(session, user=user)

    assert report.llm_model == "šablona"
    assert "nepoužil" in report.generation_note
    assert "0,85" in report.summary


def test_model_dostane_pravidla_i_fakta(mereni, model):
    model.reply = "Poměr IR/ER 0,85 je pod 1,00."
    user, session = mereni
    services.build_draft(session, user=user)

    zpravy = model.requests[0]["body"]["messages"]
    assert zpravy[0]["role"] == "system"
    assert "Používej výhradně čísla" in zpravy[0]["content"]
    assert '"kod": "FTVS-0007"' in zpravy[1]["content"]


def test_kontrola_cisel_bere_i_fakta(mereni):
    """Čísla z faktů (např. datum, věk) jsou povolená, cizí ne."""
    user, session = mereni
    data = {"datum_mereni": "01. 03. 2026", "sportovec": {"vek": 25}}
    assert narrative.verify_numbers("Měřeno 01. 03. 2026, věk 25.", [], data) == []
    assert narrative.verify_numbers("Věk 26.", [], data) == ["26"]


@pytest.mark.parametrize("text,ocekavano", [
    ("Sportovec FTVS-0007 byl změřen.", []),          # kód není číslo
    ("Hodnota VO2max je v pořádku.", []),             # název metriky není číslo
    ("Změna −4,0 cm.", ["−4,0"]),                     # skutečná záporná hodnota ano
    ("Pokles o -3,2 cm.", ["-3,2"]),
])
def test_identifikatory_nejsou_cisla(text, ocekavano):
    assert narrative.verify_numbers(text, [], {}) == ocekavano
