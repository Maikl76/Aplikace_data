"""
Klient pro jazykový model.

Mluví protokolem kompatibilním s OpenAI (``/v1/chat/completions``), který
umí Ollama, LM Studio, vLLM i llama.cpp server – a také cloudové služby
(Gemini přes svůj koncový bod kompatibilní s OpenAI). Aplikace tak není
vázaná na jeden nástroj a model se dá vyměnit nastavením, bez změny kódu.

Cloudový model (veřejná adresa mimo počítač a síť pracoviště) se smí použít
jen ve zkušebním provozu (DEMO_MODE) se smyšlenými daty: souhrny by jinak
opouštěly pracoviště. Mimo zkušební provoz se takový model nepoužije a
aplikace řekne proč.

Záměrně bez další knihovny – stačí standardní ``urllib``.
"""

import ipaddress
import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit

from django.conf import settings

logger = logging.getLogger(__name__)

# Některé modely (např. řada Qwen 3) nejdřív „přemýšlejí nahlas“ do bloku
# <think>…</think>. Do zprávy to nepatří.
THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class LLMError(Exception):
    """Model nejde použít – nedostupný, pomalý, nebo odpověděl nesmyslně."""


@dataclass
class LLMReply:
    text: str
    model: str
    seconds: float


LOCAL_SUFFIXES = (".local", ".lan", ".internal", ".home", ".localdomain", ".intranet")


def host_of(url: str | None = None) -> str:
    return (urlsplit(url or settings.LLM_BASE_URL).hostname or "").lower()


def is_remote(url: str | None = None) -> bool:
    """Veřejná adresa mimo počítač a síť pracoviště – tedy cloudový model."""
    host = host_of(url)
    if not host or host in ("localhost", "0.0.0.0"):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "." in host and not host.endswith(LOCAL_SUFFIXES)
    return not (address.is_private or address.is_loopback or address.is_link_local)


def blocked_reason() -> str:
    """Proč se nastavený model nepoužije; prázdné = v pořádku."""
    if settings.LLM_ENABLED and is_remote() and not settings.DEMO_MODE:
        return (f"Jazykový model na veřejné adrese {host_of()} se mimo zkušební provoz nepoužije: "
                "souhrny by opouštěly pracoviště. Nastavte lokální model (LM Studio, Ollama) "
                "nebo model v síti pracoviště; cloudový model patří jen do zkušebního provozu "
                "se smyšlenými daty.")
    return ""


def is_enabled() -> bool:
    return bool(settings.LLM_ENABLED) and not blocked_reason()


def describe() -> dict:
    """Stav modelu pro stránky: zapnutý, kde běží, zda je cloudový, proč je blokovaný."""
    from .ai_models import default_model

    return {"configured": bool(settings.LLM_ENABLED), "enabled": is_enabled(),
            "remote": is_remote(), "host": host_of(), "blocked": blocked_reason(),
            "model": default_model(), "has_key": bool(settings.LLM_API_KEY)}


def _headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if settings.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {settings.LLM_API_KEY}"
    return headers


def _auth_reason(code: int) -> str:
    if code in (401, 403) and (settings.LLM_API_KEY or is_remote()):
        return f"Model odmítl přístup (chyba {code}): klíč LLM_API_KEY chybí nebo neplatí."
    if code == 429:
        return "Model odmítl požadavek (429): vyčerpaný limit požadavků; zkuste to za chvíli."
    return ""


def _unreachable_hint() -> str:
    if is_remote():
        return ("Je adresa povolená ven (na PythonAnywhere musí být na seznamu povolených "
                "adres) a klíč správně?")
    return "Běží Ollama, nebo LM Studio se zapnutým serverem?"


def chat(messages: list[dict], *, model: str | None = None,
         temperature: float | None = None, timeout: int | None = None) -> LLMReply:
    from .ai_models import default_model, timeout_for

    if reason := blocked_reason():
        raise LLMError(reason)
    model = model or default_model()
    timeout = timeout or timeout_for(model)
    url = settings.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": settings.LLM_TEMPERATURE if temperature is None else temperature,
        "stream": False,
    }
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=_headers(), method="POST",
    )

    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LLMError(_auth_reason(exc.code) or _context_reason(detail, model)
                       or f"Model odpověděl chybou {exc.code}: {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise LLMError(
            f"Model není dostupný na {settings.LLM_BASE_URL} ({exc.reason}). "
            + _unreachable_hint()
        ) from exc
    except TimeoutError as exc:
        raise LLMError(f"Model {model} neodpověděl do {timeout} s.") from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise LLMError("Model vrátil odpověď, které nerozumím.") from exc

    try:
        # „content“ může u přemýšlejícího modelu chybět úplně – to řeší _empty_reason.
        text = body["choices"][0]["message"].get("content")
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise LLMError("V odpovědi modelu chybí text.") from exc

    text = THINK_BLOCK.sub("", text or "").strip()
    if not text:
        raise LLMError(_empty_reason(body, model))

    seconds = time.monotonic() - started
    # Kdo text skutečně napsal: server ho uvádí v odpovědi. LM Studio na
    # žádost o model, který nemá načtený, načte ten požadovaný – ne ten,
    # který je zrovna otevřený v okně.
    answered_by = str(body.get("model") or model) if isinstance(body, dict) else model
    logger.info("Model %s odpověděl za %.1f s", answered_by, seconds)
    return LLMReply(text=text, model=answered_by, seconds=seconds)


