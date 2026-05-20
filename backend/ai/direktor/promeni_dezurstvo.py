"""
Дежурства на лекар — само за директорот.

- „Додади ја д-р X дежурна на 21 мај 20:00-04:00" → INSERT (ново дежурство)
- „Премести / префрли дежурство на X за петок" → UPDATE (најрано идно или совпаѓачко)
"""
import re
from datetime import date, datetime
from database import get_connection
from ai._kernel.auth import require_direktor
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import ask_ai
from ai._kernel.transliteracija import transliterijaj
from ai._kernel.utils import format_datum, format_vreme
from ai.direktor.dezurstvo_kontekst import izgradi_kontekst, lekar_od_kontekst
# sistemski prompt koj mu se prakja na ai modelot
# ovde detalno se objasnuva sto treba ai da vrati
PROMPT = """Ти си систем што извлекува податоци за дежурство на лекар.Корисникот (директор) сака да ДОДАДЕ ново дежурство или да го ПРОМЕНИ постоечкото.
Врати САМО JSON:
{
  "akcija": "dodadi" | "promeni",
  "lekar": "Име Презиме" | null,
  "datum": "YYYY-MM-DD" | null,
  "vreme_od": "HH:MM" | null,
  "vreme_do": "HH:MM" | null,
  "oddel": "име на оддел" | null
}
Правила за akcija:
- „додади", „внеси", „закажи дежурство", „нека биде дежурна" → dodadi
- „премести", „префрли", „промени" → promeni
Датум: „21 мај", „21.05.2026", „утре", „петок" → YYYY-MM-DD (годината од „Денес" ако нема година).
Време: „20:00 до 04:00", „од 20:00 до 04:00" → vreme_od, vreme_do (ноќно може vreme_do < vreme_od).
Лекар: без титула (д-р, др). „Марија Хубрева" → lekar.
oddel: само ако е експлицитно (напр. „на Урологија"); инаку null.
БЕЗ markdown. Само JSON.""".strip()
# strip() se koristi za da se trgnat prazni mesta i novi redovi
# od pocetokot i krajot na stringot
# recnik za pretvaranje ime na mesec -> broj na mesec
# podrzuva i latinica i kirilica
# recnikot raboti kako key-value struktura — primer: _MESECI["maj"] -> 5
_MESECI = {
    "јануари": 1, "февруари": 2, "март": 3, "април": 4, "мај": 5, "јуни": 6,
    "јули": 7, "август": 8, "септември": 9, "октомври": 10, "ноември": 11, "декември": 12,
    "januari": 1, "fevruari": 2, "mart": 3, "april": 4, "maj": 5, "juni": 6,
    "juli": 7, "avgust": 8, "septemvri": 9, "oktomvri": 10, "noemvri": 11, "dekemvri": 12,
}


def _izvlechi_ai(prasanje: str, denes: date) -> dict:
    # funkcija koja go prakja prasanjeto do ai modelot
    # i ocekuva strukturiran json odgovor
    denes_den = [
        "понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"
    ][denes.weekday()]
    # denes.weekday() vraka broj 0-6 (0=ponedelnik, 6=nedela)
    # so toa go zemame imeto na denot od listata
    full = (
        f"Денес: {denes.isoformat()} ({denes_den})\n\n"
        f'Прашање: „{prasanje}"\nВрати JSON.'
    )
    # se kreira finalen prompt za ai — denes + prasanje od direktorot
    odgovor = ask_ai(full, system_prompt=PROMPT)
    # se povikuva ai — system_prompt e pravilata, full e konkretnoto prasanje
    print(f"[promeni_dezurstvo] AI: {odgovor!r}")
    # debug pecatenje vo terminal — !r e raw string
    return parse_ai_json(odgovor, log_tag="promeni_dezurstvo")
    # odgovorot se pretvara vo dict; nevaliden json -> greska


