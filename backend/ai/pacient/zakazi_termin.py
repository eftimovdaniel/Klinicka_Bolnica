"""
Закажување термин преку AI агент (Groq). # Izvrshuvanje na naredba

Едноставен flow: # Izvrshuvanje na naredba
  1) AI извлекува doctor_id + datum + vreme од прашањето # Izvrshuvanje na naredba
  2) Ако нешто недостасува → прашува корисникот # Izvrshuvanje na naredba
  3) Валидација (минато, викенд, работно време, дали е слободен) # Izvrshuvanje na naredba
  4) Прашува за напомена (Дали сакаш да оставиш порака за лекарот?) # Izvrshuvanje na naredba
  5) INSERT во база # Izvrshuvanje na naredba
  6) Email потврда (со напомена ако е дадена) + текст потврда # Izvrshuvanje na naredba

Главна функција: odgovori_za_zakazuvanje(prasanje, pacient, kontekst) # Izvrshuvanje na naredba
"""
from datetime import datetime, date, time # Uvoz na datetime klasi za rabota so datumi i vreme # Uvoz na datetime, date i time klasi za manipulacija so datumi
from database import get_connection # Uvoz na funkcija za konekcija so MySQL bazata # Uvoz na funkcija za konekcija so bazata
from ai._kernel.prompts import ZAKAZI_EXTRACT_PROMPT # Uvoz na prompt sablon za AI ekstrakcija # Uvoz na prompt sablon za ekstrakcija
from ai._kernel.groq_helpers import izvlechi_json_so_ai # Uvoz na Groq AI pomoshna funkcija # Uvoz na Groq AI pomosni funkcii
from ai._kernel.utils import format_datum, format_vreme # Uvoz na pomoshni funkcii za formatiranje # Uvoz na formatiracki funkcii za datum/vreme


RABOTNO_VREME_OD = time(8, 0)    # Konstanta — pocetok na rabotnoto vreme (08:00) # Dodeluvanje na vrednost
RABOTNO_VREME_DO = time(15, 30)  # Konstanta — kraj na rabotnoto vreme (15:30) # Dodeluvanje na vrednost

# Lista na denovi vo nedelata na makedonski (za prikaz vo potvrda) # Izvrshuvanje na naredba
DENOVI_VO_NEDELA = ["Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"] # Lista na denovi vo nedelata na makedonski jazik


# ───────────────── AI povik ───────────────── # Izvrshuvanje na naredba
def zimi_site_lekari_od_baza() -> list:  # SQL upit — vrakja site lekari za AI promptot # Definicija na funkcija
    """Vrakja lista na site lekari ({'doctor_ID', 'name', 'surname', 'specialty'})."""
    konekcija = None # Dodeluvanje na vrednost
    try: # Pocetok na blok za obrabotka na potencijalni greski
        konekcija = get_connection() # Otvoranje na nova konekcija so MySQL bazata
        cursor = konekcija.cursor(dictionary=True) # Dodeluvanje na vrednost
        cursor.execute("SELECT doctor_ID, name, surname, specialty FROM Doctors ORDER BY surname, name") # Izvrshuvanje na naredba
        rezultat = list(cursor.fetchall()) # Dodeluvanje na vrednost
        cursor.close() # Izvrshuvanje na naredba
        return rezultat # Vrakjanje na rezultat
    except Exception as e: # Fakjanje na bilo kakva greska i pechatenje na log poraka
        print(f"[zakazi_termin] zimi_site_lekari_od_baza: {e}") # Pechatenje na greska vo log za debagiranje
        return [] # Vrakjanje na rezultat
    finally: # Blok sto se izvrshuva sekogas (zatvaranje na resursi)
        if konekcija: # Uslovna proverka
            konekcija.close() # Izvrshuvanje na naredba


