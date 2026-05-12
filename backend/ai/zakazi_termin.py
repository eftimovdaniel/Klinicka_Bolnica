"""
Закажување термин преку AI асистент.

Како работи:
1. Пациентот пишува: „Сакам преглед кај д-р Петров среда 10:00"
2. AI (Gemini) ги извлекува: doctor_id, datum, vreme
3. Проверуваме во база дали:
   - Лекарот постои
   - Терминот е во иднина
   - Не е сабота/недела
   - Не е веќе зафатен
4. INSERT во Termin_pregled
5. Праќаме email потврда + враќаме потврда во чет

Бара: пациентот да биде логиран (frontend праќа неговите податоци)
"""

import json
import re
from datetime import datetime, date, time
from database import get_connection
from ai.gemini_client import ask_gemini
from ai.prompts import ZAKAZI_EXTRACT_PROMPT
from ai.slobodni_termini import zimi_site_lekari


# Работно време - не дозволуваме закажување надвор
RABOTNO_OD = time(8, 0)     # pocetok na rabotno vreme 
RABOTNO_DO = time(15, 30)   # kraj na rabotno vreme 


def izvlechi_podatoci_so_ai(prashanje: str) -> dict:
    """
    Прашува Gemini да ги извлече: лекар, датум, време од прашањето.

    Враќа dict со 3 полиња:
    {"doctor_id": int|None, "datum": str|None, "vreme": str|None}
    """
    site_lekari = zimi_site_lekari()

    # Lista na lekari koj ke gi koriste Gemini
    lista_text = ""
    for lekar in site_lekari:
        spec = lekar.get("specialty") or "Општа пракса" or "Општа медицина"
        lista_text += f"ID {lekar['doctor_ID']}: Д-р {lekar['name']} {lekar['surname']} - {spec}\n"

    denes = date.today().strftime("%Y-%m-%d")
    den_vo_nedela = ["понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"][date.today().weekday()]

    full_prompt = f""" Денешен датум: {denes} ({den_vo_nedela})
Листа на лекари:
{lista_text}

Корисник пишува: „{prashanje}"

Извлечи doctor_id, datum, vreme и врати JSON.
""".strip()

    odgovor = ask_gemini(full_prompt, system_prompt=ZAKAZI_EXTRACT_PROMPT)

    # Gemini понекогаш враќа JSON во markdown ```json ... ``` - тргни го
    cist = odgovor.strip()
    cist = re.sub(r"^```(?:json)?\s*", "", cist)
    cist = re.sub(r"\s*```$", "", cist)

    try:
        podatoci = json.loads(cist)
        return {
            "doctor_id": podatoci.get("doctor_id"),
            "datum": podatoci.get("datum"),
            "vreme": podatoci.get("vreme"),
        }
    except json.JSONDecodeError:
        return {"doctor_id": None, "datum": None, "vreme": None}


