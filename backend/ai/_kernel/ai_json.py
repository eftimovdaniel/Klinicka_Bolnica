"""Парсирање на JSON одговори од Groq — едно место, исто однесување."""

import json
import re

_GROQ_ERROR_MARKERS = (
    "Привремено сум",
    "Привремена грешка",
    "Не е поставен GROQ_API_KEY",
    "Невалиден API клуч",
    "AI не одговори",
    "AI врати неочекуван",
)


def is_ai_error_response(text: str | None) -> bool:
    if not text or not str(text).strip():
        return True
    return any(marker in text for marker in _GROQ_ERROR_MARKERS)


def parse_ai_json(odgovor: str, *, log_tag: str = "") -> dict:
    """
    Исчистува markdown fences, парсира JSON dict.
    При Groq грешка → {"_error": "..."}; при неуспех → {}.
    """
    if is_ai_error_response(odgovor):
        return {"_error": (odgovor or "").strip()}

    cist = (odgovor or "").strip()
    cist = re.sub(r"^```(?:json)?\s*", "", cist, flags=re.IGNORECASE)
    cist = re.sub(r"\s*```\s*$", "", cist).strip()

    try:
        data = json.loads(cist)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        if log_tag:
            print(f"[{log_tag}] неуспешен JSON: {cist[:160]!r}")
        return {}