def _datum_od_tekst(prasanje: str, denes: date) -> date | None:
    # rezervna funkcija dokolku ai ne uspeal da izvlece datum
    p = transliterijaj(prasanje).lower()
    # tekstot se normalizira — lower() za polesno sporeduvanje
    m = re.search(
        r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})",
        prasanje,
    )
    # regex za datum: 21.05.2026, 21-05-2026, 21/05/2026
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            # group(1)=den, group(2)=mesec, group(3)=godina
        except ValueError:
            pass
            # nevaliden datum — programata ne pada
    m = re.search(
        r"(\d{1,2})\s+(" + "|".join(_MESECI.keys()) + r")(?:\s+(\d{4}))?",
        p,
        re.IGNORECASE,
    )
    # regex za „21 мај" ili „21 maj 2026"
    if m:
        mes = _MESECI.get(m.group(2).lower())
        if mes:
            god = int(m.group(3)) if m.group(3) else denes.year
            try:
                return date(god, mes, int(m.group(1)))
            except ValueError:
                pass
    return None
    # ako ne se najde datum — None


def _vreme_od_tekst(prasanje: str) -> tuple[str | None, str | None]:
    # funkcija za izvlekuvanje pocetno i krajno vreme od tekst
    m = re.search(
        r"(?:од\s+)?(\d{1,2})[:.](\d{2})\s*(?:до|-|–)\s*(\d{1,2})[:.](\d{2})",
        prasanje,
        re.IGNORECASE,
    )
    # regex: 20:00 до 04:00 — ?: grupa koja ne se zacuvuva
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}", f"{int(m.group(3)):02d}:{m.group(4)}"
        # :02d dodava nula napred (4 -> 04)
    m2 = re.search( r"периодот\s+од\s+(\d{1,2})[:.](\d{2})\s+до\s+(\d{1,2})[:.](\d{2})",
        transliterijaj(prasanje).lower(),
    )
    # alternativen obrazec: „периодот од 20:00 до 04:00"
    if m2:
        return f"{int(m2.group(1)):02d}:{m2.group(2)}", f"{int(m2.group(3)):02d}:{m2.group(4)}"
    return None, None

def _vreme_samo_do(prasanje: str) -> str | None: # funkcija za vadenje samo na krajno vreme od tekst
    """«да е до 03:00», «до 03».""" # dokumentacija za tipot na vlez sto go ocekuvame
    # samo krajno vreme — na pr. „промени да е до 03:00"
    p = transliterijaj(prasanje).lower() # gi pretvorame site karakteri vo mali bukvi za polesna proverka
    m = re.search( # barame po soodveten obrazec vo tekstot
        r"(?:да\s+е\s+)?(?:до|do)\s+(\d{1,2})[:.]?(\d{2})?\b", # regex koj prepoznavase "do" sledeno od brojki
        p, # tekstot koj go prebaruvame
    )
    if m: # ako e najden soodveten obrazec
        mm = m.group(2) if m.group(2) is not None else "00" # ako nema minuti, gi postavuvame na 00
        return f"{int(m.group(1)):02d}:{mm}" # vrakame formatirano vreme kako "hh:mm"
    m2 = re.search(r"\b(\d{1,2})[:.](\d{2})\s*час", p) # alternativen regex za format "03:00 cas"
    if m2 and any(w in p for w in ("до", "do", "крај", "заврши")): # proveruvame dali ima klucni zborovi za kraj
        return f"{int(m2.group(1)):02d}:{m2.group(2)}" # vrakame formatirano vreme od vtorata grupa
    return None # ako ne e najdeno nikakvo vreme, vrakame prazna vrednost

def _baranje_ista_data(prasanje: str) -> bool: # funkcija koja proveruva dali se raboti za istiot datum
    # dali direktorot misli na istiot datum kako vo pretodniot pregled
    p = transliterijaj(prasanje).lower() # gi pretvorame bukvite vo mali i vrsime transliteracija
    return any( # vrakjame true dokolku barem eden uslov e tocen
        x in p # proveruvame dali frazata 'x' se sodrzi vo vlezniot tekst 'p'
        for x in ( # lista na klucni frazi za potvrduvanje na ist datum
            "иста дата", # opcija na kirilica
            "истиот датум", # opcija na kirilica
            "на истиот датум", # opcija na kirilica
            "на истата дата", # opcija na kirilica
            "ист ден", # opcija na kirilica
            "ista data", # opcija na latinica
            "istiot datum", # opcija na latinica
        )
    )
    # any() vraka True ako barem edna fraza postoi vo tekstot

