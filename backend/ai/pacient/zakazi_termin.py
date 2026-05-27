import re 
from datetime import datetime, date, time 
from database import get_connection 
from ai._kernel.odgovor_formatter import formatiraj_odgovor_so_ai 
from ai._kernel.prompts import ZAKAZI_EXTRACT_PROMPT 
from ai._kernel.groq_helpers import izvlechi_json_so_ai 
from ai._kernel.db_helpers import db_cursor 
from ai._kernel.utils import format_datum, format_vreme 
from ai.pacient.slobodni_termini import baranje_e_zakazuvanje, zimi_site_lekari 
RABOTNO_OD = time(8, 0)   # Konstanta: pocetok na rabotnoto vreme (08:00)
RABOTNO_DO = time(15, 30) # Konstanta: kraj na rabotnoto vreme (15:30)
DENOVI = ["Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"] # Lista na denovi vo nedelata na makedonski jazik

# Funkcija za eden povik do Groq AI koja vrakja doctor_id, datum, vreme, specialty
def _povikaj_ai(prasanje: str) -> dict: 
    lekari = zimi_site_lekari() # Zemanje na lista na site lekari 
    lista = "\n".join( # Kreiranje na formatirana lista na lekari za AI promptot
        f"ID {l['doctor_ID']}: Д-р {l['name']} {l['surname']} - "
        f"{l.get('specialty') or 'Општа пракса'}"
        for l in lekari # Iteracija niz site lekari za formatiranje na lista
    )
    denes = date.today() # Zemanje na deneshen datum za kontekst na AI promptot
    den_vo_nedela = ["понеделник", "вторник", "среда", "четврток", # Presmetka na denot vo nedelata za AI promptot
                     "петок", "сабота", "недела"][denes.weekday()]
    prompt = (
        f"Денешен датум: {denes.isoformat()} ({den_vo_nedela})\n"
        f"Листа на лекари:\n{lista}\n\n"
        f"Корисник пишува: „{prasanje}\"\n\n"
        "Извлечи doctor_id, datum, vreme, specialty и врати JSON."
    )
    podatoci = izvlechi_json_so_ai(prompt, ZAKAZI_EXTRACT_PROMPT, log_tag="zakazi_termin") # Povik do Groq AI so promptot i ekstrakcija na JSON odgovor
    if podatoci.get("_error"): # Proverka dali Groq vratile greska (nedostapen servis)
        # Groq nedostapen — vrati prazna struktura so error flag
        return {"doctor_id": None, "datum": None, "vreme": None, "specialty": None, # Vrakjanje na izvleceni podatoci vo standardiziran format
                "_error": podatoci["_error"]}
    return {
        "doctor_id": _kako_int(podatoci.get("doctor_id")),
        "datum": _kako_datum(podatoci.get("datum")),
        "vreme": _kako_vreme(podatoci.get("vreme")),
        "specialty": (podatoci.get("specialty") or None),
    }

def _kako_int(v) -> int | None: # Konverzija na vrednost vo cel broj so zastita od greski
    try: # Pocetok na blok za obrabotka na potencijalni greski
        return int(v) if v is not None else None # Vrakjanje None pri nevalidna vrednost
    except (TypeError, ValueError): # Fakjanje na greska pri nevaliden datum/vreme format
        return None # Vrakjanje None pri nevalidna vrednost


def _kako_datum(v) -> str | None: # Validacija i formatiranje na datum vo ISO format (YYYY-MM-DD)
    if not v: # Proverka dali vrednosta e prazna ili None
        return None # Vrakjanje None pri nevalidna vrednost
    s = str(v).strip()[:10]  # Konverzija na vrednost vo string i skratuvanje na 10 karakteri (YYYY-MM-DD)
    try: # Pocetok na blok za obrabotka na potencijalni greski
        datetime.strptime(s, "%Y-%m-%d")
        return s # Vrakjanje na rezultat
    except ValueError: # Fakjanje na greska pri nevaliden datum/vreme format
        return None # Vrakjanje None pri nevalidna vrednost


def _kako_vreme(v) -> str | None: # Validacija i formatiranje na vreme vo HH:MM format
    if not v: # Proverka dali vrednosta e prazna ili None
        return None # Vrakjanje None pri nevalidna vrednost
    s = str(v).strip()[:5]   # Konverzija na vrednost vo string i skratuvanje na 5 karakteri (HH:MM)
    try: # Pocetok na blok za obrabotka na potencijalni greski
        datetime.strptime(s, "%H:%M")
        return s # Vrakjanje na rezultat
    except ValueError: # Fakjanje na greska pri nevaliden datum/vreme format
        return None # Vrakjanje None pri nevalidna vrednost

