from ai._kernel.prompt_loader import load_prompt # vcituvame funkcija za polnenje na sistemski instrukcii od fajl
from ai._kernel.utils import format_datum, format_datum_vreme, format_vreme # vcituvame funkcii za formatiranje na datumi i vreme za ubav prikaz
import json # vcituvame standardna biblioteka za manipulacija so json podatoci
import re # vcituvame biblioteka za koristenje na regularni izrazi
from datetime import datetime, date, timedelta # vcituvame klasi za rabota so datum i vremenski intervali
from database import get_connection # vcituvame funkcija za otvaranje na vrska so nasata baza na podatoci
from ai._kernel.ai_json import parse_ai_json # vcituvame pomosna funkcija za cistenje i parsiranje na ai odgovorot vo json
from ai._kernel.groq_client import ask_ai # vcituvame funkcija za komunikacija so ai servisot groq


def izvlechi_potsetnik(prasanje: str) -> dict: # definirame funkcija za izvlekuvanje na podatoci od korisnicko prasanje
    """Извлекува offset и датум за потсетник.""" # dokumentacija za celata na funkcijata
    denes = date.today().strftime("%Y-%m-%d") # go zemame tekovniot datum za da mozeme da go koristime vo logikata
    full_prompt = f'Денес: {denes}\n\nКорисник: „{prasanje}"\n\nИзвлечи податоци.' # kreirame tekstualen prompt so datum i prasanje za ai modelot

    odgovor = ask_ai(full_prompt, system_prompt=load_prompt("potsetnik_extract")) # go isprakame promptot do ai i go dobivame odgovorot
    podatoci = parse_ai_json(odgovor, log_tag="postavi_potsetnik") # go pretvorame odgovorot od ai vo korisen json format
    try: # pocnuvame blok za obid da go izvleceme offsetot
        offset = int(podatoci.get("offset_minuti", 60) or 60) # se obiduvame da zememe broj na minuti, ako nema vrakame default 60
    except (ValueError, TypeError): # ako nesto ne e validen broj vo jsonot
        offset = 60 # postavuvame bezbedna vrednost od 60 minuti
    return {"offset_minuti": offset, "datum": podatoci.get("datum")} # vrakame recnik so izvlechenite minuti i datumot ako go ima


def najdi_termin_za_potsetnik(pacient_email: str, datum: str | None) -> dict | None: # funkcija za baranje termin vo baza
    """Активен термин на пациентот, опционално по датум, инаку најблискиот.""" # opis na logikata za baranje
    conn = None # inicijalizirame prazna promenliva za bazata
    try: # zapocnuvame so obidot za konekcija
        conn = get_connection() # ja otvarame konekcijata so bazata
        cur = conn.cursor(dictionary=True) # kreirame kursor koj ke ni vrakja redovi kako recnici

        query = """ # pocnuvame so definicija na sql upitot
            SELECT termin_ID, datum_pregled, vreme_pregled,
                   ime_lekar, specijalnost_termin
            FROM Termin_pregled
            WHERE LOWER(TRIM(email_pacient)) = LOWER(TRIM(%s))
              AND status_pregled = 'закажан'
              AND datum_pregled >= CURDATE()
        """ # barame zakazan termin za pacientot koj e vo idnina
        params = [pacient_email] # gi postavuvame parametrite za bezbedno izbegnuvanje na sql injekcii

        if datum: # ako korisnikot baral tocno odreden datum
            query += " AND datum_pregled = %s" # dodavame uslov vo upitot
            params.append(datum) # go dodavame datumot vo listata na parametri

        query += " ORDER BY datum_pregled, vreme_pregled LIMIT 1" # gi sortirame i zemame samo eden najblizok termin

        cur.execute(query, params) # go izbrsuvame upitot so dadenite parametri
        rezultat = cur.fetchone() # go zemame prviot rezultat od bazata
        cur.close() # go zatvorame kursorot
        return rezultat # go vrakame najdeniot termin ili None ako go nema
    except Exception as e: # ako nesto ne e vo red so bazata
        print(f"[postavi_potsetnik] greska: {e}") # pecetime greska vo logot
        return None # vrakame nisto ako ne moze da se najde termin
    finally: # sekogas se izvrsuva na kraj
        if conn: # ako vrska e otvorena
            conn.close() # ja zatvorame vrskata so bazata