def _baranje_e_premesti_datum(prasanje: str) -> bool:
    # eksplicitno premestuvanje na datum (ne samo vreme)
    p = transliterijaj(prasanje).lower()
    return any(
        w in p
        for w in ("премести", "префрли", "пренеси", "одложи", "premesti", "prefrli")
    )


def _baranje_e_promena(prasanje: str, ai_akcija: str | None) -> bool:
    # dali korisnikot saka promena na postoecko dezurstvo
    if (ai_akcija or "").lower() == "promeni":
        return True
        # ako ai vekje zaklucil deka e promena
    p = transliterijaj(prasanje).lower()
    return any(
        w in p
        for w in (
            "премести",
            "префрли",
            "промени",
            "промениш",
            "пренеси",
            "одложи",
            "смени",
            "може да го промениш",
            "da go promenish",
        )
    )
def _baranje_e_dodadi(prasanje: str, ai_akcija: str | None) -> bool: # funkcija za prepoznavanje namera za kreiranje novo dezurstvo
    # dali korisnikot saka novo dezurstvo (INSERT)
    if (ai_akcija or "").lower() == "dodadi": # ako ai modelot utvrdil akcija "dodadi"
        return True # potvrdzuvame deka korisnikot saka dodavanje
    
    p = transliterijaj(prasanje).lower() # normalizacija na vlezniot tekst
    return any( # vrakjame true dokolku najdeme klucen zbor za dodavanje
        w in p # proverka dali zborot 'w' postoi vo tekstot 'p'
        for w in ( # lista na izrazi koi sugeriraat kreiranje na novo dezurstvo
            "додади",
            "dodadi",
            "додадете",
            "внеси",
            "закажи дежурство",
            "ново дежурство",
            "нека биде дежур",
            "да биде дежур",
        )
    )

def _najdi_lekar(ime_prezime: str) -> dict | None: # funkcija za pronagjanje lekar vo bazata spored ime
    # funkcija za pronagjanje lekar vo baza
    if not ime_prezime: # ako tekstot za ime e prazen
        return None # nema sto da prebaruva, vrakjame nisto
        
    from ai._kernel.lekar_lookup import ( # uvoz na potrebni funkcii samo koga se potrebni (lazy import)
        izvlechi_delovi_ime,
        najdi_lekar_od_delovi,
        najdi_lekar_od_prasanje,
    )

    delovi = izvlechi_delovi_ime(ime_prezime) or [ # gi delime delovite od imeto ili koristime split
        d for d in ime_prezime.strip().split() if d
    ] # „Marija Hubreva" -> ["Marija", "Hubreva"]
    if len(delovi) >= 2: # ako imame ime i prezime
        return najdi_lekar_od_delovi(delovi) # koristime precizno prebaruvanje so poveke delovi
    return najdi_lekar_od_prasanje(ime_prezime) # fallback: prebaruvanje so edinstven zbor (na pr. prezime)

def _najdi_oddel_po_ime(oddel: str, specialty: str) -> str: # funkcija za mapiranje na hintot od ai vo realen oddel
    # mapiranje hint od ai vo ime na oddel vo baza
    oddel = (oddel or "").strip() # gi otstranuvame praznite mesta od kraevite
    if oddel: # ako imame vneseno ime na oddel
        conn = get_connection() # otvarame konekcija so bazata
        cur = conn.cursor() # kreirame kursor za izvrsuvanje na upiti
        cur.execute("SELECT DISTINCT ime_na_oddel FROM Oddeli") # gi zemame site unikatni iminja na oddeli
        for (row,) in cur.fetchall(): # pominuvame niz site rezultati
            if row and ( # ako redot ne e prazen
                oddel.lower() in str(row).lower() or str(row).lower() in oddel.lower() # proveruvame dali se sovpagjaat
            ):
                cur.close() # zatvorame kursor
                conn.close() # zatvorame konekcija
                return str(row) # go vrakjame najdeniot oddel
        cur.close() # zatvorame kursor ako ne najdovme nisto
        conn.close() # zatvorame konekcija
        
    spec = (specialty or "").strip() # ako ne najdovme, koristime specijalnost od lekarot
    return spec or "Општа" # ako ni toa go nema, vrakjame "Opsta" kako podrazbiraen oddel
    # fallback na specijalnost na lekarot