def _ime_lekar(doctor_id: int | None) -> str: # Prebaruvanje na ime i prezime na lekarot spored ID od lista
    if not doctor_id: # Uslovna proverka
        return ""
    for l in zimi_site_lekari(): # Iteracija niz site lekari za formatiranje na lista
        if l.get("doctor_ID") == doctor_id: # Uslovna proverka
            return f"Д-р {l.get('name', '')} {l.get('surname', '')}".strip() # Vrakjanje na rezultat
    return ""


def _lekari_po_oddel(oddel: str) -> list[dict]: # SQL upit za zemanje na site lekari od dadena specijalnost
    try: # Pocetok na blok za obrabotka na potencijalni greski
        with db_cursor() as (_, cur): # Kontekst menadzer za avtomatsko zatvaranje na konekcija i kursor
            cur.execute( # Izvrsuvanje na SQL upit
                "SELECT doctor_ID, name, surname, specialty, email "
                "FROM Doctors WHERE LOWER(TRIM(specialty)) = LOWER(TRIM(%s)) "
                "ORDER BY surname, name",
                (oddel,),
            )
            return list(cur.fetchall()) # Vrakjanje na rezultat
    except Exception as e: # Fakjanje na bilo kakva greska i pechatenje na log poraka
        print(f"[zakazi_termin] lekari_po_oddel: {e}") # Pechatenje na greska vo log za debagiranje
        return []

def _spoji_so_kontekst(izvleceno: dict, kontekst: dict | None) -> None: # Dopolni prazni polinja od prethodno zapamten kontekst (pending podatoci)
    if not isinstance(kontekst, dict): # Proverka dali objektot e od tocen tip (dict, str)
        return
    pending = (
        kontekst.get("zakazi_pending")
        or kontekst.get("zakazi_od_slobodni")
        or {}
    )
    if not isinstance(pending, dict): # Proverka dali objektot e od tocen tip (dict, str)
        return
    if not izvleceno.get("doctor_id"): # Proverka dali poleto e prazno - popolnuvanje od kontekst
        izvleceno["doctor_id"] = _kako_int(pending.get("doctor_id"))
    if not izvleceno.get("datum"): # Proverka dali poleto e prazno - popolnuvanje od kontekst
        izvleceno["datum"] = _kako_datum(pending.get("datum"))
    if not izvleceno.get("vreme"): # Proverka dali poleto e prazno - popolnuvanje od kontekst
        izvleceno["vreme"] = _kako_vreme(pending.get("vreme"))
    if not izvleceno.get("specialty"): # Proverka dali poleto e prazno - popolnuvanje od kontekst
        izvleceno["specialty"] = pending.get("specialty") # Postavuvanje na specijalnost vo pending podatoci
    if not izvleceno.get("datum") and kontekst.get("last_slobodni_datum"): # Proverka dali poleto e prazno - popolnuvanje od kontekst
        izvleceno["datum"] = _kako_datum(kontekst.get("last_slobodni_datum")) # Zemanje na podatoci od poslednite prikazani slobodni termini
    if not izvleceno.get("vreme") and kontekst.get("last_slobodni_vreme"): # Proverka dali poleto e prazno - popolnuvanje od kontekst
        izvleceno["vreme"] = _kako_vreme(kontekst.get("last_slobodni_vreme")) # Zemanje na podatoci od poslednite prikazani slobodni termini


def _zacuvaj_pending(kontekst: dict | None, izvleceno: dict) -> dict: # Zacuvuvanje na nekompletni podatoci vo kontekst za sledna poraka
    ctx = dict(kontekst) if isinstance(kontekst, dict) else {} # Kopiranje na postoecki kontekst za azuriranje
    pending: dict = {} # Inicijalizacija na prazen dictionary za pending podatoci
    for k in ("doctor_id", "datum", "vreme", "specialty"): # Iteracija niz polinjata sto se cuvaat vo pending
        v = izvleceno.get(k)
        if v: # Uslovna proverka
            pending[k] = v
    ctx["zakazi_pending"] = pending
    if pending.get("doctor_id"): # Uslovna proverka
        ctx["last_doctor_id"] = int(pending["doctor_id"])
    return ctx # Vrakjanje na rezultat