def vmetni_potsetnik(termin_id: int, pacient_email: str, vreme_potsetuvanje: datetime, poraka: str) -> bool: # funkcija za vmetnuvanje zapis
    """INSERT во Potsetnici.""" # opis na operacijata
    conn = None # inicijalizirame prazna vrska
    try: # zapocnuvame so obidot za vmetnuvanje
        conn = get_connection() # otvarame konekcija
        cur = conn.cursor() # kreirame obicen kursor
        cur.execute(""" # izvrsuvame insert sql komanda
            INSERT INTO Potsetnici (termin_ID, pacient_email, vreme_za_potsetuvanje, poraka)
            VALUES (%s, %s, %s, %s)
        """, (termin_id, pacient_email, vreme_potsetuvanje, poraka)) # gi vmetnuvame vrednostite
        conn.commit() # potvrduvame deka promenata treba trajno da se zapise
        cur.close() # zatvorame kursor
        return True # vrakame potvrda deka se e vo red
    except Exception as e: # ako nastane greska pri vmetnuvanje
        print(f"[postavi_potsetnik] insert greska: {e}") # pecetime greska
        return False # vrakame deka ne uspealo
    finally: # sekogas na kraj
        if conn: # ako postoi vrska
            conn.close() # ja zatvorame


def format_offset(minuti: int) -> str: # funkcija za citliv prikaz na vremenskiot interval
    """Претвора минути во читлив текст.""" # opis na funkcijata
    if minuti >= 1440: # ako intervalot e pogolem od den
        denovi = minuti // 1440 # presmetuvame kolku dena se
        return f"{denovi} ден" + ("а" if denovi > 1 else "") # vrakame string so dena/denovi
    if minuti >= 60: # ako intervalot e pogolem od cas
        casovi = minuti // 60 # presmetuvame kolku casi se
        return f"{casovi} час" + ("а" if casovi > 1 else "") # vrakame string so casa/casovi
    return f"{minuti} минути" # vrakame prosto minuti ako e pomalku od cas


def odgovori_za_potsetnik(prasanje: str, pacient: dict | None) -> str: # glavna funkcija za obrabotka na baranjeto
    """Главна точка.""" # dokumentacija za glavna funkcija
    if not pacient or not pacient.get("email"): # proveruvame dali pacientot e validen
        return 'За да поставиш потсетник, прво најави се како пациент.' # ako ne e, barame najava

    izvleceno = izvlechi_potsetnik(prasanje) # povikuvame ai za izvlekuvanje na detali od tekstot
    offset_min = izvleceno["offset_minuti"] # go zemame offsetot
    datum_str = izvleceno.get("datum") # go zemame datumot ako e detektiran

    termin = najdi_termin_za_potsetnik(pacient["email"], datum_str) # barame termin vo bazata

    if not termin: # ako nema takov termin
        return 'Немаш закажани активни термини за кои можам да поставам потсетник.' # vrakame poraka za greska

    datum_pregled = termin["datum_pregled"] # go zemame datumot od terminot
    vreme_pregled = termin["vreme_pregled"] # go zemame vremeto od terminot

    if isinstance(vreme_pregled, timedelta): # ako vremeto e vo format na vremensko traenje
        s = int(vreme_pregled.total_seconds()) # presmetuvame vkupno sekundi
        h = s // 3600 # dobivame casi
        m = (s % 3600) // 60 # dobivame minuti
        from datetime import time as dt_time # vcituvame klasa za vreme
        vreme_pregled = dt_time(h, m) # go konvertirame vo format time

    moment_na_pregled = datetime.combine(datum_pregled, vreme_pregled) # gi spojuvame datum i vreme vo edna tocka
    moment_na_potsetnik = moment_na_pregled - timedelta(minutes=offset_min) # presmetuvame koga treba da bide potsetnikot

    if moment_na_potsetnik <= datetime.now(): # proveruvame dali vremeto e vo minatoto
        return ( # vrakame poraka ako ne moze da se postavi potsetnik
            'Не можам да поставам потсетник во минатото. '
            'Терминот е премногу близу. Избери помал интервал.'
        )

    DENOVI = ["Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"] # niza so denovi za prikaz
    poraka = ( # kreirame poraka za korisnikot
        f"Потсетник: имаш преглед {DENOVI[datum_pregled.weekday()]} "
        f"{format_datum(datum_pregled)} во {format_vreme(vreme_pregled)} "
        f"кај Д-р {termin['ime_lekar']}."
    )

    if not vmetni_potsetnik(termin["termin_ID"], pacient["email"], moment_na_potsetnik, poraka): # se obiduvame da go zacuvame
        return "Не успеа поставувањето на потсетник." # ako ne uspeeme vrakame greska

    return ( # vrakame potvrda deka se e vo red
        f"Потсетникот е поставен!\n\n"
        f"Термин: {DENOVI[datum_pregled.weekday()]}, {format_datum(datum_pregled)} во {format_vreme(vreme_pregled)}\n"
        f"Лекар: Д-р {termin['ime_lekar']}\n"
        f"Кога: {format_offset(offset_min)} пред терминот\n"
        f"Точно време на потсетник: {format_datum_vreme(moment_na_potsetnik)}"
    )
