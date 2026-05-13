"""
Откажување термин преку AI асистент.

Како работи:
1. Пациент пишува: "Откажи го утрешниот преглед" или "Откажи го прегледот кај Петров"
2. AI ги препознава: датум (опционално) + лекар (опционално)
3. Бараме во базата термини на тој пациент што одговараат
4. Ако има точно еден → UPDATE status_pregled = 'откажан'
5. Ако има повеќе → прашаме кој
6. Ако нема → грешка

Бара логиран пациент.
"""

import json
import re
from datetime import datetime, date
from database import get_connection
from ai.groq_client import ask_ai
from ai.slobodni_termini import zimi_site_lekari


# Prompt за извлекување на термини за откажување
OTKAZI_EXTRACT_PROMPT = """
Ти си систем што извлекува податоци за откажување на медицински термин.
Од прашањето извлечи:
- doctor_id: ID на лекарот (или null)
- datum: датум во формат YYYY-MM-DD (или null)

ПРАВИЛА за датум:
- "денес" → денешен датум
- "утре" → денешен + 1
- "вчера" → денешен - 1
- "понеделник", "среда"... → следниот таков ден
- "15.05" → во оваа година
- Ако не е специфицирано → null

Врати САМО JSON без објаснувања: {"doctor_id": число_или_null, "datum": "YYYY-MM-DD"_или_null}
""".strip()


def izvlechi_otkazi_podatoci(prashanje: str) -> dict:
    """Користи AI (Groq) да извлече лекар + датум за откажување."""
    site_lekari = zimi_site_lekari()

    lista_text = ""
    for lekar in site_lekari:
        spec = lekar.get("specialty") or "Општа пракса"
        lista_text += f"ID {lekar['doctor_ID']}: Д-р {lekar['name']} {lekar['surname']} - {spec}\n"

    denes = date.today().strftime("%Y-%m-%d")
    den_vo_nedela = ["понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"][date.today().weekday()]

    full_prompt = f"""
Денес: {denes} ({den_vo_nedela})

Лекари:
{lista_text}

Корисник: „{prashanje}"

Извлечи doctor_id и datum.
""".strip()

    odgovor = ask_ai(full_prompt, system_prompt=OTKAZI_EXTRACT_PROMPT)

    # Тргни markdown ```json
    cist = re.sub(r"^```(?:json)?\s*", "", odgovor.strip())
    cist = re.sub(r"\s*```$", "", cist)

    try:
        podatoci = json.loads(cist)
        return {
            "doctor_id": podatoci.get("doctor_id"),
            "datum": podatoci.get("datum"),
        }
    except json.JSONDecodeError:
        return {"doctor_id": None, "datum": None}


def najdi_termini_za_otkazuvanje(pacient_email: str, doctor_id: int | None, datum: str | None) -> list[dict]:
    """
    Враќа активни (закажани, не откажани) термини на пациентот
    што одговараат на филтрите.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        query = """
            SELECT t.termin_ID, t.datum_pregled, t.vreme_pregled,
                   t.ime_lekar, t.specijalnost_termin, t.doctor_ID
            FROM Termin_pregled t
            WHERE LOWER(TRIM(t.email_pacient)) = LOWER(TRIM(%s))
              AND t.status_pregled = 'закажан'
              AND t.datum_pregled >= CURDATE()
        """
        params = [pacient_email]

        if doctor_id:
            query += " AND t.doctor_ID = %s"
            params.append(doctor_id)

        if datum:
            query += " AND t.datum_pregled = %s"
            params.append(datum)

        query += " ORDER BY t.datum_pregled, t.vreme_pregled"

        cur.execute(query, params)
        rezultati = cur.fetchall()
        cur.close()
        return rezultati

    except Exception as e:
        print(f"[otkazi_termin] greshka: {e}")
        return []
    finally:
        if conn:
            conn.close()


def otkazi_termin_vo_baza(termin_id: int) -> bool:
    """Поставува status_pregled = 'откажан'."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE Termin_pregled
            SET status_pregled = 'откажан'
            WHERE termin_ID = %s
        """, (termin_id,))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"[otkazi_termin] update greshka: {e}")
        return False
    finally:
        if conn:
            conn.close()


def format_vreme(v) -> str:
    """time/timedelta → HH:MM string."""
    if v is None:
        return "—"
    if hasattr(v, "strftime"):
        return v.strftime("%H:%M")
    if hasattr(v, "total_seconds"):
        s = int(v.total_seconds())
        return f"{s // 3600:02d}:{(s % 3600) // 60:02d}"
    return str(v)[:5]


def odgovori_za_otkazuvanje(prashanje: str, pacient: dict | None) -> str:
    """Главна точка - повикана од router-от."""
    if not pacient or not pacient.get("email"):
        return (
            'За да откажеш термин, прво најави се како пациент. '
            'Кликни „Најави се!" горе десно.'
        )

    izvleceno = izvlechi_otkazi_podatoci(prashanje)
    doctor_id = izvleceno.get("doctor_id")
    datum_str = izvleceno.get("datum")

    termini = najdi_termini_za_otkazuvanje(pacient["email"], doctor_id, datum_str)

    DENOVI = ["Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"]

    if not termini:
        return (
            'Не најдов активни термини што одговараат. Прашај „Кои се моите термини?" '
            'за да ги видиш сите.'
        )

    if len(termini) > 1:
        # Многу совпаѓања - прикажи ги
        delovi = ["Имаш повеќе термини. Кој точно сакаш да го откажеш?", ""]
        for t in termini:
            datum = t["datum_pregled"]
            den_ime = DENOVI[datum.weekday()]
            vreme = format_vreme(t["vreme_pregled"])
            delovi.append(
                f"- {den_ime} {datum.strftime('%d.%m.%Y')} во {vreme} "
                f"кај Д-р {t['ime_lekar']} ({t['specijalnost_termin']})"
            )
        delovi.append("")
        delovi.append('Биди поточен: „Откажи го прегледот кај д-р [презиме] на [датум]"')
        return "\n".join(delovi)

    # Точно еден термин
    t = termini[0]
    if not otkazi_termin_vo_baza(t["termin_ID"]):
        return "Не успеа да го откажам терминот. Пробај пак."

    datum = t["datum_pregled"]
    den_ime = DENOVI[datum.weekday()]
    vreme = format_vreme(t["vreme_pregled"])

    return (
        f"Терминот е откажан!\n\n"
        f"Лекар: Д-р {t['ime_lekar']}\n"
        f"Специјалност: {t['specijalnost_termin']}\n"
        f"Датум: {den_ime}, {datum.strftime('%d.%m.%Y')}\n"
        f"Време: {vreme}\n\n"
        'Можеш да закажеш нов термин со „Сакам преглед кај [презиме] [датум] [време]".'
    )
