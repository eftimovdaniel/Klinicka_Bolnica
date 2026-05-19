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
from ai._kernel.utils import format_datum, format_vreme
import json
import re
from datetime import datetime, date, time
from database import get_connection
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import ask_ai


def izvlechi_prenesi(prasanje: str) -> dict:  # funkcija za vadenje na parametri od korisnickiot vlez
    """Извлекува стар/нов датум и време за пренос на термин."""
    denes = date.today().strftime("%Y-%m-%d")  # go zemame denesniot datum za kontekst na AI
    denes_den = ["понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"][date.today().weekday()]  # go dobivame imeto na denot

    full_prompt = f'Денес: {denes} ({denes_den})\n\nКорисник: „{prasanje}"\n\nИзвлечи податоци.'  # sostavuva celosen prompt za AI

    odgovor = ask_ai(full_prompt, system_prompt=load_prompt("prenesi_extract"))  # go povikuva AI modelot za da gi izvlece informaciite
    podatoci = parse_ai_json(odgovor, log_tag="prenesi_termin")  # go parsira odgovorot vo JSON format
    return {  # vraka recnik so site potrebni podatoci za prenesuvanje
        "star_datum": podatoci.get("star_datum"),  # datumot na postoeckiot termin
        "nov_datum": podatoci.get("nov_datum"),  # noviot datum za koj sakame da go prefrlime
        "novo_vreme": podatoci.get("novo_vreme"),  # novoto vreme na pregledot
    }


def najdi_aktivni_termini(pacient_email: str, datum: str | None) -> list[dict]:  # baranje na termini vo bazata
    """Активни термини на пациентот, опционално филтрирани по датум."""
    conn = None
    try:
        conn = get_connection()  # otvora konekcija kon bazata
        cur = conn.cursor(dictionary=True)  # kreira kursor koj vraka rezultati kako recnici

        query = """
            SELECT termin_ID, doctor_ID, datum_pregled, vreme_pregled,
                   ime_lekar, specijalnost_termin
            FROM Termin_pregled
            WHERE LOWER(TRIM(email_pacient)) = LOWER(TRIM(%s))
              AND status_pregled = 'закажан'
              AND datum_pregled >= CURDATE()
        """  # sql upit za naogawe na zakazani termini vo idnina
        params = [pacient_email]  # go postavuva emailot na pacientot kako parametar

        if datum:  # proverka dali imame specificiran datum za baranje
            query += " AND datum_pregled = %s"  # dodava uslov za datum
            params.append(datum)  # go dodava datumot vo parametrite

        query += " ORDER BY datum_pregled, vreme_pregled"  # gi redi rezultatite po datum i vreme

        cur.execute(query, params)  # go izvrsuva upitot
        rezultati = cur.fetchall()  # gi zema site najdeni rezultati
        cur.close()  # go zatvora kursorot
        return rezultati  # vraka lista od termini
    except Exception as e:  # obrabotka na greski pri konekcija ili upit
        print(f"[prenesi_termin] najdi greska: {e}")  # pecati greska vo konzola
        return []  # vraka prazna lista dokolku nema termini ili ima greska
    finally:
        if conn:
            conn.close()  # zatvara konekcija sekojpat na kraj


