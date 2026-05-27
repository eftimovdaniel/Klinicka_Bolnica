"""Запиши терапија/дијагноза за пациент од лекар.
Примери:
- „Запиши терапија за пациент Марко Иванов: 2x дневно парацетамол"
- „Додај терапија на термин 42: Аспирин 100mg"
- „Дијагноза за пациент Ана Стојановска: Хипертензија. Терапија: Лосартан 50mg"
- „Запиши: дијагноза грип, терапија витамин Ц"
"""
from database import get_connection  
from ai._kernel.ai_json import parse_ai_json  
from ai._kernel.groq_client import ask_ai  
from ai._kernel.utils import format_datum, format_vreme  

# sistemski prompt koj go nasocuva ai modelot kako strogo da gi izvleche baranite podatoci vo json format
PROMPT = """ Ти си систем што од прашање извлекува податоци за запис на терапија/дијагноза. Корисникот (лекар) пишува на македонски. Извлечи:
- "ime_pacient": име+презиме на пациент или null
- "termin_id": ID на термин (само цифри) или null
- "dijagnoza": текст за дијагнозата или null
- "terapija": текст за терапијата или null
Врати САМО JSON:
{"ime_pacient": "...", "termin_id": ..., "dijagnoza": "...", "terapija": "..."}
Правила:
- Ако корисникот пишува „терапија: X" или „пропиши X" → terapija = X
- Ако пишува „дијагноза: Y" или „dx: Y" → dijagnoza = Y
- Ако само набројува лек/пропис без префикс → terapija = тоа
- Запази ги оригиналните зборови (без преведување).
Примери:
- „Запиши терапија за Марко Иванов: 2x дневно парацетамол"
  → {"ime_pacient":"Марко Иванов","termin_id":null,"dijagnoza":null,"terapija":"2x дневно парацетамол"}
- „Дијагноза за термин 42: грип. Терапија: Витамин Ц"
  → {"ime_pacient":null,"termin_id":42,"dijagnoza":"грип","terapija":"Витамин Ц"}
- „За Ана Стојановска препиши Лосартан 50mg"
  → {"ime_pacient":"Ана Стојановска","termin_id":null,"dijagnoza":null,"terapija":"Лосартан 50mg"} БЕЗ markdown, БЕЗ објаснувања.""".strip()

# vnatresna funkcija koja go povikuva groq ai za izvlekuvanje na strukturiranite podatoci od baranjeto
def _izvlechi(prasanje: str) -> dict:
    odgovor = ask_ai(f"Прашање: „{prasanje}\"", system_prompt=PROMPT)  # povik do llm preku soodvetna funkcijata
    return parse_ai_json(odgovor, log_tag="zapishi_terapija")  # bezbedno parsiranje na odgovorot vo rechnik

# pomosna funkcija za naoganje na tocen termin vo bazata spored poduredeno id i id na lekarot
def _najdi_termin_po_id(doctor_id: int, termin_id: int) -> dict | None:
    conn = None
    try:
        conn = get_connection()  # otvoranje konekcija do mysql bazata na podatoci
        cur = conn.cursor(dictionary=True)  # inicijalizacija na kursor za redovi vo vid na rechnici
        cur.execute("""
            SELECT termin_ID, ime_pacient, datum_pregled, vreme_pregled,
                   status_pregled, dijagnoza, terapija
            FROM Termin_pregled
            WHERE termin_ID = %s AND doctor_ID = %s
        """, (termin_id, doctor_id))  # izvrsuvanje na bezbeden parametriziran upit
        r = cur.fetchone()  # prevzemanje na edinstveniot pronajden red
        cur.close()  # zatvoranje na kursorot
        return r  # vrakjanje na podatocite za terminot
    except Exception as e:
        print(f"[zapishi_terapija] DB greska: {e}")  # pecatenje na greska dokolku nastane problem so bazata
        return None
    finally:
        if conn:
            conn.close()  # osiguruvajne deka vrskata so bazata sekogas ke bide zatvorena

