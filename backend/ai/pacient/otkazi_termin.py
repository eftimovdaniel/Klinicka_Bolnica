""" Otkazi zakazan pregled preku AI — samo za logiran pacient. """

# Import na potrebni moduli: prompt, formatiranje, datum, baza, groq, kontekst od zakazuvanje
from ai._kernel.prompt_loader import load_prompt          # Vcituvanje na prompt fajl
from ai._kernel.utils import format_datum, format_vreme    # Formatiranje za prikaz vo chat
from datetime import date                                  # Denesen datum vo AI prompt
from database import get_connection                        # MySQL konekcija
from ai._kernel.groq_helpers import groq_zadolzhitelen, izvlechi_json_so_ai # AI izvlekuvanje JSON
from ai.pacient.slobodni_termini import (                  # Pomosnici od zakazuvanje / lista lekari
    datum_od_zakazi_kontekst,                              # Datum od pretoden razgovor
    lekar_od_zakazi_kontekst,                              # Lekar od pretoden razgovor
    zimi_site_lekari,                                      # Site lekari za zatvorena lista vo prompt
)
# Pretvori doctor_id od AI vo int; None ako nedostasuva ili e nevaliden
def _normalize_doctor_id(v) -> int | None:
    if v is None:                                          # dokolku ai ne vrati id
        return None             # kako izlez imame none
    try:    # vo sportivno 
        return int(v)          # standarden int od broj ili string
    except (TypeError, ValueError):  # dokolku imame greska
        return None

# Groq izvlekuva lekar, datum, vreme i prezime_filter od porakata na pacientot
def izvlechi_otkazi_podatoci(prasanje: str) -> dict:
    prazno = {                                             # Defolt vrednosti ako AI ne uspee da vrati nekoja vrednost
        "doctor_id": None,
        "datum": None,
        "vreme": None,
        "prezime_filter": None,
    }
    if msg := groq_zadolzhitelen():                        # Proverka dali Groq API e dostapen
        return {**prazno, "_error": msg}                   # Vrati greska + prazni polinja

    site_lekari = zimi_site_lekari()                       # Site lekari od baza
    lista_text = ""                                        # Tekst za prompt — eden red po lekar
    for lekar in site_lekari:                              # Loop niz site lekari
        spec = lekar.get("specialty") or "Општа пракса"   # Specijalnost ili defolt
        lista_text += (
            f"ID {lekar['doctor_ID']}: Д-р {lekar['name']} {lekar['surname']} - {spec}\n"
        )

    denes = date.today().strftime("%Y-%m-%d")              # Denesen datum YYYY-MM-DD
    den_vo_nedela = [                                      # Den vo nedelata na makedonski
        "понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"
    ][date.today().weekday()]
    full_prompt = f""" Денес: {denes} ({den_vo_nedela}) Лекари: {lista_text} Корисник: „{prasanje}" Извлечи doctor_id, datum (YYYY-MM-DD), vreme (HH:MM), prezime_filter.""".strip()                                            # Cel prompt za AI
    podatoci = izvlechi_json_so_ai(
        full_prompt, load_prompt("otkazi_extract"), log_tag="otkazi_termin"
    ) # Povikaj Groq so sistemski prompt od fajl
    if podatoci.get("_error"):                             # Greska od AI servisot
        return {**prazno, "_error": podatoci["_error"]}

    vreme = podatoci.get("vreme")                          # Sirovo vreme od JSON
    return {
        "doctor_id": podatoci.get("doctor_id"),            # ID na lekarot (moze string)
        "datum": podatoci.get("datum"),                    # Datum pregled YYYY-MM-DD
        "vreme": str(vreme).strip()[:5] if vreme else None, # HH:MM — max 5 karakteri
        "prezime_filter": podatoci.get("prezime_filter"),  # Del od prezime ako nema doctor_id
    }