def proveri_dali_e_slobodno(doctor_id: int, datum_str: str, vreme_str: str) -> bool:
    """Проверка дали терминот е слободен (не е веќе закажан)."""
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
        """, (doctor_id, datum_str, vreme_str))
        return cur.fetchone() is None
    except Exception as e:
        print(f"[zakazi_termin] proveri_dali_e_slobodno: {e}")
        return False
    finally:
        if conn:
            conn.close()


def vmetni_termin_vo_baza(
    doctor_id: int,
    ime_pacient: str,
    email_pacient: str,
    telefon_pacient: str,
    datum_str: str,
    vreme_str: str,
) -> tuple[bool, str, dict | None]:
    """
    INSERT во Termin_pregled.

    Враќа: (uspeshno, poraka_za_greshka, podatoci_za_lekarot)
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        # Земи податоци за лекарот
        cur.execute("SELECT name, surname, specialty FROM Doctors WHERE doctor_ID = %s", (doctor_id,))
        doctor = cur.fetchone()
        if not doctor:
            return False, "Лекарот не постои.", None

        ime_lekar = f"{doctor['name']} {doctor['surname']}"

        cur.execute("""
            INSERT INTO Termin_pregled
            (doctor_ID, ime_pacient, specijalnost_termin, ime_lekar,
             datum_pregled, vreme_pregled, status_pregled, email_pacient,
             telefon_pacient, napomena)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            doctor_id,
            ime_pacient,
            doctor.get('specialty') or '',
            ime_lekar,
            datum_str,
            vreme_str,
            'закажан',
            email_pacient,
            telefon_pacient,
            'Закажано преку AI асистент'
        ))
        conn.commit()
        cur.close()

        return True, "", {
            "doctor_id": doctor_id,
            "ime_lekar": ime_lekar,
            "specialty": doctor.get('specialty') or 'Општа пракса',
        }

    except Exception as e:
        return False, f"Грешка при запис: {str(e)}", None
    finally:
        if conn:
            conn.close()


def formatiraj_potvrda(ime_pacient: str, ime_lekar: str, specialty: str, datum_str: str, vreme_str: str) -> str:
    """Текст за чет потврда."""
    DENOVI = ["Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"]
    dt = datetime.strptime(datum_str, "%Y-%m-%d").date()
    den_ime = DENOVI[dt.weekday()]
    datum_lep = dt.strftime("%d.%m.%Y")

    return (
        f"Терминот е успешно закажан!\n\n"
        f"Пациент: {ime_pacient}\n"
        f"Лекар: Д-р {ime_lekar}\n"
        f"Специјалност: {specialty}\n"
        f"Датум: {den_ime}, {datum_lep}\n"
        f"Време: {vreme_str}\n\n"
        f"Потврда е испратена на е-пошта."
    )


def odgovori_za_zakazuvanje(prashanje: str, pacient: dict | None) -> str:
    """
    Главна точка - повикана од router-от.

    Параметри:
        prashanje - целото прашање
        pacient   - dict со пациент податоци од frontend, или None ако не е логиран

    Враќа: текстуален одговор за пациентот.
    """
    # Проверка дали пациентот е логиран
    if not pacient or not pacient.get("email"):
        return (
            'За да закажеш термин преку AI асистентот, мораш прво да се најавиш '
            'како пациент. Кликни на копчето „Најави се!" горе десно.'
        )

    # AI извлекува податоци
    izvleceno = izvlechi_podatoci_so_ai(prashanje)

    doctor_id = izvleceno.get("doctor_id")
    datum_str = izvleceno.get("datum")
    vreme_str = izvleceno.get("vreme")

    # Што недостасува?
    nedostiga = []
    if not doctor_id:
        nedostiga.append("лекарот")
    if not datum_str:
        nedostiga.append("датумот")
    if not vreme_str:
        nedostiga.append("времето")

    if nedostiga:
        return (
            f'Не успеав да го разберам {", ".join(nedostiga)}. '
            f'Те молам напиши го прашањето поконкретно, на пример:\n'
            f'„Сакам преглед кај д-р Петров среда во 10:00"'
        )

    # Валидација на датум
    try:
        datum_obj = datetime.strptime(datum_str, "%Y-%m-%d").date()
    except ValueError:
        return "Неважечки формат на датум."

    if datum_obj < date.today():
        return "Не може да закажеш термин во минатото. Избери иден датум."

    if datum_obj.weekday() >= 5:
        return "Не се закажуваат прегледи во сабота и недела. Избери друг ден."

    # Валидација на време
    try:
        vreme_obj = datetime.strptime(vreme_str, "%H:%M").time()
    except ValueError:
        return "Неважечки формат на време."

    if vreme_obj < RABOTNO_OD or vreme_obj > RABOTNO_DO:
        return f"Работно време е од {RABOTNO_OD.strftime('%H:%M')} до {RABOTNO_DO.strftime('%H:%M')}."

    # Проверка дали е слободен
    if not proveri_dali_e_slobodno(doctor_id, datum_str, vreme_str):
        return (
            'Тој термин е веќе зафатен. Те молам прашај за слободни термини '
            'со „Кога е слободен д-р [презиме]?" и обиди се повторно.'
        )

    # Состави име на пациент
    ime_pacient = (
        (pacient.get("ime") or pacient.get("name_patient") or "") + " " +
        (pacient.get("prezime") or pacient.get("surname_patient") or "")
    ).strip()
    if not ime_pacient:
        ime_pacient = pacient.get("email", "")

    email_pacient = pacient.get("email", "")
    telefon_pacient = pacient.get("telefon") or pacient.get("phone_number") or ""

    # INSERT во базата
    uspesh, greshka, info = vmetni_termin_vo_baza(
        doctor_id=doctor_id,
        ime_pacient=ime_pacient,
        email_pacient=email_pacient,
        telefon_pacient=telefon_pacient,
        datum_str=datum_str,
        vreme_str=vreme_str,
    )

    if not uspesh:
        return f"Не успеа закажувањето: {greshka}"

    # Прати email потврда (го користиме постоечкиот SMTP код)
    try:
        from routers.termini import _poslati_potvrda_na_email
        _poslati_potvrda_na_email(
            to_email=email_pacient,
            ime_pacient=ime_pacient,
            ime_lekar=info["ime_lekar"],
            datum=datum_str,
            vreme=vreme_str,
        )
    except Exception as e:
        print(f"[zakazi_termin] email greshka: {e}")

    return formatiraj_potvrda(
        ime_pacient=ime_pacient,
        ime_lekar=info["ime_lekar"],
        specialty=info["specialty"],
        datum_str=datum_str,
        vreme_str=vreme_str,
    )
