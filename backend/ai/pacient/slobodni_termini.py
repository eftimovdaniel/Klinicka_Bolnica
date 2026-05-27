"""
Барање за слободни термини кај лекар - со помош на AI.
Како работи:
1. Зимаме сите лекари од базата (Doctors табелата).
2. Прашуваме AI (Groq): „Од прашањето кој лекар е во прашање?"
   - Му даваме листа на сите лекари + прашањето од корисникот
   - AI враќа ID број на лекар или NONE
3. Од прашањето се извлекува опционален датум (на пр. „следниот понеделник“, „слободен понеделник“,
   ден на крај од реченицата, „утре“) — локално. Ако има датум, се прикажуваат слотови само за тој ден.
4. Инаку: генерираме слотови (08:00-16:00, 30 мин) за 7 дена од денес.
5. Проверуваме кои слотови се веќе закажани во Termin_pregled.
6. Формираме убав одговор на македонски.
Се вика од: routers/ai_chat.py
"""
import re
from datetime import date, time, datetime, timedelta
from database import get_connection
from typing import Any
from ai._kernel.db_helpers import db_cursor, fetch_all, normalize_int
from ai._kernel.groq_client import ask_ai
from ai._kernel.prompts import LEKAR_EXTRACT_PROMPT
from ai._kernel.transliteracija import transliterijaj
from ai._kernel.utils import format_datum, format_vreme


# Rabotno vreme (moze da go menuvash)
RABOTNO_VREME_OD = time(8, 0)    # pocetok na rabotno vreme od 08:00
RABOTNO_VREME_DO = time(16, 0)   # kraj na rabotno vreme do 16:00
TRAENJE_TERMIN_MINUTI = 30       # sekoj termin trae 30 minuti
DENOVI_NAPRED = 7                # broj na denovi unapred za prebaruvanje
MAX_TERMINI = 8                  # MAX broj na termini vo eden den

# Ime na den (kirilica, posle translit.) -> weekday 0=pon … 6=ned
_DEN_WD = {
    "понеделник": 0, "вторник": 1, "среда": 2, "четврток": 3, "петок": 4, "сабота": 5, "недела": 6,
}
_DEN_ALT = "|".join(sorted(_DEN_WD.keys(), key=len, reverse=True))  # Podolgi iminja prvi za alternacija
_IMENA_DEN = ["понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"]

# Regex za detekcija na sleden raboten den
_RE_SLEDEN_RABOTEN_DEN = re.compile(
    r"(?:(?:следен|следниот|нареден|наредниот|прв)\s+работен\s+ден"
    r"|работен\s+ден\s+(?:следен|нареден|наредниот|следниот)"
    r"|кога\s+е\s+(?:следниот|наредниот|првиот)?\s*работен\s+ден)", re.UNICODE,
)

_SLEDEN_DEN_RE = re.compile(rf"(?:следниот|наредниот|следен|нареден|за)(?:\s+во)?\s+({_DEN_ALT}|\w+)", re.IGNORECASE)  # Regex za specificen den
_RE_ZA_VO_DEN = re.compile(r"(?:за\s+)?во\s+([a-zа-яѓќѕџјљњџ]{4,12})\s*$", re.IGNORECASE | re.UNICODE)  # Regex za den so "vo"
_OVAA_DEN_RE = re.compile(rf"(?:оваа|овиот|овој)\s+({_DEN_ALT})", re.IGNORECASE)  # Regex za den so "ovaa"

# „слободен понеделник“, „има ли термин во петок“ — без „следниот“
_KONTEXT_I_DEN_RE = re.compile(
    rf"(?:(?:слободен|слободна|слободни|слободно)\w*\s+(?:за\s+)?(?:во\s+)?"
    rf"|(?:термин(?:и)?)\s+(?:за\s+)?(?:во\s+)?"
    rf"|(?:има\s+ли)\s+(?:нешто\s+)?(?:слободни\s+)?(?:за\s+)?(?:во\s+)?"
    rf"|(?:дали\s+има)\s+(?:нешто\s+)?(?:слободни\s+)?(?:за\s+)?(?:во\s+)?)"
    rf"({_DEN_ALT}|\w{{4,12}})\b", re.IGNORECASE,
)

_DATUM_BROJ_RE = re.compile(r"(?:на|за)\s+(\d{1,2})[\./\-](\d{1,2})(?:[\./\-](\d{2,4}))?", re.IGNORECASE)  # Regex za datum vo brojcen format
_ISO_DATUM_RE = re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b")  # Regex za ISO format na datum

_MESECI_BROJ: dict[str, int] = {
    "јануари": 1, "januari": 1, "февруари": 2, "fevruari": 2, "март": 3, "mart": 3, "април": 4, "april": 4, "мај": 5, "maj": 5, "јуни": 6, "juni": 6, "јули": 7, "juli": 7, "август": 8, "avgust": 8,
    "септември": 9, "septemvri": 9, "oktomvri": 10, "октомври": 10, "ноември": 11, "декември": 12,
}

_ORDINAL_SUF = r"(?:ти|ри|ви|ti|ri|vi|-ti|-ri|-vi)?"  # Sufiksi za ordinalni broevi
_RE_DAN_MES = re.compile(
    r"(?:на\s+)?(\d{1,2})" + _ORDINAL_SUF + r"\s*(?:\.)?\s*(" + "|".join(sorted(_MESECI_BROJ.keys(), key=len, reverse=True)) + r")\b",
    re.UNICODE | re.IGNORECASE,
)  # Regex za datum so ime na mesec


def _den_od_tekst(tekst: str) -> str | None:  # Pretvoranje na tekst vo ime na den
    t = transliterijaj(tekst or "").lower().strip()  # Normalizacija na tekstot
    if not t: return None  # Ako e prazno, vrati None
    if t in _DEN_WD: return t  # Ako e tocno ime, vrati go
    
    _ALIAS = {  # Alias lista za skrateni iminja
        "ponedel": "понеделник", "ponedelnik": "понеделник", "vtorni": "вторник", "vtornik": "вторник", "vtorik": "вторник", "sreda": "среда", "chetvrtok": "четврток", "petok": "петок", "sabota": "сабота", "nedela": "недела",
    }
    if t in _ALIAS: return _ALIAS[t]  # Proverka vo alias listata
    
    for ime in _DEN_WD:  # Iteracija za slicni iminja
        if len(t) >= 4 and (ime.startswith(t) or t.startswith(ime[:4])):  # Sporedba na pocetok
            return ime  # Vrati soodvetno ime
    return None  # Ako ne najde, vrati None

def _den_od_match(m: re.Match) -> str | None:  # Izvlekuvanje den od regex match
    return _den_od_tekst(m.group(1) or "")  # Povikaj go parsiranjeto


def _den_na_kraj_od_prasanje(p: str) -> str | None:  # Den na krajot od prashanjeto (npr. "... понеделник?")
    """
    Ден во неделата на крај од прашањето („… Захариев понеделник?“),
    само ако има јасен контекст за термини/слободно време.
    """
    p2 = p.strip().rstrip("?!. ")  # Ottstranuvanje na interpunkciski znaci od krajot
    _kontekst_den = re.compile(  # Regex za proverka na kontekstot (npr. dali bara sloboden termin)
        r"\b(кога|слободен|слободна|слободни|слободно|термин|има\s+ли|"
        r"нареден|наредниот|наредна|следен|следниот|следна)\b",
        re.IGNORECASE,
    )
    for ime in sorted(_DEN_WD.keys(), key=len, reverse=True):  # Iteracija niz site denovi
        if not p2.endswith(ime): continue  # Ako prashanjeto ne zavrshuva so ovoj den, prodolzi
        pred = p2[: len(p2) - len(ime)]  # Go zema delot od prashanjeto pred denot
        if _kontekst_den.search(pred):  # Proveruva dali ima kluchen zbor pred denot
            return ime  # Vrakja ime na den ako e najden kontekst
    return None  # Vrakja None ako nema soodveten den

def sleden_raboten_datum(denes: date | None = None) -> date:  # Prviot pon-pet den po denes
    """Првиот пон–пет ден по денес (прескокнува сабота/недела)."""
    denes = denes or date.today()  # Go zema deneshniot datum ako ne e vnesen
    d = denes + timedelta(days=1)  # Pocnuva od naredniot den
    while d.weekday() >= 5:  # Ako e sabota (5) ili nedela (6), prodolzi
        d += timedelta(days=1)  # Preskokni go vikendot
    return d  # Vrakja datum na sleden raboten den

def prasanje_e_sleden_raboten_den(prasanje: str) -> bool:  # Proverka za "sleden raboten den"
    p = transliterijaj(prasanje).lower()  # Normalizacija na tekstot
    return bool(_RE_SLEDEN_RABOTEN_DEN.search(p))  # Vrakja True ako e najdeno sovpaganje

def prasanje_e_baranje_slobodni(prasanje: str) -> bool:  # Proverka dali se baraat slobodni termini
    """Прашање за слободни термини (не закажување)."""
    p = transliterijaj(prasanje).lower()  # Normalizacija
    if any(x in p for x in ("слобод", "slobod")): return True  # Ako ima zbor "sloboden"
    
    if "термин" in p or "termin" in p:  # Ako bara "termin"
        if any(x in p for x in ("има", "дали", "кога", "слобод", "slobod", "провери", "proveri", "на ", " na ", "за "," za ")): # Proverka na kontekst
            return True  # Vrakja True ako ima soodveten kontekst
        try:  # Obid za uvoz na proverka
            from ai.pacient.moi_pregledi import datum_za_pregledi_od_prasanje
            if datum_za_pregledi_od_prasanje(prasanje): return True  # Vrakja True ako AI najde datum
        except ImportError:  # Ako uvozot ne uspeal
            if datum_od_prasanje_lokalno(prasanje): return True  # Lokalna proverka
            
    if re.search(r"\b(преглед|pregled)\w*\b", p) and ("слобод" in p or "slobod" in p or "провери" in p or "proveri" in p): # Proverka za "pregled"
        return True  # Vrakja True ako se baraat slobodni termini
    return False  # Vrakja False ako ne e pronajdeno nishto

