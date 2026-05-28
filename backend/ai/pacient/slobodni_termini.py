"""
slobodni_termini.py — AI handler za „slobodni termini kaj lekar".

Korisnikot prashuva „koga e sloboden d-r X?" / „koj e sloboden utre vo 10:00?"
→ generirame slotovi (08:00-15:30, 30 min, samo pon-pet), otfrlame zakazani
vo bazata (Termin_pregled), formatirame odgovor na makedonski.

Se koristi od: handlers.py, routers/ai_chat.py, intent_detector.py,
opsto/info_lekar.py, opsto/lekari_oddel.py, opsto/preference_lekar.py,
pacient/moi_pregledi.py, oceni_pregled.py, trgni_ocena.py.
"""
import re                                              # alatka za regex — barame sablon vo tekst
from datetime import date, time, datetime, timedelta   # za rabota so datumi, vremiwa i intervali
from typing import Any                                 # tip „bilo kakov" — koristen vo dict-ovi
from database import get_connection                    # otvora konekcija so MySQL bazata
from ai._kernel.db_helpers import db_cursor, fetch_all, normalize_int  # pomoshni alatki za DB
from ai._kernel.groq_client import ask_ai              # praka prompt do Groq AI, vraka tekst
from ai._kernel.prompts import LEKAR_EXTRACT_PROMPT    # sistemski prompt za izvlekuvanje na lekar
from ai._kernel.transliteracija import transliterijaj  # latinica → kirilica za poleсno prebaruvanje
from ai._kernel.utils import format_datum, format_vreme  # formatiranje datum/vreme za prikaz

# ─── Konstanti: raboten vreme + denovi ───
RABOTNO_VREME_OD = time(8, 0)          # klinikata otvora vo 08:00
RABOTNO_VREME_DO = time(16, 0)         # klinikata zatvora vo 16:00
TRAENJE_TERMIN_MINUTI = 30             # sekoj termin trae 30 min
DENOVI_NAPRED = 7                      # kolku denovi gledame napred (koga nema datum vo prashanjeto)
MAX_TERMINI = 8                        # makc. termini vo eden odgovor (za da ne se preplavi chatot)

# Mapa: ime na den → brojka (kako Python weekday: pon=0 ... ned=6)
_DEN_WD = {"понеделник": 0, "вторник": 1, "среда": 2, "четврток": 3,
           "петок": 4, "сабота": 5, "недела": 6}
# String „понеделник|вторник|…" — gotov za vmetnuvanje vo regex (sortirani po dolzhina za sigurno match-iranje)
_DEN_ALT = "|".join(sorted(_DEN_WD.keys(), key=len, reverse=True))
# Lista imenovi za prikaz (po redosled na weekday: pon=0 → "понеделник")
_IMENA_DEN = ["понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"]

# ─── Regex-i za datum/den/zakazhuvanje ───
# „Sleden raboten den" / „Naredniot raboten den" — razni varijanti
_RE_SLEDEN_RABOTEN_DEN = re.compile(
    r"(?:(?:следен|следниот|нареден|наредниот|прв)\s+работен\s+ден"
    r"|работен\s+ден\s+(?:следен|нареден|наредниот|следниот)"
    r"|кога\s+е\s+(?:следниот|наредниот|првиот)?\s*работен\s+ден)", re.UNICODE)
# „Sledniот вторник", „наредниот петок" — sleden konkreten den
_SLEDEN_DEN_RE = re.compile(
    rf"(?:следниот|наредниот|следен|нареден|за)(?:\s+во)?\s+({_DEN_ALT}|\w+)", re.IGNORECASE)
# „за во вторник" / „во среда" — den so prefiks „во"
_RE_ZA_VO_DEN = re.compile(r"(?:за\s+)?во\s+([a-zа-яѓќѕџјљњџ]{4,12})\s*$", re.IGNORECASE | re.UNICODE)
# „oваа среда" — den od tekovnata sedmica
_OVAA_DEN_RE = re.compile(rf"(?:оваа|овиот|овој)\s+({_DEN_ALT})", re.IGNORECASE)
# „слободен понеделник" / „термин вторник" — kontekstualen den (so kluchen zbor pred imeto)
_KONTEXT_I_DEN_RE = re.compile(
    rf"(?:(?:слободен|слободна|слободни|слободно)\w*\s+(?:за\s+)?(?:во\s+)?"
    rf"|(?:термин(?:и)?)\s+(?:за\s+)?(?:во\s+)?"
    rf"|(?:има\s+ли)\s+(?:нешто\s+)?(?:слободни\s+)?(?:за\s+)?(?:во\s+)?"
    rf"|(?:дали\s+има)\s+(?:нешто\s+)?(?:слободни\s+)?(?:за\s+)?(?:во\s+)?)"
    rf"({_DEN_ALT}|\w{{4,12}})\b", re.IGNORECASE)
# Datum so brojki: „на 20.05" / „за 25/06/2026"
_DATUM_BROJ_RE = re.compile(r"(?:на|за)\s+(\d{1,2})[\./\-](\d{1,2})(?:[\./\-](\d{2,4}))?", re.IGNORECASE)
# ISO datum: „2026-05-20"
_ISO_DATUM_RE = re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b")
# Mapa: ime na mesec (kir/lat) → broj (1-12)
_MESECI_BROJ: dict[str, int] = {
    "јануари": 1, "januari": 1, "февруари": 2, "fevruari": 2, "март": 3, "mart": 3,
    "април": 4, "april": 4, "мај": 5, "maj": 5, "јуни": 6, "juni": 6,
    "јули": 7, "juli": 7, "август": 8, "avgust": 8, "септември": 9, "septemvri": 9,
    "октомври": 10, "oktomvri": 10, "ноември": 11, "декември": 12}
# Suffiks za redniот broj („20-ти", „1ви") — opcionalen
_ORDINAL_SUF = r"(?:ти|ри|ви|ti|ri|vi|-ti|-ri|-vi)?"
# Datum so ime na mesec: „на 20-ти мај"
_RE_DAN_MES = re.compile(
    r"(?:на\s+)?(\d{1,2})" + _ORDINAL_SUF + r"\s*(?:\.)?\s*("
    + "|".join(sorted(_MESECI_BROJ.keys(), key=len, reverse=True)) + r")\b",
    re.UNICODE | re.IGNORECASE)
# „Кој/Која/Кои" — prashanje za lekar (bez konkretno ime)
_KO_PRASANJE_RE = re.compile(r"\b(кој|која|кои|koj|koja|koi)\b", re.UNICODE | re.IGNORECASE)
# „закажи" / „може да ми закажете" — namera za zakazhuvanje
_RE_ZAKAZUVANJE = re.compile(
    r"(?:зака[жз]\w*|zakaz\w*|може\s+да\s+(?:ми\s+)?зака[жз]|moze\s+da\s+(?:mi\s+)?zakaz"
    r"|можете\s+да\s+(?:ми\s+)?зака[жз]|да\s+ми\s+зака[жз]|da\s+mi\s+zakaz"
    r"|запиш\w*|zapish\w*|сакам\s+(?:да\s+)?(?:зака[жз]|оди|преглед)"
    r"|може\s+ли\s+зака[жз])", re.UNICODE | re.IGNORECASE)
# Markeri „od niv / od ovie / od lekarite" — produzhuvanje po lista po oddel
_OD_NIV_SLOBODNI_MARKERS = (
    "од нив", "од овие", "од лекарите", "од горе", "од погоре", "од листата",
    "од тој оддел", "од одделот", "кој од нив", "кои од нив",
    "кој од лекарите", "кои од лекарите",
    "od niv", "od ovie", "od lekarite", "koj od niv", "koi od niv")

# ─── Gotovi error/info poraki (konstanti za pokratok kod) ───
_MSG_FALI_DATUM_VREME = ("За да проверам кој лекар е слободен, наведете датум и час.\n\nПример: {primer}.")  # primer e placeholder
_MSG_FALI_VREME = "За {datum} наведете и час.\n\nПример: {primer}."   # datum + primer placeholder-i
_MSG_NEMA_IZBRAN_LEKAR_KONTEKST = (
    "Не гледам зачуван избран лекар од претходната порака во разговорот.\n\n"
    "Прво наведете го лекарот (на пр. „Кога е слободен д-р Петров?\") "
    "или изберете термин од листата со слободни часови, па повторете со "
    "„кога е слободен избраниот лекар?\".")
_MSG_NE_RAZBRAV_LEKAR = (
    "Го разбирам барањето како прашање за слободни термини кај лекар, "
    "но не успеав да препознаам точно за кој лекар се работи.\n\n"
    "Напиши го името и презимето на лекарот како што стои во нашата листа "
    "(на пример: „Кога е слободен д-р Марко Петров?\" или „има ли термин кај Петров?\").\n\n"
    "Ако лекарот не работи кај нас, ќе треба да одбереш друг од секцијата „Лекари\" на сајтот.")


# ─── Parsiranje den/datum/cas (lokalno, bez AI) ───
# Funkcija sho od tekst vraka ime na den (npr. „понеделник") ili None
def _den_od_tekst(tekst: str) -> str | None:
    """Od tekst vraka ime na den („понеделник", …) ili None."""
    t = transliterijaj(tekst or "").lower().strip()    # latinica → kirilica + mali bukvi
    if not t: return None                              # prazno → ne e validno
    if t in _DEN_WD: return t                          # tochno se sovpaga so ime na den
    # Alijasi (latinica varijanti) — mapa kon kirilica
    alias = {"ponedel": "понеделник", "ponedelnik": "понеделник",
             "vtorni": "вторник", "vtornik": "вторник", "vtorik": "вторник",
             "sreda": "среда", "chetvrtok": "четврток",
             "petok": "петок", "sabota": "сабота", "nedela": "недела"}
    if t in alias: return alias[t]                     # ima alijas → vrati go pravilnoto ime
    for ime in _DEN_WD:   # delumno sovpaganje (min. 4 bukvi)
        if len(t) >= 4 and (ime.startswith(t) or t.startswith(ime[:4])): return ime
    return None                                        # ne e den


