"""
Историја на пациент кај овој лекар.

Достапно за СЕКОЈ најавен лекар (не само директор).

Примери:
- „Колку пати беше Петар Иванов кај мене?"
- „Историја на пациент Иванов"
- „Кога беше последен пат пациентот Петар Иванов?"
"""

import json
import re

from database import get_connection
from ai.groq_client import ask_ai


PROMPT = """
Ти си систем што извлекува име на пациент од прашање.

Корисникот е лекар и сака историја/преглед на свој пациент. Врати САМО JSON:
{"ime_pacient": "Име Презиме" | null}

Правила:
- ако има јасно име+презиме → "ime_pacient"="Име Презиме"
- ако има само едно име → "ime_pacient"="Име"
- ако нема воопшто име → null

БЕЗ markdown, БЕЗ објаснувања. Само JSON.
""".strip()


def _izvlechi(prashanje: str) -> dict:
    odgovor = ask_ai(f"Прашање: „{prashanje}\"", system_prompt=PROMPT)
    print(f"[istorija] AI: {odgovor!r}")

    if "Привремено сум" in odgovor or "Привремена грешка" in odgovor:
        return {"_error": odgovor}

    cist = re.sub(r"^```(?:json)?|```$", "", odgovor.strip()).strip()
    try:
        return json.loads(cist)
    except Exception:
        return {}


def _fmt_datum(d) -> str:
    if hasattr(d, "strftime"):
        return d.strftime("%d.%m.%Y")
    return str(d)


def _fmt_vreme(t) -> str:
    if hasattr(t, "strftime"):
        return t.strftime("%H:%M")
    return str(t)[:5]


def odgovori_za_istorija(prashanje: str, lekar: dict | None) -> str:
    """Главна точка - повикана од router-от."""
    if not lekar or not lekar.get("doctor_ID"):
        return "Мораш прво да се најавиш како лекар."

    doctor_id = lekar["doctor_ID"]

    podatoci = _izvlechi(prashanje)
    if podatoci.get("_error"):
        return podatoci["_error"]

    ime = (podatoci.get("ime_pacient") or "").strip()
    if not ime:
        return (
            'За да најдам историја ми треба име на пациент.\n'
            'Пример: „Колку пати беше Петар Иванов кај мене?"'
        )

    delovi = [d for d in ime.split() if d]
    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    sql = (
        "SELECT termin_ID, ime_pacient, datum_pregled, vreme_pregled,"
        "       status_pregled, dijagnoza, terapija"
        " FROM Termin_pregled"
        " WHERE doctor_ID = %s"
    )
    params: list = [doctor_id]

    if len(delovi) >= 2:
        sql += " AND LOWER(ime_pacient) LIKE %s AND LOWER(ime_pacient) LIKE %s"
        params.extend([f"%{delovi[0].lower()}%", f"%{delovi[-1].lower()}%"])
    else:
        sql += " AND LOWER(ime_pacient) LIKE %s"
        params.append(f"%{delovi[0].lower()}%")

    sql += " ORDER BY datum_pregled DESC, vreme_pregled DESC"
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        return f'Не најдов прегледи кај тебе за пациент „{ime}".'

    # Број по статус
    zavrseni = sum(1 for r in rows if r["status_pregled"] == "завршен")
    zakazani = sum(1 for r in rows if r["status_pregled"] == "закажан")
    otkazani = sum(1 for r in rows if r["status_pregled"] == "откажан")

    linii = [
        f'Историја на „{ime}" кај тебе (вкупно {len(rows)} прегледи):',
        f"• Завршени: {zavrseni}",
        f"• Закажани: {zakazani}",
        f"• Откажани: {otkazani}",
        "",
        "Последни прегледи:",
    ]
    for r in rows[:5]:
        linija = (
            f"• {_fmt_datum(r['datum_pregled'])} {_fmt_vreme(r['vreme_pregled'])}"
            f" — {r['status_pregled']} (ID {r['termin_ID']})"
        )
        if r.get("dijagnoza"):
            linija += f"\n  Дијагноза: {r['dijagnoza']}"
        linii.append(linija)

    return "\n".join(linii)