def prasanje_e_slobodni_za_den(prasanje: str, kontekst: dict | None = None) -> bool:  # Proverka za nov den kaj ist doktor
    """Нов ден кај истиот лекар — „за во вторник“, „ама за вторник“."""
    if baranje_e_zakazuvanje(prasanje): return False  # Ako e baraanje za zakazuvanje, vrati False
    if not datum_od_prasanje_lokalno(prasanje): return False  # Ako nema datum vo prashanjeto, vrati False
    if prasanje_e_baranje_slobodni(prasanje): return True  # Ako se baraat slobodni termini, vrati True
    
    if isinstance(kontekst, dict) and kontekst.get("zakazi_od_slobodni"):  # Ako ima kontekst za zakazuvanje
        import re as _re
        p = transliterijaj(prasanje).lower()  # Normalizacija na tekstot
        if _re.search(r"\b\d{1,2}\s*[:.]\s*\d{2}\b", p): return False  # Ako ima vreme, ne e samo za den
        return True  # Vrati True ako se odnesuva na denot
    return False  # Ako ne e nisto od toa, vrati False
            
def prasanje_bar_lekar_od_kontekst(prasanje: str) -> bool:  # Proverka za lekar od kontekst
    """„Избраниот/истиот лекар" — лекарот е во контекст од претходна порака."""
    p = transliterijaj(prasanje).lower()  # Normalizacija na tekstot
    return any(  # Proverka dali ima klucni zborovi za kontekstualen lekar
        x in p
        for x in (
            "избраниот лекар","избраниот","избраниов","избран лекар","истиот лекар","истиот","истиов","погоре","од листата","од горе","тогој лекар","тој лекар","го избрав","izbraniot","istiot",
        )
    )
def prasanje_e_otkazuvanje(prasanje: str) -> bool:  # Proverka za otkazhuvanje na termin
    """Откажување на термин (откажи, откажеш, откажам, …)."""
    p = transliterijaj(prasanje).lower()  # Normalizacija na tekstot
    if "откаж" in p or "otkaz" in p: return True  # Ako sodrzhi koren od "otkazuvanje"
    if "cancel" in p and "termin" in p: return True  # Ako sodrzhi angliski termini
    return any(  # Proverka za drugi sinonimi za otkazhuvanje
        x in p
        for x in (
            "сторнира","поништи термин","не доаѓам","не сакам термин",
        )
    )
_RE_ZAKAZUVANJE = re.compile(  # Regex za prepoznavanje na namera za zakazuvanje
    r"(?:"
    r"зака[жз]\w*|zakaz\w*|"
    r"може\s+да\s+(?:ми\s+)?зака[жз]|moze\s+da\s+(?:mi\s+)?zakaz|"
    r"можете\s+да\s+(?:ми\s+)?зака[жз]|"
    r"да\s+ми\s+зака[жз]|da\s+mi\s+zakaz|"
    r"запиш\w*|zapish\w*|"
    r"сакам\s+(?:да\s+)?(?:зака[жз]|оди|преглед)|"
    r"може\s+ли\s+зака[жз]"
    r")",
    re.UNICODE | re.IGNORECASE,
)
def baranje_e_zakazuvanje(prasanje: str) -> bool:  # Proverka dali prashanjeto e za zakazuvanje
    """Дали пораката е закажување (не повторна проверка на слободни термини)."""
    raw = (prasanje or "").lower()  # Sirova verzija na prashanjeto
    q = transliterijaj(prasanje).lower()  # Transliterirana verzija bez kirilichni znaci
    
    if _RE_ZAKAZUVANJE.search(q) or _RE_ZAKAZUVANJE.search(raw):  # Ako ima klucni zborovi za zakazuvanje
        if not any(  # Proverka dali nema zborovi za baranje slobodni termini
            w in q
            for w in ("слобод", "кога е", "има ли", "провери", "провер", "наредн", "следн")
        ):
            return True  # Vrati True ako e definitivno zakazuvanje
            
    if re.search(r"\b\d{1,2}\s*[:.]\s*\d{2}\b", q):  # Proverka dali ima format na vreme (npr. 10:00)
        if any(  # Ako ima vreme i klucen zbor za zakazuvanje
            x in q or x in raw
            for x in (
                "закаж","заказ","zakaz","термин","преглед","може да закаж","може да заказ","moze da zakaz",
            )
        ):
            return True  # Vrati True ako se bara termin vo odredeno vreme
    return False  # Vrati False ako ne e zakazuvanje

def prasanje_bar_datum_od_kontekst(prasanje: str) -> bool:  # Proverka za datum od kontekst
    """„Претходно спомнатиот / избраниот датум“ — датумот е во kontekst."""
    p = transliterijaj(prasanje).lower()  # Normalizacija na tekstot
    return any(  # Proverka za klucni zborovi za "prethoden datum"
        x in p
        for x in (
            "избраниот датум","избрана дата","избраниот","претходно спомнати","претходно","претходниот","спомнатиот датум","спомнатиот","истиот датум","наведениот датум","тогаш спомнати","pretходно","spomnat","izbraniot datum",
        )
    )

def datum_od_zakazi_kontekst(kontekst: dict | None) -> date | None:  # Izvlekuvanje datum od zakazuvanje
    """Датум зачуван по листа слободни термини / pending закажување."""
    if not isinstance(kontekst, dict): return None  # Ako kontekstot ne e recnik, vrati None
    
    for key in ("zakazi_od_slobodni", "zakazi_pending"):  # Proverka na klucovi za zakazuvanje
        z = kontekst.get(key)
        if not isinstance(z, dict) or not z.get("datum"): continue  # Preskokni ako nema datum
        try:  # Obid za parsiranje na datumot
            return datetime.strptime(str(z["datum"]).strip()[:10], "%Y-%m-%d").date()
        except ValueError: continue  # Preskokni pri greska
    return None  # Vrati None ako ne e najden datum

def prasanje_e_drugi_lekari_specijalnost(prasanje: str) -> bool:  # Proverka za "drugi lekari od istata specijalnost"
    p = transliterijaj(prasanje).lower()  # Normalizacija na tekstot
    ima_spec_ref = any(  # Proverka dali ima referenca kon specijalnost ili oddel
        x in p
        for x in (
            "специјалност","специјалности","оддел","истата","иста ","оваа","ова ","истиот","истиов","specijalnost","oddel","istata","ista ","ovaa","ova ",
        )
    )
    ima_lekari_pl = any(x in p for x in ("лекари", "lekari", "доктори", "doktori"))  # Proverka za plural na lekari
    
    if ima_lekari_pl and ima_spec_ref:  # Ako bara lekari vo ista specijalnost
        if any(x in p for x in ("истата","иста ","оваа","ова ","istata","ista ","ovaa","ova ")): return True  # Vrati True ako e ista specijalnost
        if "од " in p and any(x in p for x in ("специјалност", "specijalnost", "оддел", "oddel")): return True  # Ili ako bara lekari od specijalnost
        
    if not any(  # Proverka za "drugi" ili "ostanati"
        x in p
        for x in ("други","друг ","друга ","уште","останати","drugi","drug ","ushte","останati")
    ): return False  # Ako ne bara drugi, vrati False
    
    if not any(x in p for x in ("лекар", "лекари", "доктор", "lekari", "doktor")): return False  # Proverka za lekari
    return ima_spec_ref  # Vrati True ako ima referenca za specijalnost

def prasanje_e_specijalnost_izbran_lekar(prasanje: str, kontekst: dict | None = None) -> bool:  # Proverka za specijalnost na konkreten lekar
    if prasanje_e_drugi_lekari_specijalnost(prasanje): return False  # Ako bara drugi lekari, ne e za izbran lekar
    if prasanje_e_baranje_slobodni(prasanje): return False  # Ako bara slobodni termini, ne e info za eden lekar
    
    p = transliterijaj(prasanje).lower()  # Normalizacija
    ima_lekari_pl = any(x in p for x in ("лекари", "lekari", "доктори", "doktori"))  # Proverka za plural
    
    if not any(  # Proverka za klucni zborovi za oblast/specijalnost
        x in p
        for x in ("област","специјалност","оддел","каде работи","која е","кое е","од која","koja oblast","vo koja","specijalnost","oblast","oddel")
    ): return False  # Ako nema klucen zbor, vrati False
    
    if prasanje_bar_lekar_od_kontekst(prasanje): return True  # Ako lekarot e od kontekst
    if any(x in p for x in ("избран", "истиот", "погоре", "тој лекар", "togo lekar")): return True  # Ako se odnesuva na izbran lekar
    if ima_lekari_pl: return False  # Ako se baraat lekari vo plural, vrati False
    
    if lekar_od_zakazi_kontekst(kontekst) and any(  # Proverka za doktor od kontekstot za zakazuvanje
        x in p
        for x in ( "лекарот","лекар "," лекар","д-р"," др","докторот","доктор ","toj lekar","togo lekar")
    ): return True  # Vrati True ako se bara info za toj lekar
    
    return False  # Ako nisto ne se sovpaga, vrati False