# Funkcija sho od regex match objekt vraka ime na den
def _den_od_match(m: re.Match) -> str | None:
    """Od regex match → ime na den."""
    return _den_od_tekst(m.group(1) or "")             # zema prvata grupa od match-ot


# Funkcija sho proveruva dali na kraj od prashanjeto stoi ime na den
def _den_na_kraj_od_prasanje(p: str) -> str | None:
    """Den na kraj od prashanjeto („… Захариев понеделник?"), samo so kontekst pred nego."""
    p2 = p.strip().rstrip("?!. ")                      # iscisti gi punktuaciite na kraj
    # Regex za klucni zborovi pred imeto na den (kontekst sho potvrduva deka e za den)
    kontekst_re = re.compile(
        r"\b(кога|слободен|слободна|слободни|слободно|термин|има\s+ли|"
        r"нареден|наредниот|наредна|следен|следниот|следна)\b", re.IGNORECASE)
    # Sortirani po dolzhina, dolgite prvi — za da ne uchhe „петок" pred „четврток"
    for ime in sorted(_DEN_WD.keys(), key=len, reverse=True):
        if not p2.endswith(ime): continue              # ne zavrshuva so ova ime → preskoki
        # Pred imeto mora da ima kluchen zbor (za izbegne lazni positives)
        if kontekst_re.search(p2[: len(p2) - len(ime)]): return ime
    return None                                        # ne najdovme


# Funkcija sho vraka prv RABOTEN den (pon-pet) posle denes
def sleden_raboten_datum(denes: date | None = None) -> date:
    """Prv raboten den (pon–pet) posle denes."""
    denes = denes or date.today()                      # ako ne e dadeno → koristi denesh
    d = denes + timedelta(days=1)                      # pochni od utre
    while d.weekday() >= 5: d += timedelta(days=1)     # preskoki sabota (5) / nedela (6)
    return d                                           # prv raboten den


# Funkcija sho najduva sleden kalendarski den so dadenoto ime (npr. „sledniот вторник")
def _sleden_takov_kalendarski_den(denes: date, ime_den: str) -> date:
    """Prv den so dadenoto ime posle denes („следниот вторник")."""
    days = (_DEN_WD[ime_den] - denes.weekday()) % 7    # kolku denovi do toj weekday (0-6)
    if days == 0: days = 7                             # denes e toj den → sledna nedela
    return denes + timedelta(days=days)                # vraka go datumot


# Funkcija sho najduva ime na den vo tekovnata nedela
def _ovaa_nedela_den(denes: date, ime_den: str) -> date:
    """Den od tekovnata nedela (ili sledna ako veke pomina)."""
    pocetok = denes - timedelta(days=denes.weekday())  # ponedelnik na ovaa nedela
    cand = pocetok + timedelta(days=_DEN_WD[ime_den])  # baranite den vo ovaa nedela
    if cand < denes: cand += timedelta(days=7)         # ako veke pomina → sledna nedela
    return cand


# Funkcija sho od tekst vraka broj na mesec (1-12)
def _mesec_od_tekst(tekst: str) -> int | None:
    """„мај"/„септември" → 1-12."""
    t = transliterijaj(tekst).lower().strip()          # normaliziraj
    if t in _MESECI_BROJ: return _MESECI_BROJ[t]       # tochno sovpaganje
    # Delumno sovpaganje po prvi 3 bukvi (za skratenicii)
    for k, v in _MESECI_BROJ.items():
        if t.startswith(k[:3]) or k.startswith(t[:3]): return v
    return None                                        # ne e mesec


# Funkcija sho parsi den+mesec+godina i vraka date objekt
def _parsiraj_dd_mm_gggg(denes: date, d: int, m: int, g: int | None) -> date | None:
    """date(year, month, day) ili None ako e nevaliden/minat."""
    god = g if g is not None else denes.year           # ako nema godina → tekovnata
    if god < 100: god += 2000                          # „26" → „2026" (2-cifрена godina)
    try: out = date(god, m, d)                         # probaj da napravish date
    except ValueError: return None                     # nevaliden datum (npr. 30 feb)
    if out < denes:                                    # ako e vo minatoto
        if g is None and m >= denes.month:             # ako nema godina i mesecot ne e pominat
            try: out = date(denes.year + 1, m, d)     # probaj sledna godina
            except ValueError: return None
        elif out < denes: return None                  # so godina i sepak minat → None
    return out


# Funkcija sho parsi „20 mai" / „на 1 јуни" → date
def _parsiraj_dan_mesec(p: str, denes: date) -> date | None:
    """„20 мај", „на 1 јуни" → date."""
    m = _RE_DAN_MES.search(p)                          # probaj go regex-ot
    if not m: return None                              # nema sovpaganje
    mesec = _mesec_od_tekst(m.group(2))                # vtorata grupa = ime na mesec
    if not mesec: return None                          # ne e validen mesec
    return _parsiraj_dd_mm_gggg(denes, int(m.group(1)), mesec, None)  # delegira na pomoshnata


# Funkcija sho prepoznava datum vo prashanjeto LOKALNO (bez AI, samo regex)
def datum_od_prasanje_lokalno(prasanje: str) -> date | None:
    """Lokalno (bez AI) preponanvanje datum vo prashanjeto."""
    p = transliterijaj(prasanje).lower()               # normaliziraj go tekstot
    denes = date.today()                               # referenten datum

    if _RE_SLEDEN_RABOTEN_DEN.search(p): return sleden_raboten_datum(denes)  # „sleden raboten den"
    if "задутре" in p or "задутра" in p: return denes + timedelta(days=2)  # 2 dena napred
    if re.search(r"\bутре\b", p): return denes + timedelta(days=1)         # utre (1 den napred)

    m = _ISO_DATUM_RE.search(prasanje)   # ISO: 2026-05-20
    if m:
        try:
            out = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))  # godina, mesec, den
            return out if out >= denes else None                            # ne vraka minatosti
        except ValueError: pass                                             # nevaliden datum → preskoki

    dm = _parsiraj_dan_mesec(p, denes)   # „20 мај"
    if dm is not None: return dm                       # uspeh

    m = _DATUM_BROJ_RE.search(p)   # „на 20.05" / „за 12/06/26"
    if m:
        g = int(m.group(3)) if m.group(3) else None    # godina (opcionalna)
        parsed = _parsiraj_dd_mm_gggg(denes, int(m.group(1)), int(m.group(2)), g)
        if parsed is not None: return parsed

    m = _OVAA_DEN_RE.search(p)   # „оваа среда"
    if m and (ime := _den_od_match(m)): return _ovaa_nedela_den(denes, ime)

    m = _SLEDEN_DEN_RE.search(p)   # „следниот вторник"
    if m and (ime := _den_od_match(m)): return _sleden_takov_kalendarski_den(denes, ime)

    m = _RE_ZA_VO_DEN.search(p)   # „за во вторник"
    if m and (ime := _den_od_tekst(m.group(1))): return _sleden_takov_kalendarski_den(denes, ime)

    m = _KONTEXT_I_DEN_RE.search(p)   # „слободен понеделник"
    if m and (ime := _den_od_match(m)): return _sleden_takov_kalendarski_den(denes, ime)

    ime_kraj = _den_na_kraj_od_prasanje(p)   # den na kraj („… Захариев понеделник?")
    if ime_kraj: return _sleden_takov_kalendarski_den(denes, ime_kraj)
    return None                                        # ne najdovme datum


# Funkcija sho izvlekuva cas (vreme) od prashanjeto LOKALNO
def vreme_od_prasanje_lokalno(prasanje: str) -> str | None:
    """Cas: „12:00", „во 12 часот", „12.30" → „HH:MM" ili None."""
    p = transliterijaj(prasanje or "").lower().strip()  # normaliziraj
    if not p: return None                               # prazno
    # Standarden zapis „HH:MM" ili „HH.MM"
    m = re.search(r"\b(\d{1,2})\s*[:.]\s*(\d{2})\b", p)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))        # zema h i mi
        if 0 <= h <= 23 and 0 <= mi <= 59: return f"{h:02d}:{mi:02d}"  # vraka „HH:MM"
    # „во 12" / „vo 12 cas" — bez minuti
    m = re.search(r"(?:во|vo|at)\s+(\d{1,2})(?:\s*(?:час|часот|cas|casot))?\b", p)
    if m and 0 <= (h := int(m.group(1))) <= 23: return f"{h:02d}:00"
    # „12 час" — bez „во"
    m = re.search(r"\b(\d{1,2})\s*(?:час|часот|cas|casot)\b", p)
    if m and 0 <= (h := int(m.group(1))) <= 23: return f"{h:02d}:00"
    return None                                         # nema cas


# ─── Intent detekcija ───
# Funkcija sho proveruva dali e prashanje za „sleden raboten den"
def prasanje_e_sleden_raboten_den(prasanje: str) -> bool:
    """„Koga e sledniот раboten den?"."""
    return bool(_RE_SLEDEN_RABOTEN_DEN.search(transliterijaj(prasanje).lower()))


# Funkcija sho proveruva dali prashanjeto e za SLOBODNI termini (a ne zakazhuvanje)
def prasanje_e_baranje_slobodni(prasanje: str) -> bool:
    """Dali prashanjeto bara SLOBODNI termini (ne zakazhuvanje)?"""
    p = transliterijaj(prasanje).lower()
    if any(x in p for x in ("слобод", "slobod")): return True  # ima zbor „слободен/слободни" → da
    if "термин" in p or "termin" in p:                          # ima zbor „termin" → proveri ushte
        if any(x in p for x in ("има", "дали", "кога", "слобод", "slobod",
                                "провери", "proveri", "на ", " na ", "за ", " za ")):
            return True
        # Ako prashanjeto ima datum, najverojatno e za slobodni (a ne za istorija)
        try:
            from ai.pacient.moi_pregledi import datum_za_pregledi_od_prasanje
            if datum_za_pregledi_od_prasanje(prasanje): return True
        except ImportError:
            if datum_od_prasanje_lokalno(prasanje): return True
    # „pregled" + „slobod/proveri" → tochno e za slobodni
    if re.search(r"\b(преглед|pregled)\w*\b", p) and (
        "слобод" in p or "slobod" in p or "провери" in p or "proveri" in p): return True
    return False


