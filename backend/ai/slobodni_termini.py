"""
Барање за слободни термини кај лекар - со помош на AI.
Како работи:
1. Зимаме сите лекари од базата (Doctors табелата).
2. Прашуваме AI (Groq): „Од прашањето кој лекар е во прашање?"
   - Му даваме листа на сите лекари + прашањето од корисникот
   - AI враќа ID број на лекар или NONE
3. Ако AI најде лекар, генерираме слотови (08:00-16:00, 30 мин) за 7 дена.
4. Проверуваме кои слотови се веќе закажани во Termin_pregled.
5. Формираме убав одговор на македонски.
Се вика од: routers/ai_chat.py
"""
from datetime import date, time, datetime, timedelta
from database import get_connection
from ai.groq_client import ask_ai
from ai.prompts import LEKAR_EXTRACT_PROMPT


# Работно време (може да го менуваш)
RABOTNO_VREME_OD = time(8, 0)    # pocetok na rabotno vrem od 08:00
RABOTNO_VREME_DO = time(16, 0)   # kraj na rabotno vreme do 16:00
TRAENJE_TERMIN_MINUTI = 30       # sekoj termin trae 30 minuti
DENOVI_NAPRED = 7
MAX_TERMINI = 8                  # MAX broj na termini vo eden den


# gi zemame site lekari od the database
def zimi_site_lekari() -> list[dict]:
    conn = None
    # ostvaruvanje na konekcija so bazata
    try:
        conn = get_connection() 
        cur = conn.cursor(dictionary=True)
        # se izvlekuvat site lekari od bazata so ime i prezime
        cur.execute("""
            SELECT doctor_ID, name, surname, specialty
            FROM Doctors
            ORDER BY surname, name
        """)
        lekari = cur.fetchall()     # vo lekari gi stavame site lekari so fetchall
        cur.close()
        return lekari   # gi vraka site lekari
    except Exception as e:
        print(f"[slobodni_termini] Greshka pri zimanje na lekari: {e}")
        return []
    finally:
        if conn:
            conn.close()
#funkcija koja so pomos na ai gi zima lekarite
# koristam Groq AI i on g gleda lekarite od bazata
def najdi_lekar_so_ai(prashanje: str) -> dict | None:
    site_lekari = zimi_site_lekari()    # vo site_lekari se smesteni lekarite od the database
    if not site_lekari: 
        return None

    # Формираме listа на лекари како текст за AI
    lista_text = ""
    for lekar in site_lekari:
        spec = lekar.get("specialty") or "Општа пракса"
        lista_text += f"ID {lekar['doctor_ID']}: Д-р {lekar['name']} {lekar['surname']} - {spec}\n"

    # Прашање за AI
    full_prompt = f""" Листа на лекари во болницата: {lista_text}
Прашање од корисник: „{prashanje}" За кој лекар прашува корисникот? Врати само ID број или NONE.""".strip()

    # Повикај AI со специјален системски prompt (само број или NONE)
    odgovor = ask_ai(full_prompt, system_prompt=LEKAR_EXTRACT_PROMPT)

    # Парсирај го одговорот - очекуваме само број или NONE
    odgovor_cist = odgovor.strip().upper().replace(".", "").replace(",", "")

    if "NONE" in odgovor_cist:
        return None

    # Извлечи го првиот број од одговорот
    import re
    match = re.search(r"\d+", odgovor_cist)
    if not match:
        return None

    doctor_id = int(match.group())

    # Најди го лекарот во листата
    for lekar in site_lekari:
        if lekar["doctor_ID"] == doctor_id:
            return lekar

    return None


def generiraj_slotovi_za_den(datum: date) -> list[datetime]:
    """
    Генерира сите можни слотови за еден ден (08:00, 08:30, ... 15:30).
    Прескокнува сабота и недела.
    """
    if datum.weekday() >= 5:  # 5=сабота, 6=недела
        return []

    slotovi = []
    momentalno = datetime.combine(datum, RABOTNO_VREME_OD)
    kraj = datetime.combine(datum, RABOTNO_VREME_DO)

    while momentalno < kraj:
        slotovi.append(momentalno)
        momentalno += timedelta(minutes=TRAENJE_TERMIN_MINUTI)

    return slotovi


