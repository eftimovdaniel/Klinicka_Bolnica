from fastapi import APIRouter, HTTPException, Request
from typing import Optional
from datetime import datetime, date
import os
import string
from database import get_connection
from routers.utils import debug_log, transliterate_mk_to_lat
from password_utils import hash_password, verify_password

router = APIRouter(prefix="/lekari", tags=["lekari"])

# Привремена лозинка за сите лекари – мора да се смени само ако е оваа (инаку не се менува)
DEFAULT_LOZINKA_LEKARI = "Test123.."

# Валидација на лозинка за лекари: мин. 8 знаци, барем една голема буква, барем еден број, барем еден интерпункциски знак
# Подразуеваната привремена лозинка не смее да се користи како нова – мора да се смени во нешто друго
def _validna_lozinka_lekar(lozinka: str) -> tuple:
    if not lozinka or len(lozinka) < 8:
        return False, "Лозинката мора да има најмалку 8 карактери"
    if lozinka.strip() == DEFAULT_LOZINKA_LEKARI:
        return False, "Лозинката не смее да биде привремената/подразуеваната лозинка. Изберете друга лозинка според правилата (мин. 8 знаци, голема буква, број, интерпункциски знак)."
    if not any(c.isupper() for c in lozinka):
        return False, "Лозинката мора да содржи барем една голема буква"
    if not any(c.isdigit() for c in lozinka):
        return False, "Лозинката мора да содржи барем еден број"
    if not any(c in string.punctuation for c in lozinka):
        return False, "Лозинката мора да содржи барем еден интерпункциски знак"
    return True, ""

@router.get("")
def get_lekari(specijalnost: Optional[str] = None):                                                     # ako se vnese string vraka lekari od vnesena specijalnost, ako ne vnese string gi dava site lekari 
    conn = None         # se postavuva deka nema da ima konekcija na pocetokot, sekoja konekcija ja otvaram vo try, a ja zatvaram vo finally
    try:            
        conn = get_connection()                     # povrzuvanje so bazata na podatoci, vo conn se cuva konekcijata
        db_cursor = conn.cursor(dictionary=True)       # db_cursor objekt sto ovozmozuva da se vrsi sql naredba, argumento (dictionary=True) ni go dava izlezot kako recenica ne kako tuples
        # tuka so voa izlezot ke mi e [ {'id': 1, 'ime': 'Ana', 'vozrast': 22},{'id': 2, 'ime': 'Marko', 'vozrast': 21}]

        if specijalnost and specijalnost.strip():   # se proveruva dali e izbrana specijalnost
            db_cursor.execute("""
                SELECT doctor_ID, name, surname, COALESCE(specialty, '') AS specijalnost, email
                FROM Doctors
                WHERE specialty = %s
                ORDER BY name, surname
            """, (specijalnost.strip(),))
        else:
            # сите лекари – вклучувајќи ги и оние без специјалност (ќе се прикаже Н/П на frontend)
            db_cursor.execute("""
                SELECT doctor_ID, name, surname, COALESCE(specialty, '') AS specijalnost, email
                FROM Doctors
                ORDER BY name, surname
            """)
        lekari = db_cursor.fetchall()  # fetchall() vraka lista na lekari vo vid na recinica i se zapisuvaat vo promenlivata lakari
        if os.getenv("DEBUG_DB", "").strip().lower() in ("1", "true", "yes"):
            debug_log("lekari.get_lekari", "Broj na vrateni lekari", {"count": len(lekari), "specijalnost_filter": specijalnost or "(site)"})
        return lekari       # se vrakaat lekarite vo JSON format {"doctor_ID": 1, ...},{... }}
    except Exception as e:  # ako nastane greska, Exception, vo e e smenstena porakata za greska 
        raise HTTPException(status_code=500, detail=str(e))     # se dava 500 kako kod za greska  detail=str(e) poraka za prikaza na klient
    finally:                                # se vrsi ovoj blok bez razlika dali ima ili nema nastanato greska 
        if conn and conn.is_connected():    # dokolku postoi konekcija i taa e aktivna
            conn.close()                    # istata taa konekcija se zatvara


