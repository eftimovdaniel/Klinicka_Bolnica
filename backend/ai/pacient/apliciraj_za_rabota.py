import re                                        
from datetime import datetime                      
from database import get_connection                
from ai._kernel.ai_json import parse_ai_json       
from ai._kernel.db_helpers import (                # pomoshni alatki za rabota so tabelata prijaveni_lekari
    as_dict,                                       # pretvora red od baza vo obichen Python dict
    fetch_one,                                     # zemi samo eden red (ili None ako nema)
    normalize_int,                                 # sigurno „17" → 17 (ili None ako ne moze)
    prijaveni_order_desc,                          # vraka SQL string „ORDER BY datum DESC" — najnovi prvo
    prijaveni_pk_column,                           # vraka ime na primary key kolonata (razlichno po tabela)
    prijaveni_row_id,                              # vadi ID od eden red (bez vaznost kako se vika kolonata)
    prijaveni_select_sql,                          # standarden SELECT od prijaveni_lekari (bez WHERE)
)
from ai._kernel.groq_client import ask_ai          # funkcija — praka prompt do Groq AI i vraka tekst
from ai._kernel.transliteracija import transliterijaj  # pretvora latinica → kirilica (za polesno prebaruvanje)
from ai._kernel.utils import format_datum_vreme    # formatira datetime objekt vo ubav tekst za prikaz
from vrabotuvanje_helpers import (                 # modul za alatki okolu „Vrabotuvanje / Kariera"
    fetch_aktivni_oglasi_rows,                     # SELECT od tabelata Vrabotuvanje (samo aktivni oglasi)
    format_rok_datum,                              # formatira DATE → string „21.07.2024"
)
# Koga ke odgovorime, frontend-ot ke go nosi korisnikot do sekcijata „Kariera" na sajtot
NAV_KARIERA = {"target": "index.html#kariera", "label": "Кариера"}

# AI prompt — upatstvo kako LLM-ot da izvlece pozicija od prashanjeto kako JSON.
# LLM-ot sekogash mora da vraka isklucivo JSON {"pozicija": ...} — nikakov drug tekst.
PROMPT_POZICIJA = """ Ти си систем што извлекува позиција за работа од прашање. Корисникот сака да аплицира за работа во болница. Извлечи го името на позицијата.
Врати САМО JSON: {"pozicija": "<име на позицијата>" | null}
Правила:
- Корисникот пишува на македонски (можно и латиница).
- Прифатени примери: „кардиолог", „хирург", „медицинска сестра", „гинеколог" итн.
- Ако пишува на латиница, врати на кирилица: „kardiolog" → „Кардиолог".
- Ако позицијата НЕ е јасна (само „сакам да аплицирам") → null.
- Ако корисникот залепи цел оглас за работа → извлечи ја позицијата од текстот.
БЕЗ markdown, БЕЗ објаснувања.
""".strip()  # .strip() gi trga praznite mesta na pochetok/kraj (LLM-ovite se chuvstvitelni)

# AI prompt za izvlekuvanje na broj na medicinska licenca od odgovor.
# `preskoki: true` znaci „korisnikot ne saka da dade" (napishal „nemam", „preska", itn.)
PROMPT_LICENCA = """ Ти си систем што извлекува број на медицинска лиценца од одговор.
Врати САМО JSON: {"licenca": "<број (само цифри)>" | null, "preskoki": true/false}
Правила:
- Извлечи го бројот. Пр. „Бројот ми е 12345" → "12345".
- Ако корисникот напише „немам", „преска", „пропушти", „не сакам" → preskoki: true.
- Ако не е јасно → licenca: null, preskoki: false. БЕЗ markdown.""".strip()

# Funkcija sho praka potvrda na email po uspeshen INSERT vo bazata
def _isprati_email_za_aplikacija( to_email: str, ime: str, prezime: str, pozicija: str, licenca: str | None,) -> None:                                        
    """Praka potvrda na email po uspeshen INSERT."""
    # Prva proverka — ako email-ot ne e validen, ne pravime nishto
    if not to_email or "@" not in to_email:
        return # izlez bez greshka (ne e kritichno)
    # Lazy import — go import-irame helper-ot ovde, ne na vrvot na fajlot.
    # Zoshto? — za da izbegneme „circular import" (termini.py isto se vika od drugo mesto).
    from routers.termini import _isprati_email_poraka
    # Uslovno pokazuvame licenca — ako nema, pishuvame „(не е внесена)"
    licenca_red = f"\nЛиценца: {licenca}" if licenca else "\nЛиценца: (не е внесена)"
    subject = "Потврда за апликација – Клиничка Болница Штип" # Naslov na mailot
    # Telo na mailot — se koristat f-stringovi za da se vmetnat vrednostite
    body = (
        f"Почитуван/а {ime} {prezime},\n\n"
        f"Вашата апликација за работа е успешно поднесена.\n\n"
        f"Позиција: {pozicija}{licenca_red}\n\n"
        f"Тимот за човечки ресурси ќе ве контактира за следните чекори.\n\n"
        f"Клиничка Болница Штип\n"
    )
    # Vikame postoechki SMTP helper — toj se grizhi za greshki i logiranje
    _isprati_email_poraka(to_email, subject, body, "Потврда за апликација испратена на")

