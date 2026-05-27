"""
Закажување термин преку AI агент (Groq).

Едноставен flow:
  1) AI извлекува doctor_id + datum + vreme од прашањето
  2) Ако нешто недостасува → прашува корисникот
  3) Валидација (минато, викенд, работно време, дали е слободен)
  4) Прашува за напомена (Дали сакаш да оставиш порака за лекарот?)
  5) INSERT во база
  6) Email потврда (со напомена ако е дадена) + текст потврда

Главна функција: odgovori_za_zakazuvanje(prasanje, pacient, kontekst)
"""
from datetime import datetime, date, time  # Uvoz na datetime klasi za rabota so datumi i vreme
from database import get_connection  # Uvoz na funkcija za konekcija so MySQL bazata
from ai._kernel.prompts import ZAKAZI_EXTRACT_PROMPT  # Uvoz na prompt sablon za AI ekstrakcija
from ai._kernel.groq_helpers import izvlechi_json_so_ai  # Uvoz na Groq AI pomoshna funkcija
from ai._kernel.utils import format_datum, format_vreme  # Uvoz na pomoshni funkcii za formatiranje


RABOTNO_VREME_OD = time(8, 0)    # Konstanta — pocetok na rabotnoto vreme (08:00)
RABOTNO_VREME_DO = time(15, 30)  # Konstanta — kraj na rabotnoto vreme (15:30)

# Lista na denovi vo nedelata na makedonski (za prikaz vo potvrda)
DENOVI_VO_NEDELA = ["Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"]


# ───────────────── AI povik ─────────────────
def zimi_site_lekari_od_baza() -> list:  # SQL upit — vrakja site lekari za AI promptot
    """Vrakja lista na site lekari ({'doctor_ID', 'name', 'surname', 'specialty'})."""
    konekcija = None  # Inicijalizacija — vazno za finally blokot
    try:  # Pocetok na blok za obrabotka na potencijalni greski
        konekcija = get_connection()  # Otvoranje na nova konekcija so MySQL bazata
        cursor = konekcija.cursor(dictionary=True)  # Kreiranje na dictionary kursor za pristap po ime na kolona
        cursor.execute("SELECT doctor_ID, name, surname, specialty FROM Doctors ORDER BY surname, name")  # SQL upit za site lekari sortirani po prezime i ime
        rezultat = list(cursor.fetchall())  # Zemanje na site redovi i konverzija vo lista
        cursor.close()  # Zatvaranje na kursorot
        return rezultat  # Vrakjanje na listata na lekari
    except Exception as e:  # Fakjanje na bilo kakva greska (DB nedostapna, SQL greska)
        print(f"[zakazi_termin] zimi_site_lekari_od_baza: {e}")  # Pechatenje na greska vo log za debagiranje
        return []  # Pri greska — vrati prazna lista (ne ja kreshvaj programata)
    finally:  # Blok sto se izvrshuva sekogas (zatvaranje na resursi)
        if konekcija:  # Uslovna proverka — samo ako konekcijata e otvorena
            konekcija.close()  # Zatvaranje na konekcijata so bazata


def izvlechi_podatoci_so_ai(prasanje: str) -> dict:  # Eden Groq povik koj vrakja doctor_id / datum / vreme
    """AI extract: doctor_id, datum (YYYY-MM-DD), vreme (HH:MM)."""
    site_lekari = zimi_site_lekari_od_baza()  # Lista na site lekari za AI da znae koe ID kome pripaga

    # Tekst-lista na lekari za AI promptot
    lista_tekst = ""  # Pochetna prazna niza koja ke ja popolnuvame
    for lekar in site_lekari:  # Iteracija niz site lekari za formatiranje
        spec = lekar.get("specialty") or "Општа пракса"  # Specijalnost — ako nema, koristi „Општа пракса“ kako default
        lista_tekst += f"ID {lekar['doctor_ID']}: Д-р {lekar['name']} {lekar['surname']} — {spec}\n"  # Dodavanje na nov red so podatoci za sekoj lekar

    # Deneshen datum i den vo nedelata (AI gi koristi za „утре“, „среда“ itn.)
    deneshen_datum = date.today()  # Zemanje na deneshen datum od sistemot
    denovi_mali = ["понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"]  # Lista na denovi na kirilica (mali bukvi)
    deneshen_den = denovi_mali[deneshen_datum.weekday()]  # Presmetka na deneshniot den (weekday vrakja 0-6)

    # Polniot prompt sto se prakja kako „user“ poraka (system prompt e ZAKAZI_EXTRACT_PROMPT)
    full_prompt = (  # Sostavuvanje na promptot od delovi
        f"Денешен датум: {deneshen_datum.isoformat()} ({deneshen_den})\n"  # Prv red — denesniot datum
        f"Листа на лекари:\n{lista_tekst}\n"  # Vtor blok — listata na lekari
        f"Корисник пишува: „{prasanje}\"\n\n"  # Tret red — prashanjeto od korisnikot
        "Извлечи doctor_id, datum, vreme и врати JSON."  # Komanda za AI da vrati JSON
    )

    return izvlechi_json_so_ai(full_prompt, ZAKAZI_EXTRACT_PROMPT, log_tag="zakazi_termin")  # Povik do Groq AI i vrakjanje na izvlechenite podatoci