# Funkcija sho proveruva „za vo vtornik" — produzhuvanje so nov den kaj istiот lekar
def prasanje_e_slobodni_za_den(prasanje: str, kontekst: dict | None = None) -> bool:
    """„За во вторник" / „ама за вторник" — nov den kaj istiot lekar."""
    if baranje_e_zakazuvanje(prasanje): return False           # zakazhuvanje → ne e slobodni
    if not datum_od_prasanje_lokalno(prasanje): return False   # bez datum → ne e
    if prasanje_e_baranje_slobodni(prasanje): return True      # direktno bara slobodni
    # Imame kontekst od „zakazi_od_slobodni" — prashanje za drug den e validno
    if isinstance(kontekst, dict) and kontekst.get("zakazi_od_slobodni"):
        p = transliterijaj(prasanje).lower()
        if re.search(r"\b\d{1,2}\s*[:.]\s*\d{2}\b", p): return False   # ima cas → toa e zakazhuvanje
        return True
    return False


# Funkcija sho proveruva „izbraniот lekar" — referira na lekar od prethoden razgovor
def prasanje_bar_lekar_od_kontekst(prasanje: str) -> bool:
    """„Избраниот/истиот лекар" — lekarот e vo kontekst od prethodna poraka."""
    p = transliterijaj(prasanje).lower()
    return any(x in p for x in (
        "избраниот лекар", "избраниот", "избраниов", "избран лекар",
        "истиот лекар", "истиот", "истиов", "погоре", "од листата",
        "од горе", "тогој лекар", "тој лекар", "го избрав", "izbraniot", "istiot"))


# Funkcija sho proveruva dali e otkazhuvanje na termin
def prasanje_e_otkazuvanje(prasanje: str) -> bool:
    """Otkazhuvanje na termin?"""
    p = transliterijaj(prasanje).lower()
    if "откаж" in p or "otkaz" in p: return True              # ima zbor „otkazhi"
    if "cancel" in p and "termin" in p: return True            # angliska varijanta
    return any(x in p for x in ("сторнира", "поништи термин", "не доаѓам", "не сакам термин"))


# Funkcija sho proveruva dali e ZAKAZHUVANJE (a ne provera za slobodni)
def baranje_e_zakazuvanje(prasanje: str) -> bool:
    """Zakazhuvanje (a ne povtorna provera na slobodni)?"""
    raw = (prasanje or "").lower()                             # raw tekst (kirilica)
    q = transliterijaj(prasanje).lower()                       # transliterirana versija
    if _RE_ZAKAZUVANJE.search(q) or _RE_ZAKAZUVANJE.search(raw):
        # Ako ima „slobod/koga/ima li/proveri/naredno/sledno" → toa e PROVERKA, ne zakazhuvanje
        if not any(w in q for w in ("слобод", "кога е", "има ли", "провери",
                                     "провер", "наредн", "следн")):
            return True
    # Ima cas (10:00) + kluchen zbor → najverojatno e zakazhuvanje
    if re.search(r"\b\d{1,2}\s*[:.]\s*\d{2}\b", q):
        if any(x in q or x in raw for x in ("закаж", "заказ", "zakaz", "термин", "преглед",
                                             "може да закаж", "може да заказ", "moze da zakaz")):
            return True
    return False


# Funkcija sho proveruva „izbraniot DATUM" — datum od prethoden razgovor
def prasanje_bar_datum_od_kontekst(prasanje: str) -> bool:
    """„Претходниот/избраниот датум" — datumот e vo kontekst."""
    p = transliterijaj(prasanje).lower()
    return any(x in p for x in (
        "избраниот датум", "избрана дата", "избраниот", "претходно спомнати",
        "претходно", "претходниот", "спомнатиот датум", "спомнатиот",
        "истиот датум", "наведениот датум", "тогаш спомнати",
        "pretходно", "spomnat", "izbraniot datum"))


# Funkcija sho proveruva „drugi lekari od istata specijalnost" — produzhuvanje po oddel
def prasanje_e_drugi_lekari_specijalnost(prasanje: str) -> bool:
    """„Кои други лекари од истата специјалност" — produzhuvanje po oddel."""
    p = transliterijaj(prasanje).lower()
    # Dali se spomenuva specijalnost/oddel
    ima_spec = any(x in p for x in ("специјалност", "специјалности", "оддел",
                                     "истата", "иста ", "оваа", "ова ", "истиот", "истиов",
                                     "specijalnost", "oddel", "istata", "ista ", "ovaa", "ova "))
    ima_lekari = any(x in p for x in ("лекари", "lekari", "доктори", "doktori"))  # ima zbor „lekari"

    if ima_lekari and ima_spec:
        # „istata/ovaa" — referira na prethodno spomenata specijalnost
        if any(x in p for x in ("истата", "иста ", "оваа", "ова ",
                                 "istata", "ista ", "ovaa", "ova ")): return True
        # „od specijalnost / od oddel" — eksplicitno
        if "од " in p and any(x in p for x in
                              ("специјалност", "specijalnost", "оддел", "oddel")): return True

    # Mora da ima zbor „drugi/uste/ostanati"
    if not any(x in p for x in ("други", "друг ", "друга ", "уште", "останати",
                                 "drugi", "drug ", "ushte", "останati")): return False
    if not any(x in p for x in ("лекар", "лекари", "доктор", "lekari", "doktor")): return False
    return ima_spec


# Funkcija sho proveruva „koja e specijalnostа na izbraniот lekar?" — info za 1 lekar
def prasanje_e_specijalnost_izbran_lekar(prasanje: str, kontekst: dict | None = None) -> bool:
    """„Која е специјалноста на избраниот лекар?" — info za konkreten lekar."""
    if prasanje_e_drugi_lekari_specijalnost(prasanje): return False  # toa e drugo prashanje
    if prasanje_e_baranje_slobodni(prasanje): return False           # i toa e drugo

    p = transliterijaj(prasanje).lower()
    # Mora da ima zbor za „oblast/specijalnost/oddel"
    if not any(x in p for x in ("област", "специјалност", "оддел", "каде работи",
                                 "која е", "кое е", "од која", "koja oblast", "vo koja",
                                 "specijalnost", "oblast", "oddel")): return False

    if prasanje_bar_lekar_od_kontekst(prasanje): return True  # eksplicitno „izbraniot"
    # „izbran/istiот/pogore/toj lekar" — referira na 1 lekar
    if any(x in p for x in ("избран", "истиот", "погоре", "тој лекар", "togo lekar")): return True
    if any(x in p for x in ("лекари", "lekari", "доктори", "doktori")): return False  # lista → drugo

    # Ima lekar vo kontekst + zbor „lekarот/докторот" → toj e referenten
    if lekar_od_zakazi_kontekst(kontekst) and any(x in p for x in (
        "лекарот", "лекар ", " лекар", "д-р", " др",
        "докторот", "доктор ", "toj lekar", "togo lekar")): return True
    return False


# Funkcija sho proveruva „site lekari vo bolnicata" — slobodni za site
def prasanje_bar_site_lekari_za_slobodni(prasanje: str) -> bool:
    """Korisnikот saka slobodni kaj SITE lekari vo bolnicata."""
    p = transliterijaj(prasanje).lower()
    return any(x in p for x in ("на болницата", "во болницата", "во целата", "целата болница",
                                 "кај било кој", "било кој лекар", "сите лекари",
                                 "site lekari", "celata bolnica"))


# Funkcija sho proveruva „koj od niv e sloboden" — produzhuvanje po lista lekari od oddel
def prasanje_e_od_niv_sloboden(prasanje: str) -> bool:
    """„Кој од нив е слободен..." — produzhuvanje po lista lekari od oddel."""
    p = transliterijaj(prasanje).lower()
    if "слобод" not in p and "slobod" not in p: return False   # bez „slobod" → ne e
    return any(m in p for m in _OD_NIV_SLOBODNI_MARKERS)        # ima marker „od niv/od ovie"


# Funkcija sho proveruva dali vo kontekst ima zachuvana lista lekari od oddel
def _ima_oddel_lekari_kontekst(kontekst: dict | None) -> bool:
    """Dali vo kontekst e zachuvana lista lekari od oddel?"""
    if not isinstance(kontekst, dict): return False             # kontekst-ot e None/ne-dict
    ids = kontekst.get("last_oddel_doctor_ids")                 # lista IDs od prethodno
    return isinstance(ids, list) and len(ids) > 0               # mora da e neprazna lista


# Funkcija sho proveruva „koj e sloboden na 25.05 vo 12:00?" (bez konkreten lekar)
def prasanje_e_ko_e_sloboden_datum_vreme(prasanje: str, kontekst: dict | None = None) -> bool:
    """„Кој е слободен на 25.05 во 12:00?" — bez konkreten lekar."""
    p = transliterijaj(prasanje).lower()
    if "слобод" not in p and "slobod" not in p: return False    # bez zbor „slobod"

    from ai._kernel.lekar_lookup import prasanje_ukazuva_kon_konkreten_lekar  # lazy import

    # Imame kontekst so lista lekari od oddel → razni varijanti na „koj od niv"
    if _ima_oddel_lekari_kontekst(kontekst) and (
        prasanje_e_od_niv_sloboden(prasanje)                                       # eksplicitno „od niv"
        or (_KO_PRASANJE_RE.search(p) and _oddel_od_kontekst(kontekst))           # „koj" + ima oddel
        or (prasanje_e_baranje_slobodni(prasanje)                                  # ima baranje za slobodni
            and datum_od_prasanje_lokalno(prasanje)                                # ima datum
            and not vreme_od_prasanje_lokalno(prasanje)                            # NEMA cas (samo den)
            and not prasanje_ukazuva_kon_konkreten_lekar(prasanje))               # ne e za konkreten lekar
    ): return True

    baran_datum = datum_od_prasanje_lokalno(prasanje)            # datum (ako ima)
    barano_vreme = vreme_od_prasanje_lokalno(prasanje)           # cas (ako ima)
    if not baran_datum and not barano_vreme: return False        # bez nitu datum nitu cas → ne e
    if _KO_PRASANJE_RE.search(p): return True                    # ima „koj/koja/koi" → da

    # Ima datum I cas, no nema referenca kon konkreten lekar → najverojatno e „koj e sloboden..."
    if baran_datum and barano_vreme:
        from ai._kernel.lekar_lookup import izvlechi_delovi_ime, najdi_lekar_od_delovi
        delovi = izvlechi_delovi_ime(prasanje)
        if not delovi or not najdi_lekar_od_delovi(delovi): return True
    return False


