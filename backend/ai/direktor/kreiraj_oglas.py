""" Креирање оглас за работа преку AI — само за директорот. Директорот пишува неструктурирано (залепен оглас, разговорен стил). Groq извлекува позиција, оддел и рок → INSERT во Vrabotuvanje. """
import re
from datetime import date, datetime, timedelta
from database import get_connection
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.auth import require_direktor
from ai._kernel.groq_client import GROQ_OFFLINE_MSG, ask_ai, groq_e_isklucen
from ai._kernel.groq_helpers import groq_zadolzhitelen
from ai._kernel.prompt_loader import load_prompt
from ai._kernel.prompt_helpers import today_prompt_line
from ai._kernel.transliteracija import transliterijaj
from ai._kernel.utils import format_datum
# funkcija koja gi vlece site oddeli od bazata na podatoci i gi vraka kako lista vo tip na string
def _zimi_oddeli() -> list[str]:
    conn = get_connection() # se pravi konekcija so bazata na podatoci
    cur = conn.cursor() # se pravi kveri za izveduvanje akcii vo bazata
    cur.execute("SELECT DISTINCT ime_na_oddel FROM Oddeli ORDER BY ime_na_oddel") # se selektiraat site iminja na oddelite i gi podreduvame po ime
    oddeli = [str(r[0]) for r in cur.fetchall() if r[0] is not None]    # site vrateni izlezi gi zemame i go stavame vo nova lista , dokolku ima takvi a vo sprotivno se vraka none
    cur.close() # preku na kveri za izveduvanje akcii 
    conn.close() # zatvaranje na konekcijata so bazata na podatoci
    return oddeli   # vraka oddeli
# funkcija za usoglasuvanje na oddelot so ai so tocnoto ime vo bazata na podatoci
def _najdi_oddel(oddel: str, site_oddeli: list[str]) -> str | None:
    """Споредба со листа оддели од база."""
    if not oddel:   # ako vrednosta za oddelot od ai e prazna 
        return None # se vraka none
    o = oddel.lower().strip()   # inaku vo o se smestuvat site oddeli so mala bukva
    for x in site_oddeli:    # pominuva niz site oddeli koj gi ima vo bazata na podatoci
        if x.lower() == o or o in x.lower() or x.lower() in o:  # dokolku ima celosno ili delumno poklupuvanje vo tekstot
            return x    # se vraka tocnoti ime na oddelot, a vo sprotivno none
    return None
# funkcija koja datumot od ai go pretvara vo Python datum objekt
def _parsiraj_rok(rok_val) -> date | None:  
    if not rok_val: # ako ai ne izvlece datum ili vrednosta e none ili ne e navedena
        return None # se vraka none
    s = str(rok_val).strip()[:10] # go zema tekstot i go pretvata vo GGGG-MM-DD  (prvite 10 karakteri)
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()  # stringot se parsira vo validen data objekt
    except ValueError:  # ako formatiranjeto ne e soodvetno ili dade greski 
        return None # se vraka one.
# funkcija koja raboti so groq
def _izvlechi_so_ai(prasanje: str, denes: date, site_oddeli: list[str]) -> dict:
    """Само Groq JSON: pozicija, oddel, rok."""
    if msg := groq_zadolzhitelen(): # proverka dali imam groq servis so moze da obrabote baranjeto
        return {"_error": msg}  # ako nemam ili ne e dostapen vraka poraka za greska
# formiranje na promto sto ke se prati do groq
    prompt = (
        f"{today_prompt_line()} ({format_datum(denes)}).\n\n"    # se dava denesniot datumo dokolku e potrebno da ja presmeta datata
        f"Оддели во базата: {', '.join(site_oddeli)}\n\n"   # se davaat lista na site oddeli koj bolnicata gi ima vo bazata
        f"Текст од корисникот:\n{prasanje}\n\nВрати JSON."  # se zema teksto od direktorot i se praka vo json format za obrabotka
    )
    odgovor = ask_ai(prompt, system_prompt=load_prompt("direktor_kreiraj_oglas"))   # povik do ai so goreformiraniot promt
    print(f"[kreiraj_oglas] AI: {odgovor!r}")   
    return parse_ai_json(odgovor, log_tag="kreiraj_oglas")  # go pretvata tekstot vo recnik i go vraka
