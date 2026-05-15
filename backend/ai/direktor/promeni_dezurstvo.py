"""
Менување на дежурство на лекар - само за директорот.

Примери:
- „Префрли го д-р Петров за петок"             → UPDATE Dezurstva (најден иден shift)
- „Премести го дежурството на Иванов за 25.05"
- „Премести го дежурството на Александра за утре 09:00-15:00"

Логика:
1. AI извлекува: име на лекар, нов датум, ново време (опционално).
2. Бараме НАЈРАН ИДЕН дежурство на тој лекар.
3. UPDATE на тоа дежурство со новиот датум (и евентуално време).
"""

import re
from datetime import date, datetime

from database import get_connection
from ai._kernel.auth import require_direktor
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import ask_ai


PROMPT = """
Ти си систем што извлекува податоци за пренасочување на дежурство.

Корисникот (директор) сака да го промени дежурството на лекар. Врати САМО JSON:
{"lekar": "Име Презиме" | null, "nov_datum": "YYYY-MM-DD" | null,
 "novo_vreme_od": "HH:MM" | null, "novo_vreme_do": "HH:MM" | null}

Правила за датум:
- „денес" = денешен датум
- „утре" = денес + 1
- „понеделник", „вторник", „среда", „четврток", „петок", „сабота", „недела" = следниот таков ден
- „15.05" или „15ти мај" = во оваа година во формат YYYY-MM-DD

Правила за време:
- „09:00", „09 часот", „наутро" = 09:00
- „попладне" = 14:00
- ако корисникот вели само еден час → "novo_vreme_od" = тој час, "novo_vreme_do" = null

Лекар: само име+презиме, без титула („д-р", „др"). Ако нема → null.

БЕЗ markdown, БЕЗ објаснувања. Само JSON.
""".strip()


def _izvlechi(prashanje: str) -> dict:
    denes = date.today().strftime("%Y-%m-%d")
    denes_den = ["понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"][
        date.today().weekday()
    ]
    full = f'Денес: {denes} ({denes_den})\n\nПрашање: „{prashanje}"\nВрати JSON.'
    odgovor = ask_ai(full, system_prompt=PROMPT)
    print(f"[promeni_dezurstvo] AI: {odgovor!r}")
    return parse_ai_json(odgovor, log_tag="promeni_dezurstvo")


def _najdi_lekar(ime_prezime: str) -> dict | None:
    """Барај лекар по име/презиме (case-insensitive, partial match)."""
    if not ime_prezime:
        return None
    delovi = [d for d in ime_prezime.strip().split() if d]
    if not delovi:
        return None

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    # Прво проба со точно име + презиме
    if len(delovi) >= 2:
        cur.execute(
            "SELECT doctor_ID, name, surname, specialty FROM Doctors"
            " WHERE LOWER(name) LIKE %s AND LOWER(surname) LIKE %s",
            (f"%{delovi[0].lower()}%", f"%{delovi[-1].lower()}%"),
        )
        row = cur.fetchone()
        if row:
            cur.close()
            conn.close()
            return row

    # Потоа проба со само едно име (било име, било презиме)
    cur.execute(
        "SELECT doctor_ID, name, surname, specialty FROM Doctors"
        " WHERE LOWER(name) LIKE %s OR LOWER(surname) LIKE %s",
        (f"%{delovi[0].lower()}%", f"%{delovi[-1].lower()}%"),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if len(rows) == 1:
        return rows[0]
    return None  # 0 или повеќе од 1 → амбигвитет


def _najdi_idno_dezurstvo(doctor_id: int) -> dict | None:
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT dezurstvo_ID, datum, oddel, vreme_od, vreme_do FROM Dezurstva"
        " WHERE doctor_ID = %s AND datum >= CURDATE()"
        " ORDER BY datum, vreme_od LIMIT 1",
        (doctor_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def _format_datum(d) -> str:
    if hasattr(d, "strftime"):
        return d.strftime("%d.%m.%Y")
    return str(d)


def _format_vreme(t) -> str:
    if hasattr(t, "strftime"):
        return t.strftime("%H:%M")
    # MySQL timedelta за TIME
    s = str(t)
    return s[:5] if len(s) >= 5 else s


def odgovori_za_dezurstvo(prashanje: str, lekar: dict | None) -> str:
    """Главна точка - повикана од router-от."""
    if err := require_direktor(lekar):
        return err

    podatoci = _izvlechi(prashanje)
    if podatoci.get("_error"):
        return podatoci["_error"]

    ime = (podatoci.get("lekar") or "").strip()
    nov_datum_str = podatoci.get("nov_datum")
    novo_od = podatoci.get("novo_vreme_od")
    novo_do = podatoci.get("novo_vreme_do")

    if not ime or not nov_datum_str:
        return (
            'За промена на дежурство ми треба: лекар + нов датум.\n'
            'Пример: „Премести го дежурството на д-р Петров за петок"\n'
            'Или: „Префрли го д-р Иванов за 25.05 09:00-15:00"'
        )

    try:
        nov_datum = datetime.strptime(nov_datum_str, "%Y-%m-%d").date()
    except Exception:
        return f'Неважечки датум: „{nov_datum_str}". Пример: „за петок" или „25.05".'

    if nov_datum < date.today():
        return "Не можам да го преместам дежурството во минатото."

    found = _najdi_lekar(ime)
    if not found:
        return f'Не најдов лекар „{ime}". Провери го името/презимето.'

    dez = _najdi_idno_dezurstvo(found["doctor_ID"])
    if not dez:
        return f'Д-р {found["name"]} {found["surname"]} нема идни дежурства.'

    # Изгради UPDATE
    sets = ["datum = %s"]
    params: list = [nov_datum]
    if novo_od:
        try:
            datetime.strptime(novo_od, "%H:%M")
            sets.append("vreme_od = %s")
            params.append(novo_od)
        except Exception:
            pass
    if novo_do:
        try:
            datetime.strptime(novo_do, "%H:%M")
            sets.append("vreme_do = %s")
            params.append(novo_do)
        except Exception:
            pass
    params.append(dez["dezurstvo_ID"])

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        f"UPDATE Dezurstva SET {', '.join(sets)} WHERE dezurstvo_ID = %s",
        params,
    )
    conn.commit()
    cur.close()
    conn.close()

    return (
        f"Дежурството е променето.\n\n"
        f"Лекар: д-р {found['name']} {found['surname']}\n"
        f"Оддел: {dez['oddel']}\n"
        f"Стар датум: {_format_datum(dez['datum'])} ({_format_vreme(dez['vreme_od'])}–{_format_vreme(dez['vreme_do'])})\n"
        f"Нов датум: {nov_datum.strftime('%d.%m.%Y')}"
        + (f" ({novo_od}" + (f"–{novo_do}" if novo_do else "") + ")" if novo_od else "")
    )
