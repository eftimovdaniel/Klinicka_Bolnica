""" Oceni zavrshen pregled preku AI — samo za logiran pacient. """

# Import na potrebni moduli za prompt, formatiranje, datum, baza, groq i lista lekari
from ai._kernel.prompt_loader import load_prompt          # Vcituvanje na prompt
from ai._kernel.utils import format_datum, format_vreme    # Formatiranje na datum i vreme
from datetime import date                                  # Rabota so datum
from database import get_connection                        # DB konekcija
from ai._kernel.groq_helpers import groq_zadolzhitelen, izvlechi_json_so_ai # AI pomosnici
from ai.pacient.slobodni_termini import zimi_site_lekari   # Lista lekari


# Groq izvlekuva ocena, komentar, doctor_id i datum od porakata
def izvlechi_ocena_podatoci(prasanje: str) -> dict:
    if msg := groq_zadolzhitelen():                        # Proverka dali AI raboti
        return {"_error": msg, "ocena": None, "komentar": None, "doctor_id": None, "datum": None}
    site_lekari = zimi_site_lekari()                       # Zemi lista na lekari
    lista_text = ""                                        # Inicijaliziraj string
    for lekar in site_lekari:                              # Loop niz lekarite
        spec = lekar.get("specialty") or "Општа пракса"   # Defolt specijalnost
        lista_text += f"ID {lekar['doctor_ID']}: Д-р {lekar['name']} {lekar['surname']} - {spec}\n"
    denes = date.today().strftime("%Y-%m-%d")              # Denesen datum
    den_vo_nedela = [
        "понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"
    ][date.today().weekday()]                              # Den vo nedelata
    full_prompt = f"""Денес: {denes} ({den_vo_nedela}) Лекари: {lista_text} Корисник: „{prasanje}" Извлечи ocena, komentar, doctor_id и datum.""".strip()   # definiranje na izgledot na promtot                                   # Formatiraj prompt
    podatoci = izvlechi_json_so_ai(
        full_prompt, load_prompt("oceni_extract"), log_tag="oceni_pregled"
    ) # Povikaj AI
    if podatoci.get("_error"):
        return podatoci                                    # Vrati greska
    ocena_raw = podatoci.get("ocena")                      # Zemi sirova ocena
    try:
        ocena = int(ocena_raw) if ocena_raw is not None else None # Konvertiraj vo broj
    except (TypeError, ValueError):
        ocena = None                                       # Nevaliden broj
    return {
        "ocena": ocena,
        "komentar": (podatoci.get("komentar") or None),
        "doctor_id": podatoci.get("doctor_id"),
        "datum": podatoci.get("datum"),
    }


# Bara zavrshen termin vo baza za toj pacient (opcionalno lekar i datum)
def najdi_zaversen_termin(
    pacient_email: str, doctor_id: int | None, datum: str | None
) -> list[dict]:
    conn = None                                            # Prazna konekcija
    try:
        conn = get_connection()                            # Otvori baza
        cur = conn.cursor(dictionary=True)                 # Kursor so recnik
        query = """
            SELECT t.termin_ID, t.datum_pregled, t.vreme_pregled,
                   t.ime_lekar, t.specijalnost_termin, t.doctor_ID,
                   pf.feedback_ID AS postoecka_ocena
            FROM Termin_pregled t
            LEFT JOIN Pregled_feedback pf ON pf.termin_ID = t.termin_ID
            WHERE LOWER(TRIM(t.email_pacient)) = LOWER(TRIM(%s))
              AND t.status_pregled = 'завршен'
        """ # Samo zavrsheni pregledi (kirilica kako vo baza)
        params: list[object] = [pacient_email]             # Postavi email parametar
        if doctor_id:                                      # Filtriraj po lekar
            query += " AND t.doctor_ID = %s"
            params.append(doctor_id)
        if datum:                                          # Filtriraj po datum
            query += " AND t.datum_pregled = %s"
            params.append(datum)
        query += " ORDER BY t.datum_pregled DESC, t.vreme_pregled DESC" # Sortiraj najnovi
        cur.execute(query, params)                         # Izvrsi query
        rezultati = cur.fetchall()                         # Zemi site redovi
        cur.close()                                        # Zatvori kursor
        return rezultati                                   # Vrati termini
    except Exception as e:
        print(f"[oceni_pregled] greska: {e}")              # Logiraj greska
        return []
    finally:
        if conn:
            conn.close()                                   # Zatvori konekcija


