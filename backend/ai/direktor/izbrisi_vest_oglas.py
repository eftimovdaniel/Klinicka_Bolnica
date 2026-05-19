"""
Бришење вест или оглас — само за директорот (правила + AI, локално за „истата").

Примери:
- „Избриши го најновиот оглас"           → DELETE од Vrabotuvanje (последниот)
- „Избриши ја најновата вест"            → DELETE од Novosti (последната)
- „Избриши ја веста со наслов …"         → DELETE по наслов од Novosti
- „Избриши оглас ID 5"                   → DELETE Vrabotuvanje WHERE id=5
- „Избриши вест 3"                       → DELETE Novosti WHERE id=3
"""

import re
from typing import Any
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.auth import require_direktor
from ai._kernel.db_helpers import ai_error_text, db_cursor, fetch_one, normalize_int
from ai._kernel.groq_client import GROQ_OFFLINE_MSG, ask_ai, groq_e_isklucen
from ai._kernel.prompt_loader import load_prompt
from ai._kernel.transliteracija import transliterijaj
from ai.opsto.vest_naslov import (
    prasanje_e_izbrisi_po_kontekst,     # proverka dali prasanjeto seodnesuva na vest sto posledno bila objavena
    prasanje_e_izbrisi_vest_oglas,      # proverka dali prasanjeto se odnesuva na toa dali korisnikot saka da ja izbrise vesta
    prasanje_ima_brisenje_marker,       # proveka dali vo teksto ime izbrisi, brisenje , trgni ili slicno   
    pronajdi_vest_po_naslov,            # funkcii za proverka vo bazata koristejki go nejzinoto ime 
)
# funkcija koja go prasuva ai modelot sto tocno sakame da izbriseme 
def _izvlechi(prasanje: str) -> dict[str, Any]:
    """AI враќа dict со tip/id/kriterium."""
    odgovor = ask_ai(   # povikuvanje na ai modelot
        f"Прашање: „{prasanje}\"",  # se postavuva prasanjeto sto e vneseno od korisnikot 
        system_prompt=load_prompt("direktor_izbrisi_vest_oglas"), # go vcituvame promto so pravila za toa kako teba da se odnsuva koga se brisi nekoja vest i slicno
        )
    print(f"[izbrisi] AI: {odgovor!r}") 
    return parse_ai_json(odgovor, log_tag="izbrisi_vest_oglas")
# pomosna funkcija koja ja birse novosta po id ili onaa koja e objavena najnova ili posledna
def _izbrisi_vest(target_id: int | None) -> str:
    """Брише вест по ID или најновата."""
    with db_cursor() as (conn, cur):    # se vospostavuva konekcija so bazata i se vlecat informacii od bazata po ostvaruvanje na konekcijata
        if target_id:   # dokolku korisnikot vnel id za biresenje na novosta se bara po id 
            cur.execute("SELECT id, naslov FROM Novosti WHERE id = %s", (target_id,))   # se selektira novosta koja e odgovara na vneseniot id od starna na direktorot
        else:
            cur.execute(
                "SELECT id, naslov FROM Novosti ORDER BY created_at DESC, id DESC LIMIT 1"  # vo sprotivno se izvlekuvaat novostit od najnova koj nastara
            )
        vest = fetch_one(cur)   # se zema redot ili vesta od bazata koja e najnova a e smestena vo cur
        if not vest:        # ako id ne odgovata na nitu edna vest 
            if target_id:   # ili se bara nekoj konkteren id 
                return f"Не најдов вест со ID {target_id}."     # se vraka poraka deka ne e pronajdena vest so toj id 
            return "Немате вести во базата."    # se vraka poraka deka nema vesti vo bazata  

        vest_id = int(vest["id"])   # se zema id na vesta i se smestuva vo vest_id za da moze da se koristi za brisenje na vestata od bazata
        naslov = str(vest.get("naslov") or "")  # se zema naslovot na vesta 
        cur.execute("DELETE FROM Novosti WHERE id = %s", (vest_id,))    # se koristi za da ja izbriseme vesta od bazata so id 
        conn.commit()   # site promeni se zacuvuvaat vo bazata na podatoci
    return f"Вест е избришана.\n\nID: {vest_id}\nНаслов: {naslov}"  # vraka poraka deka vesta e izbrisana so toj i toj id i naslovot na vesta