def resolviraj_lekar_za_slobodni(prasanje: str, kontekst: dict | None) -> tuple[dict | None, bool, str | None]:  # Najdi lekar za slobodni termini
    if prasanje_bar_lekar_od_kontekst(prasanje):  # Ako lekarot se bara od prethoden kontekst
        lekar = lekar_iz_izbran_kontekst(kontekst)  # Izvleci lekar od kontekst
        if not lekar and isinstance(kontekst, dict):  # Ako nema lekar, pobaraj izbor od lista
            poraka = _poraka_izberi_lekar_od_lista(kontekst)  # Formiraj poraka za izbor
            if poraka: return None, False, poraka  # Vrati poraka ako treba izbor
        return lekar, lekar is not None, None  # Vrati go lekarot ako e najden
    from ai._kernel.lekar_lookup import (  # Uvoz na pomosni funkcii za prebaruvanje
        izvlechi_delovi_ime, najdi_lekar_od_prasanje, najdi_lekari_po_delovi,
        najdi_lekari_po_prezime, poraka_za_vise_lekari, prezime_na_pocetok_od_prasanje,
    )
    prezime_poc = prezime_na_pocetok_od_prasanje(prasanje)  # Proverka za prezime na pocetok
    if prezime_poc:  # Ako e najdeno prezime
        kandidati = najdi_lekari_po_prezime(prezime_poc)  # Prebaraj lekari po prezime
        if len(kandidati) == 1: return kandidati[0], False, None  # Ako e eden, vrati go
        if len(kandidati) > 1: return None, False, poraka_za_vise_lekari(kandidati, [prezime_poc])  # Ako se poveke, vrati poraka za izbor
    delovi = izvlechi_delovi_ime(prasanje)  # Izvlechi delovi od imeto
    kandidati = najdi_lekari_po_delovi(delovi)  # Prebaraj lekari po delovi od ime
    if len(kandidati) > 1: return None, False, poraka_za_vise_lekari(kandidati, delovi)  # Ako se poveke, vrati poraka
    lekar = najdi_lekar_od_prasanje(prasanje)  # Probaj da najdes lekar direktno od prashanjeto
    if lekar: return lekar, False, None  # Vrati go ako e najden    
    lekar = lekar_od_zakazi_kontekst(kontekst)  # Probaj lekar od kontekst za zakazuvanje
    if lekar: return lekar, True, None  # Vrati go ako e najden   
    if prasanje_e_baranje_slobodni(prasanje) and datum_od_prasanje_lokalno(prasanje):  # Proverka za slobodni termini
        lekar = lekar_od_oddel_kontekst(kontekst)  # Probaj lekar od oddelot vo kontekstot
        if lekar: return lekar, True, None  # Vrati go ako e najden    
    return None, False, None  # Vrati nisto ako ne e najden lekar

def _sleden_takov_kalendarski_den(denes: date, ime_den: str) -> date:  # Presmetaj datum za sleden specificen den
    twd = _DEN_WD[ime_den]  # Indeks na denot vo nedelata
    dwd = denes.weekday()  # Denesniot den vo nedelata
    days = (twd - dwd) % 7  # Presmetaj broj na denovi do toj den
    if days == 0: days = 7  # Ako e denes, zemi go naredniot den
    return denes + timedelta(days=days)  # Vrati go noviot datum

def _ovaa_nedela_den(denes: date, ime_den: str) -> date:  # Presmetaj datum vo tekovnata nedela
    twd = _DEN_WD[ime_den]  # Indeks na denot
    pocetok = denes - timedelta(days=denes.weekday())  # Pocetok na nedelata
    cand = pocetok + timedelta(days=twd)  # Potencijalen datum
    if cand < denes: cand += timedelta(days=7)  # Ako e vo minatoto, dodaj edna nedela
    return cand  # Vrati go datumot

def _mesec_od_tekst(tekst: str) -> int | None:  # Pretvoranje na ime na mesec vo brojka
    t = transliterijaj(tekst).lower().strip()  # Normalizacija
    if t in _MESECI_BROJ: return _MESECI_BROJ[t]  # Vrati brojka ako e najdeno
    for k, v in _MESECI_BROJ.items():  # Proverka za slicnost na tekstot
        if t.startswith(k[:3]) or k.startswith(t[:3]): return v  # Vrati brojka
    return None  # Ako ne e najdeno, vrati None

def _parsiraj_dan_mesec(p: str, denes: date) -> date | None:  # Parsiranje na datum so mesec
    """„20 мај", „на 20.05" со име на месец."""
    m = _RE_DAN_MES.search(p)  # Prebaraj datum vo tekstot
    if not m: return None  # Ako nema datum, vrati None
    dan = int(m.group(1))  # Izvleci den
    mesec = _mesec_od_tekst(m.group(2))  # Izvleci mesec
    if not mesec: return None  # Ako nema mesec, vrati None
    return _parsiraj_dd_mm_gggg(denes, dan, mesec, None)  # Vrati kompleten datum objekt

def vreme_od_prasanje_lokalno(prasanje: str) -> str | None:  # Izvlekuvanje na vreme od prashanje
    """Час од „во 12:00", „12 часот". """
    p = transliterijaj(prasanje or "").lower().strip()  # Normalizacija na tekstot
    if not p: return None  # Ako e prazno, vrati None
    m = re.search(r"\b(\d{1,2})\s*[:.]\s*(\d{2})\b", p)  # Regex za format HH:MM ili HH.MM
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59: return f"{h:02d}:{mi:02d}"  # Vrati formatirano vreme  
    m = re.search(r"(?:во|vo|at)\s+(\d{1,2})(?:\s*(?:час|часот|cas|casot))?\b", p)  # Regex za "vo 12 casot"
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23: return f"{h:02d}:00"  # Vrati polen cas    
    m = re.search(r"\b(\d{1,2})\s*(?:час|часот|cas|casot)\b", p)  # Regex za "12 casot"
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23: return f"{h:02d}:00"  # Vrati polen cas
    return None  # Ako ne e najdeno vreme, vrati None


def vreme_iz_kontekst(kontekst: dict | None) -> str | None:
    """Зачуван час од претходна порака (кој е слободен во X)."""
    if not isinstance(kontekst, dict):
        return None
    v = (kontekst.get("last_slobodni_vreme") or "").strip()
    if v:
        return v
    z = kontekst.get("zakazi_od_slobodni")
    if isinstance(z, dict):
        v = (z.get("vreme") or "").strip()
        if v:
            return v
    return None


def prasanje_e_utochnuvanje_datum(prasanje: str) -> bool:
    """
    Само уточнување на датум/ден (на пр. «наредниот петок») по претходно «кој е слободен … во 13:00».
    """
    p = transliterijaj(prasanje).lower().strip()
    if not p or len(p) > 70:
        return False
    if not datum_od_prasanje_lokalno(prasanje):
        return False
    if baranje_e_zakazuvanje(prasanje):
        return False
    from ai._kernel.lekar_lookup import prasanje_ukazuva_kon_konkreten_lekar

    if prasanje_ukazuva_kon_konkreten_lekar(prasanje):
        return False
    if _KO_PRASANJE_RE.search(p):
        return False
    if "слобод" in p or "slobod" in p:
        return False
    if re.search(r"\b(?:кај|kaj)\s+", p, re.UNICODE):
        return False
    return True


def _azuriraj_kontekst_ko_sloboden(
    kontekst: dict | None,
    baran_datum: date,
    barano_vreme: str | None,
    lekari: list[dict],
    oddel: str | None,
    pool: list[dict] | None,
) -> dict:
    ctx = dict(kontekst) if isinstance(kontekst, dict) else {}
    if oddel:
        ctx["last_oddel"] = oddel
        if pool:
            ctx["last_oddel_doctor_ids"] = [int(l["doctor_ID"]) for l in pool]
    ctx["last_slobodni_datum"] = baran_datum.strftime("%Y-%m-%d")
    if barano_vreme:
        ctx["last_slobodni_vreme"] = barano_vreme
    if lekari:
        ctx["last_slobodni_doctor_ids"] = [int(l["doctor_ID"]) for l in lekari]
        pr = lekari[0]
        z: dict = {
            "doctor_id": int(pr["doctor_ID"]),
            "datum": baran_datum.strftime("%Y-%m-%d"),
        }
        if barano_vreme:
            z["vreme"] = barano_vreme
        ctx["zakazi_od_slobodni"] = z
        ctx["last_doctor_id"] = int(pr["doctor_ID"])
    return ctx


#Regex za prepoznavanje na prashalni zborovi (koj/koja/koi)
_KO_PRASANJE_RE = re.compile(
    r"\b(кој|која|кои|koj|koja|koi)\b",
    re.UNICODE | re.IGNORECASE,
)
# Lista na klucni zborovi za kontekstualno baranje
_OD_NIV_SLOBODNI_MARKERS = (
    "од нив",
    "од овие",
    "од лекарите",
    "од горе",
    "од погоре",
    "од листата",
    "од тој оддел",
    "од одделот",
    "кој од нив",
    "кои од нив",
    "кој од лекарите",
    "кои од лекарите",
    "od niv",
    "od ovie",
    "od lekarite",
    "koj od niv",
    "koi od niv",
)
def _ima_oddel_lekari_kontekst(kontekst: dict | None) -> bool:  # Proverka dali postoi kontekst za lekari vo oddel
    if not isinstance(kontekst, dict): return False  # Ako ne e recnik, vrati False
    ids = kontekst.get("last_oddel_doctor_ids")  # Zemi lista na ID-a od kontekstot
    return isinstance(ids, list) and len(ids) > 0  # Vrati True ako listata e validna i ne e prazna

def prasanje_e_od_niv_sloboden(prasanje: str) -> bool:  # Proverka dali prashanjeto se odnesuva na lista lekari
    """„Кој од нив е слободен …" — продолжување по листа лекари од оддел."""
    p = transliterijaj(prasanje).lower()  # Normalizacija na tekstot
    if "слобод" not in p and "slobod" not in p: return False  # Mora da bara sloboden termin
    return any(m in p for m in _OD_NIV_SLOBODNI_MARKERS)  # Vrati True ako sodrzhi marker za kontekst

