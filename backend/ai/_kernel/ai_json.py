"""Парсирање на JSON одговори од Groq — едно место, исто однесување."""

import json
import re

# Markeri za prepoznavanje na greshki od Groq API (a ne validen AI odgovor)
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
    # Prazen odgovor isto se smeta za greshka
    return any(marker in text for marker in _GROQ_ERROR_MARKERS)
    # Proverka dali odgovorot sodrzhi nekoj od poznatite markeri za greshka


def parse_ai_json(odgovor: str, *, log_tag: str = "") -> dict:
    """
    Исчистува markdown fences, парсира JSON dict.
    При Groq грешка → {"_error": "..."}; при неуспех → {}.
    """
    if is_ai_error_response(odgovor):
        return {"_error": (odgovor or "").strip()}
    # Ako e greshka od AI - vrakja special dict so _error kluc

    cist = (odgovor or "").strip()
    cist = re.sub(r"^```(?:json)?\s*", "", cist, flags=re.IGNORECASE)
    # Otstranuva pochetna markdown fence ```json ili ```
    cist = re.sub(r"\s*```\s*$", "", cist).strip()
    # Otstranuva krajna markdown fence ```

    try:
        data = json.loads(cist)
        return data if isinstance(data, dict) else {}
        # Vrakja prazen dict ako toa ne e dict (na pr. lista)
    except json.JSONDecodeError:
        if log_tag:
            print(f"[{log_tag}] неуспешен JSON: {cist[:160]!r}")
            # Log za debug - prvite 160 znaci od greshniot JSON
        return {}
        # Prazen dict pri greshka za da ne se rusi povikuvachot