CONTEXT_ERROR = re.compile(r"exceed|context (size|length)|too long", re.IGNORECASE)


def _context_reason(detail: str, model: str) -> str:
    """
    Podklady se nevešly do kontextu modelu (LM Studio: „request (17486 tokens)
    exceeds the available context size (16384 tokens)“). Říct kolik a co nastavit.
    """
    if not CONTEXT_ERROR.search(detail):
        return ""
    numbers = re.findall(r"\((\d+) tokens\)", detail.replace('\\"', '"'))
    if len(numbers) >= 2:
        need, have = int(numbers[0]), int(numbers[1])
        # Potřeba je místo i na odpověď (zhruba 1–2 tisíce tokenů).
        suggest = next(size for size in (16384, 24576, 32768, 49152, 65536, 131072)
                       if size >= need + 2048)
        return (f"Podklady pro model {model} mají {need} tokenů, ale kontext je nastavený "
                f"jen na {have}. V LM Studiu u modelu (záložka Load) zvyšte Context Length "
                f"aspoň na {suggest} a model znovu načtěte.")
    return (f"Podklady se nevešly do kontextu modelu {model}. V LM Studiu u modelu "
            f"(záložka Load) zvyšte Context Length a model znovu načtěte.")


def _empty_reason(body: dict, model: str) -> str:
    """
    Proč model nenapsal žádný text – ať je jasné, co nastavit v LM Studiu.

    Přemýšlející modely (Gemma 4, Qwen, Glimmer) dávají úvahy do zvláštního
    pole a výsledek do „content“. Když dojde místo v kontextu, nebo model
    celou odpověď spotřebuje na přemýšlení, „content“ zůstane prázdný.
    """
    choice = body["choices"][0]
    message = choice.get("message") or {}
    finish = choice.get("finish_reason")
    thought = message.get("reasoning_content") or message.get("reasoning")
    prompt_tokens = (body.get("usage") or {}).get("prompt_tokens")
    size = f" (podklady mají {prompt_tokens} tokenů)" if prompt_tokens else ""
    if finish == "length":
        return (f"Model {model} nedopsal odpověď – došlo místo v kontextu{size}. "
                f"V LM Studiu u modelu (záložka Load) zvyšte Context Length aspoň na 16384 "
                f"a model znovu načtěte.")
    if thought:
        return (f"Model {model} jen přemýšlel a výslednou odpověď nenapsal. V LM Studiu "
                f"u modelu zvyšte Context Length (záložka Load) aspoň na 16384, případně "
                f"vypněte přemýšlení (záložka Inference).")
    return f"Model {model} vrátil prázdný text{size}."


def list_models(*, timeout: int = 10) -> list[str]:
    """
    Modely, které server nabízí (``GET /v1/models``).

    Hlavně kvůli LM Studiu: název modelu v aplikaci musí přesně sedět
    s identifikátorem na serveru a ten se od názvu v nabídce často liší.
    """
    if reason := blocked_reason():
        raise LLMError(reason)
    url = settings.LLM_BASE_URL.rstrip("/") + "/models"
    request = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise LLMError(_auth_reason(exc.code)
                       or f"Seznam modelů se nepodařilo načíst: {exc}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise LLMError(f"Seznam modelů se nepodařilo načíst: {exc}") from exc
    # Gemini uvádí modely jako „models/gemini-…“ a vedle chatovacích i vkládání,
    # obrázky a řeč – ty do výběru pro zprávy nepatří.
    names = [str(item.get("id", "")).removeprefix("models/")
             for item in body.get("data", []) if item.get("id")]
    return [n for n in names if not any(x in n.lower() for x in NOT_CHAT)]


NOT_CHAT = ("embedding", "imagen", "veo", "tts", "aqa", "image-generation")