def _ceka_napomena(kontekst: dict | None) -> dict | None: # Proverka dali sistemot ceka napomena od pacientot (drug cekor)
    z = (kontekst or {}).get("zakazi_ceka_napomena") # Zemanje na podatoci za cekanje na napomena od kontekstot
    if isinstance(z, dict) and z.get("doctor_id") and z.get("datum") and z.get("vreme"): # Proverka dali objektot e od tocen tip i ima site polinja
        return z # Vrakjanje na rezultat
    return None # Vrakjanje None pri nevalidna vrednost


def _e_odbiva_napomena(prasanje: str) -> bool: # Detekcija dali pacientot odbiva da ostavi napomena (negativni odgovori)
    p = re.sub(r"\s+", " ", (prasanje or "").strip().lower()) # Normalizacija na tekstot (odstranuvanje na visok prazen prostor)
    return p in {"не", "не.", "no", "nema", "нема", "немам", "без напомена",
                 "нема напомена", "не сакам", "не сакам напомена"}

def _e_samo_da(prasanje: str) -> bool: # Detekcija dali pacientot potvrdil so kratok odgovor (da, ok, vo red)
    p = re.sub(r"\s+", " ", (prasanje or "").strip().lower()) # Normalizacija na tekstot (odstranuvanje na visok prazen prostor)
    return p in {"да", "da", "ок", "ok", "okay", "во ред"}

def _postavi_ceka_napomena(kontekst: dict | None, doctor_id: int, # Postavuvanje flag deka sledna poraka ke se tretira kako napomena
                           datum_str: str, vreme_str: str) -> dict:
    ctx = dict(kontekst) if kontekst else {} # Kopiranje na postoecki kontekst za azuriranje
    ctx["zakazi_ceka_napomena"] = { # Postavuvanje na objektot za cekanje napomena vo kontekstot
        "doctor_id": int(doctor_id),
        "datum": datum_str,
        "vreme": vreme_str,
    }
    return ctx # Vrakjanje na rezultat

def _e_slobodno(doctor_id: int, datum_str: str, vreme_str: str) -> bool: # SQL proverka dali terminot e sloboden (nema drug zakazan pregled)
    """True ako terminot ne e zafateн od drug pacient."""
    try: # Pocetok na blok za obrabotka na potencijalni greski
        with db_cursor(dictionary=True) as (_, cur): # Kontekst menadzer za avtomatsko zatvaranje na konekcija i kursor
            cur.execute( # Izvrsuvanje na SQL upit
                "SELECT termin_ID FROM Termin_pregled "
                "WHERE doctor_ID = %s AND DATE(datum_pregled) = %s "
                "  AND TIME(vreme_pregled) = %s AND status_pregled = 'закажан'",
                (doctor_id, datum_str, vreme_str),
            )
            return cur.fetchone() is None # Ako nema rezultat → terminot e sloboden
    except Exception as e: # Fakjanje na bilo kakva greska i pechatenje na log poraka
        print(f"[zakazi_termin] proverka: {e}") # Pechatenje na greska vo log za debagiranje
        return False


def _insert_termin(doctor_id: int, ime_pacient: str, email_pacient: str, # INSERT upit vo bazata za nov termin so podatoci na pacientot
                   telefon_pacient: str, datum_str: str, vreme_str: str,
                   napomena: str | None) -> tuple[bool, str, dict | None]:
    """INSERT vo Termin_pregled. Vrazka (uspeh, greska, info_za_lekar)."""
    conn = None
    try: # Pocetok na blok za obrabotka na potencijalni greski
        conn = get_connection() # Otvoranje na nova konekcija so MySQL bazata
        cur = conn.cursor(dictionary=True) # Kreiranje na dictionary kursor za pristap do koloni po ime
        cur.execute( # Izvrsuvanje na SQL upit
            "SELECT name, surname, specialty FROM Doctors WHERE doctor_ID = %s",
            (doctor_id,),
        )
        doctor = cur.fetchone() # Zemanje na podatoci za lekarot od rezultatot na upitot
        if not doctor: # Ako lekarot ne postoi → neuspeh
            return False, "Лекарот не постои.", None

        cur.execute( # Izvrsuvanje na SQL upit
            "INSERT INTO Termin_pregled "
            "(doctor_ID, ime_pacient, specijalnost_termin, ime_lekar, "
            " datum_pregled, vreme_pregled, status_pregled, email_pacient, "
            " telefon_pacient, napomena) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                doctor_id, ime_pacient,
                doctor.get("specialty") or "",
                f"{doctor['name']} {doctor['surname']}",
                datum_str, vreme_str, "закажан",
                email_pacient, telefon_pacient,
                (napomena or "").strip() or None,
            ),
        )
        conn.commit() # Potvrduvanje na transakcijata (permanenten zapis)
        cur.close() # Zatvaranje na kursorot
        return True, "", { # Vrakjanje na uspeh + info za lekarot
            "doctor_id": doctor_id,
            "ime_lekar": f"{doctor['name']} {doctor['surname']}",
            "specialty": doctor.get("specialty") or "Општа пракса",
        }
    except Exception as e: # Fakjanje na bilo kakva greska i pechatenje na log poraka
        return False, f"Грешка при запис: {e}", None # Vrakjanje na neuspeh so poraka za greska
    finally: # Blok sto se izvrshuva sekogas (zatvaranje na resursi)
        if conn: # Uslovna proverka
            conn.close() # Zatvaranje na konekcijata so bazata


