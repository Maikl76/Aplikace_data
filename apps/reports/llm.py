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
    model = model or settings.LLM_MODEL
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
        with urllib.request.urlopen(request, timeout=timeout or settings.LLM_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise LLMError(f"Model odpověděl chybou {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise LLMError(
            f"Model není dostupný na {settings.LLM_BASE_URL} ({exc.reason}). "
            f"Běží Ollama?"
        ) from exc
    except TimeoutError as exc:
        raise LLMError(f"Model neodpověděl do {timeout or settings.LLM_TIMEOUT} s.") from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise LLMError("Model vrátil odpověď, které nerozumím.") from exc

    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("V odpovědi modelu chybí text.") from exc

    text = THINK_BLOCK.sub("", text or "").strip()
    if not text:
        raise LLMError("Model vrátil prázdný text.")

    seconds = time.monotonic() - started
    logger.info("Model %s odpověděl za %.1f s", model, seconds)
    return LLMReply(text=text, model=model, seconds=seconds)