# pomosna funkcija koja gi vrakja site termini za daden pacient kaj soodvetniot lekar, sortirani od najnovite
def _najdi_termini_po_ime(doctor_id: int, ime_pacient: str) -> list[dict]:
    delovi = [d for d in ime_pacient.strip().split() if d]  # razdeluvanje na imeto na poedinecni zborovi
    if not delovi:  # ako ne e pronajde se vraka []
        return []
    conn = None
    try:
        conn = get_connection()  # otvoranje vrska do mysql bazata na podatoci
        cur = conn.cursor(dictionary=True)  # inicijalizacija na kursor za redovi vo vid na rechnici
        sql = (
            "SELECT termin_ID, ime_pacient, datum_pregled, vreme_pregled, "
            "       status_pregled, dijagnoza, terapija "
            "FROM Termin_pregled "
            "WHERE doctor_ID = %s"
        )  # osnoven sql upit za pretraga na termini
        params: list = [doctor_id]  # lista na bezbedni sql parametri
        for d in delovi:
            sql += " AND LOWER(ime_pacient) LIKE %s"  # dodavanje na uslov za sekoj del od imeto
            params.append(f"%{d.lower()}%")  # vmetnuvanje na prebaruvaniot del vo parametрите
        sql += " ORDER BY datum_pregled DESC, vreme_pregled DESC LIMIT 10"  # sortiranje po hronoloshki red i limit od 10 rezultati
        cur.execute(sql, tuple(params))  # izvrsuvanje na dinamichkiot bezbeden sql upit
        rows = cur.fetchall() or []  # prevzemanje na site pronajdeni redovi
        cur.close()  # zatvoranje na kursorot
        return rows  # vrakjanje na listata od termini
    except Exception as e:
        print(f"[zapishi_terapija] DB greska: {e}")  # logiranje na greska pri rabota so bazata
        return []
    finally:
        if conn:
            conn.close()  # zatvoranje na mysql konekcijata

# pomosna funkcija koja go izvrsuva samiot update upit vo bazata za vnesuvanje na dijagnozata i terapijata
def _update_terapija( termin_id: int, dijagnoza: str | None, terapija: str | None, avtomatski_zavrshi: bool,) -> bool:
    conn = None
    try:
        conn = get_connection()  # otvoranje vrska do mysql bazata na podatoci
        cur = conn.cursor()  # inicijalizacija na kursor
        delovi = []  # lista vo koja se sozdavaat dinamichkite uslovi za set delot
        params: list = []  # lista na soodvetni sql parametri za vnesuvanje
        if dijagnoza is not None:
            delovi.append("dijagnoza = %s")  # dodavanje pole za dijagnoza ako e prepoznat tekst
            params.append(dijagnoza)  # se dodava dijagnozata
        if terapija is not None:
            delovi.append("terapija = %s")  # dodavanje pole za terapija ako e prepoznat tekst
            params.append(terapija)  # dodavanje na terapija vo  parametrite
        if avtomatski_zavrshi:
            delovi.append("status_pregled = 'завршен'")  # smeni status vo 'zavrshen' dokolku e avtomatski
        if not delovi:
            return False  # ako nema nitu dijagnoza nitu terapija, ne se izveduva nisto
        sql = "UPDATE Termin_pregled SET " + ", ".join(delovi) + " WHERE termin_ID = %s"  # spojuvanje na finalniot upit
        params.append(termin_id)  # dodavanje na id na terminot kako posleden parametar
        cur.execute(sql, tuple(params))  # izvrsuvanje na bezbedniot update upit
        conn.commit()  # potvrda na izmenite vo bazata na podatoci
        cur.close()  # zatvoranje na kursorot
        return True  # vrakjanje na uspesen status
    except Exception as e:
        print(f"[zapishi_terapija] UPDATE greska: {e}")  # logiranje greska dokolku potfrli zapisot
        return False
    finally:
        if conn:
            conn.close()  # zatvoranje na aktivnata konekcija