def _formatiraj_potvrda(ime_pacient: str, ime_lekar: str, specialty: str, # Generiranje na tekst potvrda so AI formatiranje ili fallback sablon
                        datum_str: str, vreme_str: str) -> str:
    """Tekst potvrda preku AI od fakti + sablon ako Groq padne."""
    dt = datetime.strptime(datum_str, "%Y-%m-%d").date() # Parsiranje na string vo datetime objekt za validacija
    den_ime = DENOVI[dt.weekday()] # Zemanje na imeto na denot vo nedelata
    datum_lep = format_datum(dt) # Formatiranje na datum vo citliv format za pacientot

    sablon = ( # Fallback sablon ako Groq AI padne ili e nedostapen
        "Задачата за закажување е успешно завршена. Еве што е направено во системот.\n\n"
        f"Пациент: {ime_pacient}\n"
        f"Лекар: Д-р {ime_lekar}\n"
        f"Специјалност: {specialty}\n"
        f"Датум: {den_ime}, {datum_lep}\n"
        f"Време: {vreme_str}\n\n"
        "Потврда е испратена на твојата е-пошта ако е поставен SMTP на серверот. "
        "Ако сакаш промена напиши „откажи термин“ или „префрли на друг ден“."
    )
    fakti = { # Kreiranje na dictionary so fakti za AI formatiranje
        "status": "zakazano", "pacient": ime_pacient, "lekar": f"Д-р {ime_lekar}",
        "specialnost": specialty, "datum": datum_lep, "den": den_ime,
        "vreme": vreme_str, "email_potvrda": True,
    }
    return formatiraj_odgovor_so_ai("zakazi_potvrda", fakti, sablon) # Vrakjanje na formatirana potvrda so AI ili fallback sablon


def _finaliziraj(doctor_id: int, datum_str: str, vreme_str: str, # Posledna proverka + zapis vo baza + email + generiranje potvrda
                 pacient: dict, kontekst: dict | None,
                 napomena: str | None) -> dict:
    if not _e_slobodno(doctor_id, datum_str, vreme_str): # Validacija: proverka dali terminot e zafaten od drug pacient
        ctx = dict(kontekst) if kontekst else {} # Kopiranje na postoecki kontekst za azuriranje
        ctx.pop("zakazi_ceka_napomena", None) # Brishenje na kluc od kontekstot (prekin na cekanje na napomena)
        return {
            "odgovor": "Тој термин е веќе зафатен. Прашај за слободни термини и обиди се повторно.",
            "kontekst": ctx,
        }

    ime_pacient = ( # Sostavuvanje na ime + prezime na pacientot (so fallback varianti)
        (pacient.get("ime") or pacient.get("name_patient") or "") + " "
        + (pacient.get("prezime") or pacient.get("surname_patient") or "")
    ).strip() or pacient.get("email", "") # Ako nema ime, koristi email kako identifikator
    email_pacient = pacient.get("email", "") # Zemanje na email adresata na pacientot
    telefon = pacient.get("telefon") or pacient.get("phone_number") or "" # Zemanje na telefonskiot broj na pacientot
    uspeh, greska, info = _insert_termin( # Izvrshuvanje na INSERT upitot i zemanje na rezultatot
        doctor_id, ime_pacient, email_pacient, telefon,
        datum_str, vreme_str, napomena,
    )
    if not uspeh: # Proverka dali INSERT upitot bil uspesen
        return {"odgovor": f"Не успеа закажувањето: {greska}", "kontekst": kontekst} # Vrakjanje na poraka so greska

    try: # Pocetok na blok za obrabotka na potencijalni greski
        from routers.termini import _poslati_potvrda_na_email # Uvoz na email funkcija (dinamicki, za da izbegne cirkularni importi)
        _poslati_potvrda_na_email( # Slanje na email potvrda do pacientot so detali za terminot
            to_email=email_pacient, ime_pacient=ime_pacient,
            ime_lekar=info["ime_lekar"], datum=datum_str, vreme=vreme_str,
        )
    except Exception as e: # Fakjanje na bilo kakva greska i pechatenje na log poraka
        print(f"[zakazi_termin] email: {e}") # Pechatenje na greska vo log za debagiranje

    return { # Vrakjanje na finalna potvrda i nov kontekst
        "odgovor": _formatiraj_potvrda(
            ime_pacient, info["ime_lekar"], info["specialty"],
            datum_str, vreme_str,
        ),
        "kontekst": {
            "zakazi_od_slobodni": {"doctor_id": doctor_id, "datum": datum_str},
            "last_doctor_id": doctor_id,
        },
    }