# Intent detekcija — proveruva dali korisnikot prashuva „dali imam aplicirano?"
# (Ovaa funkcija e javna — se koristi i od intent_detector.py nadvor!)
def prasanje_e_proverka_aplikacija_rabota(prasanje: str) -> bool:
    """Dali korisnikot prashuva „dali imam aplicirano?" (status, ne nov flow)?"""
    p = transliterijaj(prasanje).lower()    # Prvo normaliziraj go tekstot — kirilica + mali bukvi, za polesno prebaruvanje
    if prasanje_e_izbrisi_aplikacija_rabota(prasanje):  # Ako korisnikot saka da brishe → taa funkcija ima prioritet, ovaa NE e proverka
        return False   # izlez — ne sme vo „proverka" scenario

    # Ako korisnikot EKSPLICITNO saka da aplicira → ne e proverka, tuku nov flow
    # (bez ovaa provera, „dali mozam da aplicir..." bi se smetalo kako status-prashanje)
    # Pokrivame poveke varijanti: sakam/može/kako + (aplicir|aplicira|apliciram)
    if any(w in p for w in (
        "сакам да аплицир", "sakam da aplicir",
        "како да аплицир", "kako da aplicir",
        "може да аплицир", "moze da aplicir",         # „mozhe da apliciram/aplicira" (1-vo + 3-to lice)
        "може ли да аплицир", "moze li da aplicir",
        "може да се аплицир", "moze da se aplicir",
        "како се аплицир", "kako se aplicir",
        "како можам да аплицир", "kako mozam da aplicir",
        "дали можам да аплицир", "dali mozam da aplicir",
    )):
        return False                                # ova e nov flow, ne proverka

    # Klasichni frazi za proverka status (ako se pojavi bilo koja → vednash true)
    if any(x in p for x in ( "дали имам аплициран", "dali imam apliciran", "дали имам апликаци", "dali imam aplikaci", "дали имам поднесено", "dali imam podneseno", "имам ли апликаци", "imam li aplikaci", "моја апликаци", "moja aplikaci", "статус на апликаци", "status na aplikaci", )):
        return True                                 # sigurno e „proverka status"
    # Poopshta forma: „dali" + „aplicir/aplikaci" vo ista rechenica
    # No NE e proverka ako e spomnata konkretna pozicija/oddel (toa e nova aplikacija)
    if ("дали" in p or "dali" in p) and any(
        w in p for w in ("аплицир", "aplicir", "апликаци", "aplikaci")):
        # Ako vo prashanjeto ima zbor za pozicija/specijalnost → ova e baranje za nova aplikacija
        spec_hints = (
            "кардиол", "хирург", "урол", "анестез", "гинекол", "педијат",
            "невро", "ортопед", "радиол", "интерн", "сестр", "медицинск",
            "дермато", "офталмо", "лабор", "оториноларинг", "kardiol",
            "hirurg", "urol", "ginekol", "pedijat", "nevrol", "ortoped",
            "radiol", "sestr", "medicinsk",
        )
        if any(h in p for h in spec_hints):
            return False                            # spomnata pozicija → nov flow
        return True
    return False                                    # nitu eden uslov ne odgovara → ne e proverka

def prasanje_e_izbrisi_aplikacija_rabota(prasanje: str) -> bool:
    p = transliterijaj(prasanje).lower()     # Normaliziraj go tekstot za prebaruvanje
    # Prv uslov: mora da ima zbor za „aplikacija/prijava"
    # (za da ne zafatime brishenje na neshto drugo kako „izbrishi termin")
    if not any(w in p for w in (
        "апликаци", "aplikaci", "аплиц", "aplic", "пријав", "prijav")):
        return False                                # nema vrska so aplikacii
    # Vtor uslov: mora da ima komanda za brishenje/otkazhuvanje.
    # \w* znachi „bilo koi bukvi/cifri posle" — pa „izbrishi", „izbrisham" se sovpagaat.
    return bool(re.search(
        r"(избриш\w*|izbris\w*|откаж\w*|otkaz\w*|тргни|"
        r"отстрани|повлеч\w*|delete|cancel)", p))

# Intent detekcija — pomoshna za „sakam rabota" bez konkretna pozicija
def _prasanje_e_opsto_za_rabota(prasanje: str) -> bool:
    if prasanje_e_proverka_aplikacija_rabota(prasanje): # Ako veke e prepoznato kako proverka/brishenje → ne e „opshto"
        return False
    if prasanje_e_izbrisi_aplikacija_rabota(prasanje):
        return False
    p = transliterijaj(prasanje).lower()     # Normaliziraj go tekstot za prebaruvanje

    # Mora da sodrzi barem eden zbor povrzan so vrabotuvanje
    ima_keyword = any(w in p for w in ( "аплиц", "aplic", "пријав", "prijav", "вработ", "vrabot", "работа", "rabota"))
    if not ima_keyword:                             # nema nitu eden raboten termin
        return False
    # Ako spomnal konkretna specijalnost → NE e opshto (drugiot flow ke go obraboti)
    spec_hints = ("кардиол", "хирург", "урол", "анестез", "гинекол", "педијат", "неврол", "ортопед", "радиол", "интерн", "сестр", "медицинск")
    return not any(h in p for h in spec_hints)     # true samo ako NEMA specijalnost

# Funkcija sho gi vraka aktivnite oglasi (za prikaz na korisnikot vo chat)
def _aktivni_oglasi() -> list[dict]:
    conn = None                                     # podgotovka za try/finally
    try:
        conn = get_connection()                    # otvori MySQL vrska
        cur = conn.cursor(dictionary=True)         # cursor sho vraka dict (ne tuple)
        rows = fetch_aktivni_oglasi_rows(cur)      # SELECT od tabelata Vrabotuvanje (aktivni)
        cur.close()                                # zatvori go cursor-ot vednash

        # List comprehension — za sekoj red napravi mal dict so samo potrebnite polinja
        return [{
            "id_oglas": r.get("id_oglas"),                          # ID na oglasot
            "pozicija": (r.get("pozicija") or "").strip(),          # pozicija, bez prazni mesta
            "oddel": (r.get("oddel") or "").strip(),                # oddel, bez prazni mesta
            "rok": format_rok_datum(r.get("datum_na_prijavuvanje")),  # DATE → tekst „dd.mm.yyyy"
        } for r in (as_dict(raw) for raw in rows)]                  # sekoj red → dict
    except Exception as e:                          # ako neshto pukne → logiraj i vrati prazna lista
        print(f"[apliciraj] lista oglasi: {e}")
        return []
    finally:
        if conn:                                    # sekogash zatvori ja konekcijata
            conn.close()

