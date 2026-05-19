""" Oceni zavrshen pregled preku AI — samo za logiran pacient. Pacient pisuva ocena 1-5 + komentar, Groq izvlekuva podatoci, bara zavrshen termin vo baza, INSERT/UPDATE vo Pregled_feedback. """
from ai._kernel.prompt_loader import load_prompt
from ai._kernel.utils import format_vreme
from datetime import date
from database import get_connection
from ai._kernel.groq_helpers import groq_zadolzhitelen, izvlechi_json_so_ai
from ai.pacient.slobodni_termini import zimi_site_lekari
# funkcija koja go prasuva ai od porakata na pacientot da izvlece ocena, komentar, lekar i datum
def izvlechi_ocena_podatoci(prasanje: str) -> dict:
    if msg := groq_zadolzhitelen(): # proverka dali groq e dostapen
        return {"_error": msg, "ocena": None, "komentar": None, "doctor_id": None, "datum": None} # vraka greska ako nema ai
    site_lekari = zimi_site_lekari() # gi zema site lekari od baza za zatvorena lista vo prompt
    lista_text = "" # prazen string za da se nalepi listata na lekari
    for lekar in site_lekari: # pominuva niz site lekari
        spec = lekar.get("specialty") or "Општа пракса" # specijalnost ili opsta praksa ako nema
        lista_text += f"ID {lekar['doctor_ID']}: Д-р {lekar['name']} {lekar['surname']} - {spec}\n" # eden red vo promptot
    denes = date.today().strftime("%Y-%m-%d") # denesniot datum za ai
    den_vo_nedela = ["понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"][date.today().weekday()] # den vo nedelata
    full_prompt = f"""
Денес: {denes} ({den_vo_nedela})

Лекари:
{lista_text}

Корисник: „{prasanje}"

Извлечи ocena, komentar, doctor_id и datum.
""".strip() # go formira celiot tekst sto ke se prati do groq
    podatoci = izvlechi_json_so_ai(full_prompt, load_prompt("oceni_extract"), log_tag="oceni_pregled") # povik do groq so prompt od fajl
    if podatoci.get("_error"): # ako ai ne odgovori ili e greska
        return podatoci # se vraka recnikot so greska
    ocena_raw = podatoci.get("ocena") # sirovata vrednost od json
    try:
        ocena = int(ocena_raw) if ocena_raw is not None else None # ocenata mora da e broj 1-5
    except (TypeError, ValueError):
        ocena = None # nevaliden broj
    return {
        "ocena": ocena,
        "komentar": (podatoci.get("komentar") or None),
        "doctor_id": podatoci.get("doctor_id"),
        "datum": podatoci.get("datum"),
    } # go vraka izvleceniot recnik
# funkcija koja bara vo baza zavrseni pregledi na toj pacient
def najdi_zaversen_termin(pacient_email: str, doctor_id: int | None, datum: str | None) -> list[dict]:
    conn = None # pocetno nema konekcija
    try:
        conn = get_connection() # se pravi konekcija so bazata
        cur = conn.cursor(dictionary=True) # kursor so recnici namesto tuple
        query = """
            SELECT t.termin_ID, t.datum_pregled, t.vreme_pregled,
                   t.ime_lekar, t.specijalnost_termin, t.doctor_ID,
                   pf.feedback_ID AS postoecka_ocena
            FROM Termin_pregled t
            LEFT JOIN Pregled_feedback pf ON pf.termin_ID = t.termin_ID
            WHERE LOWER(TRIM(t.email_pacient)) = LOWER(TRIM(%s))
              AND t.status_pregled = 'завршен'
        """ # osnoven sql za zavrsheni termini na pacientot
        params: list[object] = [pacient_email] # emailot e prv parametar
        if doctor_id: # opcionalen filter po lekar
            query += " AND t.doctor_ID = %s"
            params.append(doctor_id) # se dodava id na lekarot
        if datum: # opcionalen filter po datum
            query += " AND t.datum_pregled = %s"
            params.append(datum) # se dodava datumot
        query += " ORDER BY t.datum_pregled DESC, t.vreme_pregled DESC" # najnovite prvi
        cur.execute(query, params) # se izvrsuva baranjeto
        rezultati = cur.fetchall() # site redovi od baza
        cur.close() # zatvaranje na kursorot
        return rezultati # lista na termini
    except Exception as e:
        print(f"[oceni_pregled] greska: {e}") # log za debug
        return [] # prazna lista pri greska
    finally:
        if conn:
            conn.close() # sekogas se zatvara konekcijata