# Bara aktivni (zakazani) termini na pacientot so opcionalni filtri
def najdi_termini_za_otkazuvanje(
    pacient_email: str,
    doctor_id: int | None,
    datum: str | None,
    vreme: str | None = None,
    prezime_filter: str | None = None,
) -> list[dict]:
    conn = None                                            # Konekcija — zatvora se vo finally
    try:
        conn = get_connection()                            # Otvori MySQL
        cur = conn.cursor(dictionary=True)                 # Redovi kako recnici

        query = """
            SELECT t.termin_ID, t.datum_pregled, t.vreme_pregled,
                   t.ime_lekar, t.specijalnost_termin, t.doctor_ID
            FROM Termin_pregled t
            WHERE LOWER(TRIM(t.email_pacient)) = LOWER(TRIM(%s))
              AND t.status_pregled = 'закажан'
        """ # Samo zakazani — kirilica kako vo baza; ne zavrshen/otkazan
        params: list[object] = [pacient_email]             # Prv parametar: email pacient

        if not datum:                                      # Bez datum vo poraka
            query += " AND t.datum_pregled >= CURDATE()"   # Samo denes i idnina — ne minato

        if doctor_id:                                      # Filtar po tocen lekar
            query += " AND t.doctor_ID = %s"
            params.append(doctor_id)

        if datum:                                          # Filtar po konkreten datum
            query += " AND t.datum_pregled = %s"
            params.append(datum)

        if prezime_filter and not doctor_id:               # Prezime samo ako nema doctor_id
            query += " AND LOWER(COALESCE(t.ime_lekar, '')) LIKE %s"
            params.append(f"%{prezime_filter.strip().lower()}%") # Del od ime_lekar

        if vreme:                                          # Filtar po vreme (SQL TIME)
            query += " AND TIME(t.vreme_pregled) = %s"
            params.append(vreme)

        query += " ORDER BY t.datum_pregled, t.vreme_pregled" # Najblisku vo vremeto prvi

        cur.execute(query, params)                         # Izvrsi SELECT
        rezultati = list(cur.fetchall() or [])             # Site redovi; prazna lista ako None
        cur.close()

        if vreme and rezultati:                            # Dopolnitelno filtriranje vo Python
            vf = vreme.strip()[:5]                         # Normalizirano HH:MM
            filtrirani = [
                t
                for t in rezultati
                if format_vreme(t.get("vreme_pregled")) == vf  # Sporedba so format od utils
            ]
            if filtrirani:                                 # Ako ima tocno poklopuvanje
                return filtrirani

        return rezultati                                   # Site od SQL ili prazno

    except Exception as e:
        print(f"[otkazi_termin] greska: {e}")              # Log za debug
        return []                                          # Bez termin = poraka do pacient
    finally:
        if conn:
            conn.close()                                   # Sekogas zatvori konekcija