# ───────────────── Pomoshni funkcii ─────────────────
def najdi_ime_na_lekar(doctor_id: int) -> str:  # Vrakja „Д-р Ime Prezime“ ili prazno
    for lekar in zimi_site_lekari_od_baza():  # Iteracija niz site lekari za prebaruvanje po ID
        if lekar.get("doctor_ID") == doctor_id:  # Sporeduvanje na ID-ja
            return f"Д-р {lekar['name']} {lekar['surname']}"  # Vrakjanje na formatirano ime so titula
    return ""  # Lekar so dadenoto ID ne e najden — vrakjame prazna niza


def zacuvaj_pending_vo_kontekst(kontekst, doctor_id, datum_str, vreme_str) -> dict:  # Zachuvaj nekompletni podatoci za sledna poraka
    """Po neuspeshen pokushai ili neprijaven pacient — zachuvaj sto AI uspeal da izvleche."""
    nov_kontekst = dict(kontekst) if isinstance(kontekst, dict) else {}  # Kopiranje na postoecki kontekst ili praven nov
    pending = {}  # Inicijalizacija na prazen dictionary za pending podatoci
    if doctor_id:  # Ako AI uspeal da izvleche lekar — zachuvaj go
        pending["doctor_id"] = int(doctor_id)  # Konverzija vo int za sigurnost
    if datum_str:  # Ako AI uspeal da izvleche datum — zachuvaj go
        pending["datum"] = str(datum_str)[:10]  # Skratuvanje na prvite 10 karakteri (YYYY-MM-DD)
    if vreme_str:  # Ako AI uspeal da izvleche vreme — zachuvaj go
        pending["vreme"] = str(vreme_str)[:5]  # Skratuvanje na prvite 5 karakteri (HH:MM)
    nov_kontekst["zakazi_pending"] = pending  # Zapisuvanje na pending objektot vo kontekstot
    return nov_kontekst  # Vrakjanje na noviot kontekst za prakanje kon frontend


def dopolni_od_kontekst(doctor_id, datum_str, vreme_str, kontekst):  # Dokolku AI ne izvlekol nesto — zemi od zapamten pending
    """Vrakja (doctor_id, datum_str, vreme_str) — popolneti od pending ako AI propushtil."""
    if not isinstance(kontekst, dict):  # Proverka dali kontekstot e validen recnik
        return doctor_id, datum_str, vreme_str  # Ako ne e — vrati nepromeneti vrednosti
    pending = kontekst.get("zakazi_pending") or kontekst.get("zakazi_od_slobodni") or {}  # Probaj prvo pending, potoa slobodni, ili prazen dict
    if not isinstance(pending, dict):  # Proverka dali pending e validen recnik
        return doctor_id, datum_str, vreme_str  # Ako ne e — vrati nepromeneti vrednosti
    if not doctor_id and pending.get("doctor_id"):  # Ako nema lekar od AI, a ima vo pending
        doctor_id = pending["doctor_id"]  # Iskoristi go lekarot od pending
    if not datum_str and pending.get("datum"):  # Ako nema datum od AI, a ima vo pending
        datum_str = pending["datum"]  # Iskoristi go datumot od pending
    if not vreme_str and pending.get("vreme"):  # Ako nema vreme od AI, a ima vo pending
        vreme_str = pending["vreme"]  # Iskoristi go vremeto od pending
    return doctor_id, datum_str, vreme_str  # Vrakjame trojka so popolneti vrednosti