# funkcija koja zacuvuva ocena vo Pregled_feedback
def vmetni_ili_azhuriraj_ocena(termin_id: int, ocena: int, komentar: str | None) -> bool:
    conn = None
    try:
        conn = get_connection() # konekcija so mysql
        cur = conn.cursor() # obicen kursor za insert
        cur.execute(
            """
            INSERT INTO Pregled_feedback (termin_ID, ocena, komentar)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
              ocena = VALUES(ocena),
              komentar = VALUES(komentar),
              datum_na_ocena = CURRENT_TIMESTAMP
            """,
            (termin_id, ocena, komentar),
        ) # nov zapis ili update ako veke postoi ocena za terminot
        conn.commit() # promenite se zacuvuvaat vo baza
        cur.close()
        return True # uspesno
    except Exception as e:
        print(f"[oceni_pregled] insert greska: {e}")
        return False # neuspesno
    finally:
        if conn:
            conn.close()
# glavna funkcija — ja povikuva routerot koga intent e oceni_pregled
def odgovori_za_ocenuvanje(prasanje: str, pacient: dict | None) -> str:
    if not pacient or not pacient.get("email"): # mora da e najaven pacient
        return (
            'За да оцениш преглед, прво најави се како пациент. '
            'Кликни „Најави се!" горе десно.'
        )
    izvleceno = izvlechi_ocena_podatoci(prasanje) # groq gi izvlekuva podatocite
    if izvleceno.get("_error"):
        return str(izvleceno["_error"]) # poraka od ai servisot
    ocena = izvleceno.get("ocena")
    komentar = izvleceno.get("komentar")
    doctor_id = izvleceno.get("doctor_id")
    datum_str = izvleceno.get("datum")
    if ocena is None or ocena < 1 or ocena > 5: # validacija na ocenata
        return (
            'Не разбрав која оцена сакаш да дадеш. Кажи број од 1 до 5.\n'
            'Пример: „Оцена 5 за д-р Петров — беше одличен"'
        )
    termini = najdi_zaversen_termin(pacient["email"], doctor_id, datum_str) # baranje vo baza
    DENOVI = ["Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"] # iminja na denovi za prikaz
    if not termini: # nema zavrshen pregled sto odgovara
        return (
            'Не најдов завршен преглед што одговара. Оцена може да се остави '
            'само за прегледи со статус „завршен“. Биди поспецифичен — '
            'спомни го лекарот и/или датумот.'
        )
    if len(termini) > 1: # poveke pregledi — prasame koj tocno
        delovi = ["Имаш повеќе завршени прегледи. Кој точно сакаш да го оцениш?", ""] # pocetok na odgovorot
        for t in termini[:10]: # najvise 10 stavki vo listata
            datum = t["datum_pregled"]
            den_ime = DENOVI[datum.weekday()] # den od nedelata
            vreme = format_vreme(t["vreme_pregled"]) # formatirano vreme
            oznaka = " (веќе оценет)" if t.get("postoecka_ocena") else "" # dali veke ima ocena
            delovi.append(
                f"- {den_ime} {datum.strftime('%d.%m.%Y')} во {vreme} "
                f"кај Д-р {t['ime_lekar']} ({t['specijalnost_termin']}){oznaka}"
            ) # eden red vo listata za pacientot
        delovi.append("") # prazen red
        delovi.append('Биди поточен: „Оцена 5 за прегледот кај д-р [презиме] на [датум]"')
        return "\n".join(delovi) # vraka tekst so site opcii
    t = termini[0] # tocno eden termin — zacuvuvame ocena
    veke_imal_ocena = bool(t.get("postoecka_ocena")) # dali e update ili prva ocena
    if not vmetni_ili_azhuriraj_ocena(t["termin_ID"], ocena, komentar):
        return "Не успеа да ја зачувам оцената. Пробај пак."
    datum = t["datum_pregled"]
    den_ime = DENOVI[datum.weekday()]
    vreme = format_vreme(t["vreme_pregled"])
    naslov = "Оцената е ажурирана!" if veke_imal_ocena else "Благодариме за оцената!" # naslov spored situacijata
    zvezdi = "★" * ocena + "☆" * (5 - ocena) # vizuelni zvezdi za prikaz
    delovi = [
        naslov,
        "",
        f"Лекар: Д-р {t['ime_lekar']}",
        f"Специјалност: {t['specijalnost_termin']}",
        f"Датум: {den_ime}, {datum.strftime('%d.%m.%Y')} во {vreme}",
        f"Оцена: {zvezdi} ({ocena}/5)",
    ] # linii za finalniot odgovor
    if komentar:
        delovi.append(f"Коментар: {komentar}") # opcionalen komentar
    return "\n".join(delovi) # tekstualen odgovor do pacientot vo chat
