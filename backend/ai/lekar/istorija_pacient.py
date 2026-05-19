import re
from database import get_connection
from ai._kernel.auth import require_lekar
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import ask_ai


PROMPT = """ Ти си систем што извлекува име на пациент од прашање. Корисникот е лекар и сака историја/преглед на свој пациент. Врати САМО JSON:
{"ime_pacient": "Име Презиме" | null}
Правила:
- ако има јасно име+презиме → "ime_pacient"="Име Презиме"
- ако има само едно име → "ime_pacient"="Име"
- ако нема воопшто име → null
БЕЗ markdown, БЕЗ објаснувања. Само JSON.""".strip()
# funkcija koja gi praka prasanjeto na lekarot do ai agento
def _izvlechi(prasanje: str) -> dict:
    odgovor = ask_ai(f"Прашање: „{prasanje}\"", system_prompt=PROMPT)   # se povikuva llm so prasanje i idefiniraniot sistemski prompt
    print(f"[istorija] AI: {odgovor!r}")
    return parse_ai_json(odgovor, log_tag="istorija_pacient")   # se dava odgovor od ai agento vo forma na pyrhon recnik
# funkcija za formatiranje na objekti od tip na data vo citliv mkd
def _fmt_datum(d) -> str:
    if hasattr(d, "strftime"):  # se proverkuva dali funkcijata e validen datatime ili data objekt
        return d.strftime("%d.%m.%Y")   # ako e datum go pretvata vo strig so soodvetna forma definiran vo zagradata
    return str(d)   # ako e vejke string ili drug tip na podatok go pretvara vo obicen sting i go dava
def _fmt_vreme(t) -> str:   # formatiranje na vremeto vo 24 casoven format
    if hasattr(t, "strftime"):  # ako e soodveten objket gi zema cas i minuti i istite gi vraka
        return t.strftime("%H:%M")
    return str(t)[:5] # dokolku e obicen string od bazata gi zema prvite 5 elemeti (HH:MM)
# funkcija koja vraka odgovor na lekarot
def odgovori_za_istorija(prasanje: str, lekar: dict | None) -> str:
    if err := require_lekar(lekar): # se pravi proveka dali e najaven lekar toj ima pristap
        return err  # dokolku ne e najavaen lekar se vraka error poraka
    doctor_id = lekar["doctor_ID"]  # koga ke se uvide deka e lekar se zema negoviot id za da se osigurame deka ke gi gleda samo svoite pacienti
    podatoci = _izvlechi(prasanje)  # se povikuva ai agentot za da go analizira vnesot na lekarot i da go izolira imeto na pacientot od soodvetniot kontekst
    if podatoci.get("_error"):  # se proveruva dali parsiranjeto za json ima nekoja vnatresna greska 
        return podatoci["_error"]   # dokolku posti ja vraka tehnickata greska
    ime = (podatoci.get("ime_pacient") or "").strip()   # go izolira imeto od json formatot i gi trga site prazni mesta
    if not ime: #ako nema vneseno ime vo promtot na lekarot, mu se davaat instrukcii kako da postapi
        return (
            'За да најдам историја ми треба име на пациент.\n'
            'Пример: „Колку пати беше Петар Иванов кај мене?"'
        )
    delovi = [d for d in ime.split() if d]  # pravime podelba na imeto na bukvi po praznoto mesta za da se vide dali e veneseno ime ili ime i prezime
    conn = get_connection() # ostvaruvanje na konekcia so bazata na podatoci
    cur = conn.cursor(dictionary=True)
    sql = ( # sql nareba koja mi gi selektira klucnite tabeli potrebni za ivaa aktivnost na ai agento
        "SELECT termin_ID, ime_pacient, datum_pregled, vreme_pregled,"
        "       status_pregled, dijagnoza, terapija"
        " FROM Termin_pregled"
        " WHERE doctor_ID = %s"
    )
    params: list = [doctor_id]
# dokolku ai agento razbere dva zbota 
    if len(delovi) >= 2:
        sql += " AND LOWER(ime_pacient) LIKE %s AND LOWER(ime_pacient) LIKE %s" # se dava prebaruvanje kade i prviot i vtorniot del mora da bidat isti bez razlika dali e mala ili golema bukva 
        params.extend([f"%{delovi[0].lower()}%", f"%{delovi[-1].lower()}%"])
    else: # filtriranje vo bazata samo na eden zbor, koj se pretvra vo mala bukva
        sql += " AND LOWER(ime_pacient) LIKE %s"
        params.append(f"%{delovi[0].lower()}%") # se dodava vo parametrite za sql izvrasuvanje

    sql += " ORDER BY datum_pregled DESC, vreme_pregled DESC"   # se podreduvaat pregledite taka da najnovite se na vrvot
    cur.execute(sql, params)    # se izvrasuva sql naredbata 
    rows = cur.fetchall()   # a gi zema site redovi koj se dobieni od izvrsenata aktivnost vo bazata
    cur.close() # zatvaranje na konekcijata
    conn.close()
    if not rows:    #dokolku vo bazata nema pacienti, se vrati prazna lista se pecati porakata poduli
        return f'Не најдов прегледи кај тебе за пациент „{ime}".'

    zavrseni = sum(1 for r in rows if r["status_pregled"] == "завршен") # broi vkupen broj na zavrseni pregledi
    zakazani = sum(1 for r in rows if r["status_pregled"] == "закажан") # broi kolku pregledi se zakazani od denot koga e pobarano toa pa ponatamu
    otkazani = sum(1 for r in rows if r["status_pregled"] == "откажан") # broi kolku pacienti otkazale pregled kaj dadeniot lekar
    # definiranje na tekstualniot odgovor
    # porakata go imam oblikot prikazan podolu
    linii = [
        f'Историја на „{ime}" кај тебе (вкупно {len(rows)} прегледи):',
        f"• Завршени: {zavrseni}",
        f"• Закажани: {zakazani}",
        f"• Откажани: {otkazani}",
        "",
        "Последни прегледи:",
    ] 
    for r in rows[:5]:  # pravi loop na prvite 5 reda
        linija = (
            f"• {_fmt_datum(r['datum_pregled'])} {_fmt_vreme(r['vreme_pregled'])}"  # format na linijata za datum vreme status i id na terminot
            f" — {r['status_pregled']} (ID {r['termin_ID']})"   
        )
        # proverka dali vo bazata ima postaveno i dijagnoza, dokolku ima se pacati i soodvetnata dijagnoza
        if r.get("dijagnoza"):
            linija += f"\n  Дијагноза: {r['dijagnoza']}"
        linii.append(linija)

    return "\n".join(linii) # se se spojuva vo eden paragra koj ke e prikazan kako poraka vo frontend delot
