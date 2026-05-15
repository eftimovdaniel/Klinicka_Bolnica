"""Заеднички текстови за AI prompts."""

from datetime import date

_DAYS_MK = [
    "понеделник",
    "вторник",
    "среда",
    "четврток",
    "петок",
    "сабота",
    "недела",
]


def today_prompt_line() -> str:
    d = date.today()
    return f"Денес: {d.isoformat()} ({_DAYS_MK[d.weekday()]})"


def format_doctor_list(lekari: list[dict]) -> str:
    lines: list[str] = []
    for doc in lekari:
        spec = (doc.get("specialty") or doc.get("specijalnost") or "Општа пракса") or "Општа пракса"
        lines.append(
            f"ID {doc.get('doctor_ID')}: Д-р {doc.get('name', '')} {doc.get('surname', '')} - {spec}".strip()
        )
    return "\n".join(lines)
