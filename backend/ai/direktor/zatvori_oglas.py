import re
from database import get_connection
from ai._kernel.auth import require_direktor
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import ask_ai
PROMPT = """
Ти си систем што извлекува податоци за затворање оглас за работа. Корисникот е директор и сака да затвори оглас (status → „истечен"). Врати САМО JSON:
{"id": число | null, "pozicija": "текст" | null, "site": true | false}
Правила:
- Ако корисникот спомне ID на оглас → "id"=число.
- Ако корисникот спомне позиција (пр. „кардиолог", „медицинска сестра") → "pozicija"=текст.
- Ако корисникот вели „сите огласи", „сите" → "site"=true.
- Ако нема ништо јасно → сите вредности null/false. БЕЗ markdown, БЕЗ објаснувања. Само JSON. """.strip()
# funkcija koja gi analizira baranjata an direktorot so pomos na ai 
def _izvlechi(prasanje: str) -> dict:
    odgovor = ask_ai(f"Прашање: „{prasanje}\"", system_prompt=PROMPT)   # prasanjeto se praka na groq so soodveten promt
    print(f"[zatvori_oglas] AI: {odgovor!r}")
    return parse_ai_json(odgovor, log_tag="zatvori_oglas")  # se parsira json vo python recnik
# funkcija koja zatvara oglas so koristenje na ai na samiot oglas
def _zatvori_po_id(target_id: int) -> str:
    conn = get_connection() # ostvaruvanje na konekcija so bazata na podatoci i iizveduvanje na soodvetna akcija brz nea
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id_oglas, pozicija, oddel, status_oglas FROM Vrabotuvanje WHERE id_oglas = %s",
        (target_id,), # se selektira oglasot so vneseniot id od strana ne direktorot 
    )
    oglas = cur.fetchone()  # vo oglas go prezemam baraniot oglas od bazata
    if not oglas:   # ako ne postoi oglas so baraniot id, ja zatvrame konekcijarta so bazata i se dava odgovor deka oglaso so baran id ne e pronajden vo bazata
        cur.close()
        conn.close()
        return f"Не најдов оглас со ID {target_id}."
    if (oglas["status_oglas"] or "").lower() == "истечен":# dokolki oglasot e vejke istecen mu e minat datumot se zatvara povtorno konekcijata so bazata bidejki odma koa ke mine toj datumo oglasot se brise od sajto,
        # i se dava doodetna porka
        cur.close()
        conn.close()
        return f'Огласот „{oglas["pozicija"]}" (ID {target_id}) веќе е истечен.'
# se pravat promeni vo bazata i oglasot so vnesenito id se srava kako istecen 
    cur2 = conn.cursor()
    cur2.execute(
        "UPDATE Vrabotuvanje SET status_oglas='истечен' WHERE id_oglas = %s",
        (target_id,),
    )# se pravi finalna promena i se zatvarat konekcii
    conn.commit()
    cur.close()
    cur2.close()
    conn.close()
# prikaz na stanata kaj direktorot
    return (
        f"Огласот е затворен (статус: истечен).\n\n"
        f"ID: {oglas['id_oglas']}\n"
        f"Позиција: {oglas['pozicija']}\n"
        f"Оддел: {oglas['oddel']}"
    )