def prasanje_e_ko_e_sloboden_datum_vreme(prasanje: str, kontekst: dict | None = None) -> bool:  # Proverka za "koj e sloboden"
    """„Кој/која е слободен …" или „кој од нив" по листа оддел — без конкретен лекар по име."""
    p = transliterijaj(prasanje).lower()  # Normalizacija
    if "слобод" not in p and "slobod" not in p: return False  # Mora da bara sloboden
    
    from ai._kernel.lekar_lookup import prasanje_ukazuva_kon_konkreten_lekar
    
    if _ima_oddel_lekari_kontekst(kontekst) and (  # Ako ima kontekst za oddelot
        prasanje_e_od_niv_sloboden(prasanje)  # Ako prashanjeto e za lekari od lista
        or (_KO_PRASANJE_RE.search(p) and _oddel_od_kontekst(kontekst))  # Ili prashanje za lekar vo oddel
        or (
            prasanje_e_baranje_slobodni(prasanje)  # Ili baranje za slobodni termini
            and datum_od_prasanje_lokalno(prasanje)  # So desen datum
            and not vreme_od_prasanje_lokalno(prasanje)  # Bez specifikacija na vreme
            and not prasanje_ukazuva_kon_konkreten_lekar(prasanje)  # I bez konkretno ime
        )
    ): return True
    
    baran_datum = datum_od_prasanje_lokalno(prasanje)  # Izvleci datum
    barano_vreme = vreme_od_prasanje_lokalno(prasanje)  # Izvleci vreme
    if not baran_datum and not barano_vreme: return False  # Ako nema nisto, vrati False
    if _KO_PRASANJE_RE.search(p): return True  # Ako prashuva "koj e", vrati True
    
    if baran_datum and barano_vreme:  # Ako ima datum i vreme
        from ai._kernel.lekar_lookup import izvlechi_delovi_ime, najdi_lekar_od_delovi
        delovi = izvlechi_delovi_ime(prasanje)
        if not delovi or not najdi_lekar_od_delovi(delovi): return True  # Ako ne e najden lekar, vrati True
    return False

def _parsiraj_dd_mm_gggg(denes: date, d: int, m: int, g: int | None) -> date | None:  # Pomosna funkcija za datum
    god = g if g is not None else denes.year  # Zemi godina ako e dadena, inaku tekovna
    if god < 100: god += 2000  # Pretvoranje na godini so dve cifri
    try:
        out = date(god, m, d)  # Kreiraj datum objekt
    except ValueError: return None  # Vrati None pri greshen datum 
    if out < denes:  # Ako datumot e vo minatoto
        if g is None and m >= denes.month:  # Proverka za sledna godina
            try: out = date(denes.year + 1, m, d)
            except ValueError: return None
        elif out < denes: return None  # Inaku e nevaliden
    return out

def datum_od_prasanje_lokalno(prasanje: str) -> date | None:  # Parsiranje datum od prashanje
    """Брзо препознавање на датум во прашање (кирилица по транслит.)."""
    p = transliterijaj(prasanje).lower()  # Normalizacija
    denes = date.today()  # Deneshniot datum
    if _RE_SLEDEN_RABOTEN_DEN.search(p): return sleden_raboten_datum(denes)  # Za "sleden raboten den"
    if "задутре" in p or "задутра" in p: return denes + timedelta(days=2)  # Za "zadutre"
    if re.search(r"\bутре\b", p): return denes + timedelta(days=1)  # Za "utre"
    m = _ISO_DATUM_RE.search(prasanje)  # Proverka za ISO format (YYYY-MM-DD)
    if m:
        try:
            out = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return out if out >= denes else None
        except ValueError: pass
    dm = _parsiraj_dan_mesec(p, denes)  # Proverka za "dan mesec"
    if dm is not None: return dm
    
    m = _DATUM_BROJ_RE.search(p)  # Proverka za brojcen format (DD.MM)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        g = int(m.group(3)) if m.group(3) else None
        parsed = _parsiraj_dd_mm_gggg(denes, d, mo, g)
        if parsed is not None: return parsed
    
    m = _OVAA_DEN_RE.search(p)  # Proverka za "ovaa sreda"
    if m:
        ime = _den_od_match(m)
        if ime: return _ovaa_nedela_den(denes, ime)
    m = _SLEDEN_DEN_RE.search(p)  # Proverka za "sleden vtornik"
    if m:
        ime = _den_od_match(m)
        if ime: return _sleden_takov_kalendarski_den(denes, ime)
    m = _RE_ZA_VO_DEN.search(p)  # Proverka za "vo vtornik"
    if m:
        ime = _den_od_tekst(m.group(1))
        if ime: return _sleden_takov_kalendarski_den(denes, ime) 
    m = _KONTEXT_I_DEN_RE.search(p)  # Proverka za den vo kontekst
    if m:
        ime = _den_od_match(m)
        if ime: return _sleden_takov_kalendarski_den(denes, ime)   
    ime_kraj = _den_na_kraj_od_prasanje(p)  # Proverka za den na kraj
    if ime_kraj: return _sleden_takov_kalendarski_den(denes, ime_kraj)
    return None  # Ako ne najadeno nisto se vraka none


def datum_za_zakazi_kontekst(baran_datum: date | None, slobodni: list[datetime]) -> str | None:  # Formatiranje datum za kontekstot
    """ISO датум за zakazi_od_slobodni — од барањето или од прикажаните слотови."""
    if baran_datum is not None: 
        return baran_datum.strftime("%Y-%m-%d")  # Vrati datum od baranje ako postoi
    if not slobodni: 
        return None  # Vrati None ako nema slobodni termini
    dates = sorted({dt.date() for dt in slobodni})  # Izvleci unikatni datumi od slotovite
    if len(dates) == 1: 
        return dates[0].strftime("%Y-%m-%d")  # Vrati go edinstveniot datum
    return dates[0].strftime("%Y-%m-%d")  # Vrati go najranit datum od listata

def _datum_od_prasanje_so_ai(prasanje: str) -> date | None:  # Rezervno izvlekuvanje datum preku AI
    """Резервно: датум од прашање преку Groq."""
    from ai._kernel.ai_json import is_ai_error_response, parse_ai_json
    from ai._kernel.groq_client import ask_ai
    denes = date.today().isoformat()  # Deneshen datum kako string
    prompt = f"""Денес е {denes}. Од прашањето извлечи датум за преглед (работен ден). Прашање: „{prasanje}"
    Врати JSON: {{"datum": "YYYY-MM-DD"}} или {{"datum": null}} ако нема датум.
    Само JSON."""  # Kreiranje prompt za AI
    raw = ask_ai(prompt, system_prompt="Ти извлекуваш датуми. Само валиден JSON.")  # Povikaj AI model
    if is_ai_error_response(raw): return None  # Vrati None pri greshka
    data = parse_ai_json(raw, log_tag="datum_ai")  # Parsiraj JSON odgovor
    val = data.get("datum")  # Izvleci vrednost za datum
    if not val: return None  # Ako e prazno, vrati None
    try:  # Obid za konverzija na datumot
        out = datetime.strptime(str(val).strip()[:10], "%Y-%m-%d").date()
        return out if out >= date.today() else None  # Vrati datum ako e vo idnina
    except ValueError: return None  # Vrati None pri greshka vo formatot

def termin_sloboden_na_datum_vreme(doctor_id: int, na_datum: date, vreme_str: str) -> bool:  # Proverka za sloboden termin
    if na_datum.weekday() >= 5: return False  # Vikend ne e raboten den
    try:  # Parsiranje na vremeto
        h_s, m_s = vreme_str.strip().split(":")[:2]
        t = time(int(h_s), int(m_s))
    except (ValueError, TypeError): return False  # Vrati False pri greshka vo formatot
    slotovi_den = generiraj_slotovi_za_den(na_datum)  # Generiraj dozvoleni slotovi za denot
    if not any(s.time().hour == t.hour and s.time().minute == t.minute for s in slotovi_den): return False  # Proveri dali slotot postoi
    slot_dt = datetime.combine(na_datum, t)  # Kombiniraj datum i vreme
    if slot_dt < datetime.now(): return False  # Ne moze vo minatoto
    zafateni = najdi_zafateni_slotovi(doctor_id, na_datum, na_datum)  # Izvleci zafateni termini od baza
    return (na_datum, time(t.hour, t.minute)) not in zafateni  # Vrati True

def lekar_sloboden_na_termin(lekar: dict, na_datum: date, vreme_str: str) -> bool:  # Proverka za konkreten lekar
    return termin_sloboden_na_datum_vreme(int(lekar["doctor_ID"]), na_datum, vreme_str)  # Povikaj glavna proverkav

def zimi_lekari_po_specialty(specialty: str) -> list[dict[str, Any]]:  # Izvlekuvanje lekari po specijalnost
    """Лекари од еден оддел/специјалност (исто како lekari_oddel)."""
    if not (specialty or "").strip(): return []  # Ako e prazno, vrati prazna lista
    try:
        with db_cursor() as (_, cur):  # Otvori bazen kursor
            cur.execute("""
                SELECT doctor_ID, name, surname, specialty, email
                FROM Doctors
                WHERE LOWER(TRIM(specialty)) = LOWER(TRIM(%s))
                ORDER BY surname, name
            """, (specialty.strip(),))  # Filtriraj lekari spored specijalnost
            return fetch_all(cur)  # Vrati gi site rezultati
    except Exception as e:
        print(f"[slobodni_termini] lekari po specialty greska: {e}")  # Logiraj greshka
        return []

def _oddel_od_kontekst(kontekst: dict | None) -> str | None:  # Izvlekuvanje oddel od kontekst
    if not isinstance(kontekst, dict): return None
    for key in ("last_oddel", "oddel", "specialty"):  # Proverka na klucni polinja
        val = kontekst.get(key)
        if val and str(val).strip(): 
            return str(val).strip()  # Vrati go oddelot ako postoi
    return None

def prasanje_bar_site_lekari_za_slobodni(prasanje: str) -> bool:  # Proverka za "site lekari"
    """Корисникот сака слободни низ цела болница, не само претходниот оддел."""
    p = transliterijaj(prasanje).lower()  # Normalizacija
    return any(  # Proverka za markerite
        x in p
        for x in (
            "на болницата", "во болницата", "во целата", "целата болница",
            "кај било кој", "било кој лекар", "сите лекари", "site lekari", "celata bolnica",
        )
    )

