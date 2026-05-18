"""
Groq API клиент + автоматски локален режим при 429 (исцрпени токени / rate limit).

GROQ_AUTO_OFFLINE=1 (default): по 429 нема нови API повици до истек на cooldown.
GROQ_DISABLED=1: секогаш без Groq (испит/demo).
"""

from __future__ import annotations

import os
import time

import requests
from dotenv import load_dotenv

from ai._kernel.prompts import CHAT_SYSTEM_PROMPT

load_dotenv()

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_MODEL_FALLBACK = os.getenv("GROQ_MODEL_FALLBACK", "llama-3.1-8b-instant")
GROQ_FAST_ONLY = os.getenv("GROQ_FAST_ONLY", "").lower() in ("1", "true", "yes")
GROQ_DISABLED = os.getenv("GROQ_DISABLED", "").lower() in ("1", "true", "yes")
# Автоматски локален режим по 429 (без рачно GROQ_DISABLED)
GROQ_AUTO_OFFLINE = os.getenv("GROQ_AUTO_OFFLINE", "1").lower() in (
    "1",
    "true",
    "yes",
)
try:
    GROQ_OFFLINE_COOLDOWN_SEC = max(
        60, int(os.getenv("GROQ_OFFLINE_COOLDOWN_SEC", "600") or "600")
    )
except (TypeError, ValueError):
    GROQ_OFFLINE_COOLDOWN_SEC = 600

MAX_USER_CHARS = 8000

GROQ_OFFLINE_MSG = (
    "Привремено сум преоптоварен со прашања. Те молам почекај "
    "30-60 секунди и пробај пак."
)

# Circuit breaker: после 429 не повикувај Groq до _circuit_open_until
_circuit_open_until: float = 0.0
_circuit_logged: bool = False


def _post_chat(model: str, payload: dict, headers: dict) -> requests.Response:
    payload = {**payload, "model": model}
    return requests.post(GROQ_URL, json=payload, headers=headers, timeout=30)


def _circuit_e_aktiven() -> bool:
    global _circuit_logged
    if not GROQ_AUTO_OFFLINE or GROQ_DISABLED:
        return False
    if time.time() < _circuit_open_until:
        if not _circuit_logged:
            ost = int(_circuit_open_until - time.time())
            print(
                f"[groq_client] AUTO OFFLINE — Groq паузиран ~{ost}s "
                f"(локални правила + MySQL). GROQ_AUTO_OFFLINE=0 за исклучување."
            )
            _circuit_logged = True
        return True
    if _circuit_logged:
        print("[groq_client] Cooldown завршен — повторно се пробува Groq API")
        _circuit_logged = False
    return False


def _aktiviraj_auto_offline() -> None:
    """По 429: нема нови повици до cooldown (како GROQ_DISABLED, но привремено)."""
    global _circuit_open_until, _circuit_logged
    if not GROQ_AUTO_OFFLINE or GROQ_DISABLED:
        return
    _circuit_open_until = time.time() + GROQ_OFFLINE_COOLDOWN_SEC
    _circuit_logged = False
    print(
        f"[groq_client] 429 → AUTO OFFLINE за {GROQ_OFFLINE_COOLDOWN_SEC}s "
        f"(keyword + база; без Groq API)"
    )


def groq_e_isklucen() -> bool:
    """True = нема Groq (рачно или автоматски по 429)."""
    return GROQ_DISABLED or _circuit_e_aktiven()


def groq_status() -> dict:
    """За debug / испит — дали Groq е достапен."""
    now = time.time()
    ost = max(0, int(_circuit_open_until - now)) if _circuit_e_aktiven() else 0
    return {
        "disabled_manual": GROQ_DISABLED,
        "auto_offline_enabled": GROQ_AUTO_OFFLINE,
        "circuit_active": _circuit_e_aktiven(),
        "seconds_until_retry": ost,
        "cooldown_sec": GROQ_OFFLINE_COOLDOWN_SEC,
    }


def reset_groq_circuit() -> None:
    """Рачно отвори Groq повторно (на пр. после испит)."""
    global _circuit_open_until, _circuit_logged
    _circuit_open_until = 0.0
    _circuit_logged = False
    print("[groq_client] Circuit reset — Groq повторно активен")


def ask_ai(prasanje: str, system_prompt: str = CHAT_SYSTEM_PROMPT) -> str:
    if GROQ_DISABLED:
        print("[groq_client] GROQ_DISABLED=1 — нема API повик")
        return GROQ_OFFLINE_MSG

    if _circuit_e_aktiven():
        return GROQ_OFFLINE_MSG

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return "Не е поставен GROQ_API_KEY во backend/.env фајлот."

    prasanje = (prasanje or "").strip()
    if not prasanje:
        return "Те молам внеси прашање."
    if len(prasanje) > MAX_USER_CHARS:
        prasanje = prasanje[:MAX_USER_CHARS]

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prasanje},
    ]
    payload = {
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 800,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        primary = GROQ_MODEL_FALLBACK if GROQ_FAST_ONLY else GROQ_MODEL
        response = _post_chat(primary, payload, headers)

        if response.status_code == 429 and GROQ_MODEL_FALLBACK and not GROQ_FAST_ONLY:
            print(
                f"[groq_client] RATE LIMIT (429) на {primary} → "
                f"пробувам {GROQ_MODEL_FALLBACK}"
            )
            response = _post_chat(GROQ_MODEL_FALLBACK, payload, headers)

        if response.status_code == 429:
            _aktiviraj_auto_offline()
            return GROQ_OFFLINE_MSG

        if response.status_code == 401:
            print("[groq_client] AUTH (401) - проверете го GROQ_API_KEY")
            return "Невалиден API клуч. Проверете го GROQ_API_KEY во .env."

        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"].strip()

    except requests.exceptions.Timeout:
        return "AI не одговори навреме. Обиди се повторно."

    except requests.exceptions.RequestException as e:
        print(f"[groq_client] HTTP greska: {e}")
        return "Привремена грешка при поврзување. Пробај пак за неколку секунди."

    except (KeyError, IndexError):
        return "AI врати неочекуван формат."

    except Exception as e:
        print(f"[groq_client] Nepoznata greska: {e}")
        return f"Непозната грешка: {str(e)}"
