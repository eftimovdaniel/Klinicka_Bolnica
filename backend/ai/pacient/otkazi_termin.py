"""
Откажување на закажан термин преку AI агент (Groq).

Едноставен flow:
  1) AI извлекува doctor_id + datum + vreme (+ prezime_filter) од прашањето
  2) Дополни од контекст ако нешто фали (од претходно закажување / слободни)
  3) SELECT во база — најди го терминот на пациентот
  4) Ако нема термин → порака „нема“
  5) Ако има повеќе термини → побарај да биде попрецизен
  6) Ако има точно еден → UPDATE status = 'откажан' + email потврда

Главна функција: odgovori_za_otkazuvanje(prasanje, pacient, kontekst)
"""
from datetime import date  # Uvoz na date klasa za rabota so deneshen datum
from database import get_connection  # Uvoz na funkcija za konekcija so MySQL bazata
from ai._kernel.prompt_loader import load_prompt  # Uvoz na pomoshna funkcija za citanje na prompt sablon
from ai._kernel.groq_helpers import izvlechi_json_so_ai  # Uvoz na Groq AI pomoshna funkcija
from ai._kernel.utils import format_datum, format_vreme  # Uvoz na pomoshni funkcii za formatiranje
# Lista na denovi vo nedelata na makedonski (za prikaz vo potvrda)
DENOVI_VO_NEDELA = ["Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"]

def zimi_site_lekari_od_baza() -> list:  # SQL upit — vrakja site lekari za AI promptot
    """Vrakja lista na site lekari ({'doctor_ID', 'name', 'surname', 'specialty'})."""
    konekcija = None  # Inicijalizacija — vazno za finally blokot
    try:  # Pocetok na blok za obrabotka na potencijalni greski
        konekcija = get_connection()  # Otvoranje na nova konekcija so MySQL bazata
        cursor = konekcija.cursor(dictionary=True)  # Kreiranje na dictionary kursor za pristap po ime na kolona
        cursor.execute("SELECT doctor_ID, name, surname, specialty FROM Doctors ORDER BY surname, name")  # SQL upit za site lekari
        rezultat = list(cursor.fetchall())  # Zemanje na site redovi i konverzija vo lista
        cursor.close()  # Zatvaranje na kursorot
        return rezultat  # Vrakjanje na listata na lekari
    except Exception as e:  # Fakjanje na bilo kakva greska
        print(f"[otkazi_termin] zimi_site_lekari_od_baza: {e}")  # Log za debagiranje
        return []  # Pri greska — vrati prazna lista
    finally:  # Blok sto se izvrshuva sekogas
        if konekcija:  # Uslovna proverka
            konekcija.close()  # Zatvaranje na konekcijata


def izvlechi_podatoci_so_ai(prasanje: str) -> dict:  # Eden Groq povik koj vrakja doctor_id / datum / vreme / prezime_filter
    """AI extract: doctor_id, datum (YYYY-MM-DD), vreme (HH:MM), prezime_filter."""
    site_lekari = zimi_site_lekari_od_baza()  # Lista na site lekari za AI da znae koe ID kome pripaga
    # Tekst-lista na lekari za AI promptot
    lista_tekst = ""  # Pochetna prazna niza koja ke ja popolnuvame
    for lekar in site_lekari:  # Iteracija niz site lekari
        spec = lekar.get("specialty") or "Општа пракса"  # Specijalnost ili default „Општа пракса“
        lista_tekst += f"ID {lekar['doctor_ID']}: Д-р {lekar['name']} {lekar['surname']} — {spec}\n"  # Dodavanje na red za sekoj lekar

    # Deneshen datum i den vo nedelata (AI gi koristi za „утре“, „среда“ itn.)
    deneshen_datum = date.today()  # Zemanje na deneshen datum
    denovi_mali = ["понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"]  # Denovi na kirilica
    deneshen_den = denovi_mali[deneshen_datum.weekday()]  # Deneshen den (weekday vrakja 0-6)
    # Polniot prompt sto se prakja kako „user“ poraka (system prompt e od otkazi_extract)
    full_prompt = (  # Sostavuvanje na promptot od delovi
        f"Денешен датум: {deneshen_datum.isoformat()} ({deneshen_den})\n"
        f"Листа на лекари:\n{lista_tekst}\n"
        f"Корисник пишува: „{prasanje}\"\n\n"
        "Извлечи doctor_id, datum, vreme, prezime_filter и врати JSON."
    )
    return izvlechi_json_so_ai(full_prompt, load_prompt("otkazi_extract"), log_tag="otkazi_termin")  # Povik do Groq AI