# ───────────────── Validacija ─────────────────
def proveri_datum(datum_str: str):  # Vrakja (datum_objekt, poraka_greska) — eden od dvete e None
    """Validacija na datum string: format, ne e minato, ne e vikend."""
    try:  # Pocetok na blok za obrabotka na potencijalni greski
        datum_objekt = datetime.strptime(datum_str, "%Y-%m-%d").date()  # Parsiranje na string vo date objekt
    except (ValueError, TypeError):  # Fakjanje na greska pri nevaliden datum format
        return None, "Неважечки формат на датум."  # Vrakjame None + poraka za greska
    if datum_objekt < date.today():  # Proverka dali datumot e vo minatoto
        return None, "Не може да закажеш термин во минатото. Избери иден датум."  # Greska — minat datum
    if datum_objekt.weekday() >= 5:  # 5 = sabota, 6 = nedela
        return None, "Не се закажуваат прегледи во сабота и недела. Избери друг ден."  # Greska — vikend
    return datum_objekt, None  # Validen datum — vrati objekt + None za greska


def proveri_vreme(vreme_str: str):  # Vrakja (vreme_objekt, poraka_greska)
    """Validacija na vreme string: format + rabotno vreme."""
    try:  # Pocetok na blok za obrabotka na potencijalni greski
        vreme_objekt = datetime.strptime(vreme_str, "%H:%M").time()  # Parsiranje na string vo time objekt
    except (ValueError, TypeError):  # Fakjanje na greska pri nevaliden vreme format
        return None, "Неважечки формат на време."  # Vrakjame None + poraka za greska
    if vreme_objekt < RABOTNO_VREME_OD or vreme_objekt > RABOTNO_VREME_DO:  # Proverka dali e vo rabotno vreme
        poraka = (  # Sostavuvanje na poraka za greska so opsegot
            f"Работно време е од {format_vreme(RABOTNO_VREME_OD)} "
            f"до {format_vreme(RABOTNO_VREME_DO)}."
        )
        return None, poraka  # Vrakjame None + poraka za nadvor od rabotno vreme
    return vreme_objekt, None  # Valdno vreme — vrati objekt + None za greska


def terminot_e_sloboden(doctor_id: int, datum_str: str, vreme_str: str) -> bool:  # SQL proverka dali drug pacient veke zakazal vo toj termin
    """True ako terminot ne e veke zafateн (sprechuva preklopuvanje)."""
    konekcija = None  # Inicijalizacija — vazno za finally blokot
    try:  # Pocetok na blok za obrabotka na potencijalni greski
        konekcija = get_connection()  # Otvoranje na nova konekcija so bazata
        cursor = konekcija.cursor(dictionary=True)  # Kreiranje na dictionary kursor
        # Barame dali ima drug zakazan termin so iste doctor_ID + datum + vreme
        cursor.execute(  # Izvrsuvanje na SQL upit
            "SELECT termin_ID FROM Termin_pregled "
            "WHERE doctor_ID = %s AND DATE(datum_pregled) = %s "
            "  AND TIME(vreme_pregled) = %s AND status_pregled = 'закажан'",
            (doctor_id, datum_str, vreme_str),  # Parametri za SQL placeholder-ite (%s)
        )
        red = cursor.fetchone()  # Zemanje na prviot rezultat (None ako nema)
        cursor.close()  # Zatvaranje na kursorot
        return red is None  # Ako nema rezultat — terminot e sloboden
    except Exception as e:  # Fakjanje na bilo kakva greska
        print(f"[zakazi_termin] terminot_e_sloboden: {e}")  # Log za debagiranje
        return False  # Pri greska — bezbedno vrati False (ne dozvoluvaj duplo zakazuvanje)
    finally:  # Blok sto se izvrshuva sekogas
        if konekcija:  # Uslovna proverka
            konekcija.close()  # Zatvaranje na konekcijata


# ───────────────── Napomena flow (2-step state machine) ─────────────────
def proveri_dali_cekame_napomena(kontekst):  # Vrakja recnik so {doctor_id, datum, vreme} ili None
    """Dali sme vo faza na cekanje napomena od pacientot (drug cekor)."""
    if not isinstance(kontekst, dict):  # Proverka dali kontekstot e validen recnik
        return None  # Ako ne e — nema cekanje
    cekanje = kontekst.get("zakazi_ceka_napomena")  # Zemanje na cekanje objektot od kontekstot
    if not isinstance(cekanje, dict):  # Proverka dali e validen recnik
        return None  # Ako ne e — nema cekanje
    if cekanje.get("doctor_id") and cekanje.get("datum") and cekanje.get("vreme"):  # Proverka dali ima site tri polinja
        return cekanje  # Vrakjanje na cekanje objektot
    return None  # Ako nesto fali — nema validno cekanje