def izvlechi_podatoci_so_ai(prasanje: str) -> dict:  # Eden Groq povik koj vrakja doctor_id / datum / vreme # Definicija na funkcija
    """AI extract: doctor_id, datum (YYYY-MM-DD), vreme (HH:MM)."""
    site_lekari = zimi_site_lekari_od_baza()  # Lista na site lekari za AI da znae koe ID kome pripaga # Zemanje na lista na site lekari od kesirana funkcija

    # Tekst-lista na lekari za AI promptot # Izvrshuvanje na naredba
    lista_tekst = "" # Dodeluvanje na vrednost
    for lekar in site_lekari: # Iteracija niz site lekari za formatiranje na lista
        spec = lekar.get("specialty") or "Општа пракса" # Dodeluvanje na vrednost
        lista_tekst += f"ID {lekar['doctor_ID']}: Д-р {lekar['name']} {lekar['surname']} — {spec}\n" # Dodeluvanje na vrednost

    # Deneshen datum i den vo nedelata (AI gi koristi za „утре“, „среда“ itn.) # Izvrshuvanje na naredba
    deneshen_datum = date.today() # Zemanje na deneshen datum za kontekst na AI promptot
    denovi_mali = ["понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"] # Dodeluvanje na vrednost
    deneshen_den = denovi_mali[deneshen_datum.weekday()] # Dodeluvanje na vrednost

    # Polniot prompt sto se prakja kako „user“ poraka (system prompt e ZAKAZI_EXTRACT_PROMPT) # Izvrshuvanje na naredba
    full_prompt = ( # Dodeluvanje na vrednost
        f"Денешен датум: {deneshen_datum.isoformat()} ({deneshen_den})\n" # Izvrshuvanje na naredba
        f"Листа на лекари:\n{lista_tekst}\n" # Izvrshuvanje na naredba
        f"Корисник пишува: „{prasanje}\"\n\n" # Izvrshuvanje na naredba
        "Извлечи doctor_id, datum, vreme и врати JSON." # Izvrshuvanje na naredba
    ) # Izvrshuvanje na naredba

    return izvlechi_json_so_ai(full_prompt, ZAKAZI_EXTRACT_PROMPT, log_tag="zakazi_termin") # Vrakjanje na rezultat


# ───────────────── Pomoshni funkcii ───────────────── # Izvrshuvanje na naredba
def najdi_ime_na_lekar(doctor_id: int) -> str:  # Vrakja „Д-р Ime Prezime“ ili prazno # Definicija na funkcija
    for lekar in zimi_site_lekari_od_baza(): # Iteracija niz site lekari za formatiranje na lista
        if lekar.get("doctor_ID") == doctor_id: # Uslovna proverka
            return f"Д-р {lekar['name']} {lekar['surname']}" # Vrakjanje na rezultat
    return "" # Vrakjanje na rezultat


def zacuvaj_pending_vo_kontekst(kontekst, doctor_id, datum_str, vreme_str) -> dict:  # Zachuvaj nekompletni podatoci za sledna poraka # Definicija na funkcija
    """Po neuspeshen pokushai ili neprijaven pacient — zachuvaj sto AI uspeal da izvleche."""
    nov_kontekst = dict(kontekst) if isinstance(kontekst, dict) else {} # Dodeluvanje na vrednost
    pending = {} # Inicijalizacija na prazen dictionary za pending podatoci
    if doctor_id: # Uslovna proverka
        pending["doctor_id"] = int(doctor_id) # Dodeluvanje na vrednost
    if datum_str: # Uslovna proverka
        pending["datum"] = str(datum_str)[:10] # Dodeluvanje na vrednost
    if vreme_str: # Uslovna proverka
        pending["vreme"] = str(vreme_str)[:5] # Dodeluvanje na vrednost
    nov_kontekst["zakazi_pending"] = pending # Zemanje na podatoci za cekanje na napomena od kontekstot
    return nov_kontekst # Vrakjanje na rezultat


def dopolni_od_kontekst(doctor_id, datum_str, vreme_str, kontekst):  # Dokolku AI ne izvlekol nesto — zemi od zapamten pending # Definicija na funkcija
    """Vrakja (doctor_id, datum_str, vreme_str) — popolneti od pending ako AI propushtil."""
    if not isinstance(kontekst, dict): # Proverka dali objektot e od tocen tip (dict, str)
        return doctor_id, datum_str, vreme_str # Vrakjanje na izvleceni podatoci vo standardiziran format
    pending = kontekst.get("zakazi_pending") or kontekst.get("zakazi_od_slobodni") or {} # Inicijalizacija na prazen dictionary za pending podatoci
    if not isinstance(pending, dict): # Proverka dali objektot e od tocen tip (dict, str)
        return doctor_id, datum_str, vreme_str # Vrakjanje na izvleceni podatoci vo standardiziran format
    if not doctor_id and pending.get("doctor_id"): # Uslovna proverka
        doctor_id = pending["doctor_id"] # Dodeluvanje na vrednost
    if not datum_str and pending.get("datum"): # Uslovna proverka
        datum_str = pending["datum"] # Dodeluvanje na vrednost
    if not vreme_str and pending.get("vreme"): # Proverka dali vrednosta e prazna ili None
        vreme_str = pending["vreme"] # Dodeluvanje na vrednost
    return doctor_id, datum_str, vreme_str # Vrakjanje na izvleceni podatoci vo standardiziran format