def _napomena_faza(prasanje: str, pacient: dict, ceka: dict, # Obrabotka na napomenata: odbieno, potvrdeno, ili tekst na napomena
                   kontekst: dict | None) -> dict:
    did = int(ceka["doctor_id"]) # Zemanje na ID na lekarot od cekanje objektot
    ds = str(ceka["datum"]) # Zemanje na datumot od cekanje objektot
    vs = str(ceka["vreme"]) # Zemanje na vremeto od cekanje objektot

    if _e_odbiva_napomena(prasanje): # Ako korisnikot odbiva napomena → finaliziraj bez napomena
        return _finaliziraj(did, ds, vs, pacient, kontekst, napomena=None)
    if _e_samo_da(prasanje): # Ako e samo „da" → prashaj vo sledna poraka da ja napishi
        return {
            "odgovor": "Во ред. Напишете ја напомената за лекарот (на пр. алергии) во следната порака.",
            "kontekst": _postavi_ceka_napomena(kontekst, did, ds, vs),
        }
    tekst = (prasanje or "").strip() # Zemanje na tekstot na napomenata i odstranuvanje na prazni mesta
    if len(tekst) < 2: # Proverka dali napomenata e prekratka (najmalku 2 karakteri)
        return {
            "odgovor": "Напишете ја напомената или кажете „не\" ако не сакате.",
            "kontekst": _postavi_ceka_napomena(kontekst, did, ds, vs),
        }
    return _finaliziraj(did, ds, vs, pacient, kontekst, napomena=tekst) # Validna napomena → finaliziraj zakazuvanjeto so nea

def _vo_zakazi_flow(prasanje: str, kontekst: dict | None) -> bool: # Proverka dali porakata e del od zakazuvackiot flow (klucni zborovi ili kontekst)
    """Dali porakata navistina prodolzuva zakaz-flow (so klucni zborovi ili kontekst)."""
    if baranje_e_zakazuvanje(prasanje): # Proverka dali porakata sodrzi klucni zborovi za zakazuvanje
        return True
    if _ceka_napomena(kontekst): # Proverka dali sme vo faza na cekanje na napomena
        return True
    if not isinstance(kontekst, dict): # Proverka dali objektot e od tocen tip (dict, str)
        return False
    if kontekst.get("zakazi_pending") or kontekst.get("zakazi_od_slobodni"): # Ako ima pending od prethodna poraka
        q = (prasanje or "").lower() # Normalizacija na porakata na mali bukvi za proverka
        if re.search(r"\b\d{1,2}\s*[:.]\s*\d{2}\b", q): # Detekcija na vremenski format (HH:MM) vo porakata
            return True
        if any(x in q for x in ( # Detekcija na klucni zborovi za zakazuvacki flow
            "закаж", "zakaz", "термин", "termin", "напомена",
            "нема", "не ", "кај ", "kaj ", "утре", "време", "датум",
        )):
            return True
    return False

