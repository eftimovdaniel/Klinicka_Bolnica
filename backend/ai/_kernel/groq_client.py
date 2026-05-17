import os
import requests
from dotenv import load_dotenv
from ai._kernel.prompts import CHAT_SYSTEM_PROMPT

load_dotenv()

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# llm provider: groq (облако, free лимит) | ollama (локално, без 429 — за брзо тестирање)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").strip().lower()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

# Groq модел — llama-3.3-70b-versatile е најмоќен од бесплатните на Groq.
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
MAX_USER_CHARS = 8000


def _koristi_ollama() -> bool:
    return LLM_PROVIDER == "ollama"


def _chat_completions_url() -> str:
    if _koristi_ollama():
        return f"{OLLAMA_BASE_URL}/chat/completions"
    return GROQ_URL


def _aktiven_model() -> str:
    return OLLAMA_MODEL if _koristi_ollama() else GROQ_MODEL


def ask_ai(prasanje: str, system_prompt: str = CHAT_SYSTEM_PROMPT) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    if not _koristi_ollama() and not api_key:
        return "Не е поставен GROQ_API_KEY во backend/.env фајлот."

    prasanje = (prasanje or "").strip()
    if not prasanje:
        return "Те молам внеси прашање."
    if len(prasanje) > MAX_USER_CHARS:
        prasanje = prasanje[:MAX_USER_CHARS]

    model = _aktiven_model()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prasanje},
        ],
        "temperature": 0.5,
        "max_tokens": 800,
    }
    headers = {"Content-Type": "application/json"}
    if not _koristi_ollama():
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = requests.post(
            _chat_completions_url(),
            json=payload,
            headers=headers,
            timeout=120 if _koristi_ollama() else 30,
        )

        if not _koristi_ollama() and response.status_code == 429:
            print(f"[llm] RATE LIMIT (429) Groq модел {model}")
            return (
                "Привремено сум преоптоварен со прашања. Те молам почекај "
                "30-60 секунди и пробај пак. (За брзо тестирање: LLM_PROVIDER=ollama во .env)"
            )

        if not _koristi_ollama() and response.status_code == 401:
            print("[llm] AUTH (401) - проверете го GROQ_API_KEY")
            return "Невалиден API клуч. Проверете го GROQ_API_KEY во .env."

        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"].strip()

    except requests.exceptions.ConnectionError:
        if _koristi_ollama():
            return (
                "Ollama не одговара. Стартувај ја апликацијата Ollama и во терминал: "
                f"ollama pull {OLLAMA_MODEL}"
            )
        return "Привремена грешка при поврзување. Пробај пак за неколку секунди."

    except requests.exceptions.Timeout:
        return "AI не одговори навреме. Обиди се повторно."

    except requests.exceptions.RequestException as e:
        print(f"[llm] HTTP greska ({LLM_PROVIDER}): {e}")
        return "Привремена грешка при поврзување. Пробај пак за неколку секунди."

    except (KeyError, IndexError):
        return "AI врати неочекуван формат."

    except Exception as e:
        print(f"[llm] Nepoznata greska: {e}")
        return f"Непозната грешка: {str(e)}"