# ───────────────── Validacija ───────────────── # Izvrshuvanje na naredba
def proveri_datum(datum_str: str):  # Vrakja (datum_objekt, poraka_greska) — eden od dvete e None # Definicija na funkcija
    """Validacija na datum string: format, ne e minato, ne e vikend."""
    try: # Pocetok na blok za obrabotka na potencijalni greski
        datum_objekt = datetime.strptime(datum_str, "%Y-%m-%d").date() # Parsiranje na string vo datetime objekt za validacija
    except (ValueError, TypeError): # Fakjanje na greska pri nevaliden datum/vreme format
        return None, "Неважечки формат на датум." # Vrakjanje None pri nevalidna vrednost
    if datum_objekt < date.today(): # Uslovna proverka
        return None, "Не може да закажеш термин во минатото. Избери иден датум." # Vrakjanje None pri nevalidna vrednost
    if datum_objekt.weekday() >= 5:  # 5 = sabota, 6 = nedela # Validacija: zakazuvanje e zabraneto za vikend (sabota=5, nedela=6)
        return None, "Не се закажуваат прегледи во сабота и недела. Избери друг ден." # Vrakjanje None pri nevalidna vrednost
    return datum_objekt, None # Vrakjanje None pri nevalidna vrednost


def proveri_vreme(vreme_str: str):  # Vrakja (vreme_objekt, poraka_greska) # Definicija na funkcija
    """Validacija na vreme string: format + rabotno vreme."""
    try: # Pocetok na blok za obrabotka na potencijalni greski
        vreme_objekt = datetime.strptime(vreme_str, "%H:%M").time() # Parsiranje na string vo datetime objekt za validacija
    except (ValueError, TypeError): # Fakjanje na greska pri nevaliden datum/vreme format
        return None, "Неважечки формат на време." # Vrakjanje None pri nevalidna vrednost
    if vreme_objekt < RABOTNO_VREME_OD or vreme_objekt > RABOTNO_VREME_DO: # Uslovna proverka
        poraka = ( # Dodeluvanje na vrednost
            f"Работно време е од {format_vreme(RABOTNO_VREME_OD)} " # Izvrshuvanje na naredba
            f"до {format_vreme(RABOTNO_VREME_DO)}." # Izvrshuvanje na naredba
        ) # Izvrshuvanje na naredba
        return None, poraka # Vrakjanje None pri nevalidna vrednost
    return vreme_objekt, None # Vrakjanje None pri nevalidna vrednost


def terminot_e_sloboden(doctor_id: int, datum_str: str, vreme_str: str) -> bool:  # SQL proverka dali drug pacient veke zakazal vo toj termin # Definicija na funkcija
    """True ako terminot ne e veke zafateн (sprechuva preklopuvanje)."""
    konekcija = None # Dodeluvanje na vrednost
    try: # Pocetok na blok za obrabotka na potencijalni greski
        konekcija = get_connection() # Otvoranje na nova konekcija so MySQL bazata
        cursor = konekcija.cursor(dictionary=True) # Dodeluvanje na vrednost
        # Barame dali ima drug zakazan termin so iste doctor_ID + datum + vreme # Izvrshuvanje na naredba
        cursor.execute( # Izvrshuvanje na naredba
            "SELECT termin_ID FROM Termin_pregled " # Izvrshuvanje na naredba
            "WHERE doctor_ID = %s AND DATE(datum_pregled) = %s " # Dodeluvanje na vrednost
            "  AND TIME(vreme_pregled) = %s AND status_pregled = 'закажан'", # Dodeluvanje na vrednost
            (doctor_id, datum_str, vreme_str), # Izvrshuvanje na naredba
        ) # Izvrshuvanje na naredba
        red = cursor.fetchone() # Dodeluvanje na vrednost
        cursor.close() # Izvrshuvanje na naredba
        return red is None  # Ako nema rezultat — terminot e sloboden # Vrakjanje None pri nevalidna vrednost
    except Exception as e: # Fakjanje na bilo kakva greska i pechatenje na log poraka
        print(f"[zakazi_termin] terminot_e_sloboden: {e}") # Pechatenje na greska vo log za debagiranje
        return False # Vrakjanje na rezultat
    finally: # Blok sto se izvrshuva sekogas (zatvaranje na resursi)
        if konekcija: # Uslovna proverka
            konekcija.close() # Izvrshuvanje na naredba


