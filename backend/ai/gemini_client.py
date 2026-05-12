"""
Gemini клиент - функција што испраќа барање до Google Gemini API
и враќа текстуален одговор.

Како функционира:
1. Зема API клуч од .env (GEMINI_API_KEY)
2. Праќа HTTP POST до Gemini со прашањето и системскиот prompt
3. Го извлекува текстот од JSON одговорот
4. Враќа го како string

Се користи од: routers/ai_chat.py
"""

import os
import requests
from dotenv import load_dotenv

from ai.prompts import CHAT_SYSTEM_PROMPT


load_dotenv()


# Gemini 2.5 Flash има НИЗОК rate limit на free tier (~10 RPM).
# 2.0 Flash има подобар лимит за free tier (~15 RPM, 1500 RPD).
# Може да се промени со GEMINI_MODEL во .env (на пр. "gemini-2.5-flash" ако имаш платена сметка).
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    f"models/{GEMINI_MODEL}:generateContent"
)


def ask_gemini(prashanje: str, system_prompt: str = CHAT_SYSTEM_PROMPT) -> str:
    """
    Праќа прашање до Gemini и враќа одговор како string.

    Параметри:
        prashanje      - текст од корисникот (на пр. „Кога е работно време?")
        system_prompt  - упатство за AI-то (default = chat prompt)

    Враќа:
        Текстуален одговор од Gemini, или порака за грешка.
    """

    # Прифаќаме и GEMINI_API_KEY и GOOGLE_API_KEY (двете се валидни имиња)
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return "Не е поставен GEMINI_API_KEY (или GOOGLE_API_KEY) во backend/.env фајлот."

    prashanje = (prashanje or "").strip()
    if not prashanje:
        return "Те молам внеси прашање."

    # Тело на барањето (формат што Gemini го очекува)
    payload = {
        "system_instruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prashanje}]
            }
        ],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 500
        }
    }

    try:
        response = requests.post(
            f"{GEMINI_URL}?key={api_key}",
            json=payload,
            timeout=30
        )

        # Посебно обработи 429 (Too Many Requests) - rate limit
        if response.status_code == 429:
            print(f"[gemini_client] RATE LIMIT (429) на модел {GEMINI_MODEL}")
            return (
                "Привремено сум преоптоварен со прашања. Те молам почекај "
                "30-60 секунди и пробај пак."
            )

        response.raise_for_status()
        result = response.json()

        # Gemini структура: candidates -> [0] -> content -> parts -> [0] -> text
        return result["candidates"][0]["content"]["parts"][0]["text"].strip()

    except requests.exceptions.Timeout:
        return "Gemini не одговори навреме. Обиди се повторно."

    except requests.exceptions.RequestException as e:
        print(f"[gemini_client] HTTP greshka: {e}")
        return "Привремена грешка при поврзување. Пробај пак за неколку секунди."

    except (KeyError, IndexError):
        return "Gemini врати неочекуван формат."

    except Exception as e:
        return f"Непозната грешка: {str(e)}"