def korisnikot_odbiva_napomena(prasanje: str) -> bool:  # Dali pacientot odbiva da ostavi napomena
    """Detekcija na negativni odgovori („ne“, „nema“, „bez napomena“…)."""
    p = (prasanje or "").strip().lower()  # Normalizacija — trim + mali bukvi
    return p in {  # Sporeduvanje so set od poznati negativni odgovori
        "не", "не.", "no", "nema", "нема", "немам", "немам напомена",
        "без напомена", "нема напомена", "не сакам", "не сакам напомена",
    }


def postavi_cekanje_na_napomena(kontekst, doctor_id, datum_str, vreme_str) -> dict:  # Postavuva flag deka sledna poraka = napomena
    """Vrakja nov kontekst so zakazi_ceka_napomena = {doctor_id, datum, vreme}."""
    nov_kontekst = dict(kontekst) if isinstance(kontekst, dict) else {}  # Kopiranje na postoecki kontekst ili praven nov
    nov_kontekst["zakazi_ceka_napomena"] = {  # Postavuvanje na flag-objektot za cekanje napomena
        "doctor_id": int(doctor_id),  # Konverzija vo int za sigurnost
        "datum": str(datum_str)[:10],  # Skratuvanje na YYYY-MM-DD format
        "vreme": str(vreme_str)[:5],  # Skratuvanje na HH:MM format
    }
    return nov_kontekst  # Vrakjanje na noviot kontekst


# ───────────────── INSERT + email + potvrda ─────────────────
def insert_termin_vo_baza(doctor_id, ime_pacient, email_pacient, telefon_pacient, datum_str, vreme_str, napomena):  # Zachuvuvanje na nov termin vo Termin_pregled
    """Vrakja (uspeh, info_za_lekar_ili_greska)."""
    konekcija = None  # Inicijalizacija — vazno za finally blokot
    try:  # Pocetok na blok za obrabotka na potencijalni greski
        konekcija = get_connection()  # Otvoranje na nova konekcija so bazata
        cursor = konekcija.cursor(dictionary=True)  # Kreiranje na dictionary kursor

        # Prvo zememe podatoci za lekarot (ime, prezime, specijalnost) za INSERT-ot
        cursor.execute(  # SQL upit za zemanje podatoci za lekarot
            "SELECT name, surname, specialty FROM Doctors WHERE doctor_ID = %s",
            (doctor_id,),  # Parametar — ID na lekarot
        )
        lekar = cursor.fetchone()  # Zemanje na podatocite za lekarot (eden red)
        if not lekar:  # Ako lekarot ne postoi vo bazata
            return False, "Лекарот не постои."  # Vrakjame neuspeh + poraka

        ime_lekar = f"{lekar['name']} {lekar['surname']}"  # Sostavuvanje na celosno ime na lekarot
        specijalnost = lekar.get("specialty") or "Општа пракса"  # Specijalnost ili default „Општа пракса“
        # Napomenata e opcionalna — ako e prazna, vo baza zapisi NULL (ne prazna niza)
        napomena_db = (napomena or "").strip() or None  # Ako napomenata e prazna ili samo blanko — vo baza ide NULL

        cursor.execute(  # Glavniot INSERT upit za nov termin
            "INSERT INTO Termin_pregled "
            "(doctor_ID, ime_pacient, specijalnost_termin, ime_lekar, "
            " datum_pregled, vreme_pregled, status_pregled, email_pacient, "
            " telefon_pacient, napomena) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (  # Parametri za site placeholder-i
                doctor_id, ime_pacient, specijalnost, ime_lekar,
                datum_str, vreme_str, "закажан",  # Statusot e hard-kodiran „закажан“
                email_pacient, telefon_pacient, napomena_db,
            ),
        )
        konekcija.commit()  # Potvrduvanje na transakcijata (permanenten zapis)
        cursor.close()  # Zatvaranje na kursorot

        return True, {"ime_lekar": ime_lekar, "specijalnost": specijalnost}  # Vrakjame uspeh + info za potvrda
    except Exception as e:  # Fakjanje na bilo kakva greska
        return False, f"Грешка при запис: {e}"  # Vrakjame neuspeh + poraka so greska
    finally:  # Blok sto se izvrshuva sekogas
        if konekcija:  # Uslovna proverka
            konekcija.close()  # Zatvaranje na konekcijata