# ───────────────── Napomena flow (2-step state machine) ───────────────── # Izvrshuvanje na naredba
def proveri_dali_cekame_napomena(kontekst):  # Vrakja recnik so {doctor_id, datum, vreme} ili None # Definicija na funkcija
    """Dali sme vo faza na cekanje napomena od pacientot (drug cekor)."""
    if not isinstance(kontekst, dict): # Proverka dali objektot e od tocen tip (dict, str)
        return None # Vrakjanje None pri nevalidna vrednost
    cekanje = kontekst.get("zakazi_ceka_napomena") # Zemanje na podatoci za cekanje na napomena od kontekstot
    if not isinstance(cekanje, dict): # Proverka dali objektot e od tocen tip (dict, str)
        return None # Vrakjanje None pri nevalidna vrednost
    if cekanje.get("doctor_id") and cekanje.get("datum") and cekanje.get("vreme"): # Uslovna proverka
        return cekanje # Vrakjanje na rezultat
    return None # Vrakjanje None pri nevalidna vrednost


def korisnikot_odbiva_napomena(prasanje: str) -> bool:  # Dali pacientot odbiva da ostavi napomena # Definicija na funkcija
    """Detekcija na negativni odgovori („ne“, „nema“, „bez napomena“…)."""
    p = (prasanje or "").strip().lower() # Dodeluvanje na vrednost
    return p in { # Vrakjanje na rezultat
        "не", "не.", "no", "nema", "нема", "немам", "немам напомена", # Izvrshuvanje na naredba
        "без напомена", "нема напомена", "не сакам", "не сакам напомена", # Izvrshuvanje na naredba
    } # Izvrshuvanje na naredba


def postavi_cekanje_na_napomena(kontekst, doctor_id, datum_str, vreme_str) -> dict:  # Postavuva flag deka sledna poraka = napomena # Definicija na funkcija
    """Vrakja nov kontekst so zakazi_ceka_napomena = {doctor_id, datum, vreme}."""
    nov_kontekst = dict(kontekst) if isinstance(kontekst, dict) else {} # Dodeluvanje na vrednost
    nov_kontekst["zakazi_ceka_napomena"] = { # Zemanje na podatoci za cekanje na napomena od kontekstot
        "doctor_id": int(doctor_id), # Izvrshuvanje na naredba
        "datum": str(datum_str)[:10], # Izvrshuvanje na naredba
        "vreme": str(vreme_str)[:5], # Izvrshuvanje na naredba
    } # Izvrshuvanje na naredba
    return nov_kontekst # Vrakjanje na rezultat