# Zacuvaj ili azuriraj ocena vo Pregled_feedback (upsert)
def vmetni_ili_azhuriraj_ocena(termin_id: int, ocena: int, komentar: str | None) -> bool:
    conn = None
    try:
        conn = get_connection()                            # Konektiraj baza
        cur = conn.cursor()                                # Otvori kursor
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
        ) # Upsert logika
        conn.commit()                                      # Zacuvaj promeni
        cur.close()                                        # Zatvori kursor
        return True                                        # Uspesno
    except Exception as e:
        print(f"[oceni_pregled] insert greska: {e}")       # Logiraj greska
        return False
    finally:
        if conn:
            conn.close()                                   # Zatvori konekcija


# Glaven handler — intent oceni_pregled
def odgovori_za_ocenuvanje(prasanje: str, pacient: dict | None) -> str:
    if not pacient or not pacient.get("email"):            # Proverka za pacient
        return (
            'За да оцениш преглед, прво најави се како пациент. '
            'Кликни „Најави се!" горе десно.'
        )

    izvleceno = izvlechi_ocena_podatoci(prasanje)          # Parsiraj so AI
    if izvleceno.get("_error"):
        return str(izvleceno["_error"])                    # Greska od Groq

    ocena = izvleceno.get("ocena")
    komentar = izvleceno.get("komentar")
    doctor_id = izvleceno.get("doctor_id")
    datum_str = izvleceno.get("datum")

    if ocena is None or ocena < 1 or ocena > 5:            # Validacija na ocena
        return (
            'Не разбрав која оцена сакаш да дадеш. Кажи број од 1 до 5.\n'
            'Пример: „Оцена 5 за д-р Петров — беше одличен"'
        )

    termini = najdi_zaversen_termin(pacient["email"], doctor_id, datum_str) # Najdi termin
    DENOVI = [
        "Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"
    ] # Iminja na denovi za prikaz

    if not termini:
        return (
            'Не најдов завршен преглед што одговара. Оцена може да се остави '
            'само за прегледи со статус „завршен“. Биди поспецифичен — '
            'спомни го лекарот и/или датумот.'
        )

    if len(termini) > 1:                                 # Poveke termini — prasaj za pojasnuvanje
        delovi = ["Имаш повеќе завршени прегледи. Кој точно сакаш да го оцениш?", ""]
        for t in termini[:10]:                           # Najmnogu 10 vo listata
            datum = t["datum_pregled"]
            den_ime = DENOVI[datum.weekday()]              # Den od nedelata
            vreme = format_vreme(t["vreme_pregled"])       # Formatirano vreme
            oznaka = " (веќе оценет)" if t.get("postoecka_ocena") else ""
            delovi.append(
                f"- {den_ime} {format_datum(datum)} во {vreme} "
                f"кај Д-р {t['ime_lekar']} ({t['specijalnost_termin']}){oznaka}"
            )
        delovi.append("")
        delovi.append('Биди поточен: „Оцена 5 за прегледот кај д-р [презиме] на [датум]"')
        return "\n".join(delovi)

    t = termini[0]                                       # Tocno eden termin
    veke_imal_ocena = bool(t.get("postoecka_ocena"))     # Update ili prva ocena
    if not vmetni_ili_azhuriraj_ocena(t["termin_ID"], ocena, komentar): # Zacuvaj
        return "Не успеа да ја зачувам оцената. Пробај пак."

    datum = t["datum_pregled"]
    den_ime = DENOVI[datum.weekday()]
    vreme = format_vreme(t["vreme_pregled"])
    naslov = "Оцената е ажурирана!" if veke_imal_ocena else "Благодариме за оцената!"
    zvezdi = "★" * ocena + "☆" * (5 - ocena)              # Vizuelni zvezdi
    delovi = [
        naslov,
        "",
        f"Лекар: Д-р {t['ime_lekar']}",
        f"Специјалност: {t['specijalnost_termin']}",
        f"Датум: {den_ime}, {format_datum(datum)} во {vreme}",
        f"Оцена: {zvezdi} ({ocena}/5)",
    ]
    if komentar:
        delovi.append(f"Коментар: {komentar}")

    return "\n".join(delovi)                               # Finalen odgovor