@router.post("/login")
async def login_lekar(request: Request):
    """
    Endpoint за најава на лекар со корисничко име (име.презиме) и лозинка.
    Валидира дали комбинацијата корисничко име/лозинка е точна и враќа податоци за лекарот.
    """
    conn = None
    try:
        # #region agent log
        debug_log("main.py:226", "login_lekar: Request received", {"timestamp": datetime.now().isoformat()}, hypothesis_id="E")
        # #endregion
        data = await request.json()  # ги земаме податоците од frontend (JSON формат)
        username = (data.get("username") or "").strip().lower()  # корисничко име на лекарот (име.презиме)
        password = data.get("password") or ""  # лозинка на лекарот
        
        # #region agent log
        debug_log("main.py:229", "login_lekar: Data parsed", {"username": username, "has_password": bool(password)}, hypothesis_id="E")
        # #endregion
        
        # Валидација: проверуваме дали се внесени и корисничко име и лозинка
        if not username:
            raise HTTPException(status_code=400, detail="Внесете корисничко име")
        if not password:
            raise HTTPException(status_code=400, detail="Внесете лозинка")
        
        conn = get_connection()  # воспоставување конекција со базата на податоци
        db_cursor = conn.cursor(dictionary=True)  # cursor за извршување SQL наредби со резултат како речник
        
        # Проверка дали постои лекар со даденото корисничко име (име.презиме на латиница)
        # Корисничкото име е во формат "име.презиме" на латиница (напр. "ana.ivanovska")
        # Ги земаме сите лекари и проверуваме во Python дали транслитерираното корисничко име се совпаѓа
        db_cursor.execute("SELECT doctor_ID, name, surname, email, specialty AS specijalnost, password FROM Doctors")
        all_doctors = db_cursor.fetchall()
        doctor = None
        checked_usernames = []
        
        for doc in all_doctors:
            doc_ime_lat = transliterate_mk_to_lat(doc.get("name") or "")
            doc_prezime_lat = transliterate_mk_to_lat(doc.get("surname") or "")
            doc_username = f"{doc_ime_lat}.{doc_prezime_lat}"
            checked_usernames.append(doc_username)
            
            # Проверка за точно совпаѓање
            if doc_username == username:
                doctor = doc
                break
            
            # Алтернативна проверка: ако корисникот внесува без "h" за "sh" (напр. "usinov" наместо "ushinov")
            # Ова е за поддршка на различни транслитерации
            # Проверка 1: Доколку корисникот внесува "usinov" а во базата е "ushinov"
            doc_username_no_sh = doc_username.replace("sh", "s").replace("zh", "z").replace("ch", "c")
            if doc_username_no_sh == username:
                doctor = doc
                break
            
            # Проверка 2: Доколку корисникот внесува "ushinov" а во базата е "usinov" (обратно)
            username_with_sh = username.replace("s", "sh").replace("z", "zh").replace("c", "ch")
            if doc_username == username_with_sh:
                doctor = doc
                break
            
            # Проверка 3: Пофлексибилно совпаѓање за мали грешки во транслитерацијата
            # Проверува дали името се совпаѓа точно и презимето е сличено (разлика од максимум 2 карактера)
            if "." in username and "." in doc_username:
                username_parts = username.split(".")
                doc_username_parts = doc_username.split(".")
                if len(username_parts) == 2 and len(doc_username_parts) == 2:
                    username_ime, username_prezime = username_parts
                    doc_ime, doc_prezime = doc_username_parts
                    
                    # Проверка дали името се совпаѓа точно
                    if username_ime == doc_ime:
                        # Проверка дали презимето е сличено (Levenshtein distance <= 2)
                        # Едноставна проверка: дали се совпаѓаат повеќето карактери
                        max_len = max(len(username_prezime), len(doc_prezime))
                        min_len = min(len(username_prezime), len(doc_prezime))
                        
                        # Ако разликата е мала (<= 2 карактери) и се совпаѓаат повеќето карактери
                        if max_len - min_len <= 2:
                            # Брои колку карактери се совпаѓаат на иста позиција
                            common_chars = sum(1 for a, b in zip(username_prezime, doc_prezime) if a == b)
                            # Ако се совпаѓаат најмалку 80% од карактерите
                            if common_chars >= min_len - 2:
                                doctor = doc
                                break
        
        if not doctor:
            raise HTTPException(status_code=401, detail="Невалидно корисничко име или лозинка")
        
        # #region agent log
        debug_log("main.py:261", "login_lekar: Doctor found", {"doctor_id": doctor.get("doctor_ID"), "has_stored_password": bool(doctor.get("password"))}, hypothesis_id="E")
        # #endregion
        
        # Проверка на лозинката: секој лекар мора да има поставена лозинка во базата
        stored_password_hash = (doctor.get("password") or "").strip()
        
        if not stored_password_hash:
            raise HTTPException(
                status_code=403,
                detail="Овој лекар сè уште не е регистриран. Користете ја опцијата „Регистрирај се“ за да креирате профил (име, презиме, специјалност, е-пошта, лозинка). По регистрација најавете се со корисничко име име.презиме и лозинката што ја поставивте."
            )
        if not verify_password(password, stored_password_hash):
            raise HTTPException(status_code=401, detail="Невалидно корисничко име или лозинка")
        
        doctor_id = doctor["doctor_ID"]  # ID на лекарот за да ги земеме неговите термини
        
        # Земаме термини со дијагноза и терапија од Termin_pregled табелата
        # ВАЖНО: Според базата, колоните се: Ime_pacient, Ime_lekar (со голема буква I)
        # COALESCE: ако дијагноза/терапија е NULL во базата, врати празен string '' наместо NULL
        db_cursor.execute("""
            SELECT termin_ID, Ime_pacient, datum_pregled, vreme_pregled, email_pacient, telefon_pacient,
                   COALESCE(dijagnoza, '') AS dijagnoza, COALESCE(terapija, '') AS terapija
            FROM Termin_pregled
            WHERE doctor_ID = %s AND (status_pregled IS NULL OR status_pregled = 'закажан')
            ORDER BY datum_pregled, vreme_pregled
        """, (doctor_id,))
        
        rows = db_cursor.fetchall()  # ги земаме сите термини за лекарот
        termini = []  # листа за термините
        
        for r in rows:  # r минува низ сите термини
            d = r.get("datum_pregled")  # d - датум на преглед, ако најде термин се сместува датумот на преглед
            t = r.get("vreme_pregled")  # t - време на преглед, ако е пронајден се сместува времето на преглед
            
            # Форматирање на датумот во облик [година-месец-ден]
            datum_str = d.strftime("%Y-%m-%d") if d and hasattr(d, "strftime") else (str(d)[:10] if d else "")
            
            # Форматирање на времето: ако е datetime/time објект, користи strftime; инаку како string (frontend ќе го форматира)
            if t and hasattr(t, "strftime"):
                vreme_str = t.strftime("%H:%M")
            else:
                vreme_str = str(t) if t else ""
            
            # Додавање во листата
            # ВАЖНО: Користиме Ime_pacient од базата (со голема буква I)
            termini.append({
                "termin_ID": r.get("termin_ID"),
                "ime_pacient": (r.get("Ime_pacient") or "").strip(),  # го зема името на пациентот од Ime_pacient колоната
                "datum_pregled": datum_str,  # датумот на преглед во формат како погоре
                "vreme_pregled": vreme_str,  # времето на преглед во формат како погоре
                "email_pacient": (r.get("email_pacient") or "").strip(),  # го зема маилот на пациентот, и отстранува сите празни места
                "telefon_pacient": (r.get("telefon_pacient") or "").strip(),  # го зема телефонскиот број на пациентот
                "dijagnoza": (r.get("dijagnoza") or "").strip(),  # се зема дијагнозата
                "terapija": (r.get("terapija") or "").strip(),  # се зема терапијата
            })
        
        # #region agent log
        debug_log("main.py:314", "login_lekar: Success", {"doctor_id": doctor["doctor_ID"], "termini_count": len(termini)}, hypothesis_id="E")
        # #endregion
        
        # Дали лекар мора да ја смени лозинката: само ако тековната лозинка е привремената Test123..
        must_change = verify_password(DEFAULT_LOZINKA_LEKARI, stored_password_hash)

        # Враќаме JSON објект со податоци за лекарот и неговите термини
        return {
            "doctor": {
                "doctor_ID": doctor["doctor_ID"],
                "name": doctor["name"],
                "surname": doctor["surname"],
                "email": doctor.get("email") or "",
                "specijalnost": (doctor.get("specijalnost") or "").strip(),
            },
            "termini": termini,
            "must_change_password": must_change,  # при прва најава – задолжителна смена на лозинка
        }
    except HTTPException as e:  # форматирана грешка
        # #region agent log
        debug_log("main.py:325", "login_lekar: HTTPException", {"status_code": e.status_code, "detail": e.detail}, hypothesis_id="E")
        # #endregion
        raise  # се продолжува
    except Exception as e:  # доколку се јави било која друга грешка
        # #region agent log
        debug_log("main.py:327", "login_lekar: Exception", {"error_type": type(e).__name__, "error_message": str(e)}, hypothesis_id="E")
        # #endregion
        raise HTTPException(status_code=500, detail=str(e))  # статусен код 500 и објаснување сместено во e
    finally:  # се проверува дали има конекција, ако има се затвора, се извршува без разлика дали има или нема грешка
        if conn and conn.is_connected():
            conn.close()