# ───────────────── INSERT + email + potvrda ───────────────── # Izvrshuvanje na naredba
def insert_termin_vo_baza(doctor_id, ime_pacient, email_pacient, telefon_pacient, datum_str, vreme_str, napomena):  # Zachuvuvanje na nov termin vo Termin_pregled # Definicija na funkcija
    """Vrakja (uspeh, info_za_lekar_ili_greska)."""
    konekcija = None # Dodeluvanje na vrednost
    try: # Pocetok na blok za obrabotka na potencijalni greski
        konekcija = get_connection() # Otvoranje na nova konekcija so MySQL bazata
        cursor = konekcija.cursor(dictionary=True) # Dodeluvanje na vrednost

        # Prvo zememe podatoci za lekarot (ime, prezime, specijalnost) za INSERT-ot # Izvrshuvanje na naredba
        cursor.execute( # Izvrshuvanje na naredba
            "SELECT name, surname, specialty FROM Doctors WHERE doctor_ID = %s", # Dodeluvanje na vrednost
            (doctor_id,), # Izvrshuvanje na naredba
        ) # Izvrshuvanje na naredba
        lekar = cursor.fetchone() # Dodeluvanje na vrednost
        if not lekar: # Uslovna proverka
            return False, "Лекарот не постои." # Vrakjanje na rezultat

        ime_lekar = f"{lekar['name']} {lekar['surname']}" # Dodeluvanje na vrednost
        specijalnost = lekar.get("specialty") or "Општа пракса" # Dodeluvanje na vrednost
        # Napomenata e opcionalna — ako e prazna, vo baza zapisi NULL (ne prazna niza) # Izvrshuvanje na naredba
        napomena_db = (napomena or "").strip() or None # Dodeluvanje na vrednost

        cursor.execute( # Izvrshuvanje na naredba
            "INSERT INTO Termin_pregled " # Izvrshuvanje na naredba
            "(doctor_ID, ime_pacient, specijalnost_termin, ime_lekar, " # Izvrshuvanje na naredba
            " datum_pregled, vreme_pregled, status_pregled, email_pacient, " # Izvrshuvanje na naredba
            " telefon_pacient, napomena) " # Izvrshuvanje na naredba
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", # Izvrshuvanje na naredba
            ( # Izvrshuvanje na naredba
                doctor_id, ime_pacient, specijalnost, ime_lekar, # Izvrshuvanje na naredba
                datum_str, vreme_str, "закажан", # Izvrshuvanje na naredba
                email_pacient, telefon_pacient, napomena_db, # Izvrshuvanje na naredba
            ), # Izvrshuvanje na naredba
        ) # Izvrshuvanje na naredba
        konekcija.commit() # Izvrshuvanje na naredba
        cursor.close() # Izvrshuvanje na naredba

        return True, {"ime_lekar": ime_lekar, "specijalnost": specijalnost} # Vrakjanje na rezultat
    except Exception as e: # Fakjanje na bilo kakva greska i pechatenje na log poraka
        return False, f"Грешка при запис: {e}" # Vrakjanje na rezultat
    finally: # Blok sto se izvrshuva sekogas (zatvaranje na resursi)
        if konekcija: # Uslovna proverka
            konekcija.close() # Izvrshuvanje na naredba


def finaliziraj_zakazuvanje(doctor_id, datum_str, vreme_str, pacient, napomena):  # Posledna proverka + INSERT + email + potvrda # Definicija na funkcija
    """Posleden cekor — odi vo baza i prakja email."""
    # Posledna proverka — vo megjuvreme nekoj mozhebi zakazal vo istiot termin # Izvrshuvanje na naredba
    if not terminot_e_sloboden(int(doctor_id), datum_str, vreme_str): # Uslovna proverka
        return { # Vrakjanje na rezultat
            "odgovor": "Тој термин е веќе зафатен. Прашај за слободни термини и обиди се повторно.", # Izvrshuvanje na naredba
            "kontekst": None, # Izvrshuvanje na naredba
        } # Izvrshuvanje na naredba

    # Podatoci za pacientot od najava # Izvrshuvanje na naredba
    ime_pacient = ( # Dodeluvanje na vrednost
        (pacient.get("ime") or pacient.get("name_patient") or "") + " " # Izvrshuvanje na naredba
        + (pacient.get("prezime") or pacient.get("surname_patient") or "") # Izvrshuvanje na naredba
    ).strip() or pacient.get("email", "") # Izvrshuvanje na naredba
    email_pacient = pacient.get("email", "") # Zemanje na email adresata na pacientot
    telefon_pacient = pacient.get("telefon") or pacient.get("phone_number") or "" # Zemanje na telefonskiot broj na pacientot

    # INSERT vo baza # Izvrshuvanje na naredba
    uspeh, info = insert_termin_vo_baza( # Dodeluvanje na vrednost
        int(doctor_id), ime_pacient, email_pacient, telefon_pacient, # Izvrshuvanje na naredba
        datum_str, vreme_str, napomena, # Izvrshuvanje na naredba
    ) # Izvrshuvanje na naredba
    if not uspeh: # Proverka dali INSERT upitot bil uspesen
        return {"odgovor": f"Не успеа закажувањето: {info}", "kontekst": None} # Vrakjanje None pri nevalidna vrednost

    # Email potvrda (ne e fatalna ako padne — terminoot e veke zapisан) # Izvrshuvanje na naredba
    try: # Pocetok na blok za obrabotka na potencijalni greski
        from routers.termini import _poslati_potvrda_na_email # Uvoz na email funkcija (dinamicki, za da izbegne cirkularni importi)
        _poslati_potvrda_na_email( # Slanje na email potvrda do pacientot so detali za terminot
            to_email=email_pacient, # Zemanje na email adresata na pacientot
            ime_pacient=ime_pacient, # Dodeluvanje na vrednost
            ime_lekar=info["ime_lekar"], # Dodeluvanje na vrednost
            datum=datum_str, # Dodeluvanje na vrednost
            vreme=vreme_str, # Dodeluvanje na vrednost
            napomena=napomena,  # Napomena vleguva vo mailot ako e dadena # Dodeluvanje na vrednost
        ) # Izvrshuvanje na naredba
    except Exception as e: # Fakjanje na bilo kakva greska i pechatenje na log poraka
        print(f"[zakazi_termin] email: {e}") # Pechatenje na greska vo log za debagiranje

    # Tekst potvrda za korisnikot # Izvrshuvanje na naredba
    datum_objekt = datetime.strptime(datum_str, "%Y-%m-%d").date() # Parsiranje na string vo datetime objekt za validacija
    ime_na_den = DENOVI_VO_NEDELA[datum_objekt.weekday()] # Lista na denovi vo nedelata na makedonski jazik
    datum_za_prikaz = format_datum(datum_objekt) # Konverzija na datum string vo date objekt za validacija

    odgovor_tekst = ( # Dodeluvanje na vrednost
        "Терминот е успешно закажан.\n\n" # Izvrshuvanje na naredba
        f"Пациент: {ime_pacient}\n" # Izvrshuvanje na naredba
        f"Лекар: Д-р {info['ime_lekar']}\n" # Izvrshuvanje na naredba
        f"Специјалност: {info['specijalnost']}\n" # Izvrshuvanje na naredba
        f"Датум: {ime_na_den}, {datum_za_prikaz}\n" # Izvrshuvanje na naredba
        f"Време: {vreme_str}\n" # Izvrshuvanje na naredba
    ) # Izvrshuvanje na naredba
    if napomena and napomena.strip(): # Uslovna proverka
        odgovor_tekst += f"Напомена за лекарот: {napomena.strip()}\n" # Zemanje na tekstot na napomenata i odstranuvanje na prazni mesta
    odgovor_tekst += "\nПотврда е испратена на твојата е-пошта (ако е поставен SMTP)." # Dodeluvanje na vrednost

    return { # Vrakjanje na rezultat
        "odgovor": odgovor_tekst, # Izvrshuvanje na naredba
        "kontekst": { # Izvrshuvanje na naredba
            "zakazi_od_slobodni": {"doctor_id": int(doctor_id), "datum": datum_str}, # Izvrshuvanje na naredba
            "last_doctor_id": int(doctor_id), # Izvrshuvanje na naredba
        }, # Izvrshuvanje na naredba
    } # Izvrshuvanje na naredba


