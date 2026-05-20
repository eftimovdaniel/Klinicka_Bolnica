"""Заеднички текстови за AI prompts."""

from datetime import date

# Imiata na denovite po reden broj (0=ponedelnik, 6=nedela)
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
    # Zema deneshen datum
    return f"Денес: {d.isoformat()} ({_DAYS_MK[d.weekday()]})"
    # Vrakja red za prompt: "Денес: 2026-05-20 (среда)" - AI da znae koj e denes


def format_doctor_list(lekari: list[dict]) -> str:
    lines: list[str] = []
    for doc in lekari:
        spec = (doc.get("specialty") or doc.get("specijalnost") or "Општа пракса") or "Општа пракса"
        # Dvoen fallback: prvo proba "specialty", pa "specijalnost", pa default
        lines.append(
            f"ID {doc.get('doctor_ID')}: Д-р {doc.get('name', '')} {doc.get('surname', '')} - {spec}".strip()
        )
        # Format: "ID 5: Д-р Marko Petrov - Kardiologija"
    return "\n".join(lines)
    # Edna lekar po linija - format koj AI go ochekuva vo promptot
