"""
Groq форматирање на одговори од структурирани факти (база/JSON).
Без шаблон fallback — само AI или јасна Groq грешка.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time
from typing import Any

from ai._kernel.groq_client import GROQ_OFFLINE_MSG, ask_ai, groq_e_isklucen
from ai._kernel.prompt_loader import load_prompt

_GRESKA_POCETOCI = (
    "Не е поставен GROQ_API_KEY",
    "Те молам внеси прашање",
    "Привремено сум преоптоварен",
    "Невалиден API клуч",
    "AI не одговори навреме",
    "Привремена грешка при поврзување",
    "AI врати неочекуван формат",
    "Непозната грешка:",
)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, time):
        return obj.strftime("%H:%M")
    return str(obj)


def _e_groq_greska(tekst: str) -> bool:
    t = (tekst or "").strip()
    if not t:
        return True
    return any(t.startswith(p) for p in _GRESKA_POCETOCI)


def formatiraj_odgovor_so_ai(
    tip: str,
    podatoci: dict[str, Any],
    sablon_fallback: str,
    prasanje: str | None = None,
) -> str:
    """
    tip: info_lekar | zakazi_potvrda | lekari_oddel | uslugi | novosti_rezime
    podatoci: структурирани факти од handler
    sablon_fallback: задржан за компатибилност со повици; не се користи како fallback.
    """
    _ = sablon_fallback  # API compat — AI-only режим

    if groq_e_isklucen():
        return GROQ_OFFLINE_MSG

    try:
        system = load_prompt("formatiraj_odgovor")
    except KeyError:
        return "Недостасува prompt formatiraj_odgovor."

    facts_json = json.dumps(podatoci, ensure_ascii=False, indent=2, default=_json_default)
    user_parts = [
        f"Тип одговор: {tip}",
    ]
    if prasanje and prasanje.strip():
        user_parts.append(f'Прашање на корисникот: „{prasanje.strip()}"')
    user_parts.extend(
        [
            "",
            "Факти (користи ги точно — не додавај податоци што ги нема):",
            facts_json,
        ]
    )
    if podatoci.get("sledna_akcija"):
        user_parts.append(f"\nСледна акција (задржи ја смислата): {podatoci['sledna_akcija']}")

    ai = ask_ai("\n".join(user_parts), system_prompt=system)
    if _e_groq_greska(ai):
        print(f"[odgovor_formatter] AI fail tip={tip!r}")
        return (ai or "").strip() or GROQ_OFFLINE_MSG
    ai = ai.strip()
    if not ai:
        return GROQ_OFFLINE_MSG
    return ai