# ───────────────── Napomena handler (drug cekor) ───────────────── # Izvrshuvanje na naredba
def obrabotka_na_napomena(prasanje: str, pacient: dict, cekanje: dict) -> dict:  # Obrabotka na napomenata posle prashanjeto „Dali sakas napomena?“ # Definicija na funkcija
    """
    Sekoja poraka po prashanjeto za napomena vlguva tuka: # Izvrshuvanje na naredba
      - „не“ / „нема“ → INSERT bez napomena # Izvrshuvanje na naredba
      - bilo koj drug tekst → INSERT so toj tekst kako napomena # Izvrshuvanje na naredba
    """
    doctor_id = int(cekanje["doctor_id"]) # Dodeluvanje na vrednost
    datum_str = str(cekanje["datum"]) # Dodeluvanje na vrednost
    vreme_str = str(cekanje["vreme"]) # Dodeluvanje na vrednost

    if korisnikot_odbiva_napomena(prasanje): # Uslovna proverka
        return finaliziraj_zakazuvanje(doctor_id, datum_str, vreme_str, pacient, napomena=None) # Vrakjanje na izvleceni podatoci vo standardiziran format

    # Sekoj drug tekst go tretirame kako napomena # Izvrshuvanje na naredba
    napomena_tekst = (prasanje or "").strip() # Zemanje na tekstot na napomenata i odstranuvanje na prazni mesta
    if len(napomena_tekst) < 2: # Uslovna proverka
        # Premalku karakteri — barame povtorno # Izvrshuvanje na naredba
        return { # Vrakjanje na rezultat
            "odgovor": "Напишете ја напомената или кажете „не“ ако не сакате.", # Izvrshuvanje na naredba
            "kontekst": postavi_cekanje_na_napomena({}, doctor_id, datum_str, vreme_str), # Izvrshuvanje na naredba
        } # Izvrshuvanje na naredba
    return finaliziraj_zakazuvanje(doctor_id, datum_str, vreme_str, pacient, napomena=napomena_tekst) # Vrakjanje na izvleceni podatoci vo standardiziran format