# Funkcija sho bara aktiven oglas po pozicija (+ opcionalno po oddel od prashanjeto)
def _najdi_aktiven_oglas(baran: str, prasanje: str = "") -> dict | None:
    """
    Najdi aktiven oglas po pozicija.
    Ako ima poveke kandidati (pr. „Medicinska sestra" za 2 razlichni oddeli),
    izberi go onoj chii oddel e spomnat vo prashanjeto.
    """
    site = _aktivni_oglasi()                       # zemi gi site aktivni oglasi
    if not site:                                    # nema aktivni — vrati None
        return None
    b = baran.lower().strip()                       # normaliziraj go baranot (mali bukvi, bez prazno)
    p_norm = transliterijaj(prasanje).lower() if prasanje else ""  # za sporedba so oddel

    # Chekor 1: izvadi gi kandidati sho odgovaraat na pozicijata
    # (tochno sovpaganje ILI substring vo dvete naskoki)
    kandidati: list[dict] = []
    for o in site:
        pos = (o.get("pozicija") or "").strip().lower()
        if pos == b or (b and (b in pos or pos in b)):
            kandidati.append(o)

    # Nema nitu eden kandidat → vrati None
    if not kandidati:
        return None
    # Samo eden kandidat → direktno vrati go
    if len(kandidati) == 1:
        return kandidati[0]

    # Pove'kje kandidati → probaj da go izberesh prefered po oddel spomnat vo prashanjeto
    if p_norm:
        najdobar = None
        najdobar_skor = 0
        for o in kandidati:
            odd = transliterijaj(o.get("oddel") or "").lower().strip()
            if not odd:
                continue
            # Skor 1: cel oddel kako substring vo prashanjeto („urologija" vo „...na urologija")
            if odd in p_norm and len(odd) > najdobar_skor:
                najdobar_skor = len(odd)
                najdobar = o
                continue
            # Skor 2: prv zbor od oddel (npr. „Урологија" od „Урологија и нефрологија")
            prv_zbor = odd.split()[0] if odd.split() else ""
            if len(prv_zbor) >= 4 and prv_zbor in p_norm and len(prv_zbor) > najdobar_skor:
                najdobar_skor = len(prv_zbor)
                najdobar = o
        if najdobar:
            return najdobar

    # Nema match po oddel — vrati prv kandidat (default)
    return kandidati[0]

# Pomoshna funkcija — formatira pozicija + oddel za prikaz vo chat
def _format_pozicija_oglas(oglas: dict) -> str:
    poz = (oglas.get("pozicija") or "").strip() or "—"   # pozicija (ili crtichka ako nema)
    odd = (oglas.get("oddel") or "").strip()             # oddel
    if odd and odd.lower() not in poz.lower():  # Ako imame oddel i ne e veke vo imeto na pozicijata → dodaj vo zagrada
        return f'„{poz}" ({odd})'                  # pr. „Кардиолог" (Кардиологија)
    return f'„{poz}"'                              # inaku samo pozicijata

# AI funkcija sho izvlekuva pozicija od prashanjeto na korisnikot (preku Groq)
def _izvlechi_pozicija(prasanje: str) -> str | None:
    odgovor = ask_ai(f"Прашање: „{prasanje}\"", system_prompt=PROMPT_POZICIJA) # Prakame prompt na LLM-ot + negovoto sistemsko upatstvo (PROMPT_POZICIJA)
    data = parse_ai_json(odgovor, log_tag="apliciraj_pozicija")  # Parsiraj go JSON-ot — funkcijata vraka dict so „_error": True ako pukne
    if data.get("_error"):                          # LLM-ot ne vratil validen JSON
        return None
    val = data.get("pozicija")   # Izvleci go poleto „pozicija" i trgni prazni mesta (ako postoi)
    return str(val).strip() if val else None       # ako e prazno/None → vrati None

# AI funkcija sho izvlekuva broj na medicinska licenca (i preskok flag)
def _izvlechi_licenca(prasanje: str) -> tuple[str | None, bool]:
    from ai._kernel.groq_client import groq_e_isklucen # Lazy import za da izbegneme cirkularen import
    if groq_e_isklucen():   # Ako Groq ne e dostapen (nema tokeni, mrezhen problem) → ne mozheme izvlece
        return None, False                          # nishto ne mozheme da zaklucime
    
    # Prati go korisnichkiot odgovor + sistemski prompt za licenca
    odgovor = ask_ai(f"Одговор: „{prasanje}\"", system_prompt=PROMPT_LICENCA)
    data = parse_ai_json(odgovor, log_tag="apliciraj_licenca") # Parsiraj go JSON-ot
    if data.get("_error"):                          # nevazechki JSON
        return None, False
    # Izvleci gi dvete polinja od dict-ot
    licenca = data.get("licenca")                  # mozhe da e string so broj ili None
    preskoki = bool(data.get("preskoki"))          # true ako korisnikot rekol „nemam"
    if licenca:          # Zemi samo cifri od licencata (LLM-ot ponekogash vraka „12345-A" ili so punktuacija)
        licenca = re.sub(r"\D", "", str(licenca)) or None   # \D = bilo shto NE e cifra
    return licenca, preskoki                       # vrakame par (tuple)