def finaliziraj_zakazuvanje(doctor_id, datum_str, vreme_str, pacient, napomena):  # Posledna proverka + INSERT + email + potvrda
    """Posleden cekor — odi vo baza i prakja email."""
    # Posledna proverka — vo megjuvreme nekoj mozhebi zakazal vo istiot termin
    if not terminot_e_sloboden(int(doctor_id), datum_str, vreme_str):  # Proverka pred INSERT
        return {  # Vrakjame poraka deka terminot e zafateн
            "odgovor": "Тој термин е веќе зафатен. Прашај за слободни термини и обиди се повторно.",
            "kontekst": None,  # Brishenje na kontekstot — pacientot treba da pochne odpocetok
        }

    # Podatoci za pacientot od najava
    ime_pacient = (  # Sostavuvanje na ime + prezime od dva razlichni naziva na polinja (legacy)
        (pacient.get("ime") or pacient.get("name_patient") or "") + " "
        + (pacient.get("prezime") or pacient.get("surname_patient") or "")
    ).strip() or pacient.get("email", "")  # Ako nema ime — koristi email kako identifikator
    email_pacient = pacient.get("email", "")  # Email od najavata
    telefon_pacient = pacient.get("telefon") or pacient.get("phone_number") or ""  # Telefon od dva mozni naziva

    # INSERT vo baza
    uspeh, info = insert_termin_vo_baza(  # Povik na INSERT funkcijata
        int(doctor_id), ime_pacient, email_pacient, telefon_pacient,
        datum_str, vreme_str, napomena,
    )
    if not uspeh:  # Ako INSERT ne uspeal
        return {"odgovor": f"Не успеа закажувањето: {info}", "kontekst": None}  # Vrakjame poraka so greska

    # Email potvrda (ne e fatalna ako padne — terminoot e veke zapisан)
    try:  # Pocetok na blok za obrabotka na potencijalni greski
        from routers.termini import _poslati_potvrda_na_email  # Dinamicki import za izbegnuvanje na cirkularni zavisnosti
        _poslati_potvrda_na_email(  # Prakjanje na email so detali za terminot
            to_email=email_pacient,
            ime_pacient=ime_pacient,
            ime_lekar=info["ime_lekar"],
            datum=datum_str,
            vreme=vreme_str,
            napomena=napomena,  # Napomena vleguva vo mailot ako e dadena
        )
    except Exception as e:  # Email greska ne e fatalna — terminoot e veke vo baza
        print(f"[zakazi_termin] email: {e}")  # Log za debagiranje

    # Tekst potvrda za korisnikot
    datum_objekt = datetime.strptime(datum_str, "%Y-%m-%d").date()  # Parsiranje na datum za prikaz
    ime_na_den = DENOVI_VO_NEDELA[datum_objekt.weekday()]  # Zemanje na ime na den od listata
    datum_za_prikaz = format_datum(datum_objekt)  # Formatiranje na datum vo lokalen citliv format

    odgovor_tekst = (  # Sostavuvanje na potvrdata so site detali
        "Терминот е успешно закажан.\n\n"
        f"Пациент: {ime_pacient}\n"
        f"Лекар: Д-р {info['ime_lekar']}\n"
        f"Специјалност: {info['specijalnost']}\n"
        f"Датум: {ime_na_den}, {datum_za_prikaz}\n"
        f"Време: {vreme_str}\n"
    )
    if napomena and napomena.strip():  # Ako ima napomena — prikazji ja vo potvrdata
        odgovor_tekst += f"Напомена за лекарот: {napomena.strip()}\n"
    odgovor_tekst += "\nПотврда е испратена на твојата е-пошта (ако е поставен SMTP)."  # Dodavanje na poraka za email

    return {  # Vrakjame uspeshen rezultat + kontekst za sledni poraki
        "odgovor": odgovor_tekst,
        "kontekst": {
            "zakazi_od_slobodni": {"doctor_id": int(doctor_id), "datum": datum_str},  # Pamtenje za sledno zakazuvanje kaj istiot lekar
            "last_doctor_id": int(doctor_id),  # Pamtenje na posledniot lekar
        },
    }