def validiraj_doctor_id(vrednost) -> int | None:  # Pretvori vrednost vo int ili vrati None
    """Validacija na doctor_id od AI — vrakja int ili None."""
    if vrednost is None:  # Ako AI ne vratil id
        return None  # Vrati None
    try:  # Pocetok na blok za obrabotka na potencijalni greski
        return int(vrednost)  # Konverzija vo int (od broj ili string)
    except (TypeError, ValueError):  # Ako konverzijata ne uspee
        return None  # Vrati None

def dopolni_od_kontekst(doctor_id, datum_str, prasanje, kontekst):  # Dokolku AI ne izvlekol — zemi od pretohden razgovor
    """Vrakja (doctor_id, datum_str) — popolneti od kontekst ako AI propushtil."""
    if not isinstance(kontekst, dict):  # Proverka dali kontekstot e validen recnik
        return doctor_id, datum_str  # Ako ne e — vrati nepromeneti vrednosti
    # Probaj prvo od „slobodni“, potoa od „pending“ kontekst (od prethodno zakazuvanje)
    pretohden = kontekst.get("zakazi_od_slobodni") or kontekst.get("zakazi_pending") or {}  # Pretohden razgovor
    if not isinstance(pretohden, dict):  # Proverka dali e validen recnik
        return doctor_id, datum_str  # Ako ne e — vrati nepromeneti vrednosti

    # Dopolni lekar od kontekst ako AI propushtil
    if not doctor_id and pretohden.get("doctor_id"):  # Nema lekar od AI, a ima vo kontekst
        doctor_id = pretohden["doctor_id"]  # Iskoristi go lekarot od kontekst

    # Dopolni datum od kontekst — samo ako poruka referenсia kon „тој/истиот термин“
    if not datum_str and pretohden.get("datum"):  # Nema datum od AI, a ima vo kontekst
        klucni_zborovi = (  # Klucni zborovi koi ukazuvaat „toj termin“
            "терминот", "термин", "прегледот", "преглед",
            "го откаж", "го отказ", "избраниот", "истиот", "погоре",
        )
        p = (prasanje or "").lower()  # Normaliziranje na prashanjeto
        if any(klucen in p for klucen in klucni_zborovi):  # Ako sodrzi nekoj od klucnite zborovi
            datum_str = str(pretohden["datum"])[:10]  # Iskoristi go datumot od kontekst

    return doctor_id, datum_str  # Vrakjame dvojka so popolneti vrednosti

def najdi_termini_za_otkazuvanje(email_pacient, doctor_id, datum_str, vreme_str, prezime_filter) -> list:  # SELECT na aktivni termini
    konekcija = None  # Inicijalizacija — vazno za finally blokot
    try:  # Pocetok na blok za obrabotka na potencijalni greski
        konekcija = get_connection()  # Otvoranje na konekcija so bazata
        cursor = konekcija.cursor(dictionary=True)  # Dictionary kursor za citki redovi
        # Osnoven SQL upit — site zakazani termini na ovoj pacient
        query = (
            "SELECT termin_ID, datum_pregled, vreme_pregled, "
            "       ime_lekar, specijalnost_termin, doctor_ID "
            "FROM Termin_pregled "
            "WHERE LOWER(TRIM(email_pacient)) = LOWER(TRIM(%s)) "
            "  AND status_pregled = 'закажан'"  # Samo zakazani (ne zavrseni / otkazani)
        )
        parametri = [email_pacient]  # Prv parametar — email na pacientot
        # Ako nema konkreten datum vo prashanjeto — pokazi samo idni termini
        if not datum_str:  # Bez datum
            query += " AND datum_pregled >= CURDATE()"  # Samo denes i nataka
        # Ako ima konkreten lekar — filtriraj po doctor_ID
        if doctor_id:  # Imame doctor_id od AI ili kontekst
            query += " AND doctor_ID = %s"  # Dodavanje na uslov
            parametri.append(doctor_id)  # Dodavanje na parametar
        # Ako ima konkreten datum — filtriraj po datum
        if datum_str:  # Imame datum
            query += " AND datum_pregled = %s"  # Dodavanje na uslov
            parametri.append(datum_str)  # Dodavanje na parametar
        # Ako nema doctor_id no ima del od prezime — pretraga po ime_lekar
        if prezime_filter and not doctor_id:  # Imame prezime, no nemame ID
            query += " AND LOWER(COALESCE(ime_lekar, '')) LIKE %s"  # LIKE pretraga
            parametri.append(f"%{prezime_filter.strip().lower()}%")  # Wildcard pretraga
        # Ako ima konkretno vreme — filtriraj po vreme
        if vreme_str:  # Imame vreme
            query += " AND TIME(vreme_pregled) = %s"  # SQL TIME() konverzija
            parametri.append(vreme_str)  # Dodavanje na parametar
        query += " ORDER BY datum_pregled, vreme_pregled"  # Sortirano po datum i vreme
        cursor.execute(query, parametri)  # Izvrshuvanje na upitot
        rezultati = list(cursor.fetchall() or [])  # Zemanje na site redovi
        cursor.close()  # Zatvaranje na kursorot

        # Dopolnitelno filtriranje vo Python (za sigurnost so HH:MM format)
        if vreme_str and rezultati:  # Ako baravme vreme i imame rezultati
            vreme_filter = vreme_str.strip()[:5]  # Normaliziraj na HH:MM
            filtrirani = [t for t in rezultati if format_vreme(t.get("vreme_pregled")) == vreme_filter]  # Filtriraj
            if filtrirani:  # Ako ima tocno poklopuvanje
                return filtrirani  # Vrati gi filtriranite

        return rezultati  # Vrakjanje na site rezultati
    except Exception as e:  # Fakjanje na bilo kakva greska
        print(f"[otkazi_termin] najdi_termini: {e}")  # Log za debagiranje
        return []  # Pri greska — prazna lista
    finally:  # Blok sto se izvrshuva sekogas
        if konekcija:  # Uslovna proverka
            konekcija.close()  # Zatvaranje na konekcijata


