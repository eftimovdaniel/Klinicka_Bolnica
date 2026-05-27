import re
from database import get_connection
from ai._kernel.auth import require_lekar
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import ask_ai
from ai._kernel.utils import format_datum, format_vreme
# sistemski promt koj go uci modelot da dava samo ime i prezime
PROMPT = """ Ти си систем што извлекува име на пациент. Корисникот е лекар и сака медицински картон на пациент. Врати САМО JSON:
{"ime_pacient": "Име Презиме" | null}
БЕЗ markdown, БЕЗ објаснувања. Само JSON. """.strip()
# pomosna funkcija koja go povikuva ai modelot za da go analizira baranjeto na lekarot
def _izvlechi(prasanje: str) -> dict:
    odgovor = ask_ai(f"Прашање: „{prasanje}\"", system_prompt=PROMPT) # se praka prasanje do groq so soodvetno formiran promt
    print(f"[karton] AI: {odgovor!r}")
    return parse_ai_json(odgovor, log_tag="karton_pacient") #odgovorot se parsira vo python recnik

# glavna funkcija koja se povikuva za obrabotka od ai asistesten
def odgovori_za_karton(prasanje: str, lekar: dict | None) -> str:
    if err := require_lekar(lekar): # proverka dali e najaven lekar kako korisnik ili pacient
        return err  # ako ne e najaven lekar se dava error poraka ova smee samo da go obrabotuva lekarot
    podatoci = _izvlechi(prasanje)  # se povikuva llm modelot sto go koristam za izvlekuvanje na imeto na paxientp
    if podatoci.get("_error"):  # ako nastane greska pri povikot ili pri parsiranjeto na json
        return podatoci["_error"]   # se vraka greska nazad do korisnikot vo ovoj slucaj do lekarot
    ime = (podatoci.get("ime_pacient") or "").strip() # ako e vo red se zema imeto na paciento i se trgat site prazni mesta
    if not ime: # dokolku nema ime sto moze da se detektira od strana na ai modelot se vraka poraka do lekarot so instrukcii i primer kako treba da izgleda
        return (
            'За картон ми треба име на пациент.\n'  #baranje
            'Пример: „Дај ми картон на Петар Иванов"'   # primer kako da se postavi prasanje do agento
        )