# funkcija koja go brise oglasot za rabota 
def _izbrisi_oglas(target_id: int | None) -> str:
    """Брише оглас по ID или најновиот."""
    with db_cursor() as (conn, cur):    # kreiranje na konekcija so bazata i moznost za izvvrasuvanje na aktivnosti na istata
        if target_id:   # ako korisnikto navede tocen id na oglasot se bara po vneseniot id
            cur.execute(        # se selektira oglasot od bazata so toj id
                "SELECT id_oglas, pozicija, oddel FROM Vrabotuvanje WHERE id_oglas = %s",
                (target_id,),
            )
        else:   # dokolku ne e vnesen id se bara najnoviot oglas za rabota
            cur.execute(
                "SELECT id_oglas, pozicija, oddel FROM Vrabotuvanje"    # se selekira oglasot za rabota
                " ORDER BY datum_na_objava DESC, id_oglas DESC LIMIT 1" # i se podreduva vo opagacki redosled od najnoviot do najstariot
            )
        oglas = fetch_one(cur)  # se zema oglasot od bazata dokolku postoi i go smestuvamee vo oglas
        if not oglas:   # dokolku ne e oglas
            if target_id:   # ako baranjeto po id , bazata vraka prazno 
                return f"Не најдов оглас со ID {target_id}."    # se pecati deka ne e pronajden oglas
            return "Немате огласи во базата."   # se pecati deka nema oglas vo bazata
        oglas_id = int(oglas["id_oglas"])   # se zima id na oglasot i go pretvarame vo int  
        pozicija = str(oglas.get("pozicija") or "") # se zema rabotnata pozicija od oglasot 
        oddel = str(oglas.get("oddel") or "")   # se zema oddelot za koj e namente toj oglas
        cur.execute("DELETE FROM Vrabotuvanje WHERE id_oglas = %s", (oglas_id,))    # se brise oglasot so toj id od bazata
        conn.commit()   # site promeni se zacuvuvaat vo bazata na podatoci

    return (    # modelot vraka poraka deka oglasot e izbrisan so konktetniot id koj e dodaden pri negovi kreiranje, pozicija i oddel za koj istiot toj oglas bil namenet
        f"Огласот е избришан.\n\n"
        f"ID: {oglas_id}\n"
        f"Позиција: {pozicija}\n"
        f"Оддел: {oddel}"
    )
# glavna tocka za brisenje na vest ili na oglasi
def odgovori_za_brisenje(
    prasanje: str, lekar: dict | None, kontekst: dict | None = None # prime prasanje vo vid na string, lekar i memorija od porakite smesteni vo kontekstoto
) -> str:   # se vraka finalniot tekst na ekranot so koj e potvrdeno deka e napravena promena ili pa ne e
    """Главна точка - повикана од router-от."""
    if err := require_direktor(lekar):  # proverka dali korisnikot koj se obiduva izbrise vest ili oglas e direktor (se dava da se pravat ovie promeni dokolku e najaven 
        # др Владко Захариев vo sportivno ova ne treba da e ovozmozeno)
        return err      # ako ne e najaven gorespoenetiot lekar se vraka error, porka za nastanata greska 

    if prasanje_e_izbrisi_po_kontekst(prasanje, kontekst) and kontekst: # proverka dali korisnikot saka da ja izbrise vesta spored konekstot na prethodnite poraki
        vid = kontekst.get("last_vest_id")  # se zema posledniot id na objavenata vest
        if vid: # ako toa id postoi vo memorijata na porakite 
            return _izbrisi_vest(int(vid))  # vesta se brise od sajtot 

    if groq_e_isklucen():   # se proveruva dali ai e islucen ili ako nemam ostanato tokeni
        return GROQ_OFFLINE_MSG # se pecate poraka za nastanata greska
    podatoci = _izvlechi(prasanje) # gi praka podatocite do ai za da se izvlece tipot i id 
    if msg := ai_error_text(podatoci):  # proverka dali ai vo svojot json odgovor vratil sistemska gresja
        return msg  # ako ima ja vraka greskata do korisnikot

    tip = (podatoci.get("tip") or "").strip().lower()   # go zema tipot na objektot (vest ili novost) go trgna praznoto mesto i gi pretvara site vo malku bukvi
    target_id = normalize_int(podatoci.get("id"))   # go pretvara i go cisti id to 
    if tip not in ("vest", "oglas"):    # dokolku ne moze da se vide dali e vest oglas, ai ne moze da poznae
        low = prasanje.lower()  
        if any(w in low for w in ("оглас", "oglas")):
            tip = "oglas"
        elif any(w in low for w in ("вест", "новост", "vest", "novost")):
            tip = "vest"
        else:
            return (
                "Не разбирам што да избришам. Пример:\n"
                "• „Избриши го најновиот оглас\"\n"
                "• „Избриши ја најновата вест\"\n"
                "• „Избриши оглас ID 5\""
            )

    if tip == "vest":       # ako tipot e vest
        kriterium = (podatoci.get("kriterium") or "").strip().lower()   # se proveruva dali kriteriumot za brisenje od ai e po naslov
        naslov_ai = (podatoci.get("naslov") or "").strip()  # go zema naslovot koj ai uspeal da go izdvoi od prasanjeto
        if kriterium == "naslov" or naslov_ai:  # ako se brise vrz osnova na naslovot na vesta
            vest = pronajdi_vest_po_naslov(naslov_ai or prasanje)   # ja prebaruva bazata za da najde vest so takov naslov
            if vest:    # ako najde soodvetna vest so toj naslov vo bazata 
                return _izbrisi_vest(int(vest["id"]))       # se zema id na vesta i ja povikuva funkciajta so koja ke se izbrise vesta od bazata pa i od sajtot
            return (    # vo sprotivno se vraka 
                "Не најдов вест со тој наслов.\n\n"
                "Проверете го насловот или наведете ID, на пр. „Избриши вест 3“."
            )
        return _izbrisi_vest(target_id) # ako ne e pronajden naslov se birse i spored id (vesta, novosta)
    return _izbrisi_oglas(target_id)    # funkcija koja se povikuva za brisenje na oglasot spored id