# Pomoshna funkcija — parsira „da"/„ne" od kratok odgovor
def _parse_da_ne(prasanje: str) -> str | None:
    p = transliterijaj(prasanje).lower().strip() # Prvo normaliziraj go tekstot (mali bukvi, kirilica, bez prazni mesta)
    p = re.sub(r"[^\w\sа-яѓќѕџ]+", " ", p, flags=re.IGNORECASE) # Trgni gi interpunkciite (zapirki, tochki, itn.) — da ostane samo tekst
    p = re.sub(r"\s+", " ", p).strip()  # Site povtoreni prazni mesta → eden edinstven (za urednost)
    ne_frazi = ("не сакам", "ne sakam", "не би", "не сак", "откажи", "odkazi", "не ме интересира") # „Ne" varijanti — ako se sovpaga bilo koe → korisnikot rekol NE
    if p in ("не", "ne", "no") or any(x in p for x in ne_frazi):
        return "ne"
    
    if p in ("да", "da", "yes", "ja", "сакам", "аплицирај", "аплицирам", "во ред", "ok", "okej", "okay", "се разбира"):  # „Da" varijanti — eднoznachni odgovori
        return "da"

    # Poopsht sluchaj: „da" kako posebеn zbor vo rechenica (no bez „ne" voopshto)
    if re.search(r"\bда\b", p) and "не" not in p:
        return "da"
    return None  # ne sme sigurni → nishto

# Funkcija sho vraka odgovor koj bara od korisnikot da se najavi kako pacient
def _odgovor_bara_pacient_login(kontekst: dict | None, prikaz: str) -> dict:
    # `kontekst` se pamti na frontend-ot — po uspeshen login se vraka so „ceka=login"
    return {
        "odgovor": (
            f"Го препознав огласот за работа: {prikaz}.\n\n"
            "За да ја испратам апликацијата преку AI, прво треба да се "
            "најавиш како пациент (не како лекар). Ти ја отворам формата за најава — "
            'по најавата напиши „да" или „сакам да аплицирам".'),
        "akcija": "otvori_pacient_login",          # znak za frontend-ot: otvori ja formata
        "navigacija": NAV_KARIERA,                  # navigacija kon sekcijata „Kariera"
        "kontekst": kontekst,                       # zachuvan oglas za posle login (ili None)
    }


# Funkcija sho odgovara koga nema imenuvana pozicija — prikazuva lista oglasi
def _odgovor_izberi_pozicija(_pacient: dict) -> dict:
    oglasi = _aktivni_oglasi() # zemi gi site aktivni oglasi
    # Ako bazata nema aktivni oglasi → informiraj go korisnikot
    if not oglasi:
        return {
            "odgovor": ("Моментално нема отворени работни позиции за пријавување.\n\n"
                        'Страницата ќе се отвори на делот "Кариера" — '
                        "проверете повторно подоцна."),
            "kontekst": None, "navigacija": NAV_KARIERA}

    if len(oglasi) == 1:        # Ako ima SAMO eden oglas → direktno vlezi vo flow za potvrda (nema smisla da prashuvame)
        return _pocni_potvrda_flow(oglasi[0])
    linii = ["Моментално има следниве отворени позиции:", ""]    # Ima poveke oglasi → prikazi gi kako lista so buleti
    for o in oglasi:                                # za sekoj oglas dodaj edna linija so bulet
        linii.append(f"• {o['pozicija']} — оддел: {o.get('oddel') or '—'}. "
                     f"Рок: {o.get('rok') or '—'}.")
    linii.extend(["", "Напишете која позиција ве интересира, на пример:",'„Сакам да аплицирам за Уролог" или „Аплицирај ме за кардиолог".',]) # Finalni instrukcii za korisnikot
    # \n go spojuva listata vo eden tekst (so novi redovi megju niv)
    return {"odgovor": "\n".join(linii), "kontekst": None, "navigacija": NAV_KARIERA}

# Funkcija sho zapochnuva flow za potvrda (chekor 1)
def _pocni_potvrda_flow(oglas: dict) -> dict:
    prikaz = _format_pozicija_oglas(oglas)         # „Кардиолог (Кардиологија)"
    # Uslovno pokazi rok — samo ako oglasot ima datum na prijavuvanje
    rok_linija = f"\nРок за пријава: {oglas['rok']}." if oglas.get("rok") else ""
    return {
        "odgovor": (f"Во моментов има отворена позиција за {prikaz}.{rok_linija}\n\n" "Дали сакате да аплицирате?\n" 'Одговорете со „да" или „не".'),
        # Kontekstot se pamti na frontend-ot — slednata poraka ke go vrati nazad tuka
        # za da znaeme deka sme vo „chekor za potvrda" za toj konkreten oglas.
        "kontekst": {
            "intent": "apliciraj_za_rabota",       # za koj handler e namenetо
            "ceka": "potvrda",                      # tekoven chekor vo flow-ot
            "pozicija": oglas["pozicija"],         # pozicija (za nova poraka da znaeme za koja sme)
            "id_oglas": oglas["id_oglas"],         # foreign key — za INSERT vo baza
            "oddel": oglas.get("oddel") or "",     # oddel (za prikaz vo potvrdata)
            "rok": oglas.get("rok") or "",         # rok (za prikaz)
        },
        "navigacija": NAV_KARIERA,
    }