# go delime vlezot na zborovi za polesno prebaruvanje
    delovi = [d for d in ime.split() if d]
    conn = get_connection() # konekcija so bazata i ovozmozuvanje manipulacija so istata
    cur = conn.cursor(dictionary=True)
    # prebaruvanje i prezemanje na podatoci od tabelta pacient
    where = []    # lista za skadiranje na ulovite za sql
    params: list = []      #lisra za parametrite
    if len(delovi) >= 2:    # se proveruva ako se vneseni najmalku dva zbora 
        where.append("LOWER(name_patient) LIKE %s AND LOWER(surname_patient) LIKE %s")  # se prebaruva po ime i prezime vo bazata
        params.extend([f"%{delovi[0].lower()}%", f"%{delovi[-1].lower()}%"])    # se dodavaat vrednostite so procenti za delumno sovpaganje
    else:   # ako e vneseno eden zbor
        where.append("(LOWER(name_patient) LIKE %s OR LOWER(surname_patient) LIKE %s)")  # se pravi proveka dali dali zborot sodrzi ime ILI Prezime
        params.extend([f"%{delovi[0].lower()}%", f"%{delovi[0].lower()}%"]) # se dodava istit zbor dva pati za dvata uslovi
    cur.execute(    # se izvrasuva sql upit za naoganje na pacientot
        "SELECT patient_ID, name_patient, surname_patient, email, phone_number"
        f" FROM patient WHERE {' AND '.join(where)} LIMIT 5",
        params,
    )
    pacienti = cur.fetchall()   # se prevzemaat site pronajdeni pacienti
    if not pacienti:    # dokolku ne e pronajden nitu eden pacient so toa ime vo bazata
        cur.close() # se zatvara konekcija
        conn.close()
        return f'Не најдов пациент „{ime}" во базата.'  # i se pecari soodvetna porka deka ne e pronajden pacient so toa ime
    # dokolku e pronajdeno poveke pacienti so isto ime 
    if len(pacienti) > 1:
        cur.close() # se zatvara konekcijata
        conn.close()
        lista = "\n".join(  # gi spojuvame site pacienti so isto ime i mail adresa za razlikuvanje
            f"• {p['name_patient']} {p['surname_patient']} ({p['email']})"
            for p in pacienti
        )
        return f'Најдов повеќе пациенти со име „{ime}":\n{lista}\n\nТе молам прецизирај име+презиме.'   # se bara preciziranje 
    p = pacienti[0]     # ako imame tocno edno sovpaganje go zememe toj konkreten pacient

    # prezemanje na site pregledi za toj pacient
    cur.execute(
        "SELECT termin_ID, ime_lekar, specijalnost_termin, datum_pregled, vreme_pregled,"
        "       status_pregled, dijagnoza, terapija, napomena"
        " FROM Termin_pregled"
        " WHERE LOWER(TRIM(email_pacient)) = LOWER(TRIM(%s))"  # se povrzuvaat pregleduvanjata preku emailot na pacientot
        " ORDER BY datum_pregled DESC, vreme_pregled DESC",     # se sortiraat od najnovite kon najstarite
        (p["email"] or "",),
    )
    pregledi = cur.fetchall()   # se prezema celata istorija na paciento
    cur.close() # se zatvara konekcijata
    conn.close()

    # 3) Definiranje na strukturata na medicinskiot karton
    linii = [
        f"МЕДИЦИНСКИ КАРТОН",
        f"Пациент: {p['name_patient']} {p['surname_patient']}",
        f"E-пошта: {p['email'] or '-'}",
        f"Телефон: {p['phone_number'] or '-'}",
        f"ID на пациент: {p['patient_ID']}",
        "",
    ]
    if not pregledi:    # dokolku pacientot postoi vo bazata no nema napraveno pregled
        linii.append("Нема забележани прегледи.")   # se vraka tekst
        return "\n".join(linii)

    zavrseni = sum(1 for r in pregledi if r["status_pregled"] == "завршен") # broi kolku zavrseni pregled ima paciento
    zakazani = sum(1 for r in pregledi if r["status_pregled"] == "закажан") # broi kolku se zakazani
    linii.append(f"Вкупно прегледи: {len(pregledi)} (завршени: {zavrseni}, закажани: {zakazani})")  # definira krajna struktura na porakta.
    linii.append("")
    linii.append("Последни прегледи:")
# se naogjaat i prikazuvaat detalite za poslednite najmnogu 6 pregledi na pacientot
    for r in pregledi[:6]:
        linija = (
            f"\n• {format_datum(r['datum_pregled'])} {format_vreme(r['vreme_pregled'])}"
            f" — {r['status_pregled']} (ID {r['termin_ID']})"
        )
        if r.get("ime_lekar"):  # dokolku e zapisano imeto na lekarot koj go izvrsil pregledot
            linija += f"\n  Лекар: {r['ime_lekar']}"    # se dodava imeto na lekarot
        if r.get("specijalnost_termin"):    # dokolku se znae specijalnosta
            linija += f" ({r['specijalnost_termin']})"  # se dodava i specijalnosta isto za dijagnoza terapija i napomena
        if r.get("dijagnoza"):
            linija += f"\n  Дијагноза: {r['dijagnoza']}"
        if r.get("terapija"):
            linija += f"\n  Терапија: {r['terapija']}"
        if r.get("napomena"):
            linija += f"\n  Напомена: {r['napomena']}"
        linii.append(linija)

    return "\n".join(linii) # se spojuvaat site linii vo edna poraka za prikaz na lekaort