def _poraka_nedostasuvaat(izvleceno: dict, kontekst: dict | None, # Generiranje na poraka za nedostasuvacki podatoci (lekar/datum/vreme)
                          ime_lekar: str) -> dict:
    """Edna funkcija za site varijanti na „nedostasuva lekar/datum/vreme"."""
    did = izvleceno.get("doctor_id") # Zemanje na ID na lekarot od izvleceni podatoci
    ds = izvleceno.get("datum") # Zemanje na datumot od izvleceni podatoci
    vs = izvleceno.get("vreme") # Zemanje na vremeto od izvleceni podatoci
    if not did and not ds and not vs: # Site tri polinja nedostasuvaat
        return _vrati_so_kontekst(
            "Го разбирам барањето како закажување, но недостасуваат податоци.\n\n"
            "Потребни се: лекар (име/презиме), датум и време.\n"
            "Пример: „Закажи кај д-р Петров среда во 10:00“.",
            kontekst, izvleceno,
        )

    if did and not ds and not vs: # Imame samo lekar - prashaj za datum i vreme
        return _vrati_so_kontekst(
            f"Кога би сакал/а да закажеш термин кај {ime_lekar or 'избраниот лекар'}?\n\n"
            "Кажи ми датум и време. Пример: „утре во 10:00“ или „среда во 14:30“.",
            kontekst, izvleceno,
        )

    if did and ds and not vs: # Imame lekar + datum, nema vreme
        try: # Pocetok na blok za obrabotka na potencijalni greski
            dt = datetime.strptime(ds, "%Y-%m-%d").date() # Parsiranje na string vo datetime objekt za validacija
            datum_lepo = format_datum(dt) # Formatiranje na datum vo citliv format za pacientot
        except ValueError: # Fakjanje na greska pri nevaliden datum/vreme format
            datum_lepo = ds # Ako parsiranje padne, koristi raw string
        return _vrati_so_kontekst(
            f"Во кое време сакаш термин кај {ime_lekar or 'лекарот'} на {datum_lepo}?\n\n"
            f"Работно време: {format_vreme(RABOTNO_OD)} – {format_vreme(RABOTNO_DO)}.",
            kontekst, izvleceno,
        )

    if did and not ds and vs: # Imame lekar + vreme, nema datum
        return _vrati_so_kontekst(
            f"Кој датум сакаш термин кај {ime_lekar or 'лекарот'} во {vs}?\n\n"
            "Пример: „утре“, „среда“, „15.05“.",
            kontekst, izvleceno,
        )

    # Nema lekar — prashaj za prezime ili specijalnost
    return _vrati_so_kontekst(
        "Кај кој лекар сакаш да закажеш? Кажи го презимето или специјалноста.\n\n"
        "Пример: „кај д-р Петров“, „преглед кај кардиолог“.",
        kontekst, izvleceno,
    )


def _vrati_so_kontekst(odgovor: str, kontekst: dict | None, # Pomosna funkcija za vrakanje odgovor so zacuvan kontekst
                       izvleceno: dict) -> dict:
    return {"odgovor": odgovor, "kontekst": _zacuvaj_pending(kontekst, izvleceno)} # Vrakjanje na odgovor so azuriran kontekst za sledna poraka


def _poraka_izberi_lekar_oddel(oddel: str, lekari: list[dict], # Generiranje na poraka so lista na lekari od izbranata specijalnost
                               datum_str: str | None,
                               kontekst: dict | None) -> dict:
    """Korisnikot kaza specijalnost — pokazi gi lekarite + filter na frontend."""
    from ai.opsto.lekari_oddel import navigacija_lekari # Uvoz na navigacija za lekari po oddel

    linii = [f"За преглед кај {oddel} во Клиничка Болница Штип, изберете лекар:", ""] # Inicijalizacija na lista za gradenje na poraka
    linii += [f"- Д-р {l['name']} {l['surname']}" for l in lekari] # Dodavanje na red za sekoj lekar
    if datum_str: # Ako ima datum, dodaj go na krajot za pojasna poraka
        try: # Pocetok na blok za obrabotka na potencijalni greski
            dt = datetime.strptime(datum_str[:10], "%Y-%m-%d").date() # Parsiranje na string vo datetime objekt za validacija
            linii.append(f"\nЗа датумот: {DENOVI[dt.weekday()]}, {format_datum(dt)}.") # Dodavanje na red so datum vo listata na poraka
        except ValueError: # Fakjanje na greska pri nevaliden datum/vreme format
            pass # Tivok fallback - bez datumski red
    linii += [
        "",
        "Наведете презиме (на пр. „кај Петров“) или прашајте:",
        "„Кога е слободен д-р [презиме]?“",
    ]

    ctx = dict(kontekst) if isinstance(kontekst, dict) else {} # Kopiranje na postoecki kontekst za azuriranje
    pending = {"specialty": oddel} # Postavuvanje na specijalnost vo pending podatoci
    if datum_str: # Uslovna proverka
        pending["datum"] = datum_str[:10]
    ctx["zakazi_pending"] = pending
    return {
        "odgovor": "\n".join(linii), # Spojuvanje na lista vo string so nov red
        "kontekst": ctx,
        "navigacija": navigacija_lekari(oddel, lekari), # Generiranje na JSON struktura za frontend navigacija
    }