def lekari_pool_za_ko_sloboden(prasanje: str, kontekst: dict | None) -> tuple[list[dict] | None, str | None]:  # Kreiranje pool na lekari
    """
    Кои лекари да се проверат за „кој е слободен“.
    Враќа (pool, oddel_ime). pool=None → сите лекари.
    """
    if prasanje_bar_site_lekari_za_slobodni(prasanje): return None, None  # Ako bara site, vrati pool=None
    
    from ai._kernel.oddel_resolver import resolve_oddel
    resolved = resolve_oddel(prasanje)  # Rezolviraj oddel od prashanje
    if resolved and resolved.ok and resolved.oddel: return zimi_lekari_po_specialty(resolved.oddel), resolved.oddel
    
    if not isinstance(kontekst, dict): return None, None  # Ako nema kontekst, vrati None
    
    oddel = _oddel_od_kontekst(kontekst)  # Zemi oddel od kontekst
    ids = kontekst.get("last_oddel_doctor_ids")  # Zemi lista na ID-a
    if isinstance(ids, list) and ids:  # Ako ima lista na ID-a
        id_set = {int(x) for x in ids}
        site = zimi_site_lekari()
        pool = [l for l in site if int(l["doctor_ID"]) in id_set]  # Filtriraj lekari
        if pool: return pool, oddel  # Vrati pool 
    if oddel:  # Ako ima oddel, vrati pool spored nego
        pool = zimi_lekari_po_specialty(oddel)
        if pool: return pool, oddel  
    return None, None  # Vrati default ako ne najde nisto

def najdi_lekari_slobodni_na(na_datum: date, vreme_str: str, lekari_pool: list[dict] | None = None) -> list[dict]:  # Najdi lekari koi se slobodni vo odredeno vreme
    """Лекари со слободен термин на даден датум и час (опционално само од pool)."""
    slobodni: list[dict] = []  # Inicijalizacija na lista za slobodni lekari
    for lekar in lekari_pool if lekari_pool is not None else zimi_site_lekari():  # Iteracija niz site ili filtrirani lekari
        if lekar_sloboden_na_termin(lekar, na_datum, vreme_str):  # Proverka dali doktorot e sloboden
            slobodni.append(lekar)  # Dodadi vo listata ako e sloboden
    return sorted(slobodni, key=lambda x: (x.get("surname") or "", x.get("name") or ""))  # Sortiraj po prezime i ime

def odgovor_slobodni_za_den_oddel(
    prasanje: str,
    na_datum: date,
    kontekst: dict | None,
) -> dict:
    """Слободни термини на датум за сите лекари од одделот (од контекст)."""
    pool, oddel = lekari_pool_za_ko_sloboden(prasanje, kontekst)
    # Zema pool na lekari za proverka
    if not pool and isinstance(kontekst, dict):
        ids = kontekst.get("last_oddel_doctor_ids") or []
        id_set = {int(x) for x in ids}
        pool = [l for l in zimi_site_lekari() if int(l["doctor_ID"]) in id_set]
        # Ako nema pool od gornata funkcija, proveri dali ima vo kontekstot

    den_ime = _IMENA_DEN[na_datum.weekday()].lower()
    datum_fmt = format_datum(na_datum)
    # Zema ime na denot i formatiran datum za prikaz

    # PROVERKA ZA VIKEND
    if na_datum.weekday() >= 5:
        naslov = (
            f"На {den_ime}, {datum_fmt} е викенд — прегледи се само во работни денови."
        )
        return {"odgovor": naslov, "kontekst": kontekst}
        # Na vikend nema termini, se vrakja poraka za toa

    # FORMIRANJE NA NASLOV
    if oddel:
        linii = [
            f"Слободни термини на {den_ime}, {datum_fmt} — оддел „{oddel}“:",
            "",
        ]
    else:
        linii = [f"Слободни термини на {den_ime}, {datum_fmt}:", ""]

    # PROVERKA DALI IMA LEKARI
    if not pool:
        linii.append("Немам зачувана листа лекари од претходната порака.")
        return {"odgovor": "\n".join(linii), "kontekst": kontekst}

    # PROVERKA NA SLOBODNI TERMINI ZA SEKOJ LEKAR
    prv_so_termini: dict | None = None
    for lekar in pool:
        slobodni = pronajdi_slobodni_termini(int(lekar["doctor_ID"]), na_datum=na_datum)
        # Za sekoj lekar se baraat slobodni termini
        ime = f"д-р {lekar.get('name', '')} {lekar.get('surname', '')}".strip()
        if slobodni:
            if prv_so_termini is None:
                prv_so_termini = lekar
                # Go zachuvuva prviot lekar so termini za kontekst
            casovi = [format_vreme(dt) for dt in slobodni[:12]]
            # Se zemaat prvite 12 termini za da ne bide predolgo
            extra = f" (+{len(slobodni) - 12} уште)" if len(slobodni) > 12 else ""
            linii.append(f"• {ime}: {', '.join(casovi)}{extra}")
        else:
            linii.append(f"• {ime}: нема слободни термини")

    # DODAVANJE NA UPATSTVO ZA ZAKAZUVANJE
    linii.extend(
        [
            "",
            "За закажување: „закажи кај [презиме] во [час]“ — датумот се зачувува.",
        ]
    )

    # AZURIRANJE NA KONTEKST
    ctx = dict(kontekst) if isinstance(kontekst, dict) else {}
    ctx["last_slobodni_datum"] = na_datum.strftime("%Y-%m-%d")
    if oddel:
        ctx["last_oddel"] = oddel
        ctx["last_oddel_doctor_ids"] = [int(l["doctor_ID"]) for l in pool]
    if prv_so_termini:
        ctx["last_doctor_id"] = int(prv_so_termini["doctor_ID"])
        ctx["zakazi_od_slobodni"] = {
            "doctor_id": int(prv_so_termini["doctor_ID"]),
            "datum": na_datum.strftime("%Y-%m-%d"),
        }
    return {"odgovor": "\n".join(linii), "kontekst": ctx}


def odgovor_ko_e_sloboden_na_termin(
    prasanje: str,
    na_datum: date,
    vreme_str: str,
    kontekst: dict | None = None,
) -> str:
    """Листа лекари слободни на конкретен датум и час."""
    den_ime = _IMENA_DEN[na_datum.weekday()].lower()
    datum_fmt = format_datum(na_datum)
    pool, oddel = lekari_pool_za_ko_sloboden(prasanje, kontekst)
    lekari = najdi_lekari_slobodni_na(na_datum, vreme_str, lekari_pool=pool)
    # Zema gi site slobodni lekari za toj datum i vreme

    # FORMIRANJE NA NASLOV I PRAZEN ODGOVOR
    if oddel:
        naslov_den = (
            f"На {den_ime}, {datum_fmt} во {vreme_str} "
            f'на одделот „{oddel}" слободни се:'
        )
        prazen_den = (
            f"На {den_ime}, {datum_fmt} во {vreme_str} "
            f'на одделот „{oddel}" нема слободен лекар.\n\n'
            f"Работно време: {format_vreme(RABOTNO_VREME_OD)}–"
            f"{format_vreme(RABOTNO_VREME_DO)}, понеделник–петок.\n\n"
            "Пробајте друг час, друг лекар од листата погоре, или "
            "„Кога е слободен д-р [презиме]?“."
        )
    else:
        naslov_den = f"На {den_ime}, {datum_fmt} во {vreme_str} слободни се:"
        prazen_den = (
            f"На {den_ime}, {datum_fmt} во {vreme_str} нема слободен лекар за закажување.\n\n"
            f"Работно време: {format_vreme(RABOTNO_VREME_OD)}–"
            f"{format_vreme(RABOTNO_VREME_DO)}, понеделник–петок.\n\n"
            "Пробајте друг час или „Кога е слободен д-р [презиме]?“ за конкретен лекар."
        )

    # AKO NEMA SLOBODNI LEKARI
    if not lekari:
        return prazen_den

    # FORMIRANJE NA LISTA NA SLOBODNI LEKARI
    linii = [naslov_den, ""]
    for l in lekari:
        spec = (l.get("specialty") or "Општа пракса").strip()
        linii.append(f"- Д-р {l['name']} {l['surname']} ({spec})")

    # DODAVANJE NA UPATSTVO ZA ZAKAZUVANJE
    if oddel:
        zakazi_hint = (
            f"За закажување на {datum_fmt} во {vreme_str} напишете, на пр.:\n"
            f"„закажи кај {lekari[0]['surname']}“ или „може да ми закажете кај "
            f"{lekari[0]['surname']}“.\n"
            "(Датумот и часот од погоре се зачувуваат автоматски.)"
        )
    else:
        zakazi_hint = (
            "За закажување наведете лекар, на пр.: „закажи кај "
            f"{lekari[0]['surname']} во {vreme_str}“."
        )
    linii.extend(["", zakazi_hint])
    return "\n".join(linii)


def izvleci_datum_za_slobodni(
    prasanje: str, kontekst: dict | None = None
) -> date | None:
    """Датум: правила → контекст → AI."""
    baran_datum = datum_od_prasanje_lokalno(prasanje)
    if baran_datum is not None:
        return baran_datum
    # Lokalnoto parsiranje e najbrzo i ne bara mrezha
    if prasanje_bar_datum_od_kontekst(prasanje):
        return datum_od_zakazi_kontekst(kontekst)
    # Ako korisnikot kaze "izbraniot datum", zemi go od kontekstot
    return _datum_od_prasanje_so_ai(prasanje)
    # AI e posledna opcija koga lokalnoto ne uspea


def formatiraj_odgovor_preku_ai(
    lekar: dict,
    slobodni: list[datetime],
    na_datum: date | None,
    prasanje: str,
) -> str:
    """Форматиран одговор од база (групирани периоди, без Groq)."""
    return formatiraj_odgovor(lekar, slobodni, na_datum=na_datum)
    # Wrapper - delegira na lokalniot formator (Groq mozhe vo idnina)


# gi zemame site lekari od the database
def zimi_site_lekari() -> list[dict[str, Any]]:
    try:
        with db_cursor() as (_, cur):
            # db_cursor() e kontekst menadzer - avtomatski zatvara
            cur.execute(
                """
                SELECT doctor_ID, name, surname, specialty, email
                FROM Doctors
                ORDER BY surname, name
                """
            )
            # ORDER BY surname, name - sortira po prezime, pa po ime
            return fetch_all(cur)
    except Exception as e:
        print(f"[slobodni_termini] Greshka pri zimanje na lekari: {e}")
        # Ako bazata ne e dostapna, se pecati greshka i se vrakja prazna lista
        return []