# glavna handler funkcija koja se povikuva od strana na router-ot
def odgovori_za_terapija(prasanje: str, lekar: dict | None) -> str:
    if not lekar or not lekar.get("doctor_ID"):  # proverka dali korisnikot e najaven kako lekar
        return (
            "За да запишеш терапија преку AI асистентот, прво најави "
            "се како лекар."
        )  # poraka dokolku se posaka ovaa akcija bez avtentikacija

    podatoci = _izvlechi(prasanje)  # povik na ai funkcijata za izvlekuvanje na podatocite
    if podatoci.get("_error"):  # ako ai funkcijata javi greska pri rabotata
        return podatoci["_error"]  # vrati ja greskata direktno nazad
    ime_pacient = (podatoci.get("ime_pacient") or "").strip() or None  # cistenje na prazni mesta i postavuvanje none ako e prazno imeto na paciento
    termin_id = podatoci.get("termin_id")  # prevzemanje na izvlechenoto id na terminot
    try:
        termin_id = int(termin_id) if termin_id else None  # konverzija na id vo cel broj
    except (ValueError, TypeError):
        termin_id = None  # ponistuvanje na vrednosta ako konverzijata e neuspesna
    dijagnoza = (podatoci.get("dijagnoza") or "").strip() or None  # formatiranje i cistenje na tekstot za dijagnoza
    terapija = (podatoci.get("terapija") or "").strip() or None  # formatiranje i cistenje na tekstot za terapija

    if not dijagnoza and not terapija:  # ako modelot ne prepoznal nitu dijagnoza nitu terapija vo baranjeto
        return (
            'Не препознав терапија или дијагноза за запис. Пробај пр.: '
            '„Запиши терапија за Марко Иванов: 2x дневно парацетамол" или '
            '„Дијагноза за термин 42: грип, терапија Витамин Ц".'
        )  # vrakjanje instrukcija za upatstvo kon lekarot

    doctor_id = lekar["doctor_ID"]  # prevzemanje na doctor_id od sesijata

    # Dokolku e dadeno id na terminot
    if termin_id:
        termin = _najdi_termin_po_id(doctor_id, termin_id)  # prebaruvanje na terminot spored negovoto id
        if not termin:  # dokolku ne e pronajden
            return (
                f"Не најдов твој термин со ID {termin_id}. "
                "Провери го бројот или пробај по име на пациент."
            )  # izvestuvanje ako vnesenoto id ne postoi ili ne pripaga na toj lekar

        avtomatski = (termin.get("status_pregled") == "закажан")  # proverka dali terminot treba avtomatski da se zatvori
        ok = _update_terapija(termin_id, dijagnoza, terapija, avtomatski)  # izmena na podatocite vo bazata
        if not ok:
            return "Се случи грешка при зачувувањето. Те молам обиди се повторно."  # greska pri update

        return _ispisi_po_uspesno(termin, dijagnoza, terapija, avtomatski)  # generiranje na uspesen tekstualen izvestaj

    # Dokolku e dadeno imeto na pacientot
    if not ime_pacient:
        return (
            'Не препознав ниту ID на термин ниту име на пациент. '
            'Пробај пр.: „Запиши терапија за Марко Иванов: ..." или '
            '„за термин 42 додај терапија ...".'
        )  # upatsvo dokolku nema nitu tochen identifikator nitu ime

    termini = _najdi_termini_po_ime(doctor_id, ime_pacient)  # pretraga na termini spored tekstualnoto ime
    if not termini:
        return f'Не најдов твој термин со пациент „{ime_pacient}".'  # poraka ako ne se najde nitu eden termin

    # ako ima samo 1 termin -> direktno koristi go nego
    if len(termini) == 1:
        t = termini[0]  # izbor na edinstveniot termin
        avtomatski = (t.get("status_pregled") == "закажан")  # proverka dali statusot e zakazan
        ok = _update_terapija(t["termin_ID"], dijagnoza, terapija, avtomatski)  # update na bazata
        if not ok:
            return "Се случи грешка при зачувувањето. Те молам обиди се повторно."  # zastita od sql greska
        return _ispisi_po_uspesno(t, dijagnoza, terapija, avtomatski)  # prikaz na uspesen izvestaj

    # ima povekje termini -> se ponuduva izbor 
    # preferiraj: zakazan bez terapija > zavrshen bez terapija > najnov
    def prioritet(t):
        ima_ter = bool((t.get("terapija") or "").strip())  # dali veke postoi zapisana terapija
        ima_dij = bool((t.get("dijagnoza") or "").strip())  # dali veke postoi zapisana dijagnoza
        st = t.get("status_pregled")  # status na tekovniot pregled
        # pomal broj → povisok prioritet pri sortiranje
        if st == "закажан" and not (ima_ter or ima_dij):
            return 0
        if st == "завршен" and not (ima_ter or ima_dij):
            return 1
        if st == "закажан":
            return 2
        return 3

    termini_sortirani = sorted(termini, key=prioritet)  # sortiranje na listata termini spored definiranata funkcija za prioritet
    najpriroditen = termini_sortirani[0]  # zemanje na najsoodvetniot termin

    # ako ima mnogu „soodvetni" termini, baraj eksplicitno id poradi bezbednost
    relevantni = [t for t in termini if not (
        (t.get("terapija") or "").strip() or (t.get("dijagnoza") or "").strip()
    )]  # filtriranje na site prazni termini
    if len(relevantni) > 1:
        redovi = [
            f'Имаш повеќе термини со пациент „{ime_pacient}" без запис. '
            'Те молам наведи го ID:',
            "",
        ]  # inicijalizacija na porakata za izbor na id
        for t in relevantni[:5]:
            redovi.append(
                f'• ID {t["termin_ID"]} – {format_datum(t.get("datum_pregled"))} '
                f'{format_vreme(t.get("vreme_pregled"))} ({t.get("status_pregled")})'
            )  # dodavanje na detalite za sekoja opcija
        redovi.append("")
        redovi.append('Пр.: „за термин 42 запиши терапија ..."')
        return "\n".join(redovi)  # vrakjanje na listata so opcii i baranje tochen vnos

    # eden priroden izbor -> direktno koristi go nego
    avtomatski = (najpriroditen.get("status_pregled") == "закажан")  # proverka na statusot na najsoodvetniot
    ok = _update_terapija(najpriroditen["termin_ID"], dijagnoza, terapija, avtomatski)  # izvrsuvanje na azhuriranjeto
    if not ok:
        return "Се случи грешка при зачувувањето. Те молам обиди се повторно."  # zastita
    return _ispisi_po_uspesno(najpriroditen, dijagnoza, terapija, avtomatski)  # vrakjanje na finalniot izvestaj


