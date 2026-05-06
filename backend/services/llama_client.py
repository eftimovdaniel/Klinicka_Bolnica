import json
import os
from typing import Optional
from urllib import error, request

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").strip().lower()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "45"))

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-1.5-flash").strip()
GOOGLE_TIMEOUT_SECONDS = int(os.getenv("GOOGLE_TIMEOUT_SECONDS", "45"))


def ollama_chat(system: str, user: str) -> str:
    """
    Повик кон Ollama /api/chat. Враќа го целиот текст од assistant пораката.
    """
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": str(system or "")},
            {"role": "user", "content": str(user or "")},
        ],
        "stream": False,
        "options": {"temperature": 0.1},
    }
    req = request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=OLLAMA_TIMEOUT_SECONDS) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        outer = json.loads(raw)
        msg = outer.get("message") or {}
        return str(msg.get("content") or "").strip()


def google_chat(system: str, user: str) -> str:
    """
    Повик кон Google AI Studio (Gemini generateContent API).
    """
    if not GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY is not configured")

    payload = {
        "system_instruction": {
            "parts": [{"text": str(system or "")}],
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": str(user or "")}],
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
        },
    }
    req = request.Request(
        (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{GOOGLE_MODEL}:generateContent?key={GOOGLE_API_KEY}"
        ),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=GOOGLE_TIMEOUT_SECONDS) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        outer = json.loads(raw)
        candidates = outer.get("candidates") or []
        first = candidates[0] if candidates else {}
        content = first.get("content") or {}
        parts = content.get("parts") or []
        texts = [str(p.get("text") or "") for p in parts if isinstance(p, dict)]
        return "\n".join(t for t in texts if t).strip()


def llm_chat(system: str, user: str) -> str:
    provider = LLM_PROVIDER
    if provider in ("google", "google_ai_studio", "gemini"):
        return google_chat(system, user)
    return ollama_chat(system, user)


def ollama_chat_safe(system: str, user: str) -> Optional[str]:
    try:
        return llm_chat(system, user)
    except (error.URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError):
        return None
