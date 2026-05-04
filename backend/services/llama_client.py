import json
import os
from typing import Optional
from urllib import error, request

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "45"))


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


def ollama_chat_safe(system: str, user: str) -> Optional[str]:
    try:
        return ollama_chat(system, user)
    except (error.URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError):
        return None