def odgovori_za_zakazuvanje(prasanje: str, pacient: dict | None, kontekst: dict | None = None) -> str | dict: # GLAVNA FUNKCIJA: vlezna tocka za celiot zakazuvacki proces
    if not _vo_zakazi_flow(prasanje, kontekst):
        return {
            "odgovor": (
                "Не го препознав ова како барање за закажување термин.\n\n"
                "Пример: „Закажи кај д-р Петров утре во 10:00“."
            ),
            "kontekst": kontekst if isinstance(kontekst, dict) else None,
        }

    izvleceno = _povikaj_ai(prasanje) # Povikaj go AI za ekstrakcija na podatoci
    _spoji_so_kontekst(izvleceno, kontekst) # Dopolni od zapamten kontekst

    # Cekame napomena (vtor cekor) — pacient mora da e najaven
    ceka = _ceka_napomena(kontekst) # Proverka dali sme vo faza na cekanje na napomena
    if ceka and pacient and pacient.get("email"): # Uslovna proverka
        return _napomena_faza(prasanje, pacient, ceka, kontekst) # Predaj kontrolata na napomena handler-ot

    # Pacient ne e najaven — otvori login modal i zacuvaj pending
    if not pacient or not pacient.get("email"): # Proverka dali pacientot e najaven (ima email)
        return _odgovor_neprijaven(izvleceno, kontekst) # Vrakjanje na odgovor so akcija za otvoranje login

    # Groq padna i nema sto da koristime — vrati greska
    if izvleceno.get("_error") and not any( # Proverka dali AI padnal i nema izvleceni podatoci
        izvleceno.get(k) for k in ("doctor_id", "datum", "vreme", "specialty")
    ):
        return str(izvleceno["_error"]) # Vrakjanje na poraka za greska kako string

    did = izvleceno.get("doctor_id") # Zemanje na ID na lekarot od izvleceni podatoci
    ds = izvleceno.get("datum") # Zemanje na datumot od izvleceni podatoci
    vs = izvleceno.get("vreme") # Zemanje na vremeto od izvleceni podatoci
    oddel = izvleceno.get("specialty") # Zemanje na specijalnosta od izvleceni podatoci
    ime_lekar = _ime_lekar(did) # Zemanje na imeto na lekarot spored ID

    # Nema lekar ama ima specijalnost → pokazi lekari od taa specijalnost
    if not did and oddel: # Proverka: nema izbran lekar ama ima specijalnost
        lekari = _lekari_po_oddel(oddel) # Zemanje na site lekari od dadenata specijalnost
        if lekari: # Uslovna proverka
            return _poraka_izberi_lekar_oddel(oddel, lekari, ds, kontekst) # Pokazi gi lekarite + filter na frontend
        return {
            "odgovor": f"Моментално нема регистрирани лекари на „{oddel}“.",
            "kontekst": kontekst,
        }

    # Ako falet bilo koe od 3-te polinja → prashaj
    if not (did and ds and vs): # Proverka dali site tri podatoci se prisutni (lekar, datum, vreme)
        return _poraka_nedostasuvaat(izvleceno, kontekst, ime_lekar) # Vrakjanje na specificna poraka spored sto nedostiga

    # Site 3 polinja gi imame — validacija + napomena prashanje
    try: # Pocetok na blok za obrabotka na potencijalni greski
        datum_obj = datetime.strptime(ds, "%Y-%m-%d").date() # Parsiranje na string vo datetime objekt za validacija
    except ValueError: # Fakjanje na greska pri nevaliden datum/vreme format
        return "Неважечки формат на датум."

    if datum_obj < date.today(): # Validacija: datumot ne smee da bide vo minatoto
        return {"odgovor": "Не може да закажеш термин во минатото.", "kontekst": kontekst}

    if datum_obj.weekday() >= 5: # Validacija: zakazuvanje e zabraneto za vikend (sabota=5, nedela=6)
        return {
            "odgovor": "Не се закажуваат прегледи во сабота и недела. Избери друг ден.",
            "kontekst": _zacuvaj_pending(kontekst, izvleceno), # Zachuvaj pending za sledna poraka
        }

    try: # Pocetok na blok za obrabotka na potencijalni greski
        vreme_obj = datetime.strptime(vs, "%H:%M").time() # Parsiranje na string vo time objekt za validacija
    except ValueError: # Fakjanje na greska pri nevaliden datum/vreme format
        return "Неважечки формат на време."

    if vreme_obj < RABOTNO_OD or vreme_obj > RABOTNO_DO: # Validacija: vremeto mora da bide vo ramki na rabotnoto vreme
        return {
            "odgovor": f"Работно време е од {format_vreme(RABOTNO_OD)} до {format_vreme(RABOTNO_DO)}.",
            "kontekst": kontekst,
        }

    if not _e_slobodno(did, ds, vs): # Validacija: proverka dali terminot e zafaten od drug pacient
        return {
            "odgovor": "Тој термин е веќе зафатен. Прашај за слободни термини и обиди се повторно.",
            "kontekst": kontekst,
        }

    # Site uslovi se ispolneti → prashaj za napomena pred INSERT
    try: # Pocetok na blok za obrabotka na potencijalni greski
        datum_lepo = format_datum(datum_obj) # Formatiranje na datum vo citliv format za pacientot
    except Exception: # Fakjanje na bilo kakva greska i pechatenje na log poraka
        datum_lepo = ds # Fallback - koristi raw datum string
    return { # Vrakjanje na poraka za napomena + postavuvanje cekanje flag
        "odgovor": (
            f"Сè е подготвено за закажување кај {ime_lekar or 'лекарот'} "
            f"на {datum_lepo} во {vs}.\n\n"
            "Дали сакате да оставите напомена за лекарот?\n"
            "Напишете ја или кажете „не“."
        ),
        "kontekst": _postavi_ceka_napomena(kontekst, did, ds, vs), # Postavi flag deka cekame napomena
    }