# pomosna funkcija za generiranje na tekstualniot prikaz po uspesnoto zachuvuvanje na podatocite vo mysql
def _ispisi_po_uspesno(termin: dict, dijagnoza: str | None, terapija: str | None,
                   avtomatski_zavrshi: bool) -> str:
    pac = (termin.get("ime_pacient") or "").strip() or "—"  # prevzemanje na imeto na pacientot
    dat = format_datum(termin.get("datum_pregled"))  # formatiranje na datumot na pregledot
    vrm = format_vreme(termin.get("vreme_pregled"))  # formatiranje na vremeto na pregledot
    delovi = [
        "Записот е сочуван!",
        "",
        f'Пациент: {pac}',
        f'Термин: ID {termin["termin_ID"]} – {dat} {vrm}',
    ]  # sozdavanje na strukturiranata lista od tekstualni linii
    if dijagnoza:
        delovi.append(f"Дијагноза: {dijagnoza}")  # vmetnuvanje na dijagnozata vo izvestajot ako postoi
    if terapija:
        delovi.append(f"Терапија: {terapija}")  # vmetnuvanje na terapijata vo izvestajot ako postoi
    if avtomatski_zavrshi:
        delovi.append("")
        delovi.append('Статусот на терминот е автоматски променет на „завршен".')  # izvestuvanje za avtomatska promena na statusot
    return "\n".join(delovi)  # spojuvanje na liniite vo celosen finalen string