# Funkcija sho proveruva „naredniот петok" — utocnuvanje na datum (so zachuvan kontekst)
def prasanje_e_utochnuvanje_datum(prasanje: str) -> bool:
    """„Наредниот петок" posle „koj e sloboden..." — samo nov datum (bez sè drugo)."""
    p = transliterijaj(prasanje).lower().strip()
    if not p or len(p) > 70: return False                        # prazno ili predolgо
    if not datum_od_prasanje_lokalno(prasanje): return False     # nema datum → ne e utochnuvanje
    if baranje_e_zakazuvanje(prasanje): return False             # zakazhuvanje → drugo

    from ai._kernel.lekar_lookup import prasanje_ukazuva_kon_konkreten_lekar
    if prasanje_ukazuva_kon_konkreten_lekar(prasanje): return False  # spomenuva lekar → drugo
    if _KO_PRASANJE_RE.search(p): return False                       # „koj/koja" → drugo
    if "слобод" in p or "slobod" in p: return False                   # spomenuva „slobod" → drugo
    if re.search(r"\b(?:кај|kaj)\s+", p, re.UNICODE): return False   # „kaj …" → drugo
    return True                                                       # samo nov datum


# Funkcija sho proveruva „slobodni za den po oddel" (bez ime na lekar)
def prasanje_e_slobodni_po_oddel_datum(prasanje: str, kontekst: dict | None = None) -> bool:
    """„Слободни термини на 25 мај" po lista lekari od oddel (bez ime)."""
    if not _ima_oddel_lekari_kontekst(kontekst): return False    # nema kontekst → ne e
    if baranje_e_zakazuvanje(prasanje): return False             # zakazhuvanje → drugo
    if not prasanje_e_baranje_slobodni(prasanje): return False   # ne e baranje za slobodni
    if not datum_od_prasanje_lokalno(prasanje): return False     # bez datum → ne e
    if vreme_od_prasanje_lokalno(prasanje): return False         # ima cas → toa e „koj e sloboden vo X"

    from ai._kernel.lekar_lookup import najdi_lekar_od_prasanje
    if najdi_lekar_od_prasanje(prasanje): return False           # spomenuva lekar → drugo
    ids = kontekst.get("last_oddel_doctor_ids") if isinstance(kontekst, dict) else []
    return isinstance(ids, list) and len(ids) > 1                # mora da ima > 1 lekar vo listata


# ─── Lekari od baza + AI lookup ───
# Funkcija sho gi vraka SITE lekari od bazata
def zimi_site_lekari() -> list[dict[str, Any]]:
    """Site lekari od bazata."""
    try:
        with db_cursor() as (_, cur):                            # context manager za DB
            cur.execute("SELECT doctor_ID, name, surname, specialty, email FROM Doctors "
                        "ORDER BY surname, name")                # site lekari sortirani po prezime
            return fetch_all(cur)                                # vraka lista od dict
    except Exception as e:
        print(f"[slobodni_termini] Greshka pri zimanje na lekari: {e}")
        return []                                                # na greshka → prazna lista


# Funkcija sho zima lekari samo od dadena specijalnost (oddel)
def zimi_lekari_po_specialty(specialty: str) -> list[dict[str, Any]]:
    """Lekari samo od dadena specijalnost (oddel)."""
    if not (specialty or "").strip(): return []                  # prazno → prazna lista
    try:
        with db_cursor() as (_, cur):
            cur.execute(
                "SELECT doctor_ID, name, surname, specialty, email FROM Doctors "
                "WHERE LOWER(TRIM(specialty)) = LOWER(TRIM(%s)) ORDER BY surname, name",
                (specialty.strip(),))                            # parametar — specialty stringот
            return fetch_all(cur)
    except Exception as e:
        print(f"[slobodni_termini] lekari po specialty greska: {e}")
        return []


# Funkcija sho prashuva GROQ AI „od prashanjeto za koj lekar e?"
def najdi_lekar_so_ai(prasanje: str) -> dict | None:
    """Prashuva Groq „od prashanjeto koj lekar?" so lista site lekari."""
    from ai._kernel.groq_helpers import groq_zadolzhitelen     # lazy import
    if groq_zadolzhitelen(): return None                         # AI nedostapen → preskoki

    site = zimi_site_lekari()                                    # site lekari
    if not site: return None                                     # nema lekari vo baza

    # Sostavi lista vo tekstualen format za AI-promptot
    lista_text = "".join(
        f"ID {l['doctor_ID']}: Д-р {l['name']} {l['surname']} - "
        f"{l.get('specialty') or 'Општа пракса'}\n" for l in site)
    # Sostavi go promptot — AI treba da vrati samo ID broj ili NONE
    prompt = (f"Листа на лекари во болницата:\n{lista_text}\n"
              f"Прашање од корисникот: „{prasanje}\"\n"
              "За кој лекар се однесува прашањето (слободни термини, закажување, преглед)?\n"
              "Име може да биде нецелосно или на латиница. Ако се спомнуваат повеќе лекари, "
              "земи го најрелевантниот.\nВрати само ID број или NONE.")

    # Praka prompt do Groq AI, dobiva tekst → cisti go (mali bukvi, bez „.")
    cist = ask_ai(prompt, system_prompt=LEKAR_EXTRACT_PROMPT).strip().upper().replace(".", "").replace(",", "")
    if "NONE" in cist: return None                                # AI rekol NEMA
    match = re.search(r"\d+", cist)                               # izvadi broj (ID)
    if not match: return None                                     # nema broj
    doctor_id = int(match.group())                                # parsiraj go ID-to
    for l in site:
        if l["doctor_ID"] == doctor_id: return l                  # najden lekar → vrati go
    return None                                                   # ID ne se sovpaga so postoechki


# ─── Kontekst helper-i ───
# Funkcija sho vraka ime na oddel zachuvan vo kontekst
def _oddel_od_kontekst(kontekst: dict | None) -> str | None:
    """Ime na oddel zachuvano vo kontekst ili None."""
    if not isinstance(kontekst, dict): return None
    # Probaj poveke kluchovi (razlichni handler-i go pamatat pod razlichno ime)
    for key in ("last_oddel", "oddel", "specialty"):
        val = kontekst.get(key)
        if val and str(val).strip(): return str(val).strip()
    return None


# Funkcija sho vraka datum zachuvan vo kontekst (po lista slobodni / pending zakazhuvanje)
def datum_od_zakazi_kontekst(kontekst: dict | None) -> date | None:
    """Datum zachuvan vo kontekst (po lista slobodni / pending zakazhuvanje)."""
    if not isinstance(kontekst, dict): return None
    for key in ("zakazi_od_slobodni", "zakazi_pending"):         # dve mozhni miesta
        z = kontekst.get(key)
        if not isinstance(z, dict) or not z.get("datum"): continue
        try: return datetime.strptime(str(z["datum"]).strip()[:10], "%Y-%m-%d").date()
        except ValueError: continue                              # nevaliden format → preskoki
    return None


# Funkcija sho vraka cas zachuvan od prethodna poraka „koj e sloboden vo X"
def vreme_iz_kontekst(kontekst: dict | None) -> str | None:
    """Zachuvan cas od prethodna poraka „koj e sloboden vo X"."""
    if not isinstance(kontekst, dict): return None
    # Prvo proba „last_slobodni_vreme"
    v = (kontekst.get("last_slobodni_vreme") or "").strip()
    if v: return v
    # Inaku proba vo „zakazi_od_slobodni.vreme"
    z = kontekst.get("zakazi_od_slobodni")
    if isinstance(z, dict):
        v = (z.get("vreme") or "").strip()
        if v: return v
    return None


# Funkcija sho vraka LEKAR od kontekst (zakazi_od_slobodni / zakazi_pending / last_doctor_id)
def lekar_od_zakazi_kontekst(kontekst: dict | None) -> dict | None:
    """Lekar od kontekst (zakazi_od_slobodni / zakazi_pending / last_doctor_id)."""
    if not kontekst: return None
    doctor_id = None
    # Probaj prvo „zakazi_od_slobodni"
    zos = kontekst.get("zakazi_od_slobodni")
    if not isinstance(zos, dict): zos = kontekst.get("zakazi_pending")  # fallback
    if isinstance(zos, dict): doctor_id = normalize_int(zos.get("doctor_id"))
    # Ako sè ushte nema → probaj „last_doctor_id"
    if doctor_id is None: doctor_id = normalize_int(kontekst.get("last_doctor_id"))
    if doctor_id is None: return None
    # Najdi go lekarот vo bazata po ID
    for l in zimi_site_lekari():
        if int(l["doctor_ID"]) == doctor_id: return l
    return None


