""" Oceni zavrshen pregled preku AI — samo za logiran pacient. """

from ai._kernel.prompt_loader import load_prompt
from ai._kernel.utils import format_datum, format_vreme
from datetime import date
from database import get_connection
from ai._kernel.groq_helpers import groq_zadolzhitelen, izvlechi_json_so_ai
from ai.pacient.slobodni_termini import zimi_site_lekari


def izvlechi_ocena_podatoci(prasanje: str) -> dict:  # funkcija za izvlekuvanje podatoci od korisnicki vlez
    if msg := groq_zadolzhitelen():  # proverka dali groq e dostapen
        return {"_error": msg, "ocena": None, "komentar": None, "doctor_id": None, "datum": None}  # vraka greska ako nema ai
    site_lekari = zimi_site_lekari()  # zemi lista na lekari od baza
    lista_text = ""  # prazen string za listata na lekari
    for lekar in site_lekari:  # pominuva niz sekoj lekar
        spec = lekar.get("specialty") or "Општа пракса"  # odredi specijalnost
        lista_text += f"ID {lekar['doctor_ID']}: Д-р {lekar['name']} {lekar['surname']} - {spec}\n"  # formatiraj red
    denes = date.today().strftime("%Y-%m-%d")  # tekoven datum
    den_vo_nedela = [
        "понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"
    ][date.today().weekday()]  # den vo nedelata
    full_prompt = f"""
Денес: {denes} ({den_vo_nedela})

Лекари:
{lista_text}

Корисник: „{prasanje}"

Извлечи ocena, komentar, doctor_id и datum.
""".strip()  # kreiraj prompt za ai
    podatoci = izvlechi_json_so_ai(
        full_prompt, load_prompt("oceni_extract"), log_tag="oceni_pregled"
    )  # povikaj ai
    if podatoci.get("_error"):  # ako ima greska
        return podatoci  # vrati ja greskata
    ocena_raw = podatoci.get("ocena")  # zemi sirova ocena
    try:
        ocena = int(ocena_raw) if ocena_raw is not None else None  # pretvori vo broj
    except (TypeError, ValueError):
        ocena = None  # nevaliden broj
    return {
        "ocena": ocena,
        "komentar": (podatoci.get("komentar") or None),
        "doctor_id": podatoci.get("doctor_id"),
        "datum": podatoci.get("datum"),
    }  # vrati recnik so podatoci


def najdi_zaversen_termin(
    pacient_email: str, doctor_id: int | None, datum: str | None
) -> list[dict]:  # najdi zavrsen termin
    conn = None  # pocetna konekcija
    try:
        conn = get_connection()  # otvori baza
        cur = conn.cursor(dictionary=True)  # kursor za dict
        query = """
            SELECT t.termin_ID, t.datum_pregled, t.vreme_pregled,
                   t.ime_lekar, t.specijalnost_termin, t.doctor_ID,
                   pf.feedback_ID AS postoecka_ocena
            FROM Termin_pregled t
            LEFT JOIN Pregled_feedback pf ON pf.termin_ID = t.termin_ID
            WHERE LOWER(TRIM(t.email_pacient)) = LOWER(TRIM(%s))
              AND t.status_pregled = 'завршен'
        """  # sql za prebaruvanje (kirilica kako vo baza)
        params: list[object] = [pacient_email]  # postavi email parametar
        if doctor_id:  # filtriraj po lekar
            query += " AND t.doctor_ID = %s"
            params.append(doctor_id)
        if datum:  # filtriraj po datum
            query += " AND t.datum_pregled = %s"
            params.append(datum)
        query += " ORDER BY t.datum_pregled DESC, t.vreme_pregled DESC"  # podredi gi
        cur.execute(query, params)  # izvrsi sql
        rezultati = cur.fetchall()  # zemi rezultati
        cur.close()  # zatvori kursor
        return rezultati  # vrati termini
    except Exception as e:
        print(f"[oceni_pregled] greska: {e}")  # logiraj greska
        return []  # vrati prazna lista
    finally:
        if conn:
            conn.close()  # zatvori konekcija


