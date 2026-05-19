"""
Заеднички помошници за Groq — intent, JSON извлекување.
Без keyword/локални fallback патеки (AI-only).
"""

from __future__ import annotations

from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import GROQ_OFFLINE_MSG, ask_ai, groq_e_isklucen


def groq_zadolzhitelen() -> str | None:
    """None ако Groq е достапен; инаку порака за корисник."""
    if groq_e_isklucen():
        return GROQ_OFFLINE_MSG
    return None


def izvlechi_json_so_ai(
    prasanje: str,
    system_prompt: str,
    *,
    log_tag: str = "groq_json",
    user_prefix: str = "",
) -> dict:
    """Groq → JSON dict; при грешка/429 → {"_error": "..."}."""
    if msg := groq_zadolzhitelen():
        return {"_error": msg}
    user = f"{user_prefix}{prasanje}".strip() if user_prefix else prasanje
    raw = ask_ai(user, system_prompt=system_prompt)
    print(f"[{log_tag}] AI raw: {raw!r}")
    return parse_ai_json(raw, log_tag=log_tag)


def detektiraj_intent_ai_only(prasanje: str) -> str:
    """Само Groq класификација на интент (без keyword листи)."""
    from ai._kernel.ai_intent_detector import detektiraj_intent_so_ai

    if not (prasanje or "").strip():
        return "general"
    if msg := groq_zadolzhitelen():
        print(f"[groq_helpers] intent blocked: {msg}")
        return "general"
    return detektiraj_intent_so_ai(prasanje)
