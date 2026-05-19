"""
Тргни (избриши) оцена за завршен преглед.

Како работи:
1. Пациент пишува: „Избриши ја оцената за вчерашниот преглед"
   или „Тргни ја оцената за д-р Петров"
2. AI извлекува: лекар (опционално) + датум (опционално)
3. Бараме завршени термини на тој пациент што имаат оцена и одговараат на филтрите
4. Ако има точно еден → DELETE од Pregled_feedback
5. Ако има повеќе → прашаме кој
6. Ако нема → грешка

Бара логиран пациент.
"""

from ai._kernel.prompt_loader import load_prompt  # vcituva sistemski instrukcii za ai
from ai._kernel.utils import format_datum, format_vreme  # pomosni funkcii za prikaz na datum i vreme
import json  # standardna bib za json
import re  # bib za regularni izrazi
from datetime import date  # klasa za rabota so denesen datum
from database import get_connection  # funkcija za povrzivanje so bazata
from ai._kernel.ai_json import parse_ai_json  # ja pretvora ai odgovorot vo json recnik
from ai._kernel.groq_client import ask_ai  # glavna funkcija za komunikacija so ai modelot
from ai.pacient.slobodni_termini import zimi_site_lekari  # funkcija sto gi zema site doktori od bazata


def izvlechi_trgni_podatoci(prasanje: str) -> dict:  # ja analizira korisnickata poraka preku ai
    """Извлекува лекар + датум за бришење оцена."""
    site_lekari = zimi_site_lekari()  # ja zemame listata na site lekari za ai da znae koj e koj

    lista_text = ""  # kreirame tekst so site lekari koj ke go pratiime vo prompt
    for lekar in site_lekari:  # iterirame niz lekarite
        spec = lekar.get("specialty") or "Општа пракса"  # zemame specijalnost ili default
        lista_text += f"ID {lekar['doctor_ID']}: Д-р {lekar['name']} {lekar['surname']} - {spec}\n"  # go gradime stringot so doktori

    denes = date.today().strftime("%Y-%m-%d")  # go zemame denesniot datum vo format yyyy-mm-dd
    den_vo_nedela = ["понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"][date.today().weekday()]  # go naogame imeto na denot

    full_prompt = f"""
Денес: {denes} ({den_vo_nedela})

Лекари:
{lista_text}

Корисник: „{prasanje}"

Извлечи doctor_id и datum.
""".strip()  # sostavuvame kompleten prompt so kontekst za ai

    odgovor = ask_ai(full_prompt, system_prompt=load_prompt("trgni_ocena_extract"))  # go prasuva ai da izvlece podatoci spored promptot

    podatoci = parse_ai_json(odgovor, log_tag="trgni_ocena")  # go parsira odgovorot od ai vo json recnik
    return {  # go vrakame recnikot so izvlechenite id na lekar i datum
        "doctor_id": podatoci.get("doctor_id"),
        "datum": podatoci.get("datum"),
    }


def najdi_oceneti_termini(pacient_email: str, doctor_id: int | None, datum: str | None) -> list[dict]:  # funkcija za baranje na oceneti termini vo baza
    conn = None
    try:
        conn = get_connection()  # otvora vrska so bazata
        cur = conn.cursor(dictionary=True)  # kursor koj vraka rezultati kako recnici
        query = """
            SELECT t.termin_ID, t.datum_pregled, t.vreme_pregled,
                   t.ime_lekar, t.specijalnost_termin, t.doctor_ID,
                   pf.feedback_ID, pf.ocena, pf.komentar
            FROM Termin_pregled t
            INNER JOIN Pregled_feedback pf ON pf.termin_ID = t.termin_ID
            WHERE LOWER(TRIM(t.email_pacient)) = LOWER(TRIM(%s))
              AND t.status_pregled = 'завршен'
        """  # sql upit sto gi spoi terminite so nivnite ocenki za toj pacient
        params: list[object] = [pacient_email]  # go stavame emailot vo parametri

        if doctor_id:  # ako ai izvlekol id na doktor
            query += " AND t.doctor_ID = %s"  # go dodavame id-to vo sql
            params.append(doctor_id)

        if datum:  # ako ai izvlekol datum
            query += " AND t.datum_pregled = %s"  # go dodavame datumot vo sql
            params.append(datum)

        query += " ORDER BY t.datum_pregled DESC, t.vreme_pregled DESC"  # gi sortira od najnovite kon postarite

        cur.execute(query, params)  # go izvrsuva upitot
        rezultati = cur.fetchall()  # gi zema site rezultati
        cur.close()  # go zatvara kursorot
        return rezultati  # vrakame lista so najdeni oceneti termini

    except Exception as e:  # ako nastane greska vo bazata
        print(f"[trgni_ocena] greska: {e}")  # pecetime greska
        return []  # vrakame prazna lista
    finally:
        if conn:
            conn.close()  # sekogas zatvorame konekcija