# Funkcija sho zapochnuva flow za licenca (chekor 2)
def _pocni_licenca_flow(oglas: dict, pacient: dict) -> dict:
    return {
        "odgovor": (
            f"Одлично! Продолжуваме со апликацијата за {_format_pozicija_oglas(oglas)}.\n\n" # Pokazi mu gi na korisnikot podatocite sho ke gi koristime od profilot
            f'Ќе ги користам твоите податоци: {pacient.get("ime","")} '
            f'{pacient.get("prezime","")}, {pacient.get("email","")}.\n\n' "Те молам испрати го бројот на твојата медицинска лиценца " '(само цифри), или напиши „немам" за да продолжиме без лиценца.'),
        "kontekst": {
            "intent": "apliciraj_za_rabota",
            "ceka": "licenca",                      # slednata poraka ke vlezi vo licenca-blokot
            "pozicija": oglas["pozicija"],         # za da ja pamtime vo narednite chekori
            "id_oglas": oglas["id_oglas"],
            # applicant_email e email-ot za koj sme vo flow — se chuva za brishenje posle uspeh
            "applicant_email": (pacient.get("email") or "").strip(),
        },
        "navigacija": NAV_KARIERA,
    }

# Funkcija sho vraka odgovor koga korisnikot rekol „ne" na potvrda
def _odgovor_odbien_aplikacija() -> dict:
    return {
        "odgovor": ("Ви благодариме.\n\n"
                    'Следете ги огласите во делот „Кариера" на сајтот. '
                    "Слободно пишете повторно ако се предомислите."),
        "kontekst": None,                          # resetiraj go kontekstot (nema aktiven flow)
        "navigacija": NAV_KARIERA,
    }

# Pomoshna funkcija — od zachuvan kontekst rekonstruira „oglas" dict
def _oglas_od_kontekst(kontekst: dict) -> dict:
    # Korisно vo sluchaj koga frontend-ot ni go vraka kontekstot posle login — go rekonstruirame oglasot
    return {
        "id_oglas": kontekst.get("id_oglas"),       # ID na oglasot za SQL
        "pozicija": kontekst.get("pozicija") or "", # pozicija (za prikaz)
        "oddel": kontekst.get("oddel") or "",       # oddel (za prikaz)
        "rok": kontekst.get("rok") or "",           # rok (za prikaz)
    }

# DB funkcija — SELECT na site aplikacii za daden email (strogo sovpaganje)
def _zemi_aplikacii_po_email(email: str) -> list[dict]:
    """SELECT od prijaveni_lekari po email — strogo sovpaganje."""
    if not email:                                   # bez email ne mozeme da barame
        return []
    conn = None                                     # za try/finally — da mozeme sekogash da zatvorime
    try:
        conn = get_connection()                    # otvori MySQL vrska
        cur = conn.cursor(dictionary=True)         # cursor sho vraka dict namesto tuple
        # SQL: SELECT od prijaveni_lekari WHERE email = ? ORDER BY datum DESC
        # LOWER+TRIM na dvete strani — za da ne pukne ako korisnikot pishal so glavni bukvi/prazni mesta
        cur.execute(
            prijaveni_select_sql()                  # standarden SELECT
            + " WHERE LOWER(TRIM(email)) = LOWER(TRIM(%s))"
            + prijaveni_order_desc(),               # ORDER BY datum DESC
            (email.strip(),))                       # parametri (tuple so eden element)
        # Site redovi kako dict-ovi
        rows = [as_dict(r) for r in cur.fetchall()]
        cur.close()                                 # zatvori go cursor-ot
        # Osiguraj deka sekoj red ima „id" kluch (nekoi tabeli imaat drugo ime na PK)
        for r in rows:
            if r.get("id") is None:                # ako kluchot „id" fali
                try:
                    r["id"] = prijaveni_row_id(r)  # izvadi ID bez vaznost kako se vika kolonata
                except ValueError:
                    pass                            # ako ne uspee → ostavi go bez id
        return rows
    except Exception as e:                          # fati bilo kakva DB greshka
        print(f"[apliciraj] zemi po email: {e!r}")  # log za debagiranje
        return []                                   # na greshka → prazna lista (nikogash ne pukaj)
    finally:
        if conn:                                    # ako imashe otvorena vrska
            conn.close()                            # sekogash zatvori ja

# Funkcija sho odgovara na „dali imam aplicirano?"
def _odgovor_proverka_aplikacija(pacient: dict | None, kontekst: dict | None) -> dict:
    # Email e prv od sesijata (ako e najaven), pa od kontekst (ako veke aplicira)
    email = (pacient or {}).get("email") or (kontekst or {}).get("applicant_email")
    email = (email or "").strip() # normaliziraj (bez prazni mesta)
    # Bez email — ne mozeme da barame, barame login
    if not email:
        return {
            "odgovor": ("За да проверам дали имате поднесена апликација, најавете "
                        "се како пациент со истата сметка со која сте аплицирале.\n\n"
                        "Потоа повторете: „Дали имам аплицирано за работа\"."),
            "akcija": "otvori_pacient_login",      # frontend ja otvori formata
            "navigacija": NAV_KARIERA, "kontekst": None,
        }
    apps = _zemi_aplikacii_po_email(email)  # Baraj aplikacii po email
    # Nema pronajdeni aplikacii — uchtivo kazhi „ne"
    if not apps:
        return {
            "odgovor": (f"Не — немам пронајдена апликација за работа во системот "
                        f"({email}).\n\n"
                        'Ако сте аплицирале преку формата во „Кариера", проверете дали '
                        "сте внеле истата е-пошта како при најавата."),
            "kontekst": None, "navigacija": NAV_KARIERA,
        }
    # Ima pronajdeni — naslov se menuva dali se edna ili poveke
    if len(apps) == 1:
        naslov = "Да — имате поднесена апликација за работа:\n"
    else:
        naslov = f"Да — имате {len(apps)} поднесени апликации за работа ({email}):\n"
    linii = [naslov]    # Sega pravime lista na buleti — eden za sekoja aplikacija
    for a in apps:                                  # pomine niz site aplikacii
        poz = (a.get("pozicija") or "—").strip() or "—"   # pozicija (ili crtichka)
        app_id = a.get("id")                       # ID na red (za prikaz)
        linii.append(f"• {poz} — пријавено на "
                     f"{format_datum_vreme(a.get('datum_prijava'))}"
                     # Prikazhi go ID-to samo ako postoi (za da korisnikot znae shto da brishe)
                     + (f" (ID: {app_id})" if app_id is not None else ""))

    # Finalni instrukcii na korisnikot
    linii.extend(["", "Тимот за човечки ресурси ќе ве контактира за следните чекори.", "", 'За откажување: „Избриши ја апликацијата".'])
    # Zachuvaj go email-ot + ID-to na najnovata aplikacija vo kontekst
    # (za poleсno brishenje ako korisnikot vednash kazhe „izbrishi")
    return {
        "odgovor": "\n".join(linii),               # site linii vo eden tekst
        "kontekst": {
            "applicant_email": email,
            "last_aplikacija_id": apps[0].get("id"),     # najnova prva (DESC)
            "last_aplikacija_pozicija": (apps[0].get("pozicija") or "").strip(),
        },
        "navigacija": NAV_KARIERA,
    }