def otkazi_termin_vo_baza(termin_id: int) -> bool:  # UPDATE status = откажан vo baza
    """Postavuva status na terminot na 'откажан' (soft delete)."""
    konekcija = None  # Inicijalizacija — vazno za finally blokot
    try:  # Pocetok na blok za obrabotka na potencijalni greski
        konekcija = get_connection()  # Otvoranje na konekcija so bazata
        cursor = konekcija.cursor()  # Obichen kursor (ne ni treba dictionary)
        cursor.execute(  # UPDATE upit — promena na status
            "UPDATE Termin_pregled SET status_pregled = 'откажан' WHERE termin_ID = %s",
            (termin_id,),  # Parametar — ID na terminot
        )
        konekcija.commit()  # Potvrduvanje na transakcijata
        cursor.close()  # Zatvaranje na kursorot
        return True  # Uspesno otkazuvanje
    except Exception as e:  # Fakjanje na bilo kakva greska
        print(f"[otkazi_termin] otkazi_termin_vo_baza: {e}")  # Log za debagiranje
        return False  # Pri greska — vrati False
    finally:  # Blok sto se izvrshuva sekogas
        if konekcija:  # Uslovna proverka
            konekcija.close()  # Zatvaranje na konekcijata


# ───────────────── Pomoshni za prikaz ─────────────────
def formatiraj_termin_za_lista(termin: dict) -> str:  # Pravi „Среда 12.03.2026 во 09:30 кај Д-р Петров (Кардиологија)“
    """Formatiranje na eden termin za prikaz vo lista."""
    datum = termin["datum_pregled"]  # Zemanje na datumot od redot
    den_ime = DENOVI_VO_NEDELA[datum.weekday()]  # Ime na denot (Понеделник, Вторник...)
    vreme = format_vreme(termin["vreme_pregled"])  # Formatiranje na vremeto HH:MM
    return (  # Sostavuvanje na red za listata
        f"- {den_ime} {format_datum(datum)} во {vreme} "
        f"кај Д-р {termin['ime_lekar']} ({termin['specijalnost_termin']})"
    )


def isprati_email_potvrda_za_otkaz(pacient: dict, termin: dict) -> None:  # SMTP potvrda za otkazan termin
    """Email potvrda za otkazan termin (ne e fatalna ako padne)."""
    try:  # Pocetok na blok za obrabotka na potencijalni greski
        from routers.termini import _poslati_otkaz_na_email  # Lazy import — izbegnuvanje na ciklus

        ime_pacient = (  # Sostavuvanje na ime + prezime za email
            (pacient.get("ime") or "") + " " + (pacient.get("prezime") or "")
        ).strip() or (termin.get("ime_pacient") or pacient.get("email", ""))  # Fallback redosled

        datum = termin["datum_pregled"]  # Zemanje na datumot
        den_ime = DENOVI_VO_NEDELA[datum.weekday()]  # Ime na denot
        datum_lep = format_datum(datum)  # Formatiranje za prikaz

        _poslati_otkaz_na_email(  # Prakjanje na email
            to_email=pacient["email"],
            ime_pacient=ime_pacient,
            ime_lekar=f"Д-р {termin['ime_lekar']}",
            datum=f"{den_ime}, {datum_lep}",
            vreme=format_vreme(termin["vreme_pregled"]),
            specialnost=termin.get("specijalnost_termin") or "",
        )
    except Exception as e:  # Email greska ne e fatalna — terminoot e vekje otkazan
        print(f"[otkazi_termin] email: {e}")  # Log za debagiranje


