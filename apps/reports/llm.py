"""
Klient pro lokální jazykový model.

Mluví protokolem kompatibilním s OpenAI (``/v1/chat/completions``), který
umí Ollama, LM Studio, vLLM i llama.cpp server. Aplikace tak není vázaná
na jeden nástroj a model se dá vyměnit nastavením, bez změny kódu.

Záměrně bez další knihovny – stačí standardní ``urllib``.
"""

import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

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


def is_enabled() -> bool:
    return bool(settings.LLM_ENABLED)


def chat(messages: list[dict], *, model: str | None = None,
         temperature: float | None = None, timeout: int | None = None) -> LLMReply:
    from .ai_models import default_model, timeout_for

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
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )

    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LLMError(_context_reason(detail, model)
                       or f"Model odpověděl chybou {exc.code}: {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise LLMError(
            f"Model není dostupný na {settings.LLM_BASE_URL} ({exc.reason}). "
            f"Běží Ollama, nebo LM Studio se zapnutým serverem?"
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
    url = settings.LLM_BASE_URL.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise LLMError(f"Seznam modelů se nepodařilo načíst: {exc}") from exc
    return [item.get("id", "") for item in body.get("data", []) if item.get("id")]
