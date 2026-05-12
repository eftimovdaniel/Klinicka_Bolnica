"""
Постави потсетник за термин.

Како работи:
1. Пациент пишува: "Потсети ме 1 ден претходно за прегледот"
   или "Потсети ме за утрешниот преглед"
2. AI извлекува: offset (колку време пред) + кој термин
3. INSERT во Potsetnici со пресметано vreme_za_potsetuvanje

ВАЖНО: Бара табела Potsetnici (види backend/migrations/add_potsetnici.sql)
ЗАБЕЛЕШКА: Не се испраќа автоматски - тоа бара scheduler. Засега само се
зачувува во базата за да биде достапен на dashboard-от на пациентот.
"""

import json
import re
from datetime import datetime, date, timedelta
from database import get_connection
from ai.gemini_client import ask_gemini


POTSETNIK_EXTRACT_PROMPT = """
Ти си систем што извлекува податоци за потсетник за медицински термин.
Од прашањето извлечи:
- offset_minuti: колку минути пред терминот да биде потсетникот
- datum: датум на терминот (YYYY-MM-DD) или null

ПРАВИЛА за offset:
- "1 ден претходно" → 1440 (60*24)
- "2 дена претходно" → 2880
- "12 часа" → 720
- "1 час" → 60
- "30 минути" → 30
- ако не е специфицирано → 60 (стандардно 1 час)

ПРАВИЛА за датум:
- "утре" → денес+1
- "среда" → следната среда
- "прегледот" без датум → null (ќе земеме најблискиот термин)

Врати САМО JSON: {"offset_minuti": число, "datum": "YYYY-MM-DD"_или_null}
""".strip()


def izvlechi_potsetnik(prashanje: str) -> dict:
    """Користи Gemini за извлекување."""
    denes = date.today().strftime("%Y-%m-%d")
    full_prompt = f'Денес: {denes}\n\nКорисник: „{prashanje}"\n\nИзвлечи податоци.'

    odgovor = ask_gemini(full_prompt, system_prompt=POTSETNIK_EXTRACT_PROMPT)
    cist = re.sub(r"^```(?:json)?\s*", "", odgovor.strip())
    cist = re.sub(r"\s*```$", "", cist)

    try:
        podatoci = json.loads(cist)
        return {
            "offset_minuti": int(podatoci.get("offset_minuti", 60) or 60),
            "datum": podatoci.get("datum"),
        }
    except (json.JSONDecodeError, ValueError, TypeError):
        return {"offset_minuti": 60, "datum": None}


def najdi_termin_za_potsetnik(pacient_email: str, datum: str | None) -> dict | None:
    """Активен термин на пациентот, опционално по датум, инаку најблискиот."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        query = """
            SELECT termin_ID, datum_pregled, vreme_pregled,
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

        query += " ORDER BY datum_pregled, vreme_pregled LIMIT 1"

        cur.execute(query, params)
        rezultat = cur.fetchone()
        cur.close()
        return rezultat
    except Exception as e:
        print(f"[postavi_potsetnik] greshka: {e}")
        return None
    finally:
        if conn:
            conn.close()


def vmetni_potsetnik(termin_id: int, pacient_email: str, vreme_potsetuvanje: datetime, poraka: str) -> bool:
    """INSERT во Potsetnici."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO Potsetnici (termin_ID, pacient_email, vreme_za_potsetuvanje, poraka)
            VALUES (%s, %s, %s, %s)
        """, (termin_id, pacient_email, vreme_potsetuvanje, poraka))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"[postavi_potsetnik] insert greshka: {e}")
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


def format_offset(minuti: int) -> str:
    """Претвора минути во читлив текст."""
    if minuti >= 1440:
        denovi = minuti // 1440
        return f"{denovi} ден" + ("а" if denovi > 1 else "")
    if minuti >= 60:
        casovi = minuti // 60
        return f"{casovi} час" + ("а" if casovi > 1 else "")
    return f"{minuti} минути"


def odgovori_za_potsetnik(prashanje: str, pacient: dict | None) -> str:
    """Главна точка."""
    if not pacient or not pacient.get("email"):
        return 'За да поставиш потсетник, прво најави се како пациент.'

    izvleceno = izvlechi_potsetnik(prashanje)
    offset_min = izvleceno["offset_minuti"]
    datum_str = izvleceno.get("datum")

    termin = najdi_termin_za_potsetnik(pacient["email"], datum_str)

    if not termin:
        return 'Немаш закажани активни термини за кои можам да поставам потсетник.'

    # Пресметај кога да биде потсетникот
    datum_pregled = termin["datum_pregled"]
    vreme_pregled = termin["vreme_pregled"]

    # vreme_pregled може да биде timedelta
    if isinstance(vreme_pregled, timedelta):
        s = int(vreme_pregled.total_seconds())
        h = s // 3600
        m = (s % 3600) // 60
        from datetime import time as dt_time
        vreme_pregled = dt_time(h, m)

    moment_na_pregled = datetime.combine(datum_pregled, vreme_pregled)
    moment_na_potsetnik = moment_na_pregled - timedelta(minutes=offset_min)

    if moment_na_potsetnik <= datetime.now():
        return (
            'Не можам да поставам потсетник во минатото. '
            'Терминот е премногу близу. Избери помал интервал.'
        )

    DENOVI = ["Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"]
    poraka = (
        f"Потсетник: имаш преглед {DENOVI[datum_pregled.weekday()]} "
        f"{datum_pregled.strftime('%d.%m.%Y')} во {format_vreme(vreme_pregled)} "
        f"кај Д-р {termin['ime_lekar']}."
    )

    if not vmetni_potsetnik(termin["termin_ID"], pacient["email"], moment_na_potsetnik, poraka):
        return "Не успеа поставувањето на потсетник."

    return (
        f"Потсетникот е поставен!\n\n"
        f"Термин: {DENOVI[datum_pregled.weekday()]}, {datum_pregled.strftime('%d.%m.%Y')} во {format_vreme(vreme_pregled)}\n"
        f"Лекар: Д-р {termin['ime_lekar']}\n"
        f"Кога: {format_offset(offset_min)} пред терминот\n"
        f"Точно време на потсетник: {moment_na_potsetnik.strftime('%d.%m.%Y %H:%M')}"
    )