def odgovori_za_otkazuvanje(prasanje: str, pacient: dict | None, kontekst: dict | None = None) -> str:  # Vlezna tocka — povikana od router
    # 1) Pacientot mora da bide najaven (email e zadolzitelen za pretraga)
    if not pacient or not pacient.get("email"):  # Proverka dali ima pacient + email
        return (  # Vrakjame poraka za najava
            "За да откажеш термин, прво најави се како пациент. "
            "Кликни „Најави се!\" горе десно."
        )
    # 2) AI ekstrakcija na podatoci od prashanjeto
    podatoci_od_ai = izvlechi_podatoci_so_ai(prasanje)  # Eden Groq povik
    if podatoci_od_ai.get("_error"):  # Ako Groq vratil greska (npr. rate-limit)
        return str(podatoci_od_ai["_error"])  # Vrakjame ja greskata kon korisnikot

    doctor_id = validiraj_doctor_id(podatoci_od_ai.get("doctor_id"))  # Konverzija vo int ili None
    datum_str = (podatoci_od_ai.get("datum") or "").strip()[:10] or None  # YYYY-MM-DD ili None
    vreme_str = (podatoci_od_ai.get("vreme") or "").strip()[:5] or None  # HH:MM ili None
    prezime_filter = (podatoci_od_ai.get("prezime_filter") or "").strip() or None  # Del od prezime ili None

    # 3) Dopolni od kontekst ako AI propushtil
    doctor_id, datum_str = dopolni_od_kontekst(doctor_id, datum_str, prasanje, kontekst)  # Lekar + datum od pretohden razgovor

    # 4) SELECT vo baza — najdi gi terminite sto se poklopuvaat
    termini = najdi_termini_za_otkazuvanje(  # SQL pretraga
        pacient["email"], doctor_id, datum_str, vreme_str, prezime_filter,
    )

    # 5a) Nemame nieden termin — porakata sodrzi sto baravme
    if not termini:  # Nema poklopuvanje vo baza
        detali = []  # Lista sto barase korisnikot za prikaz
        if datum_str:  # Ako baravme po datum
            detali.append(f"датум {datum_str}")  # Dodavanje na detal
        if vreme_str:  # Ako baravme po vreme
            detali.append(f"време {vreme_str}")  # Dodavanje na detal
        if doctor_id or prezime_filter:  # Ako baravme po lekar
            detali.append("лекар од пораката")  # Dodavanje na detal
        dodaten_tekst = f" (барано: {', '.join(detali)})" if detali else ""  # Sostavi go „барано“ del
        return (  # Vrakjame poraka deka nema poklopuvanje
            f"Не најдов активен термин со статус „закажан\" што одговара{dodaten_tekst}.\n\n"
            "Провери со „Моите прегледи\" или „Прикажи ги сите мои прегледи\", "
            "па повтори, на пр.:\n"
            "„Откажи го прегледот на 02.02.2026 во 09:30 кај Серафимов\"."
        )

    # 5b) Imame poveke termini — pacientot mora da bide popreciren
    if len(termini) > 1:  # Nejasno koj termin
        delovi = ["Имаш повеќе термини. Кој точно сакаш да го откажеш?", ""]  # Naslov + prazen red
        for termin in termini:  # Iteracija niz site termini
            delovi.append(formatiraj_termin_za_lista(termin))  # Formatiran red za sekoj
        delovi.append("")  # Prazen red
        delovi.append("Биди поточен: „Откажи го прегледот кај д-р [презиме] на [датум]\"")  # Pomoshna poraka
        return "\n".join(delovi)  # Spojuvanje so newline

    # 5c) Imame tocno eden termin — uspesno otkazuvanje
    termin = termini[0]  # Zemi go prviot (i edinstven) termin

    # 6a) UPDATE vo baza
    if not otkazi_termin_vo_baza(termin["termin_ID"]):  # Probaj da go otkazes
        return "Не успеа да го откажам терминот. Пробај пак."  # Ako UPDATE ne uspeal

    # 6b) Email potvrda (ne e fatalna ako padne — terminoot e vekje otkazan)
    isprati_email_potvrda_za_otkaz(pacient, termin)  # Prakjanje na email

    # 6c) Tekst potvrda za korisnikot
    datum = termin["datum_pregled"]  # Zemanje na datumot
    den_ime = DENOVI_VO_NEDELA[datum.weekday()]  # Ime na denot
    datum_lep = format_datum(datum)  # Formatiranje za prikaz
    vreme = format_vreme(termin["vreme_pregled"])  # Formatiranje na vremeto

    return (  # Sostavuvanje na potvrdata
        f"Терминот е откажан!\n\n"
        f"Лекар: Д-р {termin['ime_lekar']}\n"
        f"Специјалност: {termin['specijalnost_termin']}\n"
        f"Датум: {den_ime}, {datum_lep}\n"
        f"Време: {vreme}\n\n"
        "Потврда е испратена на вашата е-пошта (ако е поставен SMTP на серверот).\n\n"
        "Можеш да закажеш нов термин со „Сакам преглед кај [презиме] [датум] [време]\"."
    )