@router.patch("/promeni-lozinka")
async def promeni_lozinka_lekar(request: Request):
    """
    Смена на лозинка за најавен лекар. Потребна е тековната лозинка за верификација.
    Само најавениот лекар може да ја смени својата лозинка (побезбедно од опција „поставете за прв пат“).
    """
    conn = None
    try:
        data = await request.json()
        doctor_id = data.get("doctor_id")
        if doctor_id is not None and doctor_id != "":
            try:
                doctor_id = int(doctor_id)
            except (TypeError, ValueError):
                doctor_id = None
        trenutna = (data.get("trenutna_lozinka") or "").strip()
        nova = (data.get("nova_lozinka") or "").strip()

        if not doctor_id:
            raise HTTPException(status_code=400, detail="Недостасува doctor_id")
        if not trenutna:
            raise HTTPException(status_code=400, detail="Внесете ја тековната лозинка")
        ok, msg = _validna_lozinka_lekar(nova)
        if not ok:
            raise HTTPException(status_code=400, detail=msg)

        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)
        db_cursor.execute("SELECT doctor_ID, password FROM Doctors WHERE doctor_ID = %s", (doctor_id,))
        doctor = db_cursor.fetchone()
        if not doctor:
            raise HTTPException(status_code=404, detail="Лекар не е пронајден")

        stored = (doctor.get("password") or "").strip()
        if not stored:
            raise HTTPException(status_code=403, detail="Немате поставено лозинка. Користете ја опцијата за прв пат поставување или контактирајте го администраторот.")

        if not verify_password(trenutna, stored):
            raise HTTPException(status_code=401, detail="Тековната лозинка не е точна")

        nova_hash = hash_password(nova)
        db_cursor.execute(
            "UPDATE Doctors SET password = %s, must_change_password = 0 WHERE doctor_ID = %s",
            (nova_hash, doctor_id)
        )
        conn.commit()
        return {"message": "Лозинката е успешно променета."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()


@router.get("/termini")
def get_lekari_termini(email: str):             # funkcija za vrakanje na terminite kaj soodveten lekar, a za da se vidam se korist email adresa
    if not email or not email.strip():          # ako ne e vnesen mail ili ne e validen mail 
        raise HTTPException(status_code=400, detail="Внесете е-пошта")      # se javuva 400 statuden kod so vnesete e-posta prikaz na korisnikot
    conn = None         # nema konekcija
    try:
        conn = get_connection()     # konekcija so bazata na podatoci 
        db_cursor = conn.cursor(dictionary=True) #db_cursor objekt sto ovozmozuva da se vrsi sql naredba, argumento (dictionary=True) ni go dava izlezot kak orecenica ne kako tuples
        # selekcija na lekar spore mail adresa vnesena i zapisana vo %s
        db_cursor.execute(
            "SELECT doctor_ID, name, surname, email, specialty AS specijalnost FROM Doctors WHERE email = %s",
            (email.strip(),) # se vmetnuva parametarot, mailot
        )
        doctor = db_cursor.fetchone()      # se dava lekarot so mail, treba da bide eden bidejki sekoj lekar ima unikaten mail 
        if not doctor:                  # ako ne e pronajden mail na lekar koj se sovpaga so nekoj od bazata 
            raise HTTPException(status_code=404, detail="Не е пронајден лекар со таква е-пошта")    # se dava 404 Not Found status i objasnuvanje
        doctor_id = doctor["doctor_ID"]     # ako e pronajden lekar so vnesenito mail se zema soodvetnoto id na lekarot
        # zema terminite so dijagnoza i terapija od Termin_pregled tabelata
        # COALESCE: ako dijagnoza/terapija e NULL vo bazata, vrati prazen string '' namesto NULL
        # ВАЖНО: Според базата, колоните се: Ime_pacient, Ime_lekar (со голема буква I)
        db_cursor.execute("""
            SELECT termin_ID, Ime_pacient, datum_pregled, vreme_pregled, email_pacient, telefon_pacient,
                   COALESCE(dijagnoza, '') AS dijagnoza, COALESCE(terapija, '') AS terapija
            FROM Termin_pregled
            WHERE doctor_ID = %s AND (status_pregled IS NULL OR status_pregled = 'закажан')
            ORDER BY datum_pregled, vreme_pregled
        """, (doctor_id,))
        rows = db_cursor.fetchall()    # vo rows se zemaat site termini kaj lekar
        termini = []                # lista za termini
        for r in rows:              # r minuva niz site termini
            d = r.get("datum_pregled")      # d- datum na pregled, ako najde termin se smestuva datumot na pregled
            t = r.get("vreme_pregled")      # t - vreme na pregled, ako e pronajden se smestuva vremeto na pregled
            # formatiranje na datumot vo oblik [godina-mesec-den]
            datum_str = d.strftime("%Y-%m-%d") if d and hasattr(d, "strftime") else (str(d)[:10] if d else "")
            # formatiranje na vremeto: ako e datetime/time objekt, koristi strftime; inaku kako string (frontend ke go formatira)
            if t and hasattr(t, "strftime"):
                vreme_str = t.strftime("%H:%M")
            else:
                vreme_str = str(t) if t else ""
            # dodavanje vo listata
            # ВАЖНО: Користиме Ime_pacient од базата (со голема буква I)
            termini.append({
                "termin_ID": r.get("termin_ID"),
                "ime_pacient": (r.get("Ime_pacient") or "").strip(),    # go zema imeto na pacientot od Ime_pacient kolonata
                "datum_pregled": datum_str,         # datumot na pregled vo formatoto kako pogore
                "vreme_pregled": vreme_str,        # vremeto na pregled vo formatot kako pogore
                "email_pacient": (r.get("email_pacient") or "").strip(),        # go zema mailot na paciento, i otstrnuva site prazni mesta
                "telefon_pacient": (r.get("telefon_pacient") or "").strip(),    # go zema telefonskiot broj na pacientot
                "dijagnoza": (r.get("dijagnoza") or "").strip(),                # se zema dijagnozata
                "terapija": (r.get("terapija") or "").strip(),                  # se zema terapijata
            })
        return {        # dava JSON objekti 
            "doctor": {
                "doctor_ID": doctor["doctor_ID"],     # ID na lekarot od bazata
                "name": doctor["name"],         # imeto na lekarot
                "surname": doctor["surname"],   # prezime na lekar 
                "email": doctor.get("email") or "", #mail na lekar
                "specijalnost": (doctor.get("specijalnost") or "").strip(), #vraka specijalnost na lekarot
            },
            "termini": termini,     # site termini za lekarot   
        }
    except HTTPException:               # formatirana greska
        raise                               # se prodolzuva
    except Exception as e:              # dokolku se javi bilo koja druga greska   
        raise HTTPException(status_code=500, detail=str(e))   # statusen kod 500 i objasnuvanje smesteno vo e
    finally:                        # se proveruva dali ima konekcija, ako ima se zatvara, se izvrasuva bez razlika dali ima ili nema greksa
        if conn and conn.is_connected():
            conn.close()


@router.get("/moj-raspored/{lekar_id}")
def get_moj_raspored(lekar_id: int, datum: Optional[str] = None):
    """
    Endpoint за приказ на распоред на термини за одреден лекар.
    Прифаќа lekar_id и опционален параметар datum (ако нема датум, користи го денешниот).
    Прави JOIN со табелата patient за да ги извлече името и презимето на пациентот.
    Резултатот е сортиран по време.
    """
    conn = None
    try:
        # Ако нема датум, користи го денешниот
        if not datum:
            datum = datetime.now().date().strftime("%Y-%m-%d")
        else:
            # Проверка за ISO формат
            if "T" in datum:
                datum = datum.split("T")[0]
        
        # Валидација на датумот
        try:
            appointment_date = datetime.strptime(datum, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Неважечки формат на датум")
        
        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)
        
        # Проверка дали лекарот постои
        db_cursor.execute("SELECT doctor_ID, name, surname FROM Doctors WHERE doctor_ID = %s", (lekar_id,))
        doctor = db_cursor.fetchone()
        if not doctor:
            raise HTTPException(status_code=404, detail="Лекар не е пронајден")
        
        # Земи ги термините за лекарот на одреден датум со JOIN со patient табелата
        # JOIN преку email_pacient од Termin_pregled со email од patient табелата
        db_cursor.execute("""
            SELECT 
                tp.termin_ID,
                tp.datum_pregled,
                TIME(tp.vreme_pregled) as vreme_pregled,
                tp.status_pregled,
                tp.Ime_pacient,
                tp.email_pacient,
                COALESCE(p.name_patient, '') AS ime_pacient,
                COALESCE(p.surname_patient, '') AS prezime_pacient
            FROM Termin_pregled tp
            LEFT JOIN patient p ON LOWER(TRIM(tp.email_pacient)) = LOWER(TRIM(p.email))
            WHERE tp.doctor_ID = %s 
                AND DATE(tp.datum_pregled) = %s
                AND (tp.status_pregled IS NULL OR tp.status_pregled != 'откажан')
            ORDER BY tp.vreme_pregled ASC
        """, (lekar_id, datum))
        
        rows = db_cursor.fetchall()
        raspored = []
        
        for r in rows:
            # Форматирање на времето
            vreme = r.get("vreme_pregled")
            if vreme and hasattr(vreme, "strftime"):
                vreme_str = vreme.strftime("%H:%M")
            elif vreme and hasattr(vreme, "total_seconds"):
                s = int(vreme.total_seconds())
                vreme_str = f"{s // 3600:02d}:{(s % 3600) // 60:02d}"
            else:
                vreme_str = str(vreme)[:5] if vreme else ""
            
            # Ако имаме име и презиме од patient табелата, користи ги, инаку користи Ime_pacient
            ime_pacient = ""
            prezime_pacient = ""
            
            if r.get("ime_pacient") and r.get("prezime_pacient"):
                ime_pacient = r.get("ime_pacient", "").strip()
                prezime_pacient = r.get("prezime_pacient", "").strip()
            elif r.get("Ime_pacient"):
                # Ако нема JOIN, користи го комбинираното име од Termin_pregled
                ime_puno = r.get("Ime_pacient", "").strip()
                parts = ime_puno.split(" ", 1)
                ime_pacient = parts[0] if len(parts) > 0 else ""
                prezime_pacient = parts[1] if len(parts) > 1 else ""
            
            raspored.append({
                "termin_ID": r.get("termin_ID"),
                "datum": datum,
                "vreme": vreme_str,
                "status": r.get("status_pregled") or "закажан",
                "ime_pacient": ime_pacient,
                "prezime_pacient": prezime_pacient,
                "ime_puno": f"{ime_pacient} {prezime_pacient}".strip() or r.get("Ime_pacient", "").strip(),
                "email_pacient": r.get("email_pacient", "").strip()
            })
        
        return {
            "lekar": {
                "doctor_ID": doctor["doctor_ID"],
                "ime": doctor["name"],
                "prezime": doctor["surname"]
            },
            "datum": datum,
            "raspored": raspored
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()


@router.get("/{doctor_id}/dezurstva")
def get_dezurstva(doctor_id: int):
    """
    Endpoint за вчитување на распоред на дежурства за одреден лекар.
    Прво проверува дали има дежурства во базата, ако нема, користи динамичко пресметување.
    """
    conn = None
    try:
        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)
        
        # Земи ги податоците за лекарот
        db_cursor.execute("SELECT doctor_ID, name, surname, specialty AS specijalnost FROM Doctors WHERE doctor_ID = %s", (doctor_id,))
        doctor = db_cursor.fetchone()
        if not doctor:
            raise HTTPException(status_code=404, detail="Лекар не е пронајден")
        
        # Прво провери дали има дежурства во базата
        db_cursor.execute("""
            SELECT dezurstvo_ID, datum, oddel, vreme_od, vreme_do, napomena
            FROM Dezurstva
            WHERE doctor_ID = %s
            ORDER BY datum ASC, vreme_od ASC
        """, (doctor_id,))
        
        dezurstva_from_db = db_cursor.fetchall()
        
        if dezurstva_from_db:
            # Ако има дежурства во базата, врати ги
            result = []
            for row in dezurstva_from_db:
                result.append({
                    "datum": row["datum"].strftime("%Y-%m-%d") if row["datum"] else None,
                    "den": row["datum"].strftime("%d") if row["datum"] else "",
                    "oddel": row["oddel"],
                    "vreme_od": str(row["vreme_od"]) if row["vreme_od"] else "08:00",
                    "vreme_do": str(row["vreme_do"]) if row["vreme_do"] else "20:00",
                    "napomena": row["napomena"]
                })
            return result
        
        # Ако нема дежурства во базата, користи динамичко пресметување како fallback
        doctor_name = f"{doctor['name']} {doctor['surname']}"
        specialty = doctor.get('specijalnost', '')
        dezurstva = calculate_dezurstva(doctor_name, specialty)
        
        return dezurstva
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()


def calculate_dezurstva(doctor_name: str, specialty: str):
    """
    Пресметува распоред на дежурства врз основа на името на лекарот и специјалноста.
    """
    from datetime import datetime, timedelta
    
    # Дефинирање на распоредите за различни специјалности
    # Распоред за Акушерство & Гинекологија, Педијатрија, Кардиологија, Хирургија & Ортопедија
    akusherstvo_ginekologija = [
        "Станка Велкова", "Габриела Читкушева", "Ивана Миткова Донева", 
        "Наталија Атанасова", "Ристо Јанкулов"
    ]
    
    pedijatrija = [
        "Марија Самарџиска", "Валентина Златковска", "Вишна Гацова",
        "Емилија Шриптова", "Ирена Пешовска", "Јадранка Бреслиева", "М. Димитровска Иванова"
    ]
    
    kardiologija = [
        "Сашко Николов", "Александар Серафимов", "Благој Василев",
        "Гордана Камчева", "Маријан Јовев", "Маријан Сарџов", "Радојка Трајковска",
        "Славица Јорданова", "Никола Арсовски"
    ]
    
    hirurgija_ortopedija = [
        "Сашо Цеков", "Ален Георгиев", "Ѓорги Велков", "Илија Милев",
        "Никола Трпковски", "Стефан Петровски", "Кирил Ушинов", "Методи Илиев"
    ]
    
    # Распоред за деновите 01-31 со деновите од неделата
    danovi = [
        (1, "Нед"), (2, "Пон"), (3, "Вто"), (4, "Сре"), (5, "Чет"),
        (6, "Пет"), (7, "Саб"), (8, "Нед"), (9, "Пон"), (10, "Вто"),
        (11, "Сре"), (12, "Чет"), (13, "Пет"), (14, "Саб"), (15, "Нед"),
        (16, "Пон"), (17, "Вто"), (18, "Сре"), (19, "Чет"), (20, "Пет"),
        (21, "Саб"), (22, "Нед"), (23, "Пон"), (24, "Вто"), (25, "Сре"),
        (26, "Чет"), (27, "Пет"), (28, "Саб"), (29, "Нед"), (30, "Пон"),
        (31, "Вто")
    ]
    
    # Распоред за деновите (ден, Акушерство & Гинекологија, Педијатрија, Кардиологија, Хирургија & Ортопедија)
    raspored_danovi = [
        (1, "Нед", "Станка Велкова", "Марија Самарџиска", "Сашко Николов", "Сашо Цеков"),
        (2, "Пон", "Габриела Читкушева", "Валентина Златковска", "Александар Серафимов", "Ален Георгиев"),
        (3, "Вто", "Ивана Миткова Донева", "Вишна Гацова", "Благој Василев", "Ѓорги Велков"),
        (4, "Сре", "Наталија Атанасова", "Емилија Шриптова", "Гордана Камчева", "Илија Милев"),
        (5, "Чет", "Ристо Јанкулов", "Ирена Пешовска", "Маријан Јовев", "Никола Трпковски"),
        (6, "Пет", "Станка Велкова", "Јадранка Бреслиева", "Маријан Сарџов", "Стефан Петровски"),
        (7, "Саб", "Габриела Читкушева", "М. Димитровска Иванова", "Радојка Трајковска", "Кирил Ушинов"),
        (8, "Нед", "Ивана Миткова Донева", "Марија Самарџиска", "Славица Јорданова", "Методи Илиев"),
        (9, "Пон", "Наталија Атанасова", "Валентина Златковска", "Никола Арсовски", "Ален Георгиев"),
        (10, "Вто", "Ристо Јанкулов", "Вишна Гацова", "Александар Серафимов", "Ѓорги Велков"),
        (11, "Сре", "Станка Велкова", "Емилија Шриптова", "Благој Василев", "Илија Милев"),
        (12, "Чет", "Габриела Читкушева", "Ирена Пешовска", "Гордана Камчева", "Никола Трпковски"),
        (13, "Пет", "Ивана Миткова Донева", "Јадранка Бреслиева", "Маријан Јовев", "Стефан Петровски"),
        (14, "Саб", "Наталија Атанасова", "М. Димитровска Иванова", "Маријан Сарџов", "Кирил Ушинов"),
        (15, "Нед", "Ристо Јанкулов", "Марија Самарџиска", "Радојка Трајковска", "Сашо Цеков"),
        (16, "Пон", "Станка Велкова", "Валентина Златковска", "Славица Јорданова", "Ален Георгиев"),
        (17, "Вто", "Габриела Читкушева", "Вишна Гацова", "Никола Арсовски", "Ѓорги Велков"),
        (18, "Сре", "Ивана Миткова Донева", "Емилија Шриптова", "Александар Серафимов", "Илија Милев"),
        (19, "Чет", "Наталија Атанасова", "Ирена Пешовска", "Благој Василев", "Никола Трпковски"),
        (20, "Пет", "Ристо Јанкулов", "Јадранка Бреслиева", "Гордана Камчева", "Стефан Петровски"),
        (21, "Саб", "Станка Велкова", "М. Димитровска Иванова", "Маријан Јовев", "Методи Илиев"),
        (22, "Нед", "Габриела Читкушева", "Марија Самарџиска", "Маријан Сарџов", "Кирил Ушинов"),
        (23, "Пон", "Ивана Миткова Донева", "Валентина Златковска", "Радојка Трајковска", "Ален Георгиев"),
        (24, "Вто", "Наталија Атанасова", "Вишна Гацова", "Славица Јорданова", "Ѓорги Велков"),
        (25, "Сре", "Ристо Јанкулов", "Емилија Шриптова", "Никола Арсовски", "Илија Милев"),
        (26, "Чет", "Станка Велкова", "Ирена Пешовска", "Александар Серафимов", "Никола Трпковски"),
        (27, "Пет", "Габриела Читкушева", "Јадранка Бреслиева", "Благој Василев", "Стефан Петровски"),
        (28, "Саб", "Ивана Миткова Донева", "М. Димитровска Иванова", "Гордана Камчева", "Сашо Цеков"),
        (29, "Нед", "Наталија Атанасова", "Марија Самарџиска", "Маријан Јовев", "Методи Илиев"),
        (30, "Пон", "Ристо Јанкулов", "Валентина Златковска", "Маријан Сарџов", "Ален Георгиев"),
        (31, "Вто", "Станка Велкова", "Вишна Гацова", "Радојка Трајковска", "Ѓорги Велков")
    ]
    
    # Ротации за други специјалности
    radiologija = ["Б. Ефтимова", "М. Лазаревски", "Р. Зикова", "А. Тонева Николова"]
    nevrologija = ["В. Димова", "В. Трајкова", "Е. Јовева", "Е. Личкова"]
    urologija = ["Б. Здравев", "В. Шопов", "В. Филипов"]
    nevrohirurgija = ["Владко Захариев", "Михаил Лазаров"]
    maksilofacijalna = ["Владимир Милошев"]
    
    dezurstva = []
    current_year = datetime.now().year
    current_month = datetime.now().month
    
    # Проверка за специјалности со фиксен распоред
    if "Акушерство" in specialty or "гиникологија" in specialty.lower() or "Гинекологија" in specialty:
        matched_days = []
        doctor_name_normalized = doctor_name.strip()
        doctor_surname = doctor_name.split()[-1] if doctor_name.split() else ""
        
        for dan, den_od_nedela, akusherstvo, pedijatrija, kardiologija, hirurgija in raspored_danovi:
            akusherstvo_normalized = akusherstvo.strip()
            if (akusherstvo_normalized == doctor_name_normalized or 
                akusherstvo_normalized in doctor_name_normalized or 
                doctor_name_normalized in akusherstvo_normalized or
                (doctor_surname and doctor_surname in akusherstvo_normalized)):
                try:
                    datum = datetime(current_year, current_month, dan)
                    matched_days.append(dan)
                    dezurstva.append({
                        "datum": datum.strftime("%Y-%m-%d"),
                        "den": f"{dan:02d} ({den_od_nedela})",
                        "oddel": "Акушерство & Гинекологија",
                        "vreme_od": "08:00",
                        "vreme_do": "20:00"
                    })
                except ValueError:
                    continue
    
    if "Педијатрија" in specialty:
        matched_days = []
        doctor_name_normalized = doctor_name.strip()
        doctor_surname = doctor_name.split()[-1] if doctor_name.split() else ""
        
        for dan, den_od_nedela, akusherstvo, pedijatrija, kardiologija, hirurgija in raspored_danovi:
            pedijatrija_normalized = pedijatrija.strip()
            if (pedijatrija_normalized == doctor_name_normalized or 
                pedijatrija_normalized in doctor_name_normalized or 
                doctor_name_normalized in pedijatrija_normalized or
                (doctor_surname and doctor_surname in pedijatrija_normalized)):
                try:
                    datum = datetime(current_year, current_month, dan)
                    matched_days.append(dan)
                    dezurstva.append({
                        "datum": datum.strftime("%Y-%m-%d"),
                        "den": f"{dan:02d} ({den_od_nedela})",
                        "oddel": "Педијатрија",
                        "vreme_od": "08:00",
                        "vreme_do": "20:00"
                    })
                except ValueError:
                    continue
    
    if "Кардиологија" in specialty:
        matched_days = []
        doctor_name_normalized = doctor_name.strip()
        doctor_surname = doctor_name.split()[-1] if doctor_name.split() else ""
        
        for dan, den_od_nedela, akusherstvo, pedijatrija, kardiologija, hirurgija in raspored_danovi:
            kardiologija_normalized = kardiologija.strip()
            if (kardiologija_normalized == doctor_name_normalized or 
                kardiologija_normalized in doctor_name_normalized or 
                doctor_name_normalized in kardiologija_normalized or
                (doctor_surname and doctor_surname in kardiologija_normalized)):
                try:
                    datum = datetime(current_year, current_month, dan)
                    matched_days.append(dan)
                    dezurstva.append({
                        "datum": datum.strftime("%Y-%m-%d"),
                        "den": f"{dan:02d} ({den_od_nedela})",
                        "oddel": "Кардиологија",
                        "vreme_od": "08:00",
                        "vreme_do": "20:00"
                    })
                except ValueError:
                    continue
    
    if "Хирургија" in specialty or "Ортопедија" in specialty:
        matched_days = []
        doctor_name_normalized = doctor_name.strip()
        doctor_surname = doctor_name.split()[-1] if doctor_name.split() else ""
        
        for dan, den_od_nedela, akusherstvo, pedijatrija, kardiologija, hirurgija in raspored_danovi:
            hirurgija_normalized = hirurgija.strip()
            
            # Подобро совпаѓање: провери дали целото име се совпаѓа или презимето
            if (hirurgija_normalized == doctor_name_normalized or 
                hirurgija_normalized in doctor_name_normalized or 
                doctor_name_normalized in hirurgija_normalized or
                (doctor_surname and doctor_surname in hirurgija_normalized)):
                try:
                    datum = datetime(current_year, current_month, dan)
                    matched_days.append(dan)
                    dezurstva.append({
                        "datum": datum.strftime("%Y-%m-%d"),
                        "den": f"{dan:02d} ({den_od_nedela})",
                        "oddel": "Хирургија & Ортопедија",
                        "vreme_od": "08:00",
                        "vreme_do": "20:00"
                    })
                except ValueError:
                    continue
    
    # Ротации за други специјалности
    # Радиологија: ротираат на секои 4 дена
    if "Радиологија" in specialty:
        lekar_index = None
        for i, lekar in enumerate(radiologija):
            # Проверка дали името на лекарот се совпаѓа
            # Проверува дали презимето или кратенката се совпаѓаат
            lekar_parts = lekar.split()
            doctor_parts = doctor_name.split()
            # Проверка дали некој дел од името на лекарот (особено презимето) се совпаѓа
            if any(part in doctor_name for part in lekar_parts) or any(part in lekar for part in doctor_parts):
                lekar_index = i
                break
        
        if lekar_index is not None:
            for day in range(1, 32):
                try:
                    datum = datetime(current_year, current_month, day)
                    # Пресметај кој лекар е на дежурство за овој ден (ротира на секои 4 дена)
                    # Ден 1, 5, 9, 13, 17, 21, 25, 29 = индекс 0
                    # Ден 2, 6, 10, 14, 18, 22, 26, 30 = индекс 1
                    # Ден 3, 7, 11, 15, 19, 23, 27, 31 = индекс 2
                    # Ден 4, 8, 12, 16, 20, 24, 28 = индекс 3
                    rotation_index = ((day - 1) % 4)
                    if rotation_index == lekar_index:
                        dezurstva.append({
                            "datum": datum.strftime("%Y-%m-%d"),
                            "den": f"{day:02d}",
                            "oddel": "Радиологија",
                            "vreme_od": "08:00",
                            "vreme_do": "20:00"
                        })
                except ValueError:
                    continue
    
    # Неврологија: ротираат на секои 4 дена
    if "Неврологија" in specialty:
        lekar_index = None
        for i, lekar in enumerate(nevrologija):
            lekar_parts = lekar.split()
            doctor_parts = doctor_name.split()
            if any(part in doctor_name for part in lekar_parts) or any(part in lekar for part in doctor_parts):
                lekar_index = i
                break
        
        if lekar_index is not None:
            for day in range(1, 32):
                try:
                    datum = datetime(current_year, current_month, day)
                    rotation_index = ((day - 1) % 4)
                    if rotation_index == lekar_index:
                        dezurstva.append({
                            "datum": datum.strftime("%Y-%m-%d"),
                            "den": f"{day:02d}",
                            "oddel": "Неврологија",
                            "vreme_od": "08:00",
                            "vreme_do": "20:00"
                        })
                except ValueError:
                    continue
    
    # Урологија: ротираат на секои 3 дена
    if "Урологија" in specialty:
        lekar_index = None
        for i, lekar in enumerate(urologija):
            lekar_parts = lekar.split()
            doctor_parts = doctor_name.split()
            if any(part in doctor_name for part in lekar_parts) or any(part in lekar for part in doctor_parts):
                lekar_index = i
                break
        
        if lekar_index is not None:
            for day in range(1, 32):
                try:
                    datum = datetime(current_year, current_month, day)
                    rotation_index = ((day - 1) % 3)
                    if rotation_index == lekar_index:
                        dezurstva.append({
                            "datum": datum.strftime("%Y-%m-%d"),
                            "den": f"{day:02d}",
                            "oddel": "Урологија",
                            "vreme_od": "08:00",
                            "vreme_do": "20:00"
                        })
                except ValueError:
                    continue
    
    # Неврохирургија: се менуваат наизменично (секој втор ден)
    if "Неврохирургија" in specialty:
        lekar_index = None
        for i, lekar in enumerate(nevrohirurgija):
            lekar_parts = lekar.split()
            doctor_parts = doctor_name.split()
            if any(part in doctor_name for part in lekar_parts) or any(part in lekar for part in doctor_parts):
                lekar_index = i
                break
        
        if lekar_index is not None:
            for day in range(1, 32):
                try:
                    datum = datetime(current_year, current_month, day)
                    # Наизменично: ден 1, 3, 5, ... = индекс 0, ден 2, 4, 6, ... = индекс 1
                    rotation_index = (day - 1) % len(nevrohirurgija)
                    if rotation_index == lekar_index:
                        dezurstva.append({
                            "datum": datum.strftime("%Y-%m-%d"),
                            "den": f"{day:02d}",
                            "oddel": "Неврохирургија",
                            "vreme_od": "08:00",
                            "vreme_do": "20:00"
                        })
                except ValueError:
                    continue
    
    # Максилофацијална: приправност по потреба
    if "Максилофацијална" in specialty or "Максилофацијална хирургија" in specialty:
        if "Владимир Милошев" in doctor_name or "Милошев" in doctor_name:
            # Приправност по потреба - може да се додаде логика за специфични датуми
            dezurstva.append({
                "datum": datetime(current_year, current_month, 1).strftime("%Y-%m-%d"),
                "den": "01",
                "oddel": "Максилофацијална хирургија",
                "vreme_od": "08:00",
                "vreme_do": "20:00",
                "napomena": "Приправност по потреба"
            })
    
    # Сортирај по датум
    dezurstva.sort(key=lambda x: x['datum'])
    
    return dezurstva


@router.post("/register")
async def register_lekar(request: Request):
    """
    Endpoint за регистрација на нов лекар.
    Креира нов профил за лекар со име, презиме, специјалност, е-пошта и лозинка.
    Корисничкото име се генерира автоматски како име.презиме (мали букви).
    """
    conn = None
    try:
        # #region agent log
        debug_log("main.py:882", "register_lekar: Request received", {"timestamp": datetime.now().isoformat()}, hypothesis_id="A")
        # #endregion
        data = await request.json()
        
        # #region agent log
        debug_log("main.py:886", "register_lekar: Data parsed", {"ime": data.get("ime"), "prezime": data.get("prezime"), "specialty": data.get("specialty"), "email": data.get("email"), "has_password": bool(data.get("password"))}, hypothesis_id="A")
        # #endregion
        
        ime = (data.get("ime") or "").strip()
        prezime = (data.get("prezime") or "").strip()
        specialty = (data.get("specialty") or "").strip()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        
        # Валидација
        if not ime or not prezime:
            raise HTTPException(status_code=400, detail="Внесете име и презиме")
        if not specialty:
            raise HTTPException(status_code=400, detail="Внесете специјалност")
        if not email:
            raise HTTPException(status_code=400, detail="Внесете е-пошта")
        # Базична email валидација
        if '@' not in email or '.' not in email.split('@')[1]:
            raise HTTPException(status_code=400, detail="Внесете валидна е-пошта")
        ok, msg = _validna_lozinka_lekar(password)
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        
        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)
        
        # Генерирање на корисничко име (име.презиме на латиница во мали букви)
        # ВАЖНО: Корисничкото име мора да биде на латиница, не на кирилица
        ime_lat = transliterate_mk_to_lat(ime)
        prezime_lat = transliterate_mk_to_lat(prezime)
        username = f"{ime_lat}.{prezime_lat}"
        
        # Проверка дали веќе постои лекар со истото корисничко име (име.презиме на латиница)
        # Ги земаме сите лекари и проверуваме во Python дали транслитерираното корисничко име се совпаѓа
        db_cursor.execute("SELECT doctor_ID, name, surname FROM Doctors")
        existing_doctors = db_cursor.fetchall()
        for existing_doctor in existing_doctors:
            existing_ime_lat = transliterate_mk_to_lat(existing_doctor.get("name") or "")
            existing_prezime_lat = transliterate_mk_to_lat(existing_doctor.get("surname") or "")
            existing_username = f"{existing_ime_lat}.{existing_prezime_lat}"
            if existing_username == username:
                raise HTTPException(status_code=400, detail="Лекар со ова име и презиме веќе постои")
        
        # Проверка дали веќе постои лекар со истата е-пошта
        db_cursor.execute("SELECT doctor_ID FROM Doctors WHERE LOWER(email) = %s", (email,))
        if db_cursor.fetchone():
            raise HTTPException(status_code=400, detail="Лекар со оваа е-пошта веќе постои")
        
        # Хеширање на лозинката (bcrypt)
        password_hash = hash_password(password)
        
        # #region agent log
        debug_log("main.py:929", "register_lekar: Attempting INSERT", {"ime": ime, "prezime": prezime, "specialty": specialty, "email": email, "username": username}, hypothesis_id="A")
        # #endregion
        
        # Креирање на нов лекар (при само-регистрација лозинката е веќе избрана, не мора да се менува)
        db_cursor.execute("""
            INSERT INTO Doctors (name, surname, specialty, email, password, must_change_password)
            VALUES (%s, %s, %s, %s, %s, 0)
        """, (ime, prezime, specialty, email, password_hash))
        
        conn.commit()
        doctor_id = db_cursor.lastrowid
        
        # #region agent log
        debug_log("main.py:937", "register_lekar: Success", {"doctor_id": doctor_id, "username": username}, hypothesis_id="A")
        # #endregion
        
        return {
            "message": "Успешно се регистриравте!",
            "doctor_ID": doctor_id,
            "username": username
        }
    except HTTPException as e:
        # #region agent log
        debug_log("main.py:942", "register_lekar: HTTPException", {"status_code": e.status_code, "detail": e.detail}, hypothesis_id="A")
        # #endregion
        raise
    except Exception as e:
        # #region agent log
        debug_log("main.py:945", "register_lekar: Exception", {"error_type": type(e).__name__, "error_message": str(e)}, hypothesis_id="A")
        # #endregion
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()


