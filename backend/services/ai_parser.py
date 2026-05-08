import json
import re
from typing import Any, Dict, Optional

from services.google_ai_client import chat_safe
from services.prompt_loader import get_section


def _extract_first_json_block(text: str) -> Optional[dict]:
    s = str(text or "").strip()
    if not s:
        return None
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", s)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def parse_prompt(prompt_text: str) -> Optional[Dict[str, Any]]:
    """
    Google AI Studio + промпти од data/ai_system_prompts.json (appointment_parse.system).
    Враќа dict: intent, doctor_name, date, time, note, workdays (int, опционално).
    """
    system = get_section("appointment_parse", "system")
    if not system:
        system = (
            "Return ONLY JSON with keys: intent, doctor_name, date, time, note, workdays. "
            "intent: availability|book|availability_multi|''. date YYYY-MM-DD. time HH:MM."
        )
    content = chat_safe(system, f"Кориснички текст:\n{prompt_text}\n\nВрати само JSON објект.")
    if not content:
        return None
    parsed = _extract_first_json_block(content)
    if not parsed:
        return None
    wd = parsed.get("workdays", 5)
    try:
        workdays = int(wd)
    except (TypeError, ValueError):
        workdays = 5
    workdays = max(1, min(14, workdays))
    return {
        "intent": str(parsed.get("intent", "")).strip(),
        "doctor_name": str(parsed.get("doctor_name", "")).strip(),
        "date": str(parsed.get("date", "")).strip(),
        "time": str(parsed.get("time", "")).strip(),
        "note": str(parsed.get("note", "")).strip(),
        "workdays": workdays,
    }


def parse_news(source_excerpts: str, director_note: str) -> Optional[Dict[str, str]]:
    """Google AI Studio → JSON {naslov, sodrzina} за новост."""
    system = get_section("director_news_from_sources", "system")
    if not system:
        system = 'Врати само JSON: {"naslov":"...","sodrzina":"..."} на македонски.'
    user = (
        "Извори (извлечен текст од веб-страници):\n"
        f"{source_excerpts}\n\n"
        f"Порака од директорот (контекст):\n{director_note}\n"
    )
    content = chat_safe(system, user)
    if not content:
        return None
    parsed = _extract_first_json_block(content)
    if not parsed:
        return None
    naslov = str(parsed.get("naslov", "")).strip()
    sodrzina = str(parsed.get("sodrzina", "")).strip()
    if not naslov or not sodrzina:
        return None
    return {"naslov": naslov, "sodrzina": sodrzina}