def najdi_zafateni_slotovi(doctor_id: int, od_datum: date, do_datum: date) -> set:
    """
    Враќа множество (set) со зафатени слотови за лекар во даден интервал.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT datum_pregled, vreme_pregled
            FROM Termin_pregled
            WHERE doctor_ID = %s
              AND datum_pregled BETWEEN %s AND %s
              AND status_pregled NOT IN ('откажан', 'отказан')
        """, (doctor_id, od_datum, do_datum))
        rezultati = cur.fetchall()
        cur.close()

        zafateni = set()
        for r in rezultati:
            datum = r["datum_pregled"]
            vreme = r["vreme_pregled"]
            # vreme може да дојде како timedelta - нормализирај
            if isinstance(vreme, timedelta):
                vkupno_sekundi = int(vreme.total_seconds())
                casovi = vkupno_sekundi // 3600
                minuti = (vkupno_sekundi % 3600) // 60
                vreme = time(casovi, minuti)
            zafateni.add((datum, vreme))

        return zafateni

    except Exception as e:
        print(f"[slobodni_termini] Greshka pri barebje zafateni: {e}")
        return set()
    finally:
        if conn:
            conn.close()


def pronajdi_slobodni_termini(doctor_id: int) -> list[datetime]:
    """
    Главна функција - наоѓа слободни слотови за лекар во следните 7 дена.
    """
    denes = date.today()
    do_datum = denes + timedelta(days=DENOVI_NAPRED)

    zafateni = najdi_zafateni_slotovi(doctor_id, denes, do_datum)

    slobodni = []
    for offset in range(DENOVI_NAPRED + 1):
        datum = denes + timedelta(days=offset)
        slotovi_za_den = generiraj_slotovi_za_den(datum)

        for slot_datetime in slotovi_za_den:
            if slot_datetime < datetime.now():
                continue

            slot_vreme = slot_datetime.time()
            if (datum, slot_vreme) not in zafateni:
                slobodni.append(slot_datetime)

                if len(slobodni) >= MAX_TERMINI:
                    return slobodni

    return slobodni


def formatiraj_odgovor(lekar: dict, slobodni: list[datetime]) -> str:
    """
    Формира убава порака на македонски, групирано по ден.
    """
    DENOVI = [
        "Понеделник", "Вторник", "Среда", "Четврток",
        "Петок", "Сабота", "Недела",
    ]

    ime = f"Д-р {lekar['name']} {lekar['surname']}"
    specialnost = lekar.get("specialty") or "Општа пракса"
    zaglavie = f"{ime} - {specialnost}"

    if not slobodni:
        return f"{zaglavie}\n\nНема слободни термини во следните 7 дена."

    # Групирај термини по датум
    po_den = {}
    for dt in slobodni:
        kluc = (dt.date(), dt.weekday())
        po_den.setdefault(kluc, []).append(dt.strftime("%H:%M"))

    delovi = [zaglavie, "", "Слободни термини:"]
    for (datum, weekday), casovi in po_den.items():
        den_ime = DENOVI[weekday]
        datum_str = datum.strftime("%d.%m.%Y")
        casovi_str = ", ".join(casovi)
        delovi.append(f"{den_ime}, {datum_str}: {casovi_str}")

    return "\n".join(delovi)


def odgovori_za_slobodni_termini(prashanje: str) -> str:
    """
    Главна точка - повикана од router-от.

    Параметри:
        prashanje - целото прашање од корисникот (AI сам ќе извлече кој лекар)

    Враќа: текстуален одговор за пациентот.
    """
    # AI наоѓа кој лекар е во прашањето
    lekar = najdi_lekar_so_ai(prashanje)

    if not lekar:
        return (
            'Не успеав да препознаам за кој лекар прашуваш. '
            'Те молам напиши го името и презимето на лекарот, '
            'на пример: „Кога е слободен д-р Марко Петров?"'
            'Бараниот лекар не работи во нашата установа'
        )
# Барање во база за слободни термини
    slobodni = pronajdi_slobodni_termini(lekar["doctor_ID"])
    return formatiraj_odgovor(lekar, slobodni)