#funkcija koja so pomos na ai gi zima lekarite
# koristam Groq AI i on g gleda lekarite od bazata
def najdi_lekar_so_ai(prasanje: str) -> dict | None:
    from ai._kernel.groq_helpers import groq_zadolzhitelen
    # groq_zadolzhitelen proveruva dali AI e zadolzhitelno (na pr. za testiranje)

    if groq_zadolzhitelen():
        return None
    # Ako AI e zadolzhitelno, ne prodolzhuvaj (se koristi drug nachin)

    site_lekari = zimi_site_lekari()
    if not site_lekari:
        return None
    # Ako nema lekari vo bazata, nema shto da se bara

    # FORMIRANJE NA LISTA NA LEKARI ZA AI
    lista_text = ""
    for lekar in site_lekari:
        spec = lekar.get("specialty") or "Општа пракса"
        lista_text += f"ID {lekar['doctor_ID']}: Д-р {lekar['name']} {lekar['surname']} - {spec}\n"
    # Ja kreira listata na lekari kako tekst za AI da ja razbere

    # KREIRANJE NA PROMPT ZA AI
    full_prompt = f""" Листа на лекари во болницата:{lista_text} Прашање од корисникот: „{prasanje}" За кој лекар се однесува прашањето (слободни термини, закажување, преглед кај лекар)?
Име може да биде нецелосно или на латиница. Ако се спомнуваат повеќе лекари, земи го најрелевантниот.
Врати само ID број или NONE.""".strip() # Promptot mu dava kontekst na AI i kazhuva shto da vrati

    # POVIK NA AI
    odgovor = ask_ai(full_prompt, system_prompt=LEKAR_EXTRACT_PROMPT)
    # LEKAR_EXTRACT_PROMPT e sistemski prompt koj go postavuva AI

    # PARSIRANJE NA ODGOVOR
    odgovor_cist = odgovor.strip().upper().replace(".", "").replace(",", "")
    # Cistenje na odgovorot - otstranuvanje na tochki, zapirki, golemi bukvi

    if "NONE" in odgovor_cist:
        return None
    # NONE znachi deka AI ne prepozna lekar

    # IZVLEKUVANJE NA BROJ OD ODGOVOR
    match = re.search(r"\d+", odgovor_cist)
    if not match:
        return None
    # Ako nema broj, ne moze da se najde lekar

    doctor_id = int(match.group())
    # Go pretvara string broj vo int

    # NAOGJANJE NA LEKAROT VO LISTATA
    for lekar in site_lekari:
        if lekar["doctor_ID"] == doctor_id:
            return lekar
    # Prebaruva vo lokalnata lista za da go najde lekarot so toj ID

    return None


def lekar_od_oddel_kontekst(kontekst: dict | None) -> dict | None:
    """Единствен лекар од претходна листа по оддел (last_oddel_doctor_ids)."""
    if not isinstance(kontekst, dict):
        return None
    # Kontekstot mora da e dictionary
    ids = kontekst.get("last_oddel_doctor_ids")
    if not isinstance(ids, list) or len(ids) != 1:
        return None
    # Mora da ima tocno eden ID za da e edinstven lekar
    try:
        did = int(ids[0])
    except (TypeError, ValueError):
        return None
    # Ako ID-to ne e validen broj, vrati None
    for lekar in zimi_site_lekari():
        if int(lekar["doctor_ID"]) == did:
            return lekar
    return None


def lekar_iz_izbran_kontekst(kontekst: dict | None) -> dict | None:
    """Лекар од претходна порака: закажи/слободни, единствен од оддел, last_doctor_id."""
    lekar = lekar_od_zakazi_kontekst(kontekst)
    if lekar:
        return lekar
    # Prvo probaj od zakazuvanje kontekstot
    return lekar_od_oddel_kontekst(kontekst)
    # Ako nema vo zakazuvanje, probaj od oddel


def _poraka_izberi_lekar_od_lista(kontekst: dict) -> str:
    """Помошна порака кога има повеќе лекари од претходна листа по оддел."""
    ids = kontekst.get("last_oddel_doctor_ids")
    if not isinstance(ids, list) or len(ids) < 2:
        return ""
    # Mora da ima barem 2 lekari za da ima izbor
    id_set: set[int] = set()
    for raw in ids:
        try:
            id_set.add(int(raw))
        except (TypeError, ValueError):
            continue
    # Set() za unikatni ID-a, try/except za greshni vrednosti

    iminja: list[str] = []
    for lekar in zimi_site_lekari():
        if int(lekar["doctor_ID"]) in id_set:
            ime = (lekar.get("name") or "").strip()
            prezime = (lekar.get("surname") or "").strip()
            if ime or prezime:
                iminja.append(f"д-р {ime} {prezime}".strip())
    # Go kreira spisokot na iminja na lekarite

    if not iminja:
        return ""

    lista = ", ".join(iminja[:8])
    # Se zemaat prvite 8 iminja za da ne bide predolgo
    oddel = (kontekst.get("last_oddel") or "").strip()
    uvod = f"На одделот {oddel} " if oddel else "Од претходната листа "
    return (
        f"{uvod}има повеќе лекари ({lista}).\n\n"
        "Наведете го лекарот по име (на пр. „Кога е слободен д-р Марко Петров?“) "
        "или прашајте „кој од нив е слободен утре?“."
    )


def prasanje_e_slobodni_po_oddel_datum(
    prasanje: str, kontekst: dict | None = None
) -> bool:
    """
    „Слободни термини на 25 мај" по листа лекари од оддел — без име на лекар.
  """
    if not _ima_oddel_lekari_kontekst(kontekst):
        return False
    # Mora da ima kontekst so lekari od oddel
    if baranje_e_zakazuvanje(prasanje):
        return False
    # Ako e zakazuvanje, ne e proverka na slobodni
    if not prasanje_e_baranje_slobodni(prasanje):
        return False
    # Mora da se baraat slobodni termini
    if not datum_od_prasanje_lokalno(prasanje):
        return False
    # Mora da ima datum
    if vreme_od_prasanje_lokalno(prasanje):
        return False
    # Ako ima vreme, toa e drug tip na prasanje ("koj e sloboden vo 10:00")
    from ai._kernel.lekar_lookup import najdi_lekar_od_prasanje

    if najdi_lekar_od_prasanje(prasanje):
        return False
    # Ako e najden konkreten lekar, ne e za oddel
    ids = kontekst.get("last_oddel_doctor_ids") if isinstance(kontekst, dict) else []
    return isinstance(ids, list) and len(ids) > 1
    # Mora da ima poveke od 1 lekar za da e "oddel" prasanje


def lekar_od_zakazi_kontekst(kontekst: dict | None) -> dict | None:
    """Лекар од конверзација (листа слободни термини или недовршено закажување)."""
    if not kontekst:
        return None
    doctor_id = None
    zos = kontekst.get("zakazi_od_slobodni")
    if not isinstance(zos, dict):
        zos = kontekst.get("zakazi_pending")
    # Proveruva dva mozhni kluca kade mozhe da e zacuvan lekarot
    if isinstance(zos, dict):
        doctor_id = normalize_int(zos.get("doctor_id"))
    # normalize_int go pretvara vo int bez greshka
    if doctor_id is None:
        doctor_id = normalize_int(kontekst.get("last_doctor_id"))
    # Ako nema vo zakazuvanje, probaj vo last_doctor_id
    if doctor_id is None:
        return None
    for lekar in zimi_site_lekari():
        if int(lekar["doctor_ID"]) == doctor_id:
            return lekar
    return None


def generiraj_slotovi_za_den(datum: date) -> list[datetime]:
    """
    Генерира сите можни слотови за еден ден (08:00, 08:30, ... 15:30).
    Прескокнува сабота и недела.
    """
    if datum.weekday() >= 5:  # 5=сабота, 6=недела
        return []
    # Vikendi nemaat termini

    slotovi = []
    momentalno = datetime.combine(datum, RABOTNO_VREME_OD)
    kraj = datetime.combine(datum, RABOTNO_VREME_DO)
    # combine() pravi datetime od date i time

    while momentalno < kraj:
        slotovi.append(momentalno)
        momentalno += timedelta(minutes=TRAENJE_TERMIN_MINUTI)
        # TRAENJE_TERMIN_MINUTI e konstanta (obichno 30 min)

    return slotovi