# funkcija koja ovozmozuva brisenje na oglasot po pozicija
def _zatvori_po_pozicija(pozicija: str) -> str:
    conn = get_connection() # ostvaruvanje na konekcija so bazata
    cur = conn.cursor(dictionary=True)  
    p = f"%{pozicija.lower()}%" # obrabotka na tekstok i go smestuvam celiot da e so mali bukvi
    cur.execute(
        "SELECT id_oglas, pozicija, oddel, status_oglas FROM Vrabotuvanje"  # upit za aktivni oglasi koi gi ima vo tekstot
        " WHERE LOWER(pozicija) LIKE %s AND COALESCE(LOWER(status_oglas),'') <> 'истечен'"  
        " ORDER BY datum_na_objava DESC",   # se sortirat po najnovite objavi prvo
        (p,),
    )
    rows = cur.fetchall()   # se prezemaat site aktivni oglasi od bazata 
    if not rows:    # ako ne e pronajden aktive oglas vo bazata na taa pozicija, se zatvara konekcija i se pecati soodvetna poraka
        cur.close()
        conn.close()
        return f'Не најдов активен оглас за „{pozicija}".'
    if len(rows) > 1:   #ako imame poveke aktivni oglasi za edna ista pozicija
        # ja zatvarame konekcijata
        cur.close()
        conn.close()
        lista = "\n".join(f"• ID {r['id_oglas']}: {r['pozicija']} ({r['oddel']})" for r in rows[:5])    # i gi spojuvame site oglasi na edno mesto vo promenliva lista
        return (    # se bara od direktorot da go prepoznae id na oglasot koj saka da go izbrise
            f'Најдов повеќе огласи за „{pozicija}":\n{lista}\n\n'
            f'Те молам прецизирај, пр. „Затвори оглас ID {rows[0]["id_oglas"]}".'
        )
    oglas = rows[0] # ako ime edno sovpaganje go zema toj oglas
    cur2 = conn.cursor()  # se pravi update na poadtocite vo bazata 
    cur2.execute(
        "UPDATE Vrabotuvanje SET status_oglas='истечен' WHERE id_oglas = %s",
        (oglas["id_oglas"],),
    )# zatvaranje na konekcija i pravenje na promeni so commit
    conn.commit()
    cur.close()
    cur2.close()
    conn.close()
    return (# poraka na stana na direktorot
        f"Огласот е затворен (статус: истечен).\n\n"
        f"ID: {oglas['id_oglas']}\n"
        f"Позиција: {oglas['pozicija']}\n"
        f"Оддел: {oglas['oddel']}"
    )
# funkcija koja ovozmozuva zatvaranje na site oglasi naednskaa
def _zatvori_site() -> str:
    #ostvaruvanje na konekcija so bazata, i se pravi update na site oglasi so status istencen
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE Vrabotuvanje SET status_oglas='истечен'"
        " WHERE COALESCE(LOWER(status_oglas),'') <> 'истечен'"
    )
    promeneti = cur.rowcount    # se zemaat redovite koi bile azurirani vo bazata
    conn.commit()   # promena vo bazata i zatvaranje na site otvoreni konekcii
    cur.close()
    conn.close()
    if promeneti == 0:  # dokolku nema aktivni oglasi
        return "Нема активни огласи за затворање."
    return f"Затворени се {promeneti} огласи (статус: истечен)."

def odgovori_za_zatvoranje_oglas(prasanje: str, lekar: dict | None) -> str:
    """Главна точка - повикана од router-от."""
    if err := require_direktor(lekar):  # proveka koj e najaven na sistemot
        return err  # ako ne e direktor error
    podatoci = _izvlechi(prasanje)  #ai se povikuva za izvlekuvanje na parametrite
    if podatoci.get("_error"):  # ako nastane greska pri obrabotka ili pri parsiranje na json ni vraka error
        return podatoci["_error"]
    if podatoci.get("site"):    #ako e pobarano da se zatvora site oglasi , ai povikuva funkcija za zatvaranje na site oddednas
        return _zatvori_site()
    target_id = podatoci.get("id")  # ako postavi id 
    if target_id:   # i dokolku postoi toa id
        try:
            return _zatvori_po_id(int(target_id))   # se povikuva funkcijata za zatvaranje spored id 
        except (TypeError, ValueError): # dokolku nastane nekoj greksa se preskokunuva
            pass
    pozicija = (podatoci.get("pozicija") or "").strip() # se proveruva teksto za pozicija
    if pozicija:    # ako ima aktivna pozicija so oglas
        return _zatvori_po_pozicija(pozicija)   # ai ja povikuva funkcijata za zatvaranje na oglas spore ime na pozicija
    return (
        'Не разбирам кој оглас да го затворам. Пример:\n'
        '• „Затвори го огласот за кардиолог"\n'
        '• „Затвори оглас ID 5"\n'
        '• „Затвори ги сите огласи"'
    )