def _najdi_idno_dezurstvo(doctor_id: int) -> dict | None: # funkcija za naogawe na narednoto dezurstvo
    # najblisko idno dezurstvo >= denes za toj lekar
    conn = get_connection() # otvarame konekcija so bazata
    cur = conn.cursor(dictionary=True) # kursor koj vraka rezultati kako recnik
    cur.execute(
        "SELECT dezurstvo_ID, datum, oddel, vreme_od, vreme_do FROM Dezurstva"
        " WHERE doctor_ID = %s AND datum >= CURDATE()" # barame dezurstva od denes pa natamu
        " ORDER BY datum, vreme_od LIMIT 1", # gi podreduvame i go zema samo prvo (najskoresnoto)
        (doctor_id,), # go postavuvame id-to na lekarot kako parametar
    )
    row = cur.fetchone() # go zemame edinstveniot rezultat
    cur.close() # zatvorame kursor
    conn.close() # zatvorame konekcija
    return row # vrakjame dezurstvo ili nisto

def _najdi_dezurstvo( # funkcija za univerzalno naogawe na dezurstvo vo bazata
    doctor_id: int, # id na lekarot
    dezurstvo_id: int | None = None, # opcionalno id na konkretno dezurstvo
    na_datum: date | None = None, # opcionalen datum za baranje
) -> dict | None: # vrakja recnik so podatoci ili nisto
    # univerzalen prebaruvac: po id, po datum, ili najblisko idno
    conn = get_connection() # otvarame konekcija so bazata
    cur = conn.cursor(dictionary=True) # kursor koj vraka rezultati vo format na recnik
    
    if dezurstvo_id: # proveruvame dali imame konkretno id za prebaruvanje
        cur.execute(
            "SELECT dezurstvo_ID, datum, oddel, vreme_od, vreme_do FROM Dezurstva"
            " WHERE dezurstvo_ID = %s AND doctor_ID = %s",
            (dezurstvo_id, doctor_id),
        ) # vrsi prebaruvanje direktno po ID
    elif na_datum: # ako nema ID, proveruvame dali imame datum
        cur.execute(
            "SELECT dezurstvo_ID, datum, oddel, vreme_od, vreme_do FROM Dezurstva"
            " WHERE doctor_ID = %s AND datum = %s"
            " ORDER BY vreme_od LIMIT 1",
            (doctor_id, na_datum),
        ) # vrsi prebaruvanje po datum, zema samo eden rezultat
    else: # ako nema ni ID ni datum
        cur.close() # zatvorame kursor
        conn.close() # zatvorame konekcija
        return _najdi_idno_dezurstvo(doctor_id) # povikuvame pomosna funkcija za sledno idno dezurstvo
        
    row = cur.fetchone() # zemame eden zapis od rezultatite
    cur.close() # zatvorame kursor
    conn.close() # zatvorame konekcija
    return row # vrakjame najden rezultat ili None