# Funkcija sho vraka lekar ako vo kontekst ima TOCNO eden lekar od oddel
def lekar_od_oddel_kontekst(kontekst: dict | None) -> dict | None:
    """Lekar ako vo kontekst ima TOCNO eden lekar od oddel."""
    if not isinstance(kontekst, dict): return None
    ids = kontekst.get("last_oddel_doctor_ids")
    if not isinstance(ids, list) or len(ids) != 1: return None   # mora da e tocno 1
    try: did = int(ids[0])
    except (TypeError, ValueError): return None
    for l in zimi_site_lekari():
        if int(l["doctor_ID"]) == did: return l
    return None


# Funkcija sho vraka lekar od izbran kontekst (prvo zakazi, pa oddel)
def lekar_iz_izbran_kontekst(kontekst: dict | None) -> dict | None:
    """Lekar od prethodna poraka: prv zakazi, pa oddel."""
    return lekar_od_zakazi_kontekst(kontekst) or lekar_od_oddel_kontekst(kontekst)


# Funkcija sho gradi pomoshna poraka koga ima poveke lekari od lista po oddel
def _poraka_izberi_lekar_od_lista(kontekst: dict) -> str:
    """Pomoshna poraka koga ima poveke lekari od lista po oddel."""
    ids = kontekst.get("last_oddel_doctor_ids")
    if not isinstance(ids, list) or len(ids) < 2: return ""      # treba da ima >= 2
    id_set: set[int] = set()                                     # set za brzo prebaruvanje
    for raw in ids:
        try: id_set.add(int(raw))
        except (TypeError, ValueError): continue                 # preskoki nevaliдni

    iminja: list[str] = []                                        # ke gi polnime imeniwata
    for l in zimi_site_lekari():
        if int(l["doctor_ID"]) in id_set:
            ime = (l.get("name") or "").strip()
            prezime = (l.get("surname") or "").strip()
            if ime or prezime: iminja.append(f"д-р {ime} {prezime}".strip())
    if not iminja: return ""                                      # nema imenovi → prazna poraka

    lista = ", ".join(iminja[:8])                                 # prvi 8 (da ne se preplavi chat)
    oddel = (kontekst.get("last_oddel") or "").strip()
    uvod = f"На одделот {oddel} " if oddel else "Од претходната листа "
    return (f"{uvod}има повеќе лекари ({lista}).\n\n"
            "Наведете го лекарот по име (на пр. „Кога е слободен д-р Марко Петров?“) "
            "или прашајте „кој од нив е слободен утре?“.")


# ─── Resolve lekar + pool za „koj e sloboden" ───
# Funkcija sho izbira KONKRETEN lekar za baranjeto za slobodni termini
def resolviraj_lekar_za_slobodni(
    prasanje: str, kontekst: dict | None
) -> tuple[dict | None, bool, str | None]:
    """Vraka (lekar ili None, dali e od kontekst, opc. poraka za izbor)."""
    # Scenario 1: korisnikот referira na „izbraniот lekar" — zemi go od kontekst
    if prasanje_bar_lekar_od_kontekst(prasanje):
        lekar = lekar_iz_izbran_kontekst(kontekst)
        # Ako nema eden lekar a ima lista → barame da izbere
        if not lekar and isinstance(kontekst, dict):
            poraka = _poraka_izberi_lekar_od_lista(kontekst)
            if poraka: return None, False, poraka
        return lekar, lekar is not None, None

    # Scenario 2: probaj da go najdesh lekarot po ime od prashanjeto
    from ai._kernel.lekar_lookup import (
        izvlechi_delovi_ime, najdi_lekar_od_prasanje, najdi_lekari_po_delovi,
        najdi_lekari_po_prezime, poraka_za_vise_lekari, prezime_na_pocetok_od_prasanje)

    # Scenario 2a: prezime na pochetok („Петров кога е слободен?")
    prezime_poc = prezime_na_pocetok_od_prasanje(prasanje)
    if prezime_poc:
        kandidati = najdi_lekari_po_prezime(prezime_poc)
        if len(kandidati) == 1: return kandidati[0], False, None                          # 1 kandidat → super
        if len(kandidati) > 1: return None, False, poraka_za_vise_lekari(kandidati, [prezime_poc])

    # Scenario 2b: po izvлечени deлови od imeto (ime, prezime, ...)
    delovi = izvlechi_delovi_ime(prasanje)
    kandidati = najdi_lekari_po_delovi(delovi)
    if len(kandidati) > 1: return None, False, poraka_za_vise_lekari(kandidati, delovi)

    # Scenario 2c: opsht fallback — kompletna pretraga
    lekar = najdi_lekar_od_prasanje(prasanje)
    if lekar: return lekar, False, None

    # Scenario 3: probaj go od kontekst (poslednоto zakazi)
    lekar = lekar_od_zakazi_kontekst(kontekst)
    if lekar: return lekar, True, None

    # Scenario 4: ima baranje za slobodni + datum, no nema lekar → probaj od oddel (1 lekar)
    if prasanje_e_baranje_slobodni(prasanje) and datum_od_prasanje_lokalno(prasanje):
        lekar = lekar_od_oddel_kontekst(kontekst)
        if lekar: return lekar, True, None
    return None, False, None                                     # ne najdovme


# Funkcija sho vraka „pool" — KOI lekari da gi proverime za „koj e sloboden"
def lekari_pool_za_ko_sloboden(
    prasanje: str, kontekst: dict | None
) -> tuple[list[dict] | None, str | None]:
    """Koi lekari da se proverat za „koj e sloboden". pool=None → site."""
    # Ako korisnikот saka SITE lekari → vrati None (signal „site")
    if prasanje_bar_site_lekari_za_slobodni(prasanje): return None, None

    # Probaj od prashanjeto da izvlechesh oddel
    from ai._kernel.oddel_resolver import resolve_oddel
    resolved = resolve_oddel(prasanje)
    if resolved and resolved.ok and resolved.oddel:
        return zimi_lekari_po_specialty(resolved.oddel), resolved.oddel

    if not isinstance(kontekst, dict): return None, None         # bez kontekst → site

    # Ako vo kontekst ima zachuvana lista lekari od prethoden razgovor — koristi ja
    oddel = _oddel_od_kontekst(kontekst)
    ids = kontekst.get("last_oddel_doctor_ids")
    if isinstance(ids, list) and ids:
        id_set = {int(x) for x in ids}                            # set za brzo filtriranje
        pool = [l for l in zimi_site_lekari() if int(l["doctor_ID"]) in id_set]
        if pool: return pool, oddel
    # Fallback: imame samo ime na oddel → zemi gi site lekari od taa specijalnost
    if oddel:
        pool = zimi_lekari_po_specialty(oddel)
        if pool: return pool, oddel
    return None, None                                            # nemame info → site


# ─── Slotovi + zafateni termini ───
# Funkcija sho generira 30-min slotovi za eden raboten den (08:00 → 15:30)
def generiraj_slotovi_za_den(datum: date) -> list[datetime]:
    """30-min slotovi za raboten den (08:00 → 15:30). [] za sab./ned."""
    if datum.weekday() >= 5: return []                            # vikend → nema slotovi
    slotovi = []
    momentalno = datetime.combine(datum, RABOTNO_VREME_OD)        # pochni od 08:00
    kraj = datetime.combine(datum, RABOTNO_VREME_DO)              # zavrshi vo 16:00
    while momentalno < kraj:                                       # dodeka ne stigneme do kraj
        slotovi.append(momentalno)                                 # dodaj slot
        momentalno += timedelta(minutes=TRAENJE_TERMIN_MINUTI)    # napredi za 30 min
    return slotovi