# Pomoshna funkcija — izvlekuva broj na aplikacija od tekstot („аплик. 17" → 17)
def _izvlechi_app_id_od_prasanje(prasanje: str) -> int | None:
    p = transliterijaj(prasanje).lower()           # normaliziraj za regex
    # Prv shablon: „aplikacija 17", „aplikacijata ID 17" (faka ID posle „aplikacija")
    # Vtor shablon: „id 17" — fallback za bilo koj kontekst.
    for pat in (r"апликаци[јj][аи]?\s*(?:id)?\s*#?:?\s*(\d+)", r"\bid\s*(\d+)\b"):
        m = re.search(pat, p)
        if m:                                       # ako shablonot najde neshto
            return int(m.group(1))                 # m.group(1) = prvata grupa (brojot)
    return None                                    # ne nashovme broj

# Pomoshna funkcija — proveruva dali tekovniot lekar e direktor (admin)
def _direktor_e_admin(lekar: dict | None) -> bool:
    if not lekar or not lekar.get("doctor_ID"):    # bez lekar/bez ID → ne e admin
        return False
    try:
        # Lazy import — da ne zavisi fajlot od routers/admin.py pri load time
        from routers.admin import check_admin_access
        return bool(check_admin_access(int(lekar["doctor_ID"])))
    except Exception:                              # ako pukne neshto → trgnuvame od false (pobezbedno)
        return False


# DB funkcija — DELETE od `prijaveni_lekari` (po email ili ID)
def _izbrisi_aplikacija(email: str | None, app_id: int | None) -> tuple[bool, str]:
    # Bez nitu eden kriterium → nema shto da brisheme
    if not email and not app_id:
        return False, "Немам пронајдена апликација за бришење."
    conn = None                                     # za try/finally
    try:
        conn = get_connection()                    # otvori MySQL vrska
        cur = conn.cursor(dictionary=True)         # cursor sho vraka dict
        pk = prijaveni_pk_column()                 # ime na primary key (pr. „id_prijava")
        # 1) Najdi go redot — dve scenarija:
        if app_id is not None:                     # 1a) tochno po ID (za direktor)
            cur.execute(prijaveni_select_sql() + f" WHERE {pk} = %s LIMIT 1",
                        (app_id,))
        else:                                       # 1b) najnova za toj email (za pacient)
            cur.execute(prijaveni_select_sql()
                        + " WHERE LOWER(TRIM(email)) = LOWER(TRIM(%s))"
                        + prijaveni_order_desc() + " LIMIT 1",
                        (email.strip(),))
        row = fetch_one(cur)                       # zemi go prvot red (ili None)
        # 2) Ako ne sme nashle — uchtivo vrati greshka
        if not row:
            cur.close()
            ref = f" ({email})" if email else ""    # pokazi email vo porakata ako imame
            return False, f"Немам пронајдена апликација за бришење{ref}."
        # 3) Imame red → DELETE
        app_id_del = prijaveni_row_id(as_dict(row))   # izvadi ID bez vaznost za ime na kolonata
        poz = (row.get("pozicija") or "").strip() or "—"  # pozicija za porakata (ili crtichka)
        cur.execute(f"DELETE FROM prijaveni_lekari WHERE {pk} = %s", (app_id_del,))
        conn.commit()                              # potvrdi ja transakcijata (bez ova ne se zapisuva!)
        cur.close()
        # Vrakaj uspeshna poraka so detali (korisnikot treba da vidi shto e izbrisano)
        return True, ("Апликацијата е избришана.\n\n"
                      f"Позиција: {poz}\nID: {app_id_del}\n\n"
                      'Можете повторно да аплицирате преку „Кариера".')
    except Exception as e:                          # ako SQL pukne
        print(f"[apliciraj] DELETE: {e!r}")        # log za debagiranje
        return False, ("Се случи грешка при бришењето на апликацијата. " "Обидете се повторно.")
    finally:
        if conn:                                    # sekogash zatvori ja vrskata
            conn.close()