def _ima_preklop( # funkcija za proverka dali postoi preklop na vremenski intervali
    doctor_id: int, # id na lekarot koj se proveruva
    datum: date, # datumot na koj se proveruva
    vreme_od: str, # pocetno vreme na noviot termin
    vreme_do: str, # krajno vreme na noviot termin
) -> bool: # vrakja true ako terminot e zafaten, false ako e sloboden
    # proveruva dali lekarot vekje ima dezurstvo vo ist termin
    conn = get_connection() # otvarame konekcija so bazata
    cur = conn.cursor(dictionary=True) # kreirame kursor koj vraka rezultati kako recnik
    cur.execute(
        """
        SELECT dezurstvo_ID FROM Dezurstva
        WHERE doctor_ID = %s AND datum = %s
        AND (
            (vreme_od <= %s AND vreme_do >= %s) OR
            (vreme_od <= %s AND vreme_do >= %s) OR
            (vreme_od >= %s AND vreme_do <= %s)
        )
        """,
        # sql proverka za preklopuvanje na vremenski intervali:
        # 1. noviot termin opfaka del od postoecki
        # 2. postoeckiot termin opfaka del od noviot
        # 3. noviot termin e celosno sodrzan vo postoeckiot
        (doctor_id, datum, vreme_od, vreme_od, vreme_do, vreme_do, vreme_od, vreme_do),
    )
    # sql proverka za preklopuvanje na vremenski intervali
    row = cur.fetchone() # zemame rezultat ako najdovme preklop
    cur.close() # zatvorame kursor
    conn.close() # zatvorame konekcija
    return row is not None # vrakjame true ako e pronajden record (zafaten), inaku false
    # True = terminot e zafaten

def _as_date(d) -> date: # funkcija za pretvoranje na razlicni formati vo siguren datum objekt
    # pomosna — siguren date objekt od mysql datetime/string
    if isinstance(d, date) and not isinstance(d, datetime): # ako e vekje date, no ne i datetime
        return d # go vrakjame objektot kako sto e
    if isinstance(d, datetime): # ako e datetime objekt
        return d.date() # go izvlekuvame samo datumot
    if hasattr(d, "year") and hasattr(d, "month"): # ako objektot ima godini i meseci (duck typing)
        return d # go vrakjame objektot
    return datetime.strptime(str(d)[:10], "%Y-%m-%d").date() # parsirame datum od string vo format YYYY-MM-DD


def _valid_time(s: str) -> bool: # funkcija za validacija dali stringot e tocen vremenski format
    # proveruva dali tekstot e validno vreme HH:MM
    try:
        datetime.strptime(s, "%H:%M") # se obiduvame da go parsirame vremeto
        return True # ako uspee, vremeto e validno
    except Exception: # ako nastane greska pri parsiranjeto
        return False # vrakjame deka vremeto ne e validno

def _dodadi_dezurstvo( # funkcija za vnesuvanje novo dezurstvo vo baza
    found: dict, # recnik so podatoci za lekarot
    datum: date, # datum na dezurstvoto
    vreme_od: str, # pocetno vreme
    vreme_do: str, # krajno vreme
    oddel_hint: str | None, # opcionalen hint za oddelot
) -> str: # vrakja poraka za potvrda
    # INSERT novo dezurstvo — vraka poraka za chat
    oddel = _najdi_oddel_po_ime(oddel_hint or "", found.get("specialty") or "") # mapirame oddel spored hint ili specijalnost
    if _ima_preklop(found["doctor_ID"], datum, vreme_od, vreme_do): # proveruvame dali lekarot vekje ima drugo dezurstvo vo toj termin
        return ( # vrakjame poraka za greska ako ima preklop
            f"Д-р {found['name']} {found['surname']} веќе има дежурство на "
            f"{format_datum(datum)} во тој временски период."
        )

    conn = get_connection() # otvarame konekcija so bazata
    cur = conn.cursor() # kreirame kursor za izvrsuvanje
    cur.execute( # izvrsuvame vnesuvanje na podatocite vo tabelata Dezurstva
        """
        INSERT INTO Dezurstva (doctor_ID, datum, oddel, vreme_od, vreme_do, napomena)
        VALUES (%s, %s, %s, %s, %s, NULL)
        """,
        (found["doctor_ID"], datum, oddel, vreme_od, vreme_do), # vnesuvame NULL za napomena bidejki ne e potrebna
    )
    conn.commit() # zacuvuvame promeni vo bazata (vazen cekor)
    # commit e vazen — bez nego nema trajno zacuvuvanje
    cur.close() # zatvorame kursor
    conn.close() # zatvorame konekcija

    return ( # vrakjame potvrda so site detali za novoto dezurstvo
        f"Дежурството е додадено.\n\n"
        f"Лекар: д-р {found['name']} {found['surname']}\n"
        f"Оддел: {oddel}\n"
        f"Датум: {format_datum(datum)}\n"
        f"Време: {vreme_od}–{vreme_do}"
    )