def vmetni_ili_azhuriraj_ocena(termin_id: int, ocena: int, komentar: str | None) -> bool:  # zacuvaj ocena
    conn = None
    try:
        conn = get_connection()  # otvori baza
        cur = conn.cursor()  # kursor za manipulacija
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
        )  # insert ili update (upsert)
        conn.commit()  # zacuvaj promeni
        cur.close()  # zatvori kursor
        return True  # uspeh
    except Exception as e:
        print(f"[oceni_pregled] insert greska: {e}")  # logiraj greska
        return False  # neuspeh
    finally:
        if conn:
            conn.close()  # zatvori konekcija


def odgovori_za_ocenuvanje(prasanje: str, pacient: dict | None) -> str:  # glavna funkcija za odgovor
    if not pacient or not pacient.get("email"):  # proveri najava
        return (
            'За да оцениш преглед, прво најави се како пациент. '
            'Кликни „Најави се!" горе десно.'
        )

    izvleceno = izvlechi_ocena_podatoci(prasanje)  # izvlechi podatoci so ai
    if izvleceno.get("_error"):
        return str(izvleceno["_error"])  # vrati greska

    ocena = izvleceno.get("ocena")
    komentar = izvleceno.get("komentar")
    doctor_id = izvleceno.get("doctor_id")
    datum_str = izvleceno.get("datum")

    if ocena is None or ocena < 1 or ocena > 5:  # validacija ocena
        return (
            'Не разбрав која оцена сакаш да дадеш. Кажи број од 1 до 5.\n'
            'Пример: „Оцена 5 за д-р Петров — беше одличен"'
        )

    termini = najdi_zaversen_termin(pacient["email"], doctor_id, datum_str)  # najdi termini
    DENOVI = [
        "Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"
    ]  # iminja na denovi za prikaz

    if not termini:  # nema najden termin
        return (
            'Не најдов завршен преглед што одговара. Оцена може да се остави '
            'само за прегледи со статус „завршен“. Биди поспецифичен — '
            'спомни го лекарот и/или датумот.'
        )

    if len(termini) > 1:  # poveke termini - prasaj za pojasnuvanje
        delovi = ["Имаш повеќе завршени прегледи. Кој точно сакаш да го оцениш?", ""]
        for t in termini[:10]:  # najmnogu 10 vo listata
            datum = t["datum_pregled"]
            den_ime = DENOVI[datum.weekday()]  # den od nedelata
            vreme = format_vreme(t["vreme_pregled"])  # formatirano vreme
            oznaka = " (веќе оценет)" if t.get("postoecka_ocena") else ""
            delovi.append(
                f"- {den_ime} {format_datum(datum)} во {vreme} "
                f"кај Д-р {t['ime_lekar']} ({t['specijalnost_termin']}){oznaka}"
            )
        delovi.append("")
        delovi.append('Биди поточен: „Оцена 5 за прегледот кај д-р [презиме] на [датум]"')
        return "\n".join(delovi)

    t = termini[0]  # edinstven termin
    veke_imal_ocena = bool(t.get("postoecka_ocena"))  # update ili prva ocena
    if not vmetni_ili_azhuriraj_ocena(t["termin_ID"], ocena, komentar):  # zacuvaj
        return "Не успеа да ја зачувам оцената. Пробај пак."

    datum = t["datum_pregled"]
    den_ime = DENOVI[datum.weekday()]
    vreme = format_vreme(t["vreme_pregled"])
    naslov = "Оцената е ажурирана!" if veke_imal_ocena else "Благодариме за оцената!"
    zvezdi = "★" * ocena + "☆" * (5 - ocena)  # vizuelni zvezdi
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

    return "\n".join(delovi)  # finalen odgovor