# dali e kazana samo namerata bez da dade poveke detali
def _samo_naslov_bez_detali(prasanje: str) -> bool:
    p = re.sub(r"\s+", " ", transliterijaj(prasanje).lower().strip()) # gi brise praznite mesta i gi pretvara vo latinica
    return p in (   # vraka true ako se srekavat nekoj od zborvite podole
        "оглас за работа",
        "oglas za rabota",
        "креирај оглас",
        "kreiraj oglas",
        "објави оглас",
        "нов оглас",
    )

def odgovori_za_kreiranje_oglas(prasanje: str, lekar: dict | None) -> str:
    if err := require_direktor(lekar):  # proveka dali toj sto ja povikuva funkcijata e direktor
        return err  # ako ne e dava error
    if _samo_naslov_bez_detali(prasanje):   # ako se vnese samo poraka bez detali , za da se razbere od ai 
        return (
            "Сакате да објавите оглас — во ред.\n\n"    # bara potvrda
            "Пишете слободно, како што ви е потребно,  на пример:\n"    # instrukcija
            "«Треба медицинска сестра на гинекологија, пријави се до 10 јуни»\n" # primer
            "или залепете го целиот текст од Facebook/Word. Ќе го разберам и ќе го внесам."
        )
    if groq_e_isklucen():   # dokolku groq ne rabote
        return GROQ_OFFLINE_MSG #soodvetna error poraka
    denes = date.today() # go zema datumot kako pocetna tocka 
    site_oddeli = _zimi_oddeli()    # gi zima site oddeli na kb 
    ai = _izvlechi_so_ai(prasanje, denes, site_oddeli)  # groq gi izvediva informaciite preku json
    if ai.get("_error"):    # dokolku nasta greska kaj ai
        return str(ai["_error"])    # vraka se porakata za nastanatata greska
    pozicija = (ai.get("pozicija") or "").strip() or None   # ja izvlekuva pozicijata od ai 
    oddel_raw = (ai.get("oddel") or "").strip() or None # go zema imeto na oddelot
    oddel = _najdi_oddel(oddel_raw or "", site_oddeli)  # 
    rok = _parsiraj_rok(ai.get("rok"))  # datumot go pretvara za rok od ai so soodveten ptython datum objekt 

    if not pozicija or not oddel: #dokolku ai ne uspee da detektira oddeli ili pozicija
        delumno = []    # kreira lista kade sto e zapisano samo ona sto go razbral
        if pozicija:    # ako imame pogodok kaj pozicija
            delumno.append(f"позиција: {pozicija}") # ja dodava vo listata za izvestuvanje
        if oddel_raw and not oddel:
            delumno.append(f'оддел "{oddel_raw}" не е во базата')
        elif oddel:
            delumno.append(f"оддел: {oddel}")
        if rok:
            delumno.append(f"рок: {format_datum(rok)}")
        uvod = (
            f"Го разбирам делумно ({'; '.join(delumno)})."
            if delumno
            else "Не успеав целосно да го разберам огласот."
        )
        return (    # poraka do direktorot da dade povise detali ako ne moze da pronajde nisto
            f"{uvod}\n\n"
            "Дополнете во следната порака што недостасува (може неструктурирано), "
            "на пример: «сестра, гинекологија, до 15 јуни» или испратете го целиот текст повторно."
        )

    if rok is None: # ako ne e naveden rok koga e kraj za apliciranje se zema da e 30 dena pocnuvajki od denot na objava
        rok = denes + timedelta(days=30)
    if rok < denes: # ako e vnesen minat datum sisitemot advotatski posatvuva 30 den od momento na objava
        rok = denes + timedelta(days=30)

    conn = get_connection() # ostvaruvanje na konekcija so bazata na podatoci i kveri za nejzina manipulacija
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO Vrabotuvanje (pozicija, oddel, datum_na_objava, datum_na_prijavuvanje, status_oglas)"
        " VALUES (%s, %s, %s, %s, 'активен')",  # se postavuvaat podatocite vo soodvetnite koloni od tabelata i se stava status na oglasot aktiven
        (pozicija, oddel, denes, rok),
    )
    conn.commit()   # oslobboduvanje od konekcijata
    cur.close()
    conn.close()
# izlez na stranata na direktorot
    return (
        f"Огласот е креиран!\n\n"
        f"Позиција: {pozicija}\n"
        f"Оддел: {oddel}\n"
        f"Рок за пријава: {format_datum(rok)}\n\n"
        "Проверете го на делот Кариера на сајтот."
    )