def izbrisi_ocena(feedback_id: int) -> bool:  # funkcija za fizicko brisenje na ocenata
    """DELETE од Pregled_feedback."""
    conn = None
    try:
        conn = get_connection()  # konekcija
        cur = conn.cursor()  # kursor
        cur.execute(
            "DELETE FROM Pregled_feedback WHERE feedback_ID = %s",
            (feedback_id,),
        )  # briseme red od tabelata so oceni spored id
        conn.commit()  # ja zacuvuvame promenata trajno
        cur.close()  # zatvorame kursor
        return True  # potvrduvame uspeh
    except Exception as e:  # greska pri brisenje
        print(f"[trgni_ocena] delete greska: {e}")  # pecetime greska
        return False  # vrakame deka ne uspealo
    finally:
        if conn:
            conn.close()  # zatvorame konekcija


def odgovori_za_trgni_ocena(prasanje: str, pacient: dict | None) -> str:  # glavna funkcija za obrabotka
    """Главна точка - повикана од router-от."""
    if not pacient or not pacient.get("email"):  # proveruvame dali korisnikot e najaven
        return (
            'За да избришеш оцена, прво најави се како пациент. '
            'Кликни „Најави се!" горе десно.'
        )

    izvleceno = izvlechi_trgni_podatoci(prasanje)  # povikuvame ai za izvlekuvanje na doctor_id i datum
    doctor_id = izvleceno.get("doctor_id")  # gi zemame izvlechenite podatoci
    datum_str = izvleceno.get("datum")

    termini = najdi_oceneti_termini(pacient["email"], doctor_id, datum_str)  # bara termini so ocenki vo baza

    DENOVI = ["Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"]  # lista za prikaz na denovite

    if not termini:  # ako ne sme nasle nisto
        return (
            'Не најдов оценети прегледи што одговараат. Прашај „Кои се моите оценети прегледи?" '
            'или биди поспецифичен (лекар + датум).'
        )

    if len(termini) > 1:  # ako ima poveke od eden termin
        delovi = ["Имаш повеќе оценети прегледи. Кој точно сакаш да го избришеш?", ""]  # prasanje do korisnikot
        for t in termini[:10]:  # iterirame do prvite 10 rezultati
            datum = t["datum_pregled"]  # zemame datum
            den_ime = DENOVI[datum.weekday()]  # zemame ime na den
            vreme = format_vreme(t["vreme_pregled"])  # zemame formatirano vreme
            ocena = t.get("ocena") or 0  # zemame ocenata (ako ja nema 0)
            zvezdi = "★" * ocena + "☆" * (5 - ocena)  # kreirame vizuelen prikaz na zvezdite
            delovi.append(
                f"- {den_ime} {format_datum(datum)} во {vreme} "
                f"кај Д-р {t['ime_lekar']} - {zvezdi} ({ocena}/5)"
            )  # dodavame vo listata za prikaz
        delovi.append("")  # prazen red
        delovi.append('Биди поточен: „Тргни ја оцената за прегледот кај д-р [презиме] на [датум]"')  # upatstvo
        return "\n".join(delovi)  # ja vrakame listata kako eden tekst

    # Точно еден термин
    t = termini[0]  # go zemame prviot (i edinstven) termin
    if not izbrisi_ocena(t["feedback_ID"]):  # go povikuvame brisenjeto vo baza
        return "Не успеа да ја избришам оцената. Пробај пак."

    datum = t["datum_pregled"]  # zemame datum
    den_ime = DENOVI[datum.weekday()]  # zemame ime na den
    vreme = format_vreme(t["vreme_pregled"])  # zemame vreme
    stara_ocena = t.get("ocena") or 0  # ja zemame starata ocena za info

    ime_lekar = t['ime_lekar']  # ime na lekar
    return (  # vrakame potvrda za brisenjeto
        f"Оцената е избришана!\n\n"
        f"Лекар: Д-р {ime_lekar}\n"
        f"Специјалност: {t['specijalnost_termin']}\n"
        f"Датум: {den_ime}, {format_datum(datum)} во {vreme}\n"
        f"Избришана оцена: {stara_ocena}/5\n\n"
        'Можеш повторно да оцениш ако сакаш: „Оцена [1-5] за прегледот кај д-р '
        + str(ime_lekar) + '".'
    )