# Vo baza postavi status na terminot na otkazan (kirilica)
def otkazi_termin_vo_baza(termin_id: int) -> bool:
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE Termin_pregled
            SET status_pregled = 'откажан'
            WHERE termin_ID = %s
            """,
            (termin_id,),
        ) # Soft delete — termin ostava vo tabela so nov status
        conn.commit()                                      # Zacuvaj promena
        cur.close()
        return True                                        # Uspesno otkazuvanje
    except Exception as e:
        print(f"[otkazi_termin] update greska: {e}")
        return False
    finally:
        if conn:
            conn.close()


# Dopolni izvleceno so lekar/datum od chat kontekst (posle zakazuvanje / slobodni termini)
def _spoi_otkazi_so_kontekst(
    prasanje: str,
    izvleceno: dict,
    kontekst: dict | None,
) -> None:
    if not isinstance(kontekst, dict):                     # Nema kontekst od router
        return
    lekar = lekar_od_zakazi_kontekst(kontekst)             # Posleden izbran lekar
    if lekar and not izvleceno.get("doctor_id"):           # AI ne dade id — zemi od kontekst
        izvleceno["doctor_id"] = lekar["doctor_ID"]
    if izvleceno.get("datum"):                             # Datum veke e jasen
        return
    baran = datum_od_zakazi_kontekst(kontekst)             # Datum od pretoden cekor vo chat
    if not baran:
        return
    p = (prasanje or "").lower()                           # Poraka za klucni zborovi
    if any(                                                # Referenca na „тој“ термин без датум
        x in p
        for x in (
            "терминот",
            "термин",
            "прегледот",
            "преглед",
            "го откаж",
            "го отказ",
            "избраниот",
            "истиот",
            "погоре",
        )
    ):
        izvleceno["datum"] = baran.isoformat()             # YYYY-MM-DD za SQL filter


# Glaven handler — intent otkazi_termin; router ja povikuva so pacient i kontekst
def odgovori_za_otkazuvanje(
    prasanje: str, pacient: dict | None, kontekst: dict | None = None
) -> str:
    if not pacient or not pacient.get("email"):            # Mora najava kako pacient
        return (
            'За да откажеш термин, прво најави се како пациент. '
            'Кликни „Најави се!" горе десно.'
        )

    izvleceno = izvlechi_otkazi_podatoci(prasanje)         # AI: lekar, datum, vreme, prezime
    _spoi_otkazi_so_kontekst(prasanje, izvleceno, kontekst) # Dopolni od pretoden razgovor

    doctor_id = _normalize_doctor_id(izvleceno.get("doctor_id")) # int ili None
    datum_str = (izvleceno.get("datum") or "").strip()[:10] or None  # Max 10 za YYYY-MM-DD
    vreme_str = (izvleceno.get("vreme") or "").strip()[:5] or None   # HH:MM
    prezime_filter = (izvleceno.get("prezime_filter") or "").strip() or None

    if izvleceno.get("_error"):                            # Groq nedostapen ili greska
        return str(izvleceno["_error"])

    termini = najdi_termini_za_otkazuvanje(                # Baranje vo Termin_pregled
        pacient["email"],
        doctor_id,
        datum_str,
        vreme_str,
        prezime_filter,
    )

    DENOVI = [                                             # Za lep prikaz vo chat
        "Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"
    ]

    if not termini:                                        # Nema poklopuvanje vo baza
        detali = []                                        # Lista sto barase korisnikot
        if datum_str:
            detali.append(f"датум {datum_str}")
        if vreme_str:
            detali.append(f"време {vreme_str}")
        if doctor_id or prezime_filter:
            detali.append("лекар од пораката")
        extra = f" (барано: {', '.join(detali)})" if detali else ""
        return (
            f"Не најдов активен термин со статус „закажан“ што одговара{extra}.\n\n"
            'Проверете со „Моите прегледи“ или „Прикажи ги сите мои прегледи“, '
            'па повторете, на пр.:\n'
            '„Откажи го прегледот на 02.02.2026 во 09:30 кај Серафимов“.'
        )

    if len(termini) > 1:                                   # Nejasno koj termin — lista
        delovi = ["Имаш повеќе термини. Кој точно сакаш да го откажеш?", ""]
        for t in termini:                                  # Site poklopuvanja (bez limit 10)
            datum = t["datum_pregled"]
            den_ime = DENOVI[datum.weekday()]
            vreme = format_vreme(t["vreme_pregled"])
            delovi.append(
                f"- {den_ime} {format_datum(datum)} во {vreme} "
                f"кај Д-р {t['ime_lekar']} ({t['specijalnost_termin']})"
            )
        delovi.append("")
        delovi.append('Биди поточен: „Откажи го прегледот кај д-р [презиме] на [датум]"')
        return "\n".join(delovi)

    t = termini[0]                                         # Tocno eden termin za otkaz
    if not otkazi_termin_vo_baza(t["termin_ID"]):          # UPDATE status = откажан
        return "Не успеа да го откажам терминот. Пробај пак."

    datum = t["datum_pregled"]
    den_ime = DENOVI[datum.weekday()]
    vreme = format_vreme(t["vreme_pregled"])
    datum_lep = format_datum(datum)                        # Datum za prikaz i email

    ime_pacient = (                                        # Ime za email potvrda
        (pacient.get("ime") or "") + " " + (pacient.get("prezime") or "")
    ).strip() or (t.get("ime_pacient") or pacient.get("email", ""))

    try:
        from routers.termini import _poslati_otkaz_na_email  # Lazy import — izbegni ciklus

        _poslati_otkaz_na_email(                           # SMTP potvrda (ako e podeseno)
            to_email=pacient["email"],
            ime_pacient=ime_pacient,
            ime_lekar=f"Д-р {t['ime_lekar']}",
            datum=f"{den_ime}, {datum_lep}",
            vreme=vreme,
            specialnost=t.get("specijalnost_termin") or "",
        )
    except Exception as e:
        print(f"[otkazi_termin] email greska: {e}")        # Otkazuvanje uspee i bez email

    return (                                               # Tekstualen odgovor vo chat
        f"Терминот е откажан!\n\n"
        f"Лекар: Д-р {t['ime_lekar']}\n"
        f"Специјалност: {t['specijalnost_termin']}\n"
        f"Датум: {den_ime}, {datum_lep}\n"
        f"Време: {vreme}\n\n"
        "Потврда е испратена на вашата е-пошта (ако е поставен SMTP на серверот).\n\n"
        'Можеш да закажеш нов термин со „Сакам преглед кај [презиме] [датум] [време]".'
    )
