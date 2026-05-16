"""
Пренесување на термин - UPDATE на датум/време.

Како работи:
1. Пациент пишува: "Префрли го утрешниот преглед за петок 11:00"
2. AI извлекува: стар датум (опционо), нов датум, ново време
3. Бараме активен термин на пациентот за стариот датум
4. Проверуваме слободност на новиот термин
5. UPDATE
"""

from ai._kernel.prompt_loader import load_prompt
import json
import re
from datetime import datetime, date, time
from database import get_connection
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import ask_ai


def izvlechi_prenesi(prashanje: str) -> dict:
    """Извлекува стар/нов датум и време за пренос на термин."""
    denes = date.today().strftime("%Y-%m-%d")
    denes_den = ["понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"][date.today().weekday()]

    full_prompt = f'Денес: {denes} ({denes_den})\n\nКорисник: „{prashanje}"\n\nИзвлечи податоци.'

    odgovor = ask_ai(full_prompt, system_prompt=load_prompt("prenesi_extract"))
    podatoci = parse_ai_json(odgovor, log_tag="prenesi_termin")
    return {
        "star_datum": podatoci.get("star_datum"),
        "nov_datum": podatoci.get("nov_datum"),
        "novo_vreme": podatoci.get("novo_vreme"),
    }


def najdi_aktivni_termini(pacient_email: str, datum: str | None) -> list[dict]:
    """Активни термини на пациентот, опционално филтрирани по датум."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        query = """
            SELECT termin_ID, doctor_ID, datum_pregled, vreme_pregled,
                   ime_lekar, specijalnost_termin
            FROM Termin_pregled
            WHERE LOWER(TRIM(email_pacient)) = LOWER(TRIM(%s))
              AND status_pregled = 'закажан'
              AND datum_pregled >= CURDATE()
        """
        params = [pacient_email]

        if datum:
            query += " AND datum_pregled = %s"
            params.append(datum)

        query += " ORDER BY datum_pregled, vreme_pregled"

        cur.execute(query, params)
        rezultati = cur.fetchall()
        cur.close()
        return rezultati
    except Exception as e:
        print(f"[prenesi_termin] najdi greshka: {e}")
        return []
    finally:
        if conn:
            conn.close()


def proveri_slobodno(doctor_id: int, datum_str: str, vreme_str: str, exclude_termin_id: int) -> bool:
    """Дали новиот термин е слободен (без да го броиме истиот термин)."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT termin_ID FROM Termin_pregled
            WHERE doctor_ID = %s
              AND DATE(datum_pregled) = %s
              AND TIME(vreme_pregled) = %s
              AND status_pregled = 'закажан'
              AND termin_ID != %s
        """, (doctor_id, datum_str, vreme_str, exclude_termin_id))
        return cur.fetchone() is None
    except Exception as e:
        print(f"[prenesi_termin] proveri greshka: {e}")
        return False
    finally:
        if conn:
            conn.close()


def izvrsi_prenesuvanje(termin_id: int, nov_datum: str, novo_vreme: str) -> bool:
    """UPDATE на датум/време."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE Termin_pregled
            SET datum_pregled = %s, vreme_pregled = %s
            WHERE termin_ID = %s
        """, (nov_datum, novo_vreme, termin_id))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"[prenesi_termin] update greshka: {e}")
        return False
    finally:
        if conn:
            conn.close()


def format_vreme(v) -> str:
    if v is None:
        return "—"
    if hasattr(v, "strftime"):
        return v.strftime("%H:%M")
    if hasattr(v, "total_seconds"):
        s = int(v.total_seconds())
        return f"{s // 3600:02d}:{(s % 3600) // 60:02d}"
    return str(v)[:5]


def odgovori_za_prenesuvanje(prashanje: str, pacient: dict | None) -> str:
    """Главна точка."""
    if not pacient or not pacient.get("email"):
        return 'За да префрлиш термин, прво најави се како пациент.'

    izvleceno = izvlechi_prenesi(prashanje)
    nov_datum = izvleceno.get("nov_datum")
    novo_vreme = izvleceno.get("novo_vreme")
    star_datum = izvleceno.get("star_datum")

    if not nov_datum or not novo_vreme:
        return (
            'Не разбрав на кога да го префрлам. Напиши, на пример:\n'
            '„Префрли го утрешниот за петок 11:00"'
        )

    # Валидација на нов датум
    try:
        nov_dt = datetime.strptime(nov_datum, "%Y-%m-%d").date()
    except ValueError:
        return "Неважечки формат на нов датум."

    if nov_dt < date.today():
        return "Не може да префрлиш термин во минатото."
    if nov_dt.weekday() >= 5:
        return "Не се закажуваат прегледи во сабота/недела."

    # Валидација на ново време
    try:
        novo_v_obj = datetime.strptime(novo_vreme, "%H:%M").time()
    except ValueError:
        return "Неважечки формат на време."
    if novo_v_obj < time(8, 0) or novo_v_obj > time(15, 30):
        return "Работно време е 08:00 - 15:30."

    # Најди термин за пренесување
    termini = najdi_aktivni_termini(pacient["email"], star_datum)

    if not termini:
        return 'Не најдов активен термин за пренесување. Прашај "Кои се моите термини?"'

    DENOVI = ["Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"]

    if len(termini) > 1:
        delovi = ["Имаш повеќе термини. Кој сакаш да го префрлиш?", ""]
        for t in termini:
            d = t["datum_pregled"]
            v = format_vreme(t["vreme_pregled"])
            delovi.append(f"- {DENOVI[d.weekday()]} {d.strftime('%d.%m.%Y')} во {v} кај Д-р {t['ime_lekar']}")
        delovi.append("")
        delovi.append('Биди поточен: "Префрли го прегледот на [стар датум] за [нов датум] [време]"')
        return "\n".join(delovi)

    # Точно еден
    t = termini[0]
    if not proveri_slobodno(t["doctor_ID"], nov_datum, novo_vreme, t["termin_ID"]):
        return "Тој нов термин е веќе зафатен. Избери друго време."

    if not izvrsi_prenesuvanje(t["termin_ID"], nov_datum, novo_vreme):
        return "Не успеа пренесувањето."

    return (
        f"Терминот е пренесен!\n\n"
        f"Лекар: Д-р {t['ime_lekar']}\n"
        f"Нов датум: {DENOVI[nov_dt.weekday()]}, {nov_dt.strftime('%d.%m.%Y')}\n"
        f"Ново време: {novo_vreme}"
    )