# Funkcija sho odgovara na barannje za brishenje na aplikacija
def _odgovor_izbrisi_aplikacija(pacient: dict | None, kontekst: dict | None, prasanje: str = "", lekar: dict | None = None) -> dict:
    app_id = _izvlechi_app_id_od_prasanje(prasanje)     # Probaj da izvlechesh ID od prashanjeto („izbrishi aplikacija 17")
    email = (pacient or {}).get("email") or (kontekst or {}).get("applicant_email") # Email e prv od sesijata (pacient), pa od kontekst (ako veke aplicira vo istiot razgovor)
    email = (email or "").strip() or None          # normaliziraj (ili None ako e prazno)

    # Scenario 1: Direktor + konkreten app_id → brishi go tochno toa
    if app_id and _direktor_e_admin(lekar):
        ok, poraka = _izbrisi_aplikacija(None, app_id)
    # Scenario 2: Najaven pacient → gi brishe svoite po email (poslednata)
    elif email:
        ok, poraka = _izbrisi_aplikacija(email, None)
    # Scenario 3: Nema nishto korisно → bara login
    else:
        return {
            "odgovor": ("За бришење на апликација треба да сте најавени како пациент "
                        "со истата сметка со која сте аплицирале.\n\n"
                        "Најавете се и пишете: „Избриши ја апликацијата\"."),
            "kontekst": None, "navigacija": NAV_KARIERA}

    # Vrakame poraka od _izbrisi_aplikacija + resetiran kontekst
    return {"odgovor": poraka, "kontekst": None, "navigacija": NAV_KARIERA}