def _prasanje_e_samo_pregled(prasanje: str) -> bool: # funkcija za proverka dali se raboti samo za pregled na dezurstvo
    # samo pregled — delegira na pregled_dezurstvo modul
    from ai._kernel.intent_detector import _prasanje_e_pregled_dezurstvo # uvoz na detektorot za namera
    from ai._kernel.transliteracija import transliterijaj # uvoz na funkcija za transliteracija

    return _prasanje_e_pregled_dezurstvo(transliterijaj(prasanje).lower()) # vrakja rezultat od detektorot


def _odgovor(tekst: str, found: dict | None, dez: dict | None) -> dict: # funkcija za formatiranje na odgovorot
    # odgovor za chat + kontekst + signal za osvezi tabela
    out: dict = {"odgovor": tekst} # kreirame poceten recnik so odgovorot
    if found: # ako lekarot e pronajden
        out["kontekst"] = izgradi_kontekst(found, dez) # go gradime kontekstot za sledni poraki
    if "е додадено" in tekst or "е променето" in tekst: # ako imame uspesna promena
        out["akcija"] = "osvezi_admin_dezurstva" # dodavame signal za osvezuvanje na tabelata
    return out # go vrakjame finalniot recnik


def odgovori_za_dezurstvo( # glavna funkcija za obrabotka na baranjata za dezurstva
    prasanje: str,
    lekar: dict | None,
    kontekst: dict | None = None,
) -> dict:
    # glavna funkcija koja ja povikuva routerot
    # tuka pocnuva celata logika za dezurstva
    if err := require_direktor(lekar): # proveruvame dali korisnikot ima pristap kako direktor
        # walrus operator := — zacuvuva i proveruva istovremeno
        return {"odgovor": err} # ako nema dozvola, vrakjame greska
        # ako nema dozvola — vrakame greska

    if _prasanje_e_samo_pregled(prasanje): # ako e samo prasanje za pregled
        # samo pregled, ne promena/dodavanje
        from ai.opsto.pregled_dezurstvo import odgovori_za_pregled_dezurstvo # uvoz na modul za pregled

        raw = odgovori_za_pregled_dezurstvo(prasanje, lekar, kontekst) # obrabotka na pregledot
        return raw if isinstance(raw, dict) else {"odgovor": raw} # vrakjame rezultat

    denes = date.today() # zemame denesen datum
    # denesniot datum od sistemot
    dk = (kontekst or {}).get("dezurstvo_kontekst") # zemame kontekst od prethodniot razgovor
    # memorija od prethodniot razgovor (lekar, dezurstvo_id, datum, vreme)
    ai = _izvlechi_ai(prasanje, denes) # vrsime ekstrakcija na podatoci preku ai
    if ai.get("_error"): # ako ima greska pri ekstrakcijata
        return {"odgovor": ai["_error"]} # vrakjame greska do korisnikot

    ime = (ai.get("lekar") or "").strip() # izvlekuvame ime na lekarot
    datum_str = ai.get("datum") # izvlekuvame datum
    vreme_od = ai.get("vreme_od") # izvlekuvame pocetno vreme
    vreme_do = ai.get("vreme_do") # izvlekuvame krajno vreme
    oddel_hint = ai.get("oddel") # izvlekuvame oddel (hint)

    if not datum_str: # ako datumot ne e izvlecen preku ai
        dt = _datum_od_tekst(prasanje, denes) # probuvame so regex
        if dt:
            datum_str = dt.isoformat()
    if not vreme_od and not vreme_do: # ako vremeto ne e izvlecen preku ai
        ro, rd = _vreme_od_tekst(prasanje) # probuvame so regex
        vreme_od, vreme_do = ro, rd
    if not vreme_do: # ako nema krajno vreme
        vd = _vreme_samo_do(prasanje) # probuvame da go izvleceme posebno
        if vd:
            vreme_do = vd

    dodadi = _baranje_e_dodadi(prasanje, ai.get("akcija")) # proveruvame dali e dodavanje
    promena = _baranje_e_promena(prasanje, ai.get("akcija")) # proveruvame dali e promena
    ista = _baranje_ista_data(prasanje) # proveruvame dali e istata data
    if dk and not dodadi and (promena or ista or vreme_do or _vreme_samo_do(prasanje)): # logika za kontekst
        promena = True
        # ima kontekst + menuvanje vreme → smetame deka e promena

    found = _najdi_lekar(ime) if ime else None # naogawe na lekarot vo baza
    if not found:
        found = lekar_od_kontekst(kontekst) # ako nema ime, zemame lekar od kontekst
        # ako nema ime vo poraka — lekar od pretoden chat

    if not found: # ako lekarot ne e najden
        return {
            "odgovor": (
                "За кого е дежурството? Напиши име и презиме, "
                'или прво «Кога е дежурна д-р …?» па «Промени да е до 03:00».'
            )
        }

    # promena: datum od kontekst / ista data
    if promena and not dodadi: # ako e promena
        if (ista or not datum_str) and dk and dk.get("datum"):
            datum_str = dk["datum"] # koristime datum od kontekst
        if not datum_str:
            dez_tmp = _najdi_dezurstvo(
                found["doctor_ID"],
                dk.get("dezurstvo_id") if dk else None,
                None,
            )
            if dez_tmp and dez_tmp.get("datum"): # ako najdovme dezurstvo
                d = dez_tmp["datum"]
                datum_str = d.isoformat() if hasattr(d, "isoformat") else str(d)[:10]

    if dodadi and not datum_str: # ako nema datum za dodavanje
        return {
            "odgovor": (
                "Кој датум треба да биде дежурството?\n"
                "Пример: «Додади ја д-р Марија Хубрева дежурна на 21 мај од 20:00 до 04:00»"
            )
        }

    if not datum_str: # ako datumot e nepoznat
        return {
            "odgovor": (
                "На кој датум е дежурството што го менуваме? "
                "Или напиши «на иста дата» ако веќе го погледнавме распоредот."
            )
        }

    try:
        nov_datum = datetime.strptime(str(datum_str)[:10], "%Y-%m-%d").date() # parsiranje na datum
        # string -> python date objekt
    except Exception:
        return {"odgovor": f'Неважечки датум: „{datum_str}".'}

    if nov_datum < denes and dodadi: # ne moze vo minatoto
        return {"odgovor": "Не можам да закажам дежурство во минатото."}

    if dodadi: # ako e dodadi, izvrsuvame vnesuvanje
        # INSERT logika za novo dezurstvo
        if not vreme_od:
            vreme_od = "08:00" # podrazbirano vreme
            # default pocetok
        if not vreme_do:
            vreme_do = "20:00" # podrazbirano vreme
            # default kraj
        if not _valid_time(vreme_od) or not _valid_time(vreme_do):
            return {"odgovor": "Наведете време, на пр. «од 20:00 до 04:00»."}
        msg = _dodadi_dezurstvo(found, nov_datum, vreme_od, vreme_do, oddel_hint) # vnesuvanje vo baza
        dez = _najdi_dezurstvo(found["doctor_ID"], None, nov_datum) # zemame nov zapis
        return _odgovor(msg, found, dez) # vrakjame odgovor

    dez_id = int(dk["dezurstvo_id"]) if dk and dk.get("dezurstvo_id") else None # id od kontekst
    dez = _najdi_dezurstvo(found["doctor_ID"], dez_id, nov_datum) # naogawe na dezurstvoto
    if not dez:
        dez = _najdi_idno_dezurstvo(found["doctor_ID"]) # fallback na sledno

    # nov datum vo poraka bez „премести" -> novo dezurstvo (ne go mrda postoeckoto)
    if (
        dez
        and not ista
        and _as_date(nov_datum) != _as_date(dez["datum"])
        and not _baranje_e_premesti_datum(prasanje)
        and vreme_od
        and vreme_do
        and _valid_time(vreme_od)
        and _valid_time(vreme_do)
    ): # ako e nov datum, a ne e premesti, mozebi e novo dezurstvo
        dez_na_datum = _najdi_dezurstvo(found["doctor_ID"], None, nov_datum)
        if not dez_na_datum:
            msg = _dodadi_dezurstvo(found, nov_datum, vreme_od, vreme_do, oddel_hint)
            dez_new = _najdi_dezurstvo(found["doctor_ID"], None, nov_datum)
            return _odgovor(msg, found, dez_new or dez)

    if not dez: # ako ne e najdeno dezurstvo
        if vreme_od and vreme_do and _valid_time(vreme_od) and _valid_time(vreme_do):
            msg = _dodadi_dezurstvo(found, nov_datum, vreme_od, vreme_do, oddel_hint)
            dez = _najdi_dezurstvo(found["doctor_ID"], None, nov_datum)
            return _odgovor(msg, found, dez)
        return {
            "odgovor": (
                f"Д-р {found['name']} {found['surname']} нема дежурство на "
                f"{format_datum(nov_datum)} за промена."
            ),
            "kontekst": izgradi_kontekst(found, None),
        }

    if ista: # ako direktorot rekol "ista data"
        nov_datum = _as_date(dez["datum"])
        # ostaj na istiot datum od postoeckoto dezurstvo

    if not vreme_od and dk and dk.get("vreme_od"):
        vreme_od = dk["vreme_od"]
    if not vreme_od and dez.get("vreme_od"):
        vreme_od = format_vreme(dez["vreme_od"]) # formatiranje na vreme

    sets: list[str] = [] # lista za koloni za update
    # lista za dinamicko generiranje SQL UPDATE
    params: list = [] # parametri za sql
    # vrednosti za %s placeholderi
    if _as_date(nov_datum) != _as_date(dez["datum"]):
        sets.append("datum = %s")
        params.append(nov_datum)
    if vreme_od and _valid_time(vreme_od):
        sets.append("vreme_od = %s")
        params.append(vreme_od)
    if vreme_do and _valid_time(vreme_do):
        sets.append("vreme_do = %s")
        params.append(vreme_do)

    if not sets: # ako nema sto da se azurira
        return {
            "odgovor": (
                "Што точно да сменам? На пр. «на иста дата, да е до 03:00» "
                "или «премести за 25 мај»."
            ),
            "kontekst": izgradi_kontekst(found, dez),
        }

    params.append(dez["dezurstvo_ID"]) # dodavame id kako uslov
    conn = get_connection() # otvarame konekcija
    cur = conn.cursor() # kreirame kursor
    cur.execute(
        f"UPDATE Dezurstva SET {', '.join(sets)} WHERE dezurstvo_ID = %s",
        params,
    ) # azuriranje na zapisot
    # dinamicki sql — primer: UPDATE Dezurstva SET datum = %s, vreme_do = %s WHERE ...
    conn.commit() # zacuvuvame promeni
    cur.close() # zatvorame kursor
    conn.close() # zatvorame konekcija

    dez = _najdi_dezurstvo(found["doctor_ID"], dez["dezurstvo_ID"], None) # zemame svez zapis
    novo_do = vreme_do or format_vreme(dez.get("vreme_do"))
    novo_od = vreme_od or format_vreme(dez.get("vreme_od"))
    d_show = nov_datum if isinstance(nov_datum, date) else dez["datum"]

    msg = ( # kreirame finalna poraka
        f"Дежурството е променето.\n\n"
        f"Лекар: д-р {found['name']} {found['surname']}\n"
        f"Оддел: {dez['oddel']}\n"
        f"Датум: {format_datum(d_show)}\n"
        f"Време: {novo_od}–{novo_do}"
    )
    return _odgovor(msg, found, dez) # vrakjame odgovor
    # vrakja odgovor + nov kontekst za sledni poraki