# ───────────────── Napomena handler (drug cekor) ─────────────────
def obrabotka_na_napomena(prasanje: str, pacient: dict, cekanje: dict) -> dict:  # Obrabotka na napomenata posle prashanjeto „Dali sakas napomena?“
    """
    Sekoja poraka po prashanjeto za napomena vlguva tuka:
      - „не“ / „нема“ → INSERT bez napomena
      - bilo koj drug tekst → INSERT so toj tekst kako napomena
    """
    doctor_id = int(cekanje["doctor_id"])  # Zemanje na ID na lekarot od cekanje objektot
    datum_str = str(cekanje["datum"])  # Zemanje na datumot od cekanje objektot
    vreme_str = str(cekanje["vreme"])  # Zemanje na vremeto od cekanje objektot

    if korisnikot_odbiva_napomena(prasanje):  # Ako pacientot kazal „не“ / „нема“
        return finaliziraj_zakazuvanje(doctor_id, datum_str, vreme_str, pacient, napomena=None)  # INSERT bez napomena

    # Sekoj drug tekst go tretirame kako napomena
    napomena_tekst = (prasanje or "").strip()  # Odstranuvanje na prazni mesta od kraevite
    if len(napomena_tekst) < 2:  # Proverka dali napomenata e premnogu kratka (minimum 2 karakteri)
        # Premalku karakteri — barame povtorno
        return {  # Vrakjame poraka so povtorno barawe
            "odgovor": "Напишете ја напомената или кажете „не“ ако не сакате.",
            "kontekst": postavi_cekanje_na_napomena({}, doctor_id, datum_str, vreme_str),  # Zachuvuvame deka i ponatamu cekame napomena
        }
    return finaliziraj_zakazuvanje(doctor_id, datum_str, vreme_str, pacient, napomena=napomena_tekst)  # Validna napomena — INSERT so nea