# DB funkcija — INSERT vo `prijaveni_lekari` (zapishi nova aplikacija)
def _zapisi_aplikacija( id_oglas: int | None, pozicija: str, ime: str, prezime: str, email: str, telefon: str | None, licenca: str | None,) -> tuple[bool, int | None]:                     
    """INSERT vo `prijaveni_lekari` + vrati go generiranio ID (za kontekst)."""
    conn = None                                     # za try/finally
    try:
        conn = get_connection()                    # otvori MySQL vrska
        cur = conn.cursor(dictionary=True)         # cursor sho vraka dict
        denes = datetime.now().strftime("%Y-%m-%d %H:%M:%S") # Time-stamp na prijavata (datum + vreme)
        # Telefon/licenca vo bazata se INT (ne varchar) — zatoa samo cifrite → int.
        # Ako nema nishto korisно → None (NULL vo bazata).
        # re.sub(r"\D", "", X) → trgni se shto ne e cifra.
        tel_int = int(re.sub(r"\D", "", str(telefon))) if telefon and re.sub(
            r"\D", "", str(telefon)) else None
        lic_int = int(re.sub(r"\D", "", str(licenca))) if licenca and re.sub(
            r"\D", "", str(licenca)) else None
        #izvrasuvanje na sql komandata 
        cur.execute("""             
            INSERT INTO prijaveni_lekari
              (id_oglas, pozicija, ime_lekar, prezime_lekar,
               broj_med_licenca, email, telefon, datum_prijava)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (id_oglas, pozicija, ime, prezime, lic_int, (email or "").strip().lower(), tel_int, denes))
        new_id = cur.lastrowid                     # ID na novioт red (AUTO_INCREMENT)
        conn.commit()                              # potvrdi ja transakcijata (bez ova ne se zapisuva!)
        cur.close()                                # zatvori go cursor-ot
        return True, new_id                        # uspeh + ID na novata aplikacija
    except Exception as e:                          # ako SQL pukne
        print(f"[apliciraj] INSERT: {e}")          # log za debagiranje
        return False, None
    finally:
        if conn:                                    # sekogash zatvori ja vrskata
            conn.close()


# Glaven handler — ova e tochkata sho se vika od handlers.py (intent: apliciraj_za_rabota)
def odgovori_za_aplikacija( prasanje: str, pacient: dict | None, kontekst: dict | None, lekar: dict | None = None,) -> dict:
    ceka = (kontekst or {}).get("ceka")  # `ceka` ni kazuva vo koj chekor sme (od prethodna poraka). None = nov razgovor.
    # Brishenje + proverka imaat prioritet
    # (mozhe da se pojavat i vo sredina na flow — korisnikot mozhe da se predomisli)
    if prasanje_e_izbrisi_aplikacija_rabota(prasanje):
        return _odgovor_izbrisi_aplikacija(pacient, kontekst, prasanje, lekar)
    if prasanje_e_proverka_aplikacija_rabota(prasanje):
        return _odgovor_proverka_aplikacija(pacient, kontekst)
    
    # Po najava: prodolzhi od zachuvaniот oglas
    # Ova go faka sluchajot: korisnikot rekol „sakam kardiolog", se najavil, i sega
    # mu ja prikazuvame vednash potvrdata bez da go prashuvame povtorno za pozicijata.
    if ceka == "login" and pacient and pacient.get("email"):
        oglas = _oglas_od_kontekst(kontekst or {})
        if oglas.get("id_oglas") and oglas.get("pozicija"):
            return _pocni_potvrda_flow(oglas)
    
    if not pacient or not pacient.get("email"): # Ne sme logirani → bara login (so zachuvan kontekst za posle)
        # Ako nema aktiven flow + vo tekstot spomeknal „aplicira..." →
        # probaj da izvlechesh pozicija i da zachuvash kontekst pred da go pratish na login
        if not ceka and "аплиц" in transliterijaj(prasanje).lower():
            baran = _izvlechi_pozicija(prasanje)   # AI: izvleci pozicija
            if baran:                              # AI nashol pozicija
                # KLUCNO: prakame i prasanjeto za da se zeme predvid oddelot
                oglas = _najdi_aktiven_oglas(baran, prasanje)
                if oglas:
                    # Ima aktiven oglas — zachuvaj go vo kontekst, baraj login
                    return _odgovor_bara_pacient_login({
                        "intent": "apliciraj_za_rabota", "ceka": "login",
                        "pozicija": oglas["pozicija"], "id_oglas": oglas["id_oglas"],
                        "oddel": oglas.get("oddel") or "", "rok": oglas.get("rok") or "",
                    }, _format_pozicija_oglas(oglas))
                # Nema aktiven oglas za toa ime → informiraj, no sepak prati na login
                return _odgovor_bara_pacient_login(
                    None,
                    f'„{baran}" (во моментов нема активен оглас — провери Кариера)')
        # Opsht sluchaj: samo barame login (bez zachuvan oglas)
        return _odgovor_bara_pacient_login(None, "аплицирање за работа")

    # Od ovde natamu garantirano imame najaven pacient so email
    pozicija = (kontekst or {}).get("pozicija")    # zachuvana pozicija (ili None)
    id_oglas = (kontekst or {}).get("id_oglas")    # ID na oglasot za INSERT

    # Chekor 1: nov flow → izvleci pozicija
    if not ceka:                                    # bez aktiven flow → pocni nov
        # Korisnikot pishal „sakam rabota" bez specijalnost → prikazi lista
        if _prasanje_e_opsto_za_rabota(prasanje):
            return _odgovor_izberi_pozicija(pacient)

        # Probaj da izvlechesh konkretna pozicija preku AI
        baran = _izvlechi_pozicija(prasanje)
        if not baran:                              # AI ne nashol → prikazhi lista
            return _odgovor_izberi_pozicija(pacient)

        # Imame barana pozicija → dali postoi aktiven oglas?
        # KLUCNO: prakame i prasanjeto za da se izbere TOCNIOT oglas po oddel
        # (npr. „Медицинска сестра на Урологија" → Urologija, ne Akusherstvo)
        oglas = _najdi_aktiven_oglas(baran, prasanje)
        if not oglas:
            # Nema aktiven oglas za taa pozicija → informiraj
            return {"odgovor": (f'Во моментот нема активен оглас за „{baran}". ' "Подолу се сите отворени позиции — изберете друга или " 'проверете на делот „Кариера".'), "kontekst": None, "navigacija": NAV_KARIERA}
        return _pocni_potvrda_flow(oglas)          # se e dobro → vlezi vo potvrda
    # Chekor 2: potvrda (da / ne)
    if ceka == "potvrda":
        odluka = _parse_da_ne(prasanje)            # 'da', 'ne' ili None
        if odluka is None:
            # Korisnikot nitu rekol da, nitu ne → povtorno prashaj (zachuvaj kontekst!)
            prikaz = _format_pozicija_oglas(_oglas_od_kontekst(kontekst or {}))
            return {"odgovor": (f"Не разбрав. За позицијата {prikaz} — "
                                'одговорете со „да" или „не".'),
                    "kontekst": kontekst}           # kluchno: zachuvaj go kontekstot
        if odluka == "ne":
            return _odgovor_odbien_aplikacija()    # blagodarnost + resetiranje
        # Korisnikot rekol „da" → prodolzhi kon licenca
        return _pocni_licenca_flow(_oglas_od_kontekst(kontekst or {}), pacient)
    # Chekor 3: licenca → INSERT + email
    if ceka == "licenca":
        licenca, preskoki = _izvlechi_licenca(prasanje)   # AI parsiranje
        # Nitu broj nitu „nemam" → pobarah povtorno (no zachuvaj kontekst)
        if licenca is None and not preskoki:
            return {"odgovor": ('Не препознав важечки број на лиценца. Те молам '
                                'прати само цифри (пр. „12345") или напиши „немам".'),
                    "kontekst": kontekst}
        # Zemi gi podatocite od profilot na pacientot (ne prashuvame povtorno)
        ime = pacient.get("ime", "") or ""
        prezime = pacient.get("prezime", "") or ""
        app_email = (pacient.get("email") or "").strip()
        # Izvrshi INSERT vo baza
        ok, new_id = _zapisi_aplikacija(
            id_oglas=id_oglas, pozicija=pozicija or "",
            ime=ime, prezime=prezime, email=app_email,
            telefon=pacient.get("telefon"), licenca=licenca)
        # Ako INSERT ne uspeal → uchtivа greshka
        if not ok:
            return {"odgovor": ('Се случи грешка при зачувувањето на апликацијата. ' 'Обиди се повторно или контактирај ja рецепцијата.'), "kontekst": None} # Se uspeshno → isprati email potvrda (bez blokiranje na odgovorot)
        _isprati_email_za_aplikacija(app_email, ime, prezime, pozicija or "—", licenca)
        lic_info = f"Лиценца: {licenca}" if licenca else "Лиценца: (без)" # Finalna poraka do korisnikot + zachuvaj kontekst za mozhno brishenje
        return {
            "odgovor": ('Готово! Апликацијата е успешно испратена.\n\n'
                        f'Позиција: {pozicija}\n'
                        f'Кандидат: {ime} {prezime}\n'
                        f'Email: {app_email}\n{lic_info}\n\n'
                        'Потврда е испратена на твојата e-пошта.\n'
                        'Тимот за човечки ресурси ќе те контактира. Среќно!\n\n'
                        'За откажување: „Избриши ја апликацијата".'),
            "kontekst": {
                "applicant_email": app_email,
                "last_aplikacija_id": new_id,      # za brzo brishenje
                "last_aplikacija_pozicija": pozicija,
            },
        }

    # Nepoznat ceka → resetiraj flow (safety net)
    # Dokolku kontekstot e rasipan ili dojde neochekuvana sostojba, barame korisnikot da pochne od pochetok
    return {"odgovor": 'Те молам обиди се повторно: „Сакам да аплицирам за [позиција]".',
            "kontekst": None}
