import os
import requests
from dotenv import load_dotenv
from ai._kernel.prompts import CHAT_SYSTEM_PROMPT
load_dotenv()
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Стандарден модел - llama-3.3-70b-versatile е најмоќен од бесплатните на Groq.
# Може да се менува со GROQ_MODEL во .env.
# Опции:
#   - llama-3.3-70b-versatile (стандард, најмоќен)
#   - llama-3.1-8b-instant   (побрз, помалку точен)
#   - mixtral-8x7b-32768     (поголем контекст)
#   - gemma2-9b-it           (Google open модел)
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
MAX_USER_CHARS = 8000


def ask_ai(prasanje: str, system_prompt: str = CHAT_SYSTEM_PROMPT) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return "Не е поставен GROQ_API_KEY во backend/.env фајлот."
    prasanje = (prasanje or "").strip()
    if not prasanje:
        return "Те молам внеси прашање."
    if len(prasanje) > MAX_USER_CHARS:
        prasanje = prasanje[:MAX_USER_CHARS]
    # Groq користи OpenAI-compatible API
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prasanje},
        ],
        "temperature": 0.5,
        "max_tokens": 800,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(
            GROQ_URL,
            json=payload,
            headers=headers,
            timeout=30,
        )

        if response.status_code == 429:
            print(f"[groq_client] RATE LIMIT (429) на модел {GROQ_MODEL}")
            return (
                "Привремено сум преоптоварен со прашања. Те молам почекај "
                "30-60 секунди и пробај пак."
            )

        if response.status_code == 401:
            print(f"[groq_client] AUTH (401) - проверете го GROQ_API_KEY")
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