def proveri_slobodno(doctor_id: int, datum_str: str, vreme_str: str, exclude_termin_id: int) -> bool:  # proverka za termin
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
        """, (doctor_id, datum_str, vreme_str, exclude_termin_id))  # bara dali veke postoi zakazan termin vo to vreme
        return cur.fetchone() is None  # vraka True ako e slobodno (ne najde zapis)
    except Exception as e:
        print(f"[prenesi_termin] proveri greska: {e}")
        return False
    finally:
        if conn:
            conn.close()


def izvrsi_prenesuvanje(termin_id: int, nov_datum: str, novo_vreme: str) -> bool:  # azuriranje vo bazata
    """UPDATE на датум/време."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE Termin_pregled
            SET datum_pregled = %s, vreme_pregled = %s
            WHERE termin_ID = %s
        """, (nov_datum, novo_vreme, termin_id))  # gi menuva datumot i vremeto vo bazata
        conn.commit()  # zacuvuva promeni
        cur.close()
        return True  # potvrduva uspeh
    except Exception as e:
        print(f"[prenesi_termin] update greska: {e}")
        return False
    finally:
        if conn:
            conn.close()


def odgovori_za_prenesuvanje(prasanje: str, pacient: dict | None) -> str:  # glavna funkcija
    """Главна точка."""
    if not pacient or not pacient.get("email"):  # proverka dali korisnikot e najaven
        return 'За да префрлиш термин, прво најави се како пациент.'

    izvleceno = izvlechi_prenesi(prasanje)  # ja povikuva funkcijata za izvlekuvanje podatoci
    nov_datum = izvleceno.get("nov_datum")  # go zema noviot datum
    novo_vreme = izvleceno.get("novo_vreme")  # go zema novoto vreme
    star_datum = izvleceno.get("star_datum")  # go zema stariot datum

    if not nov_datum or not novo_vreme:  # proverka dali se izvlecheni site potrebni podatoci
        return (
            'Не разбрав на кога да го префрлам. Напиши, на пример:\n'
            '„Префрли го утрешниот за петок 11:00"'
        )

    # Валидација на нов датум
    try:
        nov_dt = datetime.strptime(nov_datum, "%Y-%m-%d").date()  # go konvertira tekstot vo datum objekt
    except ValueError:
        return "Неважечки формат на нов датум."

    if nov_dt < date.today():  # sprecuva vnesuvanje na datum vo minatoto
        return "Не може да префрлиш термин во минатото."
    if nov_dt.weekday() >= 5:  # sprecuva zakazuvanje vo vikend
        return "Не се закажуваат прегледи во сабота/недела."

    # Валидација на ново време
    try:
        novo_v_obj = datetime.strptime(novo_vreme, "%H:%M").time()  # go konvertira tekstot vo vreme objekt
    except ValueError:
        return "Неважечки формат на време."
    if novo_v_obj < time(8, 0) or novo_v_obj > time(15, 30):  # proveruva dali vleguva vo rabotno vreme
        return "Работно време е 08:00 - 15:30."

    # Најди термин за пренесување
    termini = najdi_aktivni_termini(pacient["email"], star_datum)  # bara termini za stariot datum

    if not termini:  # ako ne najde nieden termin
        return 'Не најдов активен термин за пренесување. Прашај "Кои се моите термини?"'

    DENOVI = ["Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"]  # lista za prikaz na iminja na denovi

    if len(termini) > 1:  # ako pacientot ima poveke termini, bara da precizira
        delovi = ["Имаш повеќе термини. Кој сакаш да го префрлиш?", ""]
        for t in termini:
            d = t["datum_pregled"]
            v = format_vreme(t["vreme_pregled"])
            delovi.append(f"- {DENOVI[d.weekday()]} {format_datum(d)} во {v} кај Д-р {t['ime_lekar']}")
        delovi.append("")
        delovi.append('Биди поточен: "Префрли го прегледот на [стар датум] за [нов датум] [време]"')
        return "\n".join(delovi)

    # Точно еден термин - prodolzuva so proverka za slobodno vreme
    t = termini[0]
    if not proveri_slobodno(t["doctor_ID"], nov_datum, novo_vreme, t["termin_ID"]):  # proveruva dali terminot e sloboden
        return "Тој нов термин е веќе зафатен. Избери друго време."

    if not izvrsi_prenesuvanje(t["termin_ID"], nov_datum, novo_vreme):  # ja povikuva funkcijata za update
        return "Не успеа пренесувањето."

    return (  # vraka potvrda deka terminot e uspesno prenesen
        f"Терминот е пренесен!\n\n"
        f"Лекар: Д-р {t['ime_lekar']}\n"
        f"Нов датум: {DENOVI[nov_dt.weekday()]}, {format_datum(nov_dt)}\n"
        f"Ново време: {novo_vreme}"
    )