def _odgovor_neprijaven(izvleceno: dict, kontekst: dict | None) -> dict: # Obrabotka koga pacientot ne e najaven - otvoranje na login modal
    """Pacient ne e najaven — otvori login modal i zacuvaj pending podatoci."""
    oddel = izvleceno.get("specialty") # Zemanje na specijalnosta od izvleceni podatoci
    nav = None # Inicijalizacija na navigacija (mozhe da ostane None)
    spec_hint = "" # Kreiranje na tekst so lista na lekari za neprijaven korisnik
    if oddel: # Uslovna proverka
        from ai.opsto.lekari_oddel import navigacija_lekari # Uvoz na navigacija za lekari po oddel
        lekari = _lekari_po_oddel(oddel) # Zemanje na site lekari od dadenata specijalnost
        if lekari: # Uslovna proverka
            linii = [f"За преглед кај {oddel}, изберете лекар:", ""] # Inicijalizacija na lista za gradenje na poraka
            linii += [f"- Д-р {l['name']} {l['surname']}" for l in lekari] # Dodavanje na red za sekoj lekar
            spec_hint = "\n\n" + "\n".join(linii) + f"\n\nЗачувано: специјалност „{oddel}“." # Kreiranje na tekst so lista na lekari za neprijaven korisnik
            nav = navigacija_lekari(oddel, lekari) # Generiranje na navigacija za lekari od daden oddel

    out: dict = { # Kreiranje na dictionary za odgovor so akcija za login
        "odgovor": (
            "За да закажам термин во твое име, треба да се најавиш како пациент.\n\n"
            "Ти ја отворам формата за најава — по најавата повтори ја истата наредба."
            f"{spec_hint}"
        ),
        "akcija": "otvori_pacient_login", # Akcija za frontend da otvori login modal
        "kontekst": _zacuvaj_pending(kontekst, izvleceno), # Zachuvaj pending za posle najavata
    }
    if nav: # Proverka dali postoi navigacija za lekari
        out["navigacija"] = nav
    return out