def najdi_zafateni_slotovi(doctor_id: int, od_datum: date, do_datum: date) -> set:
    """
    Враќа множество (set) со зафатени слотови за лекар во даден интервал.
    Клучевите се (date, time) со минути без секунди.

    ВАЖНО: DATE/TIME од конекторот доаѓаат како date, datetime, str, timedelta, bytes...
    Затоа во SQL ги нормализираме во низа 'YYYY-MM-DD' и 'HH:MM' за сигурно парсирање.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        # dictionary=True - rezultatite kako rechnik {ime_kolona: vrednost}
        cur.execute(
            """
            SELECT
                DATE(datum_pregled) AS dp,
                TIME_FORMAT(TIME(vreme_pregled), '%H:%i') AS vp
            FROM Termin_pregled
            WHERE doctor_ID = %s
              AND DATE(datum_pregled) BETWEEN %s AND %s
              AND status_pregled NOT IN ('откажан', 'отказан')
            """,
            (doctor_id, od_datum, do_datum),
        )
        # TIME_FORMAT(..., '%H:%i') ja vrakja kako string vo formatot HH:MM
        # NOT IN ('откажан', 'отказан') - otkazhanite termini se slobodni
        rezultati = cur.fetchall()
        cur.close()

        # PARSIRANJE NA REZULTATI
        zafateni: set[tuple[date, time]] = set()
        for r in rezultati:
            d_raw = r.get("dp")
            t_raw = r.get("vp")

            if d_raw is None or t_raw is None:
                continue
            # Ako nema datum ili vreme, prekokni gi

            # PARSIRANJE NA DATUM
            if isinstance(d_raw, datetime):
                datum = d_raw.date()
            elif isinstance(d_raw, date):
                datum = d_raw
            elif isinstance(d_raw, (bytes, bytearray)):
                try:
                    datum = datetime.strptime(d_raw.decode("utf-8", errors="ignore")[:10], "%Y-%m-%d").date()
                except ValueError:
                    continue
                # Bytes se dekodiraat i parsiraat
            elif isinstance(d_raw, str):
                try:
                    datum = datetime.strptime(d_raw.strip()[:10], "%Y-%m-%d").date()
                except ValueError:
                    continue
                # String se parsira so strptime
            else:
                continue

            # PARSIRANJE NA VREME
            vreme: time | None = None
            if isinstance(t_raw, time):
                vreme = time(t_raw.hour, t_raw.minute)
                # Bez sekundi - tochno sporeduvanje so slotovite
            elif isinstance(t_raw, timedelta):
                vkupno = int(t_raw.total_seconds())
                vreme = time((vkupno // 3600) % 24, (vkupno % 3600) // 60)
                # MySQL TIME mozhe da dojde kako timedelta - pretvori go vo HH:MM
            elif isinstance(t_raw, (bytes, bytearray)):
                t_raw = t_raw.decode("utf-8", errors="ignore").strip()

            if vreme is None:
                if isinstance(t_raw, str):
                    parts = t_raw.replace(".", ":").split(":")
                    # Zameni tochki so dvotochki za da raboti i so "8.30"
                    try:
                        h, m = int(parts[0]), int(parts[1])
                        vreme = time(h, m)
                    except (ValueError, IndexError):
                        continue
                else:
                    continue

            zafateni.add((datum, vreme))
            # Tuple (datum, vreme) - unikaten kluc vo set

        return zafateni

    except Exception as e:
        print(f"[slobodni_termini] Greshka pri barebje zafateni: {e}")
        return set()
        # Vrakja prazno mnozhestvo za da ne se rusi povikuvachot
    finally:
        if conn:
            conn.close()
        # Sekogash zatvori ja vrskata - dali ima greshka ili ne


def pronajdi_slobodni_termini(doctor_id: int, na_datum: date | None = None) -> list[datetime]:
    """
    Слободни слотови за лекар.
    - Ако na_datum е зададен: само за тој календарски ден (работен ден).
    - Инаку: првите MAX_TERMINI слотови во следните DENOVI_NAPRED дена од денес.
    """
    denes = date.today()
    if na_datum is not None and na_datum < denes:
        na_datum = None
    # Ako baranjot datum e vo minato, izbrishi go - barame od denes

    # SPECIFICEN DATUM
    if na_datum is not None:
        if na_datum.weekday() >= 5:
            return []
        # Vikend nema termini

        zafateni = najdi_zafateni_slotovi(doctor_id, na_datum, na_datum)
        # Zema zafateni samo za toj eden datum

        slobodni: list[datetime] = []
        for slot_datetime in generiraj_slotovi_za_den(na_datum):
            if slot_datetime < datetime.now():
                continue
            # Prekokni gi minatite slotovi vo denot (ako e denes)
            slot_vreme = slot_datetime.time()
            slot_vreme = time(slot_vreme.hour, slot_vreme.minute)
            # Normalizacija - bez sekundi za sporeduvanje so zafatenite
            if (na_datum, slot_vreme) not in zafateni:
                slobodni.append(slot_datetime)
        return slobodni

    # OPSEG OD DENESHEN DEN
    do_datum = denes + timedelta(days=DENOVI_NAPRED)
    zafateni = najdi_zafateni_slotovi(doctor_id, denes, do_datum)
    # Zema zafateni za celiot opseg odnaplad za efikasnost

    slobodni = []
    for offset in range(DENOVI_NAPRED + 1):
        datum = denes + timedelta(days=offset)
        slotovi_za_den = generiraj_slotovi_za_den(datum)
        # Za sekoj den generira slotovi (preskoknuvanje na vikend)

        for slot_datetime in slotovi_za_den:
            if slot_datetime < datetime.now():
                continue

            slot_vreme = slot_datetime.time()
            slot_vreme = time(slot_vreme.hour, slot_vreme.minute)
            if (datum, slot_vreme) not in zafateni:
                slobodni.append(slot_datetime)

                if len(slobodni) >= MAX_TERMINI:
                    return slobodni
                # Ranо izleguvanje - ne treba da gi proveruvame site denovi

    return slobodni


def _footer_za_zakazuvanje(eden_datum: bool) -> str:
    """Кратко упатство по листа на слободни термини."""
    if eden_datum:
        return (
            "\n\nКажете ми кој од овие термини најмногу ви одговара "
            '(на пример: „Закажи во 09:30").\n'
            "За друг работен ден — наведете нова дата."
        )
        # Ako se vrakja eden datum - poednostavno upatstvo
    return (
        '\n\nКажете ми датум, час и лекар (на пример: „Закажи кај Петров во 10:00").'
    )
    # Generalno upatstvo koga ima poveke denovi


def _cas_vo_minuti(cas_str: str) -> int:
    h, m = map(int, cas_str.split(":"))
    # split(":") razdeluva "09:30" -> ["09", "30"], map(int, ...) gi pravi broj
    return h * 60 + m
    # Vrakja vkupno minuti od pocetokot na denot za polesno sporeduvanje


def _kluc_period_za_cas(cas_str: str) -> str:
    """Групирање на слотови: рано наутро / околу пладне / попладне."""
    mins = _cas_vo_minuti(cas_str)
    if mins < 10 * 60:
        return "ran_nautro"
        # Pred 10:00 e ran nautro
    if mins < 14 * 60:
        return "okolu_pladne"
        # Megju 10:00 i 14:00 e okolu pladne
    return "popladne"
    # Po 14:00 e popladne


_PERIOD_NASLOVI: dict[str, str] = {
    "ran_nautro": "Ран наутро",
    "okolu_pladne": "Околу пладне",
    "popladne": "Попладне",
}
_PERIOD_REDO = ("ran_nautro", "okolu_pladne", "popladne")


def _opis_raspon_termini(casovi: list[str]) -> str:
    """Краток опис кога се слотовите (претпладне, попладне, …)."""
    if not casovi:
        return ""
    mins = [_cas_vo_minuti(c) for c in casovi]
    # Pretvora gi site casovi vo minuti za sporeduvanje
    min_m, max_m = min(mins), max(mins)
    # Najraniot i najdocniot moment od slobodnite slotovi
    if max_m <= 12 * 60 + 30:
        return "во текот на целото претпладне"
        # Ako sé e do 12:30 - pretpladne
    if min_m >= 14 * 60:
        return "попладне"
        # Ako pochnuva po 14:00 - popladne
    if min_m < 10 * 60 and max_m >= 14 * 60:
        return "низ целиот работен ден"
        # Od rano nautro do popladne - cel den
    if min_m >= 10 * 60 and max_m < 14 * 60:
        return "претпладне"
        # Megju 10:00 i 14:00 - pretpladne
    return "во текот на работниот ден"
    # Po default - vo tekot na rabotniot den


def _formatiraj_casovi_po_periodi(casovi: list[str]) -> list[str]:
    """Редови „Ран наутро: 08:30 | 09:00“."""
    po_period: dict[str, list[str]] = {}
    for cas in casovi:
        po_period.setdefault(_kluc_period_za_cas(cas), []).append(cas)
        # setdefault - ako kluchot ne postoi, kreiraj prazna lista, pa dodadi cas
    redici: list[str] = []
    for kluc in _PERIOD_REDO:
        if kluc in po_period:
            if redici:
                redici.append("")
                # Prazen red megju periodite za citlivost
            redici.append(
                f"{_PERIOD_NASLOVI[kluc]}: {' | '.join(po_period[kluc])}"
            )
            # Spojeni so " | " za prikaz: "Ран наутро: 08:30 | 09:00"
    return redici


def _formatiraj_den_lekar(
    lekar: dict,
    casovi: list[str],
    datum: date,
    weekday: int,
    denovi: list[str],
) -> str:
    """Еден ден: вовед + групирани часови."""
    den_ime = denovi[weekday].lower()
    datum_fmt = format_datum(datum)
    ime_lekar = f"{lekar['name']} {lekar['surname']}"
    specialnost = lekar.get("specialty") or "Општа пракса"
    # Fallback na "Општа пракса" ako lekarot nema specialnost
    raspon = _opis_raspon_termini(casovi)
    # Kratok opis kako su rasporedeni slotovite vo denot
    delovi = [
        (
            f"За {den_ime} ({datum_fmt}), кај д-р {ime_lekar} ({specialnost}) "
            f"има слободни термини {raspon}:"
        ),
        "",
        *_formatiraj_casovi_po_periodi(casovi),
        # * unpack-ot na listata za da gi dodade kako poodelni elementi
    ]
    return "\n".join(delovi)


def formatiraj_odgovor(
    lekar: dict,
    slobodni: list[datetime],
    na_datum: date | None = None,
) -> str:
    """
    Формира порака на македонски, групирано по ден.
    За еден датум: компактна листа на часови + кратко упатство за закажување.
    """
    DENOVI = [
        "Понеделник", "Вторник", "Среда", "Четврток",
        "Петок", "Сабота", "Недела",
    ]
    # Lista na imiata na denovite po reden broj (weekday: 0=Pon, 6=Ned)

    ime_lekar = f"д-р {lekar['name']} {lekar['surname']}"
    specialnost = lekar.get("specialty") or "Општа пракса"
    zaglavie_lekar = f"{ime_lekar} ({specialnost})"
    # Zaglavieto se koristi vo poveke ramnishta

    # SLUCAJ: NEMA SLOBODNI TERMINI
    if not slobodni:
        if na_datum is not None and na_datum.weekday() >= 5:
            return (
                f"Кај {zaglavie_lekar}, {format_datum(na_datum)} е викенд — "
                "прегледи се само во работни денови.\n\n"
                "Наведете работен ден (на пр. „следниот понеделник“) или прашајте без датум."
            )
            # Eksplicitna poraka za vikend
        if na_datum is not None:
            den = DENOVI[na_datum.weekday()].lower()
            return (
                f"За {den} ({format_datum(na_datum)}), кај {zaglavie_lekar} "
                "нема слободни термини.\n\n"
                "Наведете друга дата за нова проверка или прашајте без конкретен датум."
            )
            # Specifichen datum bez slobodni
        return (
            f"Кај {zaglavie_lekar} за избраниот период нема слободни термини.\n\n"
            "Пробајте друг ден или друг лекар, или наведете конкретен датум и време."
        )
        # Opshta poraka koga nema datum naveden

    # GRUPIRANJE PO DEN
    po_den: dict[tuple[date, int], list[str]] = {}
    for dt in slobodni:
        kluc = (dt.date(), dt.weekday())
        po_den.setdefault(kluc, []).append(format_vreme(dt))
        # Kluchot e (datum, weekday) - grupira slotovi vo eden den

    eden_den = len(po_den) == 1
    # Razlikuva eden vs poveke denovi za razlichni formati

    # FORMATIRANJE ZA EDEN DEN
    if eden_den:
        (datum, weekday), casovi = next(iter(po_den.items()))
        # Prva (i edinstvena) stavka od recnikot
        return (
            _formatiraj_den_lekar(lekar, casovi, datum, weekday, DENOVI)
            + _footer_za_zakazuvanje(eden_datum=True)
        )

    # FORMATIRANJE ZA POVEKE DENOVI
    delovi: list[str] = []
    for (datum, weekday), casovi in po_den.items():
        if delovi:
            delovi.append("")
            # Prazen red megju denovite
        delovi.append(_formatiraj_den_lekar(lekar, casovi, datum, weekday, DENOVI))
    delovi.append(_footer_za_zakazuvanje(eden_datum=False))
    return "\n".join(delovi)


def odgovori_za_slobodni_termini(
    prasanje: str, kontekst: dict | None = None
) -> str | dict:
    """
    Главна точка - повикана од router-от.

    Параметри:
        prasanje - целото прашање од корисникот (AI сам ќе извлече кој лекар)
        kontekst  - опционално: лекар од претходна порака (zakazi_od_slobodni)

    Враќа: текст или dict со „odgovor“ и „kontekst“ (за продолжување на закажување без повторно име).
    """
    # SLUCAJ 1: "SLEDEN RABOTEN DEN"
    if prasanje_e_sleden_raboten_den(prasanje):
        sleden = sleden_raboten_datum()
        # Presmetuva sleden raboten den (preskoknuvanje na vikend)
        den_ime = _IMENA_DEN[sleden.weekday()]
        datum_fmt = format_datum(sleden)
        lekar, _, nejasno = resolviraj_lekar_za_slobodni(prasanje, kontekst)
        # Probaj da najdes lekar - po ime, kontekst ili AI
        if nejasno:
            return {"odgovor": nejasno, "kontekst": kontekst}
            # Ako e nejasno (povekje lekari), prashaj korisnik

        if lekar:
            slobodni = pronajdi_slobodni_termini(lekar["doctor_ID"], na_datum=sleden)
            text = formatiraj_odgovor_preku_ai(
                lekar, slobodni, sleden, prasanje
            )
            ctx = {
                "zakazi_od_slobodni": {
                    "doctor_id": int(lekar["doctor_ID"]),
                    "datum": datum_za_zakazi_kontekst(sleden, slobodni),
                },
                "last_doctor_id": int(lekar["doctor_ID"]),
            }
            # Zachuvuvanje na kontekstot za prodolzhuvanje na razgovorot
            return {"odgovor": text, "kontekst": ctx}

        # AKO NE E NAJDEN LEKAR
        return {
            "odgovor": (
                f"Следниот работен ден за закажување прегледи е {den_ime}, {datum_fmt}.\n\n"
                f"Термини се закажуваат од понеделник до петок, "
                f"{format_vreme(RABOTNO_VREME_OD)}–{format_vreme(RABOTNO_VREME_DO)}. "
                "Во сабота и недела не се закажуваат прегледи.\n\n"
                "Кажи кај кој лекар сакаш термин (на пр. „следен работен ден кај Петров“) "
                "или повтори го името на лекарот од претходното барање."
            ),
            "kontekst": kontekst,
        }

    # SLUCAJ 1b: само нов датум/ден — зачувано време и оддел од претходната порака
    if prasanje_e_utochnuvanje_datum(prasanje):
        baran_datum = izvleci_datum_za_slobodni(prasanje, kontekst)
        if baran_datum:
            zacuvano_vreme = vreme_iz_kontekst(kontekst)
            if zacuvano_vreme:
                pool, oddel = lekari_pool_za_ko_sloboden(prasanje, kontekst)
                tekst = odgovor_ko_e_sloboden_na_termin(
                    prasanje, baran_datum, zacuvano_vreme, kontekst
                )
                lekari = najdi_lekari_slobodni_na(
                    baran_datum, zacuvano_vreme, lekari_pool=pool
                )
                ctx = _azuriraj_kontekst_ko_sloboden(
                    kontekst, baran_datum, zacuvano_vreme, lekari, oddel, pool
                )
                return {"odgovor": tekst, "kontekst": ctx}
            if _ima_oddel_lekari_kontekst(kontekst) or _oddel_od_kontekst(kontekst):
                return odgovor_slobodni_za_den_oddel(prasanje, baran_datum, kontekst)

    # SLUCAJ 2: "KOJ E SLOBODEN VO X CHAS?"
    if prasanje_e_ko_e_sloboden_datum_vreme(prasanje, kontekst):
        baran_datum = izvleci_datum_za_slobodni(prasanje, kontekst)
        barano_vreme = vreme_od_prasanje_lokalno(prasanje) or vreme_iz_kontekst(kontekst)
        oddel_ctx = _oddel_od_kontekst(kontekst)
        # Trojkata e: datum, vreme, oddel - se proveruva po red

        # FALI DATUM
        if not baran_datum:
            primer = (
                f"„Кој од нив е слободен на 20.05 во 12:00“"
                if oddel_ctx
                else "„Кој е слободен во среда на 20.05 во 12:00“"
            )
            # Razlichen primer ako e vo kontekst oddel
            return {
                "odgovor": (
                    "За да проверам кој лекар е слободен, наведете датум и час.\n\n"
                    f"Пример: {primer}."
                ),
                "kontekst": kontekst,
            }

        # FALI VREME
        if not barano_vreme:
            if oddel_ctx and prasanje_e_baranje_slobodni(prasanje):
                return odgovor_slobodni_za_den_oddel(prasanje, baran_datum, kontekst)
                # Ako e samo "slobodni termini" za oddel - prikazi gi site lekari
            primer = (
                "„Кој од нив е слободен во 12:00“"
                if oddel_ctx
                else f"„Кој е слободен на {format_datum(baran_datum)} во 12:00“"
            )
            return {
                "odgovor": (
                    f"За {format_datum(baran_datum)} наведете и час.\n\n"
                    f"Пример: {primer}."
                ),
                "kontekst": kontekst,
            }

        # IMA DATUM I VREME
        pool, oddel = lekari_pool_za_ko_sloboden(prasanje, kontekst)
        tekst = odgovor_ko_e_sloboden_na_termin(
            prasanje, baran_datum, barano_vreme, kontekst
        )
        lekari = najdi_lekari_slobodni_na(baran_datum, barano_vreme, lekari_pool=pool)
        ctx = _azuriraj_kontekst_ko_sloboden(
            kontekst, baran_datum, barano_vreme, lekari, oddel, pool
        )
        return {"odgovor": tekst, "kontekst": ctx}

    # SLUCAJ 3: "SLOBODNI NA DATUM" PO ODDEL (BEZ KONKRETEN LEKAR)
    if prasanje_e_slobodni_po_oddel_datum(prasanje, kontekst):
        baran_datum = izvleci_datum_za_slobodni(prasanje, kontekst)
        if baran_datum:
            return odgovor_slobodni_za_den_oddel(prasanje, baran_datum, kontekst)

    # SLUCAJ 4: STANDARDEN TEK - SLOBODNI ZA KONKRETEN LEKAR
    lekar, od_kontekst, nejasno = resolviraj_lekar_za_slobodni(prasanje, kontekst)
    # Probaj sé - ime od prasanjeto, kontekst, AI
    if nejasno:
        return {"odgovor": nejasno, "kontekst": kontekst}
        # Disambiguacija - prashaj korisnik koj lekar misli

    # AKO NE E NAJDEN LEKAR
    if not lekar:
        if prasanje_bar_lekar_od_kontekst(prasanje):
            return {
                "odgovor": (
                    "Не гледам зачуван избран лекар од претходната порака во разговорот.\n\n"
                    "Прво наведете го лекарот (на пр. „Кога е слободен д-р Петров?“) "
                    "или изберете термин од листата со слободни часови, па повторете со "
                    "„кога е слободен избраниот лекар?“."
                ),
                "kontekst": kontekst,
            }
            # Korisnikot prashuva za "izbraniot lekar" no nema vo kontekst
        return (
            "Го разбирам барањето како прашање за слободни термини кај лекар, "
            "но не успеав да препознаам точно за кој лекар се работи.\n\n"
            "Напиши го името и презимето на лекарот како што стои во нашата листа "
            '(на пример: „Кога е слободен д-р Марко Петров?" или „има ли термин кај Петров?").\n\n'
            'Ако лекарот не работи кај нас, ќе треба да одбереш друг од секцијата „Лекари" на сајтот.'
        )
        # Opshta poraka koga voopshto ne mozhe da se identifikuva lekar

    # NORMALNO BARANJE - IMA LEKAR
    baran_datum = izvleci_datum_za_slobodni(prasanje, kontekst)
    slobodni = pronajdi_slobodni_termini(lekar["doctor_ID"], na_datum=baran_datum)
    # na_datum mozhe da bide None - togash vrakja prvite MAX_TERMINI
    text = formatiraj_odgovor_preku_ai(lekar, slobodni, baran_datum, prasanje)

    # ZACHUVUVANJE NA KONTEKST
    did = int(lekar["doctor_ID"])
    ctx = dict(kontekst) if isinstance(kontekst, dict) else {}
    ctx["zakazi_od_slobodni"] = {
        "doctor_id": did,
        "datum": datum_za_zakazi_kontekst(baran_datum, slobodni),
    }
    # zakazi_od_slobodni - kluc za prodolzhuvanje so "zakazhi vo X"
    ctx["last_doctor_id"] = did
    return {"odgovor": text, "kontekst": ctx}