# ───────────────── GLAVNA FUNKCIJA ─────────────────
def odgovori_za_zakazuvanje(prasanje: str, pacient: dict | None, kontekst: dict | None = None):  # Vlezna tocka — povikana od router
    """
    Edinstven flow:
      1) ako sme vo napomena-faza → obrabotka_na_napomena
      2) AI ekstrakcija (doctor_id / datum / vreme)
      3) pacient najaven?
      4) imame li lekar/datum/vreme?
      5) validacija (datum, vreme, slobodno)
      6) prashaj za napomena → postavi flag i cekaj sledna poraka
    """

    # 1) Ako vo prethodnata poraka prashavme za napomena — ovaa poraka e nejziniot odgovor
    cekanje_napomena = proveri_dali_cekame_napomena(kontekst)  # Proverka dali ima flag za cekanje napomena
    if cekanje_napomena and pacient and pacient.get("email"):  # Ako ima cekanje + pacientot e najaven
        return obrabotka_na_napomena(prasanje, pacient, cekanje_napomena)  # Predaj kontrolata na napomena handler-ot

    # 2) AI ekstrakcija na podatoci od prashanjeto
    podatoci_od_ai = izvlechi_podatoci_so_ai(prasanje)  # Eden Groq povik
    if podatoci_od_ai.get("_error"):  # Ako AI vratile greska (npr. rate-limit)
        return {"odgovor": str(podatoci_od_ai["_error"]), "kontekst": kontekst}  # Vrakjame greska kon korisnikot

    doctor_id = podatoci_od_ai.get("doctor_id")  # Zemanje na ID na lekarot od AI odgovorot
    datum_str = podatoci_od_ai.get("datum")  # Zemanje na datum od AI odgovorot
    vreme_str = podatoci_od_ai.get("vreme")  # Zemanje na vreme od AI odgovorot

    # Dopolni gi nedostasuvackite podatoci od zachuvan pending kontekst (od prethodna poraka)
    doctor_id, datum_str, vreme_str = dopolni_od_kontekst(doctor_id, datum_str, vreme_str, kontekst)  # Popolnuvanje od kontekst ako fali nesto

    # 3) Dali pacientot e najaven (e-posta e zadolzitelna za INSERT)
    if not pacient or not pacient.get("email"):  # Proverka dali ima pacient + email
        return {  # Vrakjame poraka za najava
            "odgovor": (
                "За да закажам термин во твое име, треба да се најавиш како пациент.\n"
                "Ти ја отворам формата за најава — по најавата повтори ја истата наредба."
            ),
            "akcija": "otvori_pacient_login",  # Akcija za frontend da otvori login modal
            "kontekst": zacuvaj_pending_vo_kontekst(kontekst, doctor_id, datum_str, vreme_str),  # Zachuvaj sto AI uspeal da izvleche
        }

    # 4) Proveri dali imame se sto e potrebno (lekar + datum + vreme)
    if not doctor_id:  # Nema lekar
        return {  # Prashaj za lekar
            "odgovor": (
                "Кај кој лекар сакаш да закажеш? Кажи го презимето на лекарот.\n"
                "Пример: „кај д-р Петров“ или „кај Серафимов“."
            ),
            "kontekst": zacuvaj_pending_vo_kontekst(kontekst, doctor_id, datum_str, vreme_str),  # Zachuvaj sto imame
        }
    if not datum_str:  # Nema datum
        ime_lekar = najdi_ime_na_lekar(int(doctor_id)) or "лекарот"  # Zemi ime na lekarot za personalizirana poraka
        return {  # Prashaj za datum
            "odgovor": (
                f"Кој датум сакаш термин кај {ime_lekar}?\n"
                "Пример: „утре“, „среда“, „15.05“."
            ),
            "kontekst": zacuvaj_pending_vo_kontekst(kontekst, doctor_id, datum_str, vreme_str),
        }
    if not vreme_str:  # Nema vreme
        ime_lekar = najdi_ime_na_lekar(int(doctor_id)) or "лекарот"  # Zemi ime na lekarot
        return {  # Prashaj za vreme
            "odgovor": (
                f"Во кое време сакаш термин кај {ime_lekar}?\n"
                f"Работно време: {format_vreme(RABOTNO_VREME_OD)} – {format_vreme(RABOTNO_VREME_DO)}.\n"
                "Пример: „во 10:00“ или „14:30“."
            ),
            "kontekst": zacuvaj_pending_vo_kontekst(kontekst, doctor_id, datum_str, vreme_str),
        }

    # 5a) Validacija na datum
    datum_objekt, greska_datum = proveri_datum(str(datum_str)[:10])  # Proverka na datum (format, minato, vikend)
    if greska_datum:  # Ako ima greska
        return {"odgovor": greska_datum, "kontekst": kontekst}  # Vrakjame poraka so greska

    # 5b) Validacija na vreme
    _, greska_vreme = proveri_vreme(str(vreme_str)[:5])  # Proverka na vreme (format, rabotno vreme)
    if greska_vreme:  # Ako ima greska
        return {"odgovor": greska_vreme, "kontekst": kontekst}  # Vrakjame poraka so greska

    # 5c) Proverka za preklopuvanje — drug pacient da ne zakazal vekje
    if not terminot_e_sloboden(int(doctor_id), str(datum_str)[:10], str(vreme_str)[:5]):  # SQL proverka
        return {  # Terminot e zafateн
            "odgovor": (
                "Тој термин е веќе зафатен. Прашај за слободни термини "
                "со „Кога е слободен д-р [презиме]?“ и обиди се повторно."
            ),
            "kontekst": kontekst,
        }

    # 6) Site uslovi se ispolneti → prashaj za napomena (postavi flag i cekaj sledna poraka)
    ime_lekar = najdi_ime_na_lekar(int(doctor_id)) or "лекарот"  # Zemi ime na lekarot za poraka
    datum_za_prikaz = format_datum(datum_objekt)  # Formatiraj datum za prikaz

    odgovor_tekst = (  # Sostavuvanje na poraka za napomena
        f"Сè е подготвено за закажување кај {ime_lekar} "
        f"на {datum_za_prikaz} во {vreme_str}.\n\n"
        "Дали сакаш да оставиш напомена за лекарот?\n"
        "(на пр. алергии, хронична болест, симптоми)\n\n"
        "Напиши ја напомената во следната порака — или одговори „не“ ако не сакаш."
    )
    return {  # Vrakjame poraka + postavuvame flag za napomena
        "odgovor": odgovor_tekst,
        "kontekst": postavi_cekanje_na_napomena(  # Postavi flag deka sledna poraka = napomena
            kontekst, int(doctor_id), str(datum_str)[:10], str(vreme_str)[:5],
        ),
    }