# ───────────────── GLAVNA FUNKCIJA ───────────────── # Izvrshuvanje na naredba
def odgovori_za_zakazuvanje(prasanje: str, pacient: dict | None, kontekst: dict | None = None):  # Vlezna tocka — povikana od router # GLAVNA FUNKCIJA: vlezna tocka za celiot zakazuvacki proces
    """
    Edinstven flow: # Izvrshuvanje na naredba
      1) ako sme vo napomena-faza → obrabotka_na_napomena # Izvrshuvanje na naredba
      2) AI ekstrakcija (doctor_id / datum / vreme) # Izvrshuvanje na naredba
      3) pacient najaven? # Izvrshuvanje na naredba
      4) imame li lekar/datum/vreme? # Izvrshuvanje na naredba
      5) validacija (datum, vreme, slobodno) # Izvrshuvanje na naredba
      6) prashaj za napomena → postavi flag i cekaj sledna poraka # Izvrshuvanje na naredba
    """

    # 1) Ako vo prethodnata poraka prashavme za napomena — ovaa poraka e nejziniot odgovor # Izvrshuvanje na naredba
    cekanje_napomena = proveri_dali_cekame_napomena(kontekst) # Dodeluvanje na vrednost
    if cekanje_napomena and pacient and pacient.get("email"): # Uslovna proverka
        return obrabotka_na_napomena(prasanje, pacient, cekanje_napomena) # Vrakjanje na rezultat

    # 2) AI ekstrakcija na podatoci od prashanjeto # Izvrshuvanje na naredba
    podatoci_od_ai = izvlechi_podatoci_so_ai(prasanje) # Dodeluvanje na vrednost
    if podatoci_od_ai.get("_error"): # Uslovna proverka
        return {"odgovor": str(podatoci_od_ai["_error"]), "kontekst": kontekst} # Vrakjanje na prazna struktura so error flag pri neuspeh

    doctor_id = podatoci_od_ai.get("doctor_id") # Dodeluvanje na vrednost
    datum_str = podatoci_od_ai.get("datum") # Dodeluvanje na vrednost
    vreme_str = podatoci_od_ai.get("vreme") # Dodeluvanje na vrednost

    # Dopolni gi nedostasuvackite podatoci od zachuvan pending kontekst (od prethodna poraka) # Izvrshuvanje na naredba
    doctor_id, datum_str, vreme_str = dopolni_od_kontekst(doctor_id, datum_str, vreme_str, kontekst) # Dodeluvanje na vrednost

    # 3) Dali pacientot e najaven (e-posta e zadolzitelna za INSERT) # Izvrshuvanje na naredba
    if not pacient or not pacient.get("email"): # Proverka dali pacientot e najaven (ima email)
        return { # Vrakjanje na rezultat
            "odgovor": ( # Izvrshuvanje na naredba
                "За да закажам термин во твое име, треба да се најавиш како пациент.\n" # Izvrshuvanje na naredba
                "Ти ја отворам формата за најава — по најавата повтори ја истата наредба." # Izvrshuvanje na naredba
            ), # Izvrshuvanje na naredba
            "akcija": "otvori_pacient_login", # Izvrshuvanje na naredba
            "kontekst": zacuvaj_pending_vo_kontekst(kontekst, doctor_id, datum_str, vreme_str), # Izvrshuvanje na naredba
        } # Izvrshuvanje na naredba

    # 4) Proveri dali imame se sto e potrebno (lekar + datum + vreme) # Izvrshuvanje na naredba
    if not doctor_id: # Uslovna proverka
        return { # Vrakjanje na rezultat
            "odgovor": ( # Izvrshuvanje na naredba
                "Кај кој лекар сакаш да закажеш? Кажи го презимето на лекарот.\n" # Izvrshuvanje na naredba
                "Пример: „кај д-р Петров“ или „кај Серафимов“." # Izvrshuvanje na naredba
            ), # Izvrshuvanje na naredba
            "kontekst": zacuvaj_pending_vo_kontekst(kontekst, doctor_id, datum_str, vreme_str), # Izvrshuvanje na naredba
        } # Izvrshuvanje na naredba
    if not datum_str: # Uslovna proverka
        ime_lekar = najdi_ime_na_lekar(int(doctor_id)) or "лекарот" # Dodeluvanje na vrednost
        return { # Vrakjanje na rezultat
            "odgovor": ( # Izvrshuvanje na naredba
                f"Кој датум сакаш термин кај {ime_lekar}?\n" # Izvrshuvanje na naredba
                "Пример: „утре“, „среда“, „15.05“." # Izvrshuvanje na naredba
            ), # Izvrshuvanje na naredba
            "kontekst": zacuvaj_pending_vo_kontekst(kontekst, doctor_id, datum_str, vreme_str), # Izvrshuvanje na naredba
        } # Izvrshuvanje na naredba
    if not vreme_str: # Proverka dali vrednosta e prazna ili None
        ime_lekar = najdi_ime_na_lekar(int(doctor_id)) or "лекарот" # Dodeluvanje na vrednost
        return { # Vrakjanje na rezultat
            "odgovor": ( # Izvrshuvanje na naredba
                f"Во кое време сакаш термин кај {ime_lekar}?\n" # Izvrshuvanje na naredba
                f"Работно време: {format_vreme(RABOTNO_VREME_OD)} – {format_vreme(RABOTNO_VREME_DO)}.\n" # Izvrshuvanje na naredba
                "Пример: „во 10:00“ или „14:30“." # Izvrshuvanje na naredba
            ), # Izvrshuvanje na naredba
            "kontekst": zacuvaj_pending_vo_kontekst(kontekst, doctor_id, datum_str, vreme_str), # Izvrshuvanje na naredba
        } # Izvrshuvanje na naredba

    # 5a) Validacija na datum # Izvrshuvanje na naredba
    datum_objekt, greska_datum = proveri_datum(str(datum_str)[:10]) # Konverzija na datum string vo date objekt za validacija
    if greska_datum: # Uslovna proverka
        return {"odgovor": greska_datum, "kontekst": kontekst} # Vrakjanje na tuple so status, greska i informacii za lekarot

    # 5b) Validacija na vreme # Izvrshuvanje na naredba
    _, greska_vreme = proveri_vreme(str(vreme_str)[:5]) # Dodeluvanje na vrednost
    if greska_vreme: # Uslovna proverka
        return {"odgovor": greska_vreme, "kontekst": kontekst} # Vrakjanje na tuple so status, greska i informacii za lekarot

    # 5c) Proverka za preklopuvanje — drug pacient da ne zakazal vekje # Izvrshuvanje na naredba
    if not terminot_e_sloboden(int(doctor_id), str(datum_str)[:10], str(vreme_str)[:5]): # Uslovna proverka
        return { # Vrakjanje na rezultat
            "odgovor": ( # Izvrshuvanje na naredba
                "Тој термин е веќе зафатен. Прашај за слободни термини " # Izvrshuvanje na naredba
                "со „Кога е слободен д-р [презиме]?“ и обиди се повторно." # Izvrshuvanje na naredba
            ), # Izvrshuvanje na naredba
            "kontekst": kontekst, # Izvrshuvanje na naredba
        } # Izvrshuvanje na naredba

    # 6) Site uslovi se ispolneti → prashaj za napomena (postavi flag i cekaj sledna poraka) # Izvrshuvanje na naredba
    ime_lekar = najdi_ime_na_lekar(int(doctor_id)) or "лекарот" # Dodeluvanje na vrednost
    datum_za_prikaz = format_datum(datum_objekt) # Konverzija na datum string vo date objekt za validacija

    odgovor_tekst = ( # Dodeluvanje na vrednost
        f"Сè е подготвено за закажување кај {ime_lekar} " # Izvrshuvanje na naredba
        f"на {datum_za_prikaz} во {vreme_str}.\n\n" # Izvrshuvanje na naredba
        "Дали сакаш да оставиш напомена за лекарот?\n" # Izvrshuvanje na naredba
        "(на пр. алергии, хронична болест, симптоми)\n\n" # Izvrshuvanje na naredba
        "Напиши ја напомената во следната порака — или одговори „не“ ако не сакаш." # Izvrshuvanje na naredba
    ) # Izvrshuvanje na naredba
    return { # Vrakjanje na rezultat
        "odgovor": odgovor_tekst, # Izvrshuvanje na naredba
        "kontekst": postavi_cekanje_na_napomena( # Izvrshuvanje na naredba
            kontekst, int(doctor_id), str(datum_str)[:10], str(vreme_str)[:5], # Izvrshuvanje na naredba
        ), # Izvrshuvanje na naredba
    } # Izvrshuvanje na naredba
