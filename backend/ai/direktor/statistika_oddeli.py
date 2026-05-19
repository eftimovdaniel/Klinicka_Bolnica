import re
from datetime import date, timedelta
from database import get_connection
from ai._kernel.auth import require_direktor
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import ask_ai
PROMPT = """
Ти си систем што извлекува параметри за статистика на оддели. Корисникот сака анализа на најпосетени/најпопуларни оддели. Врати САМО JSON:{"top_n": число (1-20) | null, "period": "denes" | "nedela" | "mesec" | "godina" | "site" | null}
Правила:
- ако корисникот вели „топ 5", „топ 3" → "top_n" = тој број (1-20).
- ако нема број → null (ќе биде default 10).
- период:
  • „денес" / „сегашно" → "denes"
  • „оваа недела" / „последните 7 дена" → "nedela"
  • „овој месец" / „последните 30 дена" → "mesec"
  • „оваа година" → "godina"
  • „воопшто" / „вкупно" / не е спомнат → "site" или null
БЕЗ markdown, БЕЗ објаснувања. Само JSON. """.strip()
# funkcija koja go povika ai za da gi analizira zborovite na direktorot
def _izvlechi(prasanje: str) -> dict:
    odgovor = ask_ai(f"Прашање: „{prasanje}\"", system_prompt=PROMPT)   # go praka prasanjeto do ai so soodveten promt
    print(f"[statistika] AI: {odgovor!r}")
    return parse_ai_json(odgovor, log_tag="statistika_oddeli")  # go vraka rezlutata kako recenica
# funkcija koja gi mapira tekstualnite periodi od ai odgovorot vo konkreten sql filter  i tekstualna oznaka
def _period_to_dates(period: str | None) -> tuple[date | None, str]:
    if not period or period == "site": # ako ne e napisan period se dava site informacii koj gi ima vo bazata
        return None, "од почеток"
    if period == "denes":   # se postavuva filter i se vlecat podatoci za denesniot den 
        return date.today(), "за денес"
    if period == "nedela":  # se vlecat informacii za poslednite 7 dena 
        return date.today() - timedelta(days=7), "за последните 7 дена"
    if period == "mesec": # se postavuvaat filtri i se vlecat podatoci od poslednite 30 dena
        return date.today() - timedelta(days=30), "за последните 30 дена"
    if period == "godina":
        # od pocetokot na godinata 
        return date(date.today().year, 1, 1), f"за {date.today().year} година"
    return None, "од почеток"
# funkcija koja se povikuva koga se postavuva prasanje za statistika na nekoj oddel
def odgovori_za_statistika(prasanje: str, lekar: dict | None) -> str:
    if err := require_direktor(lekar):  # se proveruva koj e najaven, dali e najaven direktor poso onaka nikoj drug nema uvidi vo ova
        return err  # ako ne e najaven direktor error 

    podatoci = _izvlechi(prasanje)  # povikuvanje na ai ekstrakcijata na parametri od prasanjeto
    if podatoci.get("_error"):  # proverka dali se slucila greska pri parsiranjeto na json
        return podatoci["_error"]   # se vrakja opisot na greskat
    top_n = podatoci.get("top_n")   # prezemanje na vrednosta za brojot na oddeli sto treba da se prikazat
    try:
        top_n = int(top_n) if top_n else 10     # obid za konverzija vo cel broj, ako ne postoi se podrazbira top 10
    except (TypeError, ValueError): # dokolku vrednosta e loso formatirana
        top_n = 10
    top_n = max(1, min(20, top_n))  #osiguravanje na granicite: vrednosta se primoruva da bide pomegju 1 i 20 stavki
    od_datum, label = _period_to_dates(podatoci.get("period"))
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    # Брои термини по специјалност на лекарот (преку JOIN со Doctors)
    # Се користи Doctors.specialty за конзистентност (специјалноста на лекарот = оддел)
    query = """
        SELECT
          COALESCE(NULLIF(TRIM(D.specialty), ''), 'Непознат оддел') AS oddel,
          COUNT(*) AS broj_prevegledi
        FROM Termin_pregled T
        LEFT JOIN Doctors D ON D.doctor_ID = T.doctor_ID
    """
    params: list = []   # lista vo koj se smesteni dobienite podatoci
    if od_datum:    # dokolku e definiran datimot
        query += " WHERE T.datum_pregled >= %s" # se dodeluva where uslovot vo upitot
        params.append(od_datum) # dodavanje na upitot vo listata na izvrsuvanje
    query += " GROUP BY oddel ORDER BY broj_prevegledi DESC LIMIT %s"   # se grupira po oddeli i po opagacki redosled
    params.append(top_n)    # dodavanje na definiranior limit za n kako polseden parametae
    cur.execute(query, params)      # ivrasuvanje na upitot vo bazata na podatoci
    redovi = cur.fetchall()     # se zemaat site selektirani redovi

    # presmetka an vkupen broj na pregledi vo daden vremenski period 
    total_query = "SELECT COUNT(*) AS vk FROM Termin_pregled"   # podatoci se selektiraat od bazata 
    total_params: list = [] # i se smestuvaat vo nova lista
    if od_datum:
        total_query += " WHERE datum_pregled >= %s"     # se dava vo koj period treba da se napravi analiza
        total_params.append(od_datum)      # prodleduvanje na datumot
    cur.execute(total_query, total_params)  # izvrsuvanje na upitot za vkupen broj na pregledi 
    total = cur.fetchone()["vk"] or 0   # se izvlekuvat vkupniot broj i se smestuvaat vo total, dokolku nema se zema 0
    cur.close() # zatvaranje na konekciajs
    conn.close()

    if total == 0 or not redovi:    # proverka dali vo izbraniot period ime detektirano prefledi
        return f"Нема прегледи {label}."

    # formatiranje na odgovorot
    linii = [f"Најпопуларни оддели {label} (вкупно {total} прегледи):\n"]   # inicijalizacija so naslov i kupen broj na napraveni pregledi
    for i, r in enumerate(redovi, start=1):
        broj = r["broj_prevegledi"] or 0
        procent = (broj / total * 100) if total else 0
        linii.append(f"{i}. {r['oddel']}: {broj} ({procent:.1f}%)")

    return "\n".join(linii)