# Funkcija sho najduva ZAFATENI termini za lekar vo dadeen interval (od bazata)
def najdi_zafateni_slotovi(doctor_id: int, od_datum: date, do_datum: date) -> set:
    """Set od (datum, vreme) sho se VEKE zakazani za lekar vo interval."""
    conn = None
    try:
        conn = get_connection()                                   # otvori MySQL konekcija
        cur = conn.cursor(dictionary=True)                        # cursor sho vraka dict
        # SELECT zafateni termini — site sho ne se otkazhani
        cur.execute(
            "SELECT DATE(datum_pregled) AS dp, "
            "TIME_FORMAT(TIME(vreme_pregled), '%H:%i') AS vp FROM Termin_pregled "
            "WHERE doctor_ID = %s AND DATE(datum_pregled) BETWEEN %s AND %s "
            "AND status_pregled NOT IN ('откажан', 'отказан')",
            (doctor_id, od_datum, do_datum))
        rezultati = cur.fetchall()                                # site redovi
        cur.close()                                               # zatvori cursor vednash

        zafateni: set[tuple[date, time]] = set()                  # set (datum, vreme) — za brzo prebaruvanje
        for r in rezultati:
            d_raw, t_raw = r.get("dp"), r.get("vp")               # raw vrednosti od baza
            if d_raw is None or t_raw is None: continue           # ne mozeme bez datum/vreme

            # ─── parsiranje DATUM → date ─── (raznо tipovi zaradi razlichni MySQL drivers)
            if isinstance(d_raw, datetime): datum = d_raw.date()
            elif isinstance(d_raw, date): datum = d_raw
            elif isinstance(d_raw, (bytes, bytearray)):
                try: datum = datetime.strptime(d_raw.decode("utf-8", errors="ignore")[:10],
                                                "%Y-%m-%d").date()
                except ValueError: continue
            elif isinstance(d_raw, str):
                try: datum = datetime.strptime(d_raw.strip()[:10], "%Y-%m-%d").date()
                except ValueError: continue
            else: continue                                        # nepoznat tip → preskoki

            # ─── parsiranje VREME → time (bez sekundi) ─── (isto raznо tipovi)
            vreme: time | None = None
            if isinstance(t_raw, time): vreme = time(t_raw.hour, t_raw.minute)
            elif isinstance(t_raw, timedelta):                    # nekoi drajveri vrakaat timedelta
                vk = int(t_raw.total_seconds())
                vreme = time((vk // 3600) % 24, (vk % 3600) // 60)
            elif isinstance(t_raw, (bytes, bytearray)):
                t_raw = t_raw.decode("utf-8", errors="ignore").strip()
            if vreme is None and isinstance(t_raw, str):
                parts = t_raw.replace(".", ":").split(":")        # „14.30" / „14:30" → [14, 30]
                try: vreme = time(int(parts[0]), int(parts[1]))
                except (ValueError, IndexError): continue
            if vreme is None: continue                            # ne uspeavme da parsirame
            zafateni.add((datum, vreme))                          # dodaj go vo set
        return zafateni
    except Exception as e:
        print(f"[slobodni_termini] Greshka pri barebje zafateni: {e}")
        return set()                                              # na greshka → prazno
    finally:
        if conn: conn.close()                                     # sekogash zatvori konekcija


# Funkcija sho najduva SLOBODNI termini za lekar (na konkreten datum ili sledni 7 dena)
def pronajdi_slobodni_termini(doctor_id: int, na_datum: date | None = None) -> list[datetime]:
    """
    Slobodni slotovi za lekar:
      - ako `na_datum` e daden: samo za toj den
      - inaku: prvите MAX_TERMINI termini vo slednите DENOVI_NAPRED dena.
    """
    denes = date.today()                                          # referenten datum
    if na_datum is not None and na_datum < denes: na_datum = None  # minat datum → ignoriraj go

    if na_datum is not None:   # KONKRETEN datum
        if na_datum.weekday() >= 5: return []                     # vikend → prazno
        zafateni = najdi_zafateni_slotovi(doctor_id, na_datum, na_datum)  # zafateni za toj den
        slobodni: list[datetime] = []
        for slot_dt in generiraj_slotovi_za_den(na_datum):
            if slot_dt < datetime.now(): continue                 # minat slot → preskoki
            sv = time(slot_dt.time().hour, slot_dt.time().minute)
            if (na_datum, sv) not in zafateni: slobodni.append(slot_dt)  # ne e zafaten → sloboden
        return slobodni

    # OPSEG denes + DENOVI_NAPRED (default 7)
    do_datum = denes + timedelta(days=DENOVI_NAPRED)
    zafateni = najdi_zafateni_slotovi(doctor_id, denes, do_datum)  # site zafateni vo opsegot
    slobodni = []
    for offset in range(DENOVI_NAPRED + 1):                       # za sekoj den (0..7)
        datum = denes + timedelta(days=offset)
        for slot_dt in generiraj_slotovi_za_den(datum):           # site slotovi za toj den
            if slot_dt < datetime.now(): continue                 # minat → preskoki
            sv = time(slot_dt.time().hour, slot_dt.time().minute)
            if (datum, sv) not in zafateni:
                slobodni.append(slot_dt)                          # sloboden → dodaj
                if len(slobodni) >= MAX_TERMINI: return slobodni  # dosta sme nashle
    return slobodni


# Funkcija sho proveruva dali lekar e SLOBODEN na konkreten datum + cas
def termin_sloboden_na_datum_vreme(doctor_id: int, na_datum: date, vreme_str: str) -> bool:
    """Dali lekar e sloboden na daden datum i cas?"""
    if na_datum.weekday() >= 5: return False                      # vikend → ne
    try:
        h_s, m_s = vreme_str.strip().split(":")[:2]               # razdvoj „HH:MM" na h i mi
        t = time(int(h_s), int(m_s))
    except (ValueError, TypeError): return False                  # nevaliden cas

    slotovi = generiraj_slotovi_za_den(na_datum)                  # generiraj gi slotovite za denот
    # Casот mora da bide eden od validnите slotovi (08:00, 08:30, …, 15:30)
    if not any(s.time().hour == t.hour and s.time().minute == t.minute for s in slotovi):
        return False
    if datetime.combine(na_datum, t) < datetime.now(): return False  # minat datum/cas
    zafateni = najdi_zafateni_slotovi(doctor_id, na_datum, na_datum)  # zafateni za denот
    return (na_datum, time(t.hour, t.minute)) not in zafateni     # sloboden ako ne e vo zafateni


# Wrapper funkcija — pravi isto kako termin_sloboden_na_datum_vreme, no zema dict-lekar
def lekar_sloboden_na_termin(lekar: dict, na_datum: date, vreme_str: str) -> bool:
    """Wrapper za `termin_sloboden_na_datum_vreme`."""
    return termin_sloboden_na_datum_vreme(int(lekar["doctor_ID"]), na_datum, vreme_str)


# Funkcija sho najduva site lekari sho se SLOBODNI na konkreten datum + cas
def najdi_lekari_slobodni_na(
    na_datum: date, vreme_str: str, lekari_pool: list[dict] | None = None
) -> list[dict]:
    """Lista lekari sho se slobodni na daden datum i cas."""
    # Ako e daden pool — koristi go; inaku zemi gi sitе lekari
    slobodni = [l for l in (lekari_pool if lekari_pool is not None else zimi_site_lekari())
                if lekar_sloboden_na_termin(l, na_datum, vreme_str)]
    return sorted(slobodni, key=lambda x: (x.get("surname") or "", x.get("name") or ""))


# ─── Formatiranje odgovor za korisnik ───
# Funkcija sho pretvora „09:30" vo broj minuti od pochеtok na denот (570)
def _cas_vo_minuti(cas_str: str) -> int:
    """„09:30" → 570 minuti od pochеtok na denот."""
    h, m = map(int, cas_str.split(":"))
    return h * 60 + m


# Funkcija sho vraka kluc na period od casот („ran_nautro", „okolu_pladne", „popladne")
def _kluc_period_za_cas(cas_str: str) -> str:
    """Period: „ran nautro / okolu pladne / popladne"."""
    mins = _cas_vo_minuti(cas_str)
    if mins < 10 * 60: return "ran_nautro"                        # pred 10:00
    if mins < 14 * 60: return "okolu_pladne"                      # 10:00 - 14:00
    return "popladne"                                              # posle 14:00


# Mapa od kluch na period → ubav naslov za prikaz
_PERIOD_NASLOVI = {"ran_nautro": "Ран наутро", "okolu_pladne": "Околу пладне", "popladne": "Попладне"}
# Redosled — vo koj redosled da gi pokazheme periodите
_PERIOD_REDO = ("ran_nautro", "okolu_pladne", "popladne")


# Funkcija sho vraka kratok opis kade se slotовite („pretpladne", „popladne", …)
def _opis_raspon_termini(casovi: list[str]) -> str:
    """Kratok opis kade se slotovite („pretpladne", „popladne", …)."""
    if not casovi: return ""
    mins = [_cas_vo_minuti(c) for c in casovi]                    # site casovi vo minuti
    min_m, max_m = min(mins), max(mins)                           # min i max
    if max_m <= 12 * 60 + 30: return "во текот на целото претпладне"          # se do 12:30
    if min_m >= 14 * 60: return "попладне"                                     # od 14:00 navamu
    if min_m < 10 * 60 and max_m >= 14 * 60: return "низ целиот работен ден"   # rastegnati
    if min_m >= 10 * 60 and max_m < 14 * 60: return "претпладне"               # vo sredina
    return "во текот на работниot ден"


# Funkcija sho gradi redovi grupirani po period („Ран наутро: 08:30 | 09:00")
def _formatiraj_casovi_po_periodi(casovi: list[str]) -> list[str]:
    """Redovi „Ран наутро: 08:30 | 09:00"."""
    po_period: dict[str, list[str]] = {}                          # grupi po period
    for cas in casovi:
        po_period.setdefault(_kluc_period_za_cas(cas), []).append(cas)  # gruppirај go casот
    redici: list[str] = []
    for kluc in _PERIOD_REDO:                                     # po redosled na periodi
        if kluc not in po_period: continue                        # nema vo toj period → preskoki
        if redici: redici.append("")                              # prazen red za razdelnik
        redici.append(f"{_PERIOD_NASLOVI[kluc]}: {' | '.join(po_period[kluc])}")
    return redici


# Funkcija sho formatira eden den za eden lekar (vovod + grupirani casovi)
def _formatiraj_den_lekar(lekar: dict, casovi: list[str], datum: date, weekday: int,
                           denovi: list[str]) -> str:
    """Eden den: vovod + grupirani casovi."""
    ime = f"{lekar['name']} {lekar['surname']}"
    spec = lekar.get("specialty") or "Општа пракса"
    return "\n".join([
        f"За {denovi[weekday].lower()} ({format_datum(datum)}), кај д-р {ime} "
        f"({spec}) има слободни термини {_opis_raspon_termini(casovi)}:", "",
        *_formatiraj_casovi_po_periodi(casovi)])                  # site grupi po period


# Funkcija sho vraka kratok footer (upatstvo za zakazhuvanje)
def _footer_za_zakazuvanje(eden_datum: bool) -> str:
    """Kratoko upatstvo po lista na slobodni termini."""
    if eden_datum:                                                # samo eden datum vo odgovorот
        return ("\n\nКажете ми кој од овие термини најмногу ви одговара "
                "(на пример: „Закажи во 09:30\").\nЗа друг работен ден — наведете нова дата.")
    # Poveke datumi
    return "\n\nКажете ми датум, час и лекар (на пример: „Закажи кај Петров во 10:00\")."


# Funkcija sho gradi FINALEN tekst-odgovor na makedonski, gruppiran po den
def formatiraj_odgovor(lekar: dict, slobodni: list[datetime],
                       na_datum: date | None = None) -> str:
    """Finalna poraka na makedonski, gruppirano po den."""
    DENOVI = ["Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"]  # za prikaz
    ime = f"д-р {lekar['name']} {lekar['surname']}"
    spec = lekar.get("specialty") or "Општа пракса"
    zaglavie = f"{ime} ({spec})"

    # Scenarij: nema slobodni termini → tri varianti na poraka
    if not slobodni:
        if na_datum is not None and na_datum.weekday() >= 5:                          # vikend
            return (f"Кај {zaglavie}, {format_datum(na_datum)} е викенд — прегледи се само "
                    "во работни денови.\n\nНаведете работен ден (на пр. „следниот "
                    "понеделник\") или прашајте без датум.")
        if na_datum is not None:                                                       # konkreten datum, no nema
            return (f"За {DENOVI[na_datum.weekday()].lower()} ({format_datum(na_datum)}), "
                    f"кај {zaglavie} нема слободни термини.\n\nНаведете друга дата за "
                    "нова проверка или прашајте без конкретен датум.")
        return (f"Кај {zaglavie} за избраниот период нема слободни термини.\n\n"      # bez datum
                "Пробајте друг ден или друг лекар, или наведете конкретен датум и време.")

    # Grupiraj gi slobodnите po den (datum, weekday) → lista casovi
    po_den: dict[tuple[date, int], list[str]] = {}
    for dt in slobodni:
        po_den.setdefault((dt.date(), dt.weekday()), []).append(format_vreme(dt))

    # Ako e samo eden den → ednostavna struktura + footer „eden datum"
    if len(po_den) == 1:
        (datum, wd), casovi = next(iter(po_den.items()))
        return _formatiraj_den_lekar(lekar, casovi, datum, wd, DENOVI) + \
               _footer_za_zakazuvanje(eden_datum=True)

    # Poveke denovi → secija po sekoj den + footer „poveke datumi"
    delovi: list[str] = []
    for (datum, wd), casovi in po_den.items():
        if delovi: delovi.append("")                              # prazen red megu denovi
        delovi.append(_formatiraj_den_lekar(lekar, casovi, datum, wd, DENOVI))
    delovi.append(_footer_za_zakazuvanje(eden_datum=False))
    return "\n".join(delovi)


# Wrapper funkcija — zasega samo delegira na lokalniот formater
def formatiraj_odgovor_preku_ai(lekar: dict, slobodni: list[datetime],
                                  na_datum: date | None, prasanje: str) -> str:
    """Wrapper: zasega delegira na lokalniот formater."""
    return formatiraj_odgovor(lekar, slobodni, na_datum=na_datum)


# ─── Odgovori „koj e sloboden" / „slobodni po oddel" ───
# Funkcija sho gradi odgovor „slobodni za den po oddel" (site lekari od oddel)
def odgovor_slobodni_za_den_oddel(prasanje: str, na_datum: date,
                                    kontekst: dict | None) -> dict:
    """Slobodni termini za SITE lekari od oddel (od kontekst)."""
    pool, oddel = lekari_pool_za_ko_sloboden(prasanje, kontekst)  # pool lekari + ime na oddel
    # Fallback: ako pool e prazen, no ima IDs vo kontekst → koristi gi tie
    if not pool and isinstance(kontekst, dict):
        ids = kontekst.get("last_oddel_doctor_ids") or []
        id_set = {int(x) for x in ids}
        pool = [l for l in zimi_site_lekari() if int(l["doctor_ID"]) in id_set]

    den_ime = _IMENA_DEN[na_datum.weekday()].lower()              # ime na denот (npr. „понеделник")
    datum_fmt = format_datum(na_datum)                            # formatiran datum

    # Vikend → uchtivo otkazhi
    if na_datum.weekday() >= 5:
        return {"odgovor": f"На {den_ime}, {datum_fmt} е викенд — прегледи се само "
                "во работни денови.", "kontekst": kontekst}

    # Naslov — so ili bez ime na oddel
    if oddel:
        linii = [f"Слободни термини на {den_ime}, {datum_fmt} — оддел „{oddel}“:", ""]
    else:
        linii = [f"Слободни термини на {den_ime}, {datum_fmt}:", ""]

    # Nema pool lekari → informiraj
    if not pool:
        linii.append("Немам зачувана листа лекари од претходната порака.")
        return {"odgovor": "\n".join(linii), "kontekst": kontekst}

    # Za sekoj lekar — pokazhi slobodnite casovi
    prv: dict | None = None                                       # prvот sо slobodni (za default)
    for l in pool:
        slobodni = pronajdi_slobodni_termini(int(l["doctor_ID"]), na_datum=na_datum)
        ime = f"д-р {l.get('name', '')} {l.get('surname', '')}".strip()
        if slobodni:
            if prv is None: prv = l                               # zapamti go prvot za default
            casovi = [format_vreme(dt) for dt in slobodni[:12]]   # prvi 12 casovi
            extra = f" (+{len(slobodni) - 12} уште)" if len(slobodni) > 12 else ""
            linii.append(f"• {ime}: {', '.join(casovi)}{extra}")
        else:
            linii.append(f"• {ime}: нема слободни термини")
    linii.extend(["", "За закажување: „закажи кај [презиме] во [час]“ — датумот се зачувува."])

    # Sochuvaj go kontekstот za naredni prashanja
    ctx = dict(kontekst) if isinstance(kontekst, dict) else {}
    ctx["last_slobodni_datum"] = na_datum.strftime("%Y-%m-%d")     # zapamti go datumот
    if oddel:
        ctx["last_oddel"] = oddel                                  # zapamti go oddelот
        ctx["last_oddel_doctor_ids"] = [int(l["doctor_ID"]) for l in pool]  # IDs na pool
    if prv:                                                        # ima prv lekar sо slobodni
        ctx["last_doctor_id"] = int(prv["doctor_ID"])              # zapamti go za default
        ctx["zakazi_od_slobodni"] = {"doctor_id": int(prv["doctor_ID"]),
                                      "datum": na_datum.strftime("%Y-%m-%d")}
    return {"odgovor": "\n".join(linii), "kontekst": ctx}


# Funkcija sho gradi odgovor „koj e sloboden na datum + cas?"
def odgovor_ko_e_sloboden_na_termin(prasanje: str, na_datum: date, vreme_str: str,
                                     kontekst: dict | None = None) -> str:
    """Lista lekari sho se slobodni na konkreten datum i cas."""
    den_ime = _IMENA_DEN[na_datum.weekday()].lower()              # ime na den
    datum_fmt = format_datum(na_datum)                            # formatiran datum
    pool, oddel = lekari_pool_za_ko_sloboden(prasanje, kontekst)  # pool lekari + oddel
    lekari = najdi_lekari_slobodni_na(na_datum, vreme_str, lekari_pool=pool)  # najdi slobodni
    rv_od, rv_do = format_vreme(RABOTNO_VREME_OD), format_vreme(RABOTNO_VREME_DO)  # za pomoshna poraka

    # Razlichni nasloi i error-poraki spored toa dali imame oddel
    if oddel:
        naslov = f"На {den_ime}, {datum_fmt} во {vreme_str} на одделот „{oddel}\" слободни се:"
        prazen = (f"На {den_ime}, {datum_fmt} во {vreme_str} на одделот „{oddel}\" "
                  f"нема слободен лекар.\n\nРаботно време: {rv_od}–{rv_do}, "
                  "понеделник–петок.\n\nПробајте друг час, друг лекар од листата погоре, или "
                  "„Кога е слободен д-р [презиме]?\".")
    else:
        naslov = f"На {den_ime}, {datum_fmt} во {vreme_str} слободни се:"
        prazen = (f"На {den_ime}, {datum_fmt} во {vreme_str} нема слободен лекар за "
                  f"закажување.\n\nРаботно време: {rv_od}–{rv_do}, понеделник–петок.\n\n"
                  "Пробајте друг час или „Кога е слободен д-р [презиме]?\" за конкретен лекар.")

    if not lekari: return prazen                                  # nema slobodni → vrati greshka

    # Imame slobodni → pokazhi go nasloiот + lista lekari
    linii = [naslov, ""]
    for l in lekari:
        spec = (l.get("specialty") or "Општа пракса").strip()
        linii.append(f"- Д-р {l['name']} {l['surname']} ({spec})")

    # Dodaj kratok hint za zakazhuvanje
    if oddel:
        hint = (f"За закажување на {datum_fmt} во {vreme_str} напишете, на пр.:\n"
                f"„закажи кај {lekari[0]['surname']}\" или „може да ми закажете кај "
                f"{lekari[0]['surname']}\".\n(Датумот и часот од погоре се зачувуваат автоматски.)")
    else:
        hint = (f"За закажување наведете лекар, на пр.: „закажи кај {lekari[0]['surname']} "
                f"во {vreme_str}\".")
    linii.extend(["", hint])
    return "\n".join(linii)


# ─── AI fallback za datum + azhuriranje na kontekst ───
# Funkcija sho prashuva GROQ AI za datum (rezervno koga regex ne nashol)
def _datum_od_prasanje_so_ai(prasanje: str) -> date | None:
    """Rezervno: ako lokalnoto ne preponal datum, prashame Groq."""
    from ai._kernel.ai_json import is_ai_error_response, parse_ai_json
    from ai._kernel.groq_client import ask_ai

    denes = date.today().isoformat()
    prompt = (f"Денес е {denes}. Од прашањето извлечи датум за преглед (работен ден). "
              f"Прашање: „{prasanje}\"\nВрати JSON: {{\"datum\": \"YYYY-MM-DD\"}} "
              "или {\"datum\": null} ако нема датум.\nСамо JSON.")
    raw = ask_ai(prompt, system_prompt="Ти извлекуваш датуми. Само валиден JSON.")
    if is_ai_error_response(raw): return None                     # AI nedostapen
    data = parse_ai_json(raw, log_tag="datum_ai")                 # parsiraj go JSON odgovorот
    val = data.get("datum")
    if not val: return None                                       # AI rekol „nema datum"
    try:
        out = datetime.strptime(str(val).strip()[:10], "%Y-%m-%d").date()
        return out if out >= date.today() else None              # ne vraka minatosti
    except ValueError: return None


# Funkcija sho izvлекuva datum (3 metodi: regex → kontekst → AI)
def izvleci_datum_za_slobodni(prasanje: str, kontekst: dict | None = None) -> date | None:
    """Glavno izvлекuvanje: 1) lokalen regex, 2) kontekst, 3) AI."""
    baran = datum_od_prasanje_lokalno(prasanje)                   # prvo proba lokalno
    if baran is not None: return baran
    # Ako prashanjeto referira „izbraniот datum" → zemi od kontekst
    if prasanje_bar_datum_od_kontekst(prasanje): return datum_od_zakazi_kontekst(kontekst)
    return _datum_od_prasanje_so_ai(prasanje)                     # poslednoto reshenie — AI


# Funkcija sho vraka ISO format datum za kontekst „zakazi_od_slobodni"
def datum_za_zakazi_kontekst(baran_datum: date | None,
                              slobodni: list[datetime]) -> str | None:
    """ISO datum za `zakazi_od_slobodni` (od baranjeto ili od prikazот)."""
    if baran_datum is not None: return baran_datum.strftime("%Y-%m-%d")  # ima baran → koristi go
    if not slobodni: return None                                          # nema slobodni → nishto
    return sorted({dt.date() for dt in slobodni})[0].strftime("%Y-%m-%d")  # prv slobоден datum


# Funkcija sho gи azuriraj kontekstот posle „koj e sloboden" odgovor
def _azuriraj_kontekst_ko_sloboden(kontekst: dict | None, baran_datum: date,
                                    barano_vreme: str | None, lekari: list[dict],
                                    oddel: str | None, pool: list[dict] | None) -> dict:
    """Po „koj e sloboden" odgovor, sochuvaj lista lekari + datum + cas vo kontekst."""
    ctx = dict(kontekst) if isinstance(kontekst, dict) else {}    # kopija na kontekstот
    if oddel:                                                     # zapamti go oddelот
        ctx["last_oddel"] = oddel
        if pool: ctx["last_oddel_doctor_ids"] = [int(l["doctor_ID"]) for l in pool]
    ctx["last_slobodni_datum"] = baran_datum.strftime("%Y-%m-%d")  # zapamti go datumот
    if barano_vreme: ctx["last_slobodni_vreme"] = barano_vreme    # i casот ako ima
    if lekari:                                                    # ima slobodni lekari
        ctx["last_slobodni_doctor_ids"] = [int(l["doctor_ID"]) for l in lekari]  # site IDs
        prv = lekari[0]                                           # prvот kako default
        z: dict = {"doctor_id": int(prv["doctor_ID"]),
                   "datum": baran_datum.strftime("%Y-%m-%d")}
        if barano_vreme: z["vreme"] = barano_vreme
        ctx["zakazi_od_slobodni"] = z                              # podgotovka za vednash zakazhuvanje
        ctx["last_doctor_id"] = int(prv["doctor_ID"])             # default lekar
    return ctx


# ═══ GLAVNA TOCHKA — povikuvana od handlers.py ═══
def odgovori_za_slobodni_termini(prasanje: str,
                                  kontekst: dict | None = None) -> str | dict:
    """
    Logikata odi po 4 sluchai (po red):
       1: „sleden raboten den"
       1b: utochnuvanje na datum (zachuvan cas + oddel)
       2: „koj e sloboden na 25.05 vo 12:00?"
       3: „slobodni na datum" po oddel (bez lekar)
       4 (standard): „koga e sloboden d-r X?"
    Vraka: tekst ILI dict {„odgovor": …, „kontekst": …}.
    """
    # ── SLUCAJ 1: „sleden raboten den" ──
    if prasanje_e_sleden_raboten_den(prasanje):
        sleden = sleden_raboten_datum()                                    # zemi go sledniот raboten den
        lekar, _, nejasno = resolviraj_lekar_za_slobodni(prasanje, kontekst)  # probaj lekar
        if nejasno: return {"odgovor": nejasno, "kontekst": kontekst}    # poveke kandidati

        if lekar:                                                          # imame lekar → konkreten odgovor
            slobodni = pronajdi_slobodni_termini(lekar["doctor_ID"], na_datum=sleden)
            text = formatiraj_odgovor_preku_ai(lekar, slobodni, sleden, prasanje)
            return {"odgovor": text, "kontekst": {
                "zakazi_od_slobodni": {                                    # podgotovka za zakazhuvanje
                    "doctor_id": int(lekar["doctor_ID"]),
                    "datum": datum_za_zakazi_kontekst(sleden, slobodni)},
                "last_doctor_id": int(lekar["doctor_ID"])}}

        # Nema lekar → opsht odgovor (samo info za sledniот raboten den)
        return {"odgovor": (
            f"Следниот работен ден за закажување прегледи е "
            f"{_IMENA_DEN[sleden.weekday()]}, {format_datum(sleden)}.\n\n"
            f"Термини се закажуваат од понеделник до петок, "
            f"{format_vreme(RABOTNO_VREME_OD)}–{format_vreme(RABOTNO_VREME_DO)}. "
            "Во сабота и недела не се закажуваат прегледи.\n\n"
            "Кажи кај кој лекар сакаш термин (на пр. „следен работен ден кај Петров\") "
            "или повтори го името на лекарот од претходното барање."),
            "kontekst": kontekst}

    # ── SLUCAJ 1b: samo utochnuvanje na datum (zachuvan cas + oddel) ──
    if prasanje_e_utochnuvanje_datum(prasanje):
        baran_datum = izvleci_datum_za_slobodni(prasanje, kontekst)
        if baran_datum:
            zacuvano_vreme = vreme_iz_kontekst(kontekst)                  # cas od prethoden razgovor
            if zacuvano_vreme:                                             # ima cas → vraka „koj e sloboden vo X"
                pool, oddel = lekari_pool_za_ko_sloboden(prasanje, kontekst)
                tekst = odgovor_ko_e_sloboden_na_termin(prasanje, baran_datum,
                                                         zacuvano_vreme, kontekst)
                lekari = najdi_lekari_slobodni_na(baran_datum, zacuvano_vreme, lekari_pool=pool)
                ctx = _azuriraj_kontekst_ko_sloboden(kontekst, baran_datum, zacuvano_vreme,
                                                      lekari, oddel, pool)
                return {"odgovor": tekst, "kontekst": ctx}
            # Nema cas, no ima oddel → „slobodni za den po oddel"
            if _ima_oddel_lekari_kontekst(kontekst) or _oddel_od_kontekst(kontekst):
                return odgovor_slobodni_za_den_oddel(prasanje, baran_datum, kontekst)

    # ── SLUCAJ 2: „koj e sloboden..." (datum + vreme, bez lekar) ──
    if prasanje_e_ko_e_sloboden_datum_vreme(prasanje, kontekst):
        baran_datum = izvleci_datum_za_slobodni(prasanje, kontekst)
        barano_vreme = vreme_od_prasanje_lokalno(prasanje) or vreme_iz_kontekst(kontekst)
        oddel_ctx = _oddel_od_kontekst(kontekst)

        # Nema datum → pobaraj go (so primer)
        if not baran_datum:
            primer = ("„Кој од нив е слободен на 20.05 во 12:00\"" if oddel_ctx
                      else "„Кој е слободен во среда на 20.05 во 12:00\"")
            return {"odgovor": _MSG_FALI_DATUM_VREME.format(primer=primer),
                    "kontekst": kontekst}

        # Nema cas → pobaraj go (no prvo proba „slobodni za den po oddel")
        if not barano_vreme:
            if oddel_ctx and prasanje_e_baranje_slobodni(prasanje):
                return odgovor_slobodni_za_den_oddel(prasanje, baran_datum, kontekst)
            primer = ("„Кој од нив е слободен во 12:00\"" if oddel_ctx
                      else f"„Кој е слободен на {format_datum(baran_datum)} во 12:00\"")
            return {"odgovor": _MSG_FALI_VREME.format(datum=format_datum(baran_datum),
                                                       primer=primer),
                    "kontekst": kontekst}

        # Imame datum I cas → pokazhi lekari sho se slobodni
        pool, oddel = lekari_pool_za_ko_sloboden(prasanje, kontekst)
        tekst = odgovor_ko_e_sloboden_na_termin(prasanje, baran_datum, barano_vreme, kontekst)
        lekari = najdi_lekari_slobodni_na(baran_datum, barano_vreme, lekari_pool=pool)
        ctx = _azuriraj_kontekst_ko_sloboden(kontekst, baran_datum, barano_vreme,
                                              lekari, oddel, pool)
        return {"odgovor": tekst, "kontekst": ctx}

    # ── SLUCAJ 3: „slobodni na datum" po oddel (bez lekar) ──
    if prasanje_e_slobodni_po_oddel_datum(prasanje, kontekst):
        baran_datum = izvleci_datum_za_slobodni(prasanje, kontekst)
        if baran_datum:
            return odgovor_slobodni_za_den_oddel(prasanje, baran_datum, kontekst)

    # ── SLUCAJ 4 (standard): „koga e sloboden d-r X?" ──
    lekar, _, nejasno = resolviraj_lekar_za_slobodni(prasanje, kontekst)
    if nejasno: return {"odgovor": nejasno, "kontekst": kontekst}        # poveke kandidati

    # Nema lekar → razlichni greshki
    if not lekar:
        if prasanje_bar_lekar_od_kontekst(prasanje):
            return {"odgovor": _MSG_NEMA_IZBRAN_LEKAR_KONTEKST, "kontekst": kontekst}
        return _MSG_NE_RAZBRAV_LEKAR

    # Imame lekar → proveri slobodni i sochuvaj kontekst
    baran_datum = izvleci_datum_za_slobodni(prasanje, kontekst)
    slobodni = pronajdi_slobodni_termini(lekar["doctor_ID"], na_datum=baran_datum)
    text = formatiraj_odgovor_preku_ai(lekar, slobodni, baran_datum, prasanje)

    did = int(lekar["doctor_ID"])
    ctx = dict(kontekst) if isinstance(kontekst, dict) else {}
    # Podgotovka za vednash zakazhuvanje (frontend-ot ke го vrati kontekstот)
    ctx["zakazi_od_slobodni"] = {"doctor_id": did,
                                  "datum": datum_za_zakazi_kontekst(baran_datum, slobodni)}
    ctx["last_doctor_id"] = did                                            # default lekar za naredna poraka
    return {"odgovor": text, "kontekst": ctx}
