"""
slobodni_termini.py — AI handler за „слободни термини кај лекар".

Корисникот прашува „кога е слободен д-р X?" / „кој е слободен утре во 10:00?"
→ генерираме слотови (08:00-15:30, 30 мин, само пон-пет), отфрламе закажани
во базата (Termin_pregled), форматираме одговор на македонски.

Се користи од: handlers.py, routers/ai_chat.py, intent_detector.py,
opsto/info_lekar.py, opsto/lekari_oddel.py, opsto/preference_lekar.py,
pacient/moi_pregledi.py, oceni_pregled.py, trgni_ocena.py.
"""
import re
from datetime import date, time, datetime, timedelta
from typing import Any
from database import get_connection
from ai._kernel.db_helpers import db_cursor, fetch_all, normalize_int
from ai._kernel.groq_client import ask_ai
from ai._kernel.prompts import LEKAR_EXTRACT_PROMPT
from ai._kernel.transliteracija import transliterijaj
from ai._kernel.utils import format_datum, format_vreme

# ─── Константи: работно време + денови ───
RABOTNO_VREME_OD = time(8, 0)          # клиниката отвора во 08:00
RABOTNO_VREME_DO = time(16, 0)         # клиниката затвора во 16:00
TRAENJE_TERMIN_MINUTI = 30             # секој термин трае 30 мин
DENOVI_NAPRED = 7                      # колку денови гледаме напред (без датум)
MAX_TERMINI = 8                        # макс. термини во еден одговор

_DEN_WD = {"понеделник": 0, "вторник": 1, "среда": 2, "четврток": 3,
           "петок": 4, "сабота": 5, "недела": 6}
_DEN_ALT = "|".join(sorted(_DEN_WD.keys(), key=len, reverse=True))
_IMENA_DEN = ["понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"]

# ─── Regex-и за датум/ден/закажување ───
_RE_SLEDEN_RABOTEN_DEN = re.compile(
    r"(?:(?:следен|следниот|нареден|наредниот|прв)\s+работен\s+ден"
    r"|работен\s+ден\s+(?:следен|нареден|наредниот|следниот)"
    r"|кога\s+е\s+(?:следниот|наредниот|првиот)?\s*работен\s+ден)", re.UNICODE)
_SLEDEN_DEN_RE = re.compile(
    rf"(?:следниот|наредниот|следен|нареден|за)(?:\s+во)?\s+({_DEN_ALT}|\w+)", re.IGNORECASE)
_RE_ZA_VO_DEN = re.compile(r"(?:за\s+)?во\s+([a-zа-яѓќѕџјљњџ]{4,12})\s*$", re.IGNORECASE | re.UNICODE)
_OVAA_DEN_RE = re.compile(rf"(?:оваа|овиот|овој)\s+({_DEN_ALT})", re.IGNORECASE)
_KONTEXT_I_DEN_RE = re.compile(
    rf"(?:(?:слободен|слободна|слободни|слободно)\w*\s+(?:за\s+)?(?:во\s+)?"
    rf"|(?:термин(?:и)?)\s+(?:за\s+)?(?:во\s+)?"
    rf"|(?:има\s+ли)\s+(?:нешто\s+)?(?:слободни\s+)?(?:за\s+)?(?:во\s+)?"
    rf"|(?:дали\s+има)\s+(?:нешто\s+)?(?:слободни\s+)?(?:за\s+)?(?:во\s+)?)"
    rf"({_DEN_ALT}|\w{{4,12}})\b", re.IGNORECASE)
_DATUM_BROJ_RE = re.compile(r"(?:на|за)\s+(\d{1,2})[\./\-](\d{1,2})(?:[\./\-](\d{2,4}))?", re.IGNORECASE)
_ISO_DATUM_RE = re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b")
_MESECI_BROJ: dict[str, int] = {
    "јануари": 1, "januari": 1, "февруари": 2, "fevruari": 2, "март": 3, "mart": 3,
    "април": 4, "april": 4, "мај": 5, "maj": 5, "јуни": 6, "juni": 6,
    "јули": 7, "juli": 7, "август": 8, "avgust": 8, "септември": 9, "septemvri": 9,
    "октомври": 10, "oktomvri": 10, "ноември": 11, "декември": 12}
_ORDINAL_SUF = r"(?:ти|ри|ви|ti|ri|vi|-ti|-ri|-vi)?"
_RE_DAN_MES = re.compile(
    r"(?:на\s+)?(\d{1,2})" + _ORDINAL_SUF + r"\s*(?:\.)?\s*("
    + "|".join(sorted(_MESECI_BROJ.keys(), key=len, reverse=True)) + r")\b",
    re.UNICODE | re.IGNORECASE)
_KO_PRASANJE_RE = re.compile(r"\b(кој|која|кои|koj|koja|koi)\b", re.UNICODE | re.IGNORECASE)
_RE_ZAKAZUVANJE = re.compile(
    r"(?:зака[жз]\w*|zakaz\w*|може\s+да\s+(?:ми\s+)?зака[жз]|moze\s+da\s+(?:mi\s+)?zakaz"
    r"|можете\s+да\s+(?:ми\s+)?зака[жз]|да\s+ми\s+зака[жз]|da\s+mi\s+zakaz"
    r"|запиш\w*|zapish\w*|сакам\s+(?:да\s+)?(?:зака[жз]|оди|преглед)"
    r"|може\s+ли\s+зака[жз])", re.UNICODE | re.IGNORECASE)
_OD_NIV_SLOBODNI_MARKERS = (
    "од нив", "од овие", "од лекарите", "од горе", "од погоре", "од листата",
    "од тој оддел", "од одделот", "кој од нив", "кои од нив",
    "кој од лекарите", "кои од лекарите",
    "od niv", "od ovie", "od lekarite", "koj od niv", "koi od niv")

# ─── Готови error/info пораки (константи за пократок код) ───
_MSG_FALI_DATUM_VREME = ("За да проверам кој лекар е слободен, наведете датум и час.\n\nПример: {primer}.")
_MSG_FALI_VREME = "За {datum} наведете и час.\n\nПример: {primer}."
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

# ─── Парсирање ден/датум/час (локално, без AI) ───
def _den_od_tekst(tekst: str) -> str | None:
    """Од текст враќа име на ден („понеделник", …) или None."""
    t = transliterijaj(tekst or "").lower().strip()
    if not t: return None
    if t in _DEN_WD: return t
    alias = {"ponedel": "понеделник", "ponedelnik": "понеделник",
             "vtorni": "вторник", "vtornik": "вторник", "vtorik": "вторник",
             "sreda": "среда", "chetvrtok": "четврток",
             "petok": "петок", "sabota": "сабота", "nedela": "недела"}
    if t in alias: return alias[t]
    for ime in _DEN_WD:   # делумно совпаѓање (мин. 4 букви)
        if len(t) >= 4 and (ime.startswith(t) or t.startswith(ime[:4])): return ime
    return None

def _den_od_match(m: re.Match) -> str | None:
    """Од regex match → име на ден."""
    return _den_od_tekst(m.group(1) or "")

def _den_na_kraj_od_prasanje(p: str) -> str | None:
    """Ден на крајот од прашањето („… Захариев понеделник?"), само со контекст."""
    p2 = p.strip().rstrip("?!. ")
    kontekst_re = re.compile(
        r"\b(кога|слободен|слободна|слободни|слободно|термин|има\s+ли|"
        r"нареден|наредниот|наредна|следен|следниот|следна)\b", re.IGNORECASE)
    for ime in sorted(_DEN_WD.keys(), key=len, reverse=True):
        if not p2.endswith(ime): continue
        if kontekst_re.search(p2[: len(p2) - len(ime)]): return ime
    return None

def sleden_raboten_datum(denes: date | None = None) -> date:
    """Прв работен ден (пон–пет) после денес."""
    denes = denes or date.today()
    d = denes + timedelta(days=1)
    while d.weekday() >= 5: d += timedelta(days=1)   # прескокни саб./нед.
    return d

def _sleden_takov_kalendarski_den(denes: date, ime_den: str) -> date:
    """Прв ден со даденото име после денес („следниот вторник")."""
    days = (_DEN_WD[ime_den] - denes.weekday()) % 7
    if days == 0: days = 7   # денес е тој ден → следната недела
    return denes + timedelta(days=days)

def _ovaa_nedela_den(denes: date, ime_den: str) -> date:
    """Ден од тековната недела (или следна ако веќе помина)."""
    pocetok = denes - timedelta(days=denes.weekday())
    cand = pocetok + timedelta(days=_DEN_WD[ime_den])
    if cand < denes: cand += timedelta(days=7)
    return cand

def _mesec_od_tekst(tekst: str) -> int | None:
    """„мај"/„септември" → 1-12."""
    t = transliterijaj(tekst).lower().strip()
    if t in _MESECI_BROJ: return _MESECI_BROJ[t]
    for k, v in _MESECI_BROJ.items():
        if t.startswith(k[:3]) or k.startswith(t[:3]): return v
    return None

def _parsiraj_dd_mm_gggg(denes: date, d: int, m: int, g: int | None) -> date | None:
    """date(year, month, day) или None ако е невалиден/минатиот."""
    god = g if g is not None else denes.year
    if god < 100: god += 2000
    try: out = date(god, m, d)
    except ValueError: return None
    if out < denes:
        if g is None and m >= denes.month:
            try: out = date(denes.year + 1, m, d)
            except ValueError: return None
        elif out < denes: return None
    return out

def _parsiraj_dan_mesec(p: str, denes: date) -> date | None:
    """„20 мај", „на 1 јуни" → date."""
    m = _RE_DAN_MES.search(p)
    if not m: return None
    mesec = _mesec_od_tekst(m.group(2))
    if not mesec: return None
    return _parsiraj_dd_mm_gggg(denes, int(m.group(1)), mesec, None)

def datum_od_prasanje_lokalno(prasanje: str) -> date | None:
    """Локално (без AI) препознавање датум во прашањето."""
    p = transliterijaj(prasanje).lower()
    denes = date.today()
    if _RE_SLEDEN_RABOTEN_DEN.search(p): return sleden_raboten_datum(denes)
    if "задутре" in p or "задутра" in p: return denes + timedelta(days=2)
    if re.search(r"\bутре\b", p): return denes + timedelta(days=1)

    m = _ISO_DATUM_RE.search(prasanje)   # ISO: 2026-05-20
    if m:
        try:
            out = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return out if out >= denes else None
        except ValueError: pass

    dm = _parsiraj_dan_mesec(p, denes)   # „20 мај"
    if dm is not None: return dm

    m = _DATUM_BROJ_RE.search(p)   # „на 20.05"
    if m:
        g = int(m.group(3)) if m.group(3) else None
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

    ime_kraj = _den_na_kraj_od_prasanje(p)   # ден на крај („… Захариев понеделник?")
    if ime_kraj: return _sleden_takov_kalendarski_den(denes, ime_kraj)
    return None

def vreme_od_prasanje_lokalno(prasanje: str) -> str | None:
    """Час: „12:00", „во 12 часот", „12.30" → „HH:MM" или None."""
    p = transliterijaj(prasanje or "").lower().strip()
    if not p: return None
    m = re.search(r"\b(\d{1,2})\s*[:.]\s*(\d{2})\b", p)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59: return f"{h:02d}:{mi:02d}"
    m = re.search(r"(?:во|vo|at)\s+(\d{1,2})(?:\s*(?:час|часот|cas|casot))?\b", p)
    if m and 0 <= (h := int(m.group(1))) <= 23: return f"{h:02d}:00"
    m = re.search(r"\b(\d{1,2})\s*(?:час|часот|cas|casot)\b", p)
    if m and 0 <= (h := int(m.group(1))) <= 23: return f"{h:02d}:00"
    return None

# ─── Intent детекција ───
def prasanje_e_sleden_raboten_den(prasanje: str) -> bool:
    """„Кога е следниот работен ден?"."""
    return bool(_RE_SLEDEN_RABOTEN_DEN.search(transliterijaj(prasanje).lower()))

def prasanje_e_baranje_slobodni(prasanje: str) -> bool:
    """Дали прашањето бара СЛОБОДНИ термини (не закажување)?"""
    p = transliterijaj(prasanje).lower()
    if any(x in p for x in ("слобод", "slobod")): return True
    if "термин" in p or "termin" in p:
        if any(x in p for x in ("има", "дали", "кога", "слобод", "slobod",
                                "провери", "proveri", "на ", " na ", "за ", " za ")):
            return True
        try:
            from ai.pacient.moi_pregledi import datum_za_pregledi_od_prasanje
            if datum_za_pregledi_od_prasanje(prasanje): return True
        except ImportError:
            if datum_od_prasanje_lokalno(prasanje): return True
    if re.search(r"\b(преглед|pregled)\w*\b", p) and (
        "слобод" in p or "slobod" in p or "провери" in p or "proveri" in p): return True
    return False

def prasanje_e_slobodni_za_den(prasanje: str, kontekst: dict | None = None) -> bool:
    """„За во вторник" / „ама за вторник" — нов ден кај истиот лекар."""
    if baranje_e_zakazuvanje(prasanje): return False
    if not datum_od_prasanje_lokalno(prasanje): return False
    if prasanje_e_baranje_slobodni(prasanje): return True
    if isinstance(kontekst, dict) and kontekst.get("zakazi_od_slobodni"):
        p = transliterijaj(prasanje).lower()
        if re.search(r"\b\d{1,2}\s*[:.]\s*\d{2}\b", p): return False   # има час → друго
        return True
    return False

def prasanje_bar_lekar_od_kontekst(prasanje: str) -> bool:
    """„Избраниот/истиот лекар" — лекарот е во контекст од претходна порака."""
    p = transliterijaj(prasanje).lower()
    return any(x in p for x in (
        "избраниот лекар", "избраниот", "избраниов", "избран лекар",
        "истиот лекар", "истиот", "истиов", "погоре", "од листата",
        "од горе", "тогој лекар", "тој лекар", "го избрав", "izbraniot", "istiot"))

def prasanje_e_otkazuvanje(prasanje: str) -> bool:
    """Откажување на термин?"""
    p = transliterijaj(prasanje).lower()
    if "откаж" in p or "otkaz" in p: return True
    if "cancel" in p and "termin" in p: return True
    return any(x in p for x in ("сторнира", "поништи термин", "не доаѓам", "не сакам термин"))

def baranje_e_zakazuvanje(prasanje: str) -> bool:
    """Закажување (а не повторна проверка на слободни)?"""
    raw = (prasanje or "").lower()
    q = transliterijaj(prasanje).lower()
    if _RE_ZAKAZUVANJE.search(q) or _RE_ZAKAZUVANJE.search(raw):
        # ако има „слобод/кога/има ли/провери/наредно/следно" → тоа е ПРОВЕРКА
        if not any(w in q for w in ("слобод", "кога е", "има ли", "провери",
                                     "провер", "наредн", "следн")):
            return True
    # има час (10:00) + клучен збор → најверојатно закажување
    if re.search(r"\b\d{1,2}\s*[:.]\s*\d{2}\b", q):
        if any(x in q or x in raw for x in ("закаж", "заказ", "zakaz", "термин", "преглед",
                                             "може да закаж", "може да заказ", "moze da zakaz")):
            return True
    return False

def prasanje_bar_datum_od_kontekst(prasanje: str) -> bool:
    """„Претходниот/избраниот датум" — датумот е во контекст."""
    p = transliterijaj(prasanje).lower()
    return any(x in p for x in (
        "избраниот датум", "избрана дата", "избраниот", "претходно спомнати",
        "претходно", "претходниот", "спомнатиот датум", "спомнатиот",
        "истиот датум", "наведениот датум", "тогаш спомнати",
        "pretходно", "spomnat", "izbraniot datum"))

def prasanje_e_drugi_lekari_specijalnost(prasanje: str) -> bool:
    """„Кои други лекари од истата специјалност" — продолжување по оддел."""
    p = transliterijaj(prasanje).lower()
    ima_spec = any(x in p for x in ("специјалност", "специјалности", "оддел",
                                     "истата", "иста ", "оваа", "ова ", "истиот", "истиов",
                                     "specijalnost", "oddel", "istata", "ista ", "ovaa", "ova "))
    ima_lekari = any(x in p for x in ("лекари", "lekari", "доктори", "doktori"))

    if ima_lekari and ima_spec:
        if any(x in p for x in ("истата", "иста ", "оваа", "ова ",
                                 "istata", "ista ", "ovaa", "ova ")): return True
        if "од " in p and any(x in p for x in
                              ("специјалност", "specijalnost", "оддел", "oddel")): return True

    if not any(x in p for x in ("други", "друг ", "друга ", "уште", "останати",
                                 "drugi", "drug ", "ushte", "останати")): return False
    if not any(x in p for x in ("лекар", "лекари", "доктор", "lekari", "doktor")): return False
    return ima_spec

def prasanje_e_specijalnost_izbran_lekar(prasanje: str, kontekst: dict | None = None) -> bool:
    """„Која е специјалноста на избраниот лекар?" — info за конкретен лекар."""
    if prasanje_e_drugi_lekari_specijalnost(prasanje): return False
    if prasanje_e_baranje_slobodni(prasanje): return False

    p = transliterijaj(prasanje).lower()
    if not any(x in p for x in ("област", "специјалност", "оддел", "каде работи",
                                 "која е", "кое е", "од која", "koja oblast", "vo koja",
                                 "specijalnost", "oblast", "oddel")): return False

    if prasanje_bar_lekar_od_kontekst(prasanje): return True
    if any(x in p for x in ("избран", "истиот", "погоре", "тој лекар", "togo lekar")): return True
    if any(x in p for x in ("лекари", "lekari", "доктори", "doktori")): return False

    # има лекар во контекст + збор „лекарот/докторот"
    if lekar_od_zakazi_kontekst(kontekst) and any(x in p for x in (
        "лекарот", "лекар ", " лекар", "д-р", " др",
        "докторот", "доктор ", "toj lekar", "togo lekar")): return True
    return False

def prasanje_bar_site_lekari_za_slobodni(prasanje: str) -> bool:
    """Корисникот сака слободни кај СИТЕ лекари во болницата."""
    p = transliterijaj(prasanje).lower()
    return any(x in p for x in ("на болницата", "во болницата", "во целата", "целата болница",
                                 "кај било кој", "било кој лекар", "сите лекари",
                                 "site lekari", "celata bolnica"))

def prasanje_e_od_niv_sloboden(prasanje: str) -> bool:
    """„Кој од нив е слободен..." — продолжување по листа лекари од оддел."""
    p = transliterijaj(prasanje).lower()
    if "слобод" not in p and "slobod" not in p: return False
    return any(m in p for m in _OD_NIV_SLOBODNI_MARKERS)

def _ima_oddel_lekari_kontekst(kontekst: dict | None) -> bool:
    """Дали во контекст е зачувана листа лекари од оддел?"""
    if not isinstance(kontekst, dict): return False
    ids = kontekst.get("last_oddel_doctor_ids")
    return isinstance(ids, list) and len(ids) > 0

def prasanje_e_ko_e_sloboden_datum_vreme(prasanje: str, kontekst: dict | None = None) -> bool:
    """„Кој е слободен на 25.05 во 12:00?" — без конкретен лекар."""
    p = transliterijaj(prasanje).lower()
    if "слобод" not in p and "slobod" not in p: return False

    from ai._kernel.lekar_lookup import prasanje_ukazuva_kon_konkreten_lekar

    if _ima_oddel_lekari_kontekst(kontekst) and (
        prasanje_e_od_niv_sloboden(prasanje)
        or (_KO_PRASANJE_RE.search(p) and _oddel_od_kontekst(kontekst))
        or (prasanje_e_baranje_slobodni(prasanje)
            and datum_od_prasanje_lokalno(prasanje)
            and not vreme_od_prasanje_lokalno(prasanje)
            and not prasanje_ukazuva_kon_konkreten_lekar(prasanje))
    ): return True

    baran_datum = datum_od_prasanje_lokalno(prasanje)
    barano_vreme = vreme_od_prasanje_lokalno(prasanje)
    if not baran_datum and not barano_vreme: return False
    if _KO_PRASANJE_RE.search(p): return True

    if baran_datum and barano_vreme:
        from ai._kernel.lekar_lookup import izvlechi_delovi_ime, najdi_lekar_od_delovi
        delovi = izvlechi_delovi_ime(prasanje)
        if not delovi or not najdi_lekar_od_delovi(delovi): return True
    return False

def prasanje_e_utochnuvanje_datum(prasanje: str) -> bool:
    """„Наредниот петок" после претходно „кој е слободен..." — само нов датум."""
    p = transliterijaj(prasanje).lower().strip()
    if not p or len(p) > 70: return False
    if not datum_od_prasanje_lokalno(prasanje): return False
    if baranje_e_zakazuvanje(prasanje): return False

    from ai._kernel.lekar_lookup import prasanje_ukazuva_kon_konkreten_lekar
    if prasanje_ukazuva_kon_konkreten_lekar(prasanje): return False
    if _KO_PRASANJE_RE.search(p): return False
    if "слобод" in p or "slobod" in p: return False
    if re.search(r"\b(?:кај|kaj)\s+", p, re.UNICODE): return False
    return True

def prasanje_e_slobodni_po_oddel_datum(prasanje: str, kontekst: dict | None = None) -> bool:
    """„Слободни термини на 25 мај" по листа лекари од оддел (без име)."""
    if not _ima_oddel_lekari_kontekst(kontekst): return False
    if baranje_e_zakazuvanje(prasanje): return False
    if not prasanje_e_baranje_slobodni(prasanje): return False
    if not datum_od_prasanje_lokalno(prasanje): return False
    if vreme_od_prasanje_lokalno(prasanje): return False

    from ai._kernel.lekar_lookup import najdi_lekar_od_prasanje
    if najdi_lekar_od_prasanje(prasanje): return False
    ids = kontekst.get("last_oddel_doctor_ids") if isinstance(kontekst, dict) else []
    return isinstance(ids, list) and len(ids) > 1

# ─── Лекари од база + AI lookup ───
def zimi_site_lekari() -> list[dict[str, Any]]:
    """Сите лекари од базата."""
    try:
        with db_cursor() as (_, cur):
            cur.execute("SELECT doctor_ID, name, surname, specialty, email FROM Doctors "
                        "ORDER BY surname, name")
            return fetch_all(cur)
    except Exception as e:
        print(f"[slobodni_termini] Greshka pri zimanje na lekari: {e}")
        return []

def zimi_lekari_po_specialty(specialty: str) -> list[dict[str, Any]]:
    """Лекари само од дадена специјалност (оддел)."""
    if not (specialty or "").strip(): return []
    try:
        with db_cursor() as (_, cur):
            cur.execute(
                "SELECT doctor_ID, name, surname, specialty, email FROM Doctors "
                "WHERE LOWER(TRIM(specialty)) = LOWER(TRIM(%s)) ORDER BY surname, name",
                (specialty.strip(),))
            return fetch_all(cur)
    except Exception as e:
        print(f"[slobodni_termini] lekari po specialty greska: {e}")
        return []

def najdi_lekar_so_ai(prasanje: str) -> dict | None:
    """Прашува Groq „од прашањето кој лекар се однесува?" со листа сите лекари."""
    from ai._kernel.groq_helpers import groq_zadolzhitelen
    if groq_zadolzhitelen(): return None

    site = zimi_site_lekari()
    if not site: return None

    lista_text = "".join(
        f"ID {l['doctor_ID']}: Д-р {l['name']} {l['surname']} - "
        f"{l.get('specialty') or 'Општа пракса'}\n" for l in site)
    prompt = (f"Листа на лекари во болницата:\n{lista_text}\n"
              f"Прашање од корисникот: „{prasanje}\"\n"
              "За кој лекар се однесува прашањето (слободни термини, закажување, преглед)?\n"
              "Име може да биде нецелосно или на латиница. Ако се спомнуваат повеќе лекари, "
              "земи го најрелевантниот.\nВрати само ID број или NONE.")

    cist = ask_ai(prompt, system_prompt=LEKAR_EXTRACT_PROMPT).strip().upper().replace(".", "").replace(",", "")
    if "NONE" in cist: return None
    match = re.search(r"\d+", cist)
    if not match: return None
    doctor_id = int(match.group())
    for l in site:
        if l["doctor_ID"] == doctor_id: return l
    return None

# ─── Контекст helper-и ───
def _oddel_od_kontekst(kontekst: dict | None) -> str | None:
    """Име на оддел зачувано во контекст или None."""
    if not isinstance(kontekst, dict): return None
    for key in ("last_oddel", "oddel", "specialty"):
        val = kontekst.get(key)
        if val and str(val).strip(): return str(val).strip()
    return None

def datum_od_zakazi_kontekst(kontekst: dict | None) -> date | None:
    """Датум зачуван во контекст (по листа слободни / pending закажување)."""
    if not isinstance(kontekst, dict): return None
    for key in ("zakazi_od_slobodni", "zakazi_pending"):
        z = kontekst.get(key)
        if not isinstance(z, dict) or not z.get("datum"): continue
        try: return datetime.strptime(str(z["datum"]).strip()[:10], "%Y-%m-%d").date()
        except ValueError: continue
    return None

def vreme_iz_kontekst(kontekst: dict | None) -> str | None:
    """Зачуван час од претходна порака „кој е слободен во X"."""
    if not isinstance(kontekst, dict): return None
    v = (kontekst.get("last_slobodni_vreme") or "").strip()
    if v: return v
    z = kontekst.get("zakazi_od_slobodni")
    if isinstance(z, dict):
        v = (z.get("vreme") or "").strip()
        if v: return v
    return None

def lekar_od_zakazi_kontekst(kontekst: dict | None) -> dict | None:
    """Лекар од контекст (zakazi_od_slobodni / zakazi_pending / last_doctor_id)."""
    if not kontekst: return None
    doctor_id = None
    zos = kontekst.get("zakazi_od_slobodni")
    if not isinstance(zos, dict): zos = kontekst.get("zakazi_pending")
    if isinstance(zos, dict): doctor_id = normalize_int(zos.get("doctor_id"))
    if doctor_id is None: doctor_id = normalize_int(kontekst.get("last_doctor_id"))
    if doctor_id is None: return None
    for l in zimi_site_lekari():
        if int(l["doctor_ID"]) == doctor_id: return l
    return None

def lekar_od_oddel_kontekst(kontekst: dict | None) -> dict | None:
    """Лекар ако во контекст има ТОЧНО еден лекар од оддел."""
    if not isinstance(kontekst, dict): return None
    ids = kontekst.get("last_oddel_doctor_ids")
    if not isinstance(ids, list) or len(ids) != 1: return None
    try: did = int(ids[0])
    except (TypeError, ValueError): return None
    for l in zimi_site_lekari():
        if int(l["doctor_ID"]) == did: return l
    return None

def lekar_iz_izbran_kontekst(kontekst: dict | None) -> dict | None:
    """Лекар од претходна порака: прв zakazi, па oddel."""
    return lekar_od_zakazi_kontekst(kontekst) or lekar_od_oddel_kontekst(kontekst)

def _poraka_izberi_lekar_od_lista(kontekst: dict) -> str:
    """Помошна порака кога има повеќе лекари од листа по оддел."""
    ids = kontekst.get("last_oddel_doctor_ids")
    if not isinstance(ids, list) or len(ids) < 2: return ""
    id_set: set[int] = set()
    for raw in ids:
        try: id_set.add(int(raw))
        except (TypeError, ValueError): continue

    iminja: list[str] = []
    for l in zimi_site_lekari():
        if int(l["doctor_ID"]) in id_set:
            ime = (l.get("name") or "").strip()
            prezime = (l.get("surname") or "").strip()
            if ime or prezime: iminja.append(f"д-р {ime} {prezime}".strip())
    if not iminja: return ""

    lista = ", ".join(iminja[:8])
    oddel = (kontekst.get("last_oddel") or "").strip()
    uvod = f"На одделот {oddel} " if oddel else "Од претходната листа "
    return (f"{uvod}има повеќе лекари ({lista}).\n\n"
            "Наведете го лекарот по име (на пр. „Кога е слободен д-р Марко Петров?“) "
            "или прашајте „кој од нив е слободен утре?“.")

# ─── Resolve лекар + pool за „кој е слободен" ───
def resolviraj_lekar_za_slobodni(
    prasanje: str, kontekst: dict | None
) -> tuple[dict | None, bool, str | None]:
    """Враќа (лекар или None, дали е од контекст, опц. порака за избор)."""
    if prasanje_bar_lekar_od_kontekst(prasanje):
        lekar = lekar_iz_izbran_kontekst(kontekst)
        if not lekar and isinstance(kontekst, dict):
            poraka = _poraka_izberi_lekar_od_lista(kontekst)
            if poraka: return None, False, poraka
        return lekar, lekar is not None, None

    from ai._kernel.lekar_lookup import (
        izvlechi_delovi_ime, najdi_lekar_od_prasanje, najdi_lekari_po_delovi,
        najdi_lekari_po_prezime, poraka_za_vise_lekari, prezime_na_pocetok_od_prasanje)

    prezime_poc = prezime_na_pocetok_od_prasanje(prasanje)
    if prezime_poc:
        kandidati = najdi_lekari_po_prezime(prezime_poc)
        if len(kandidati) == 1: return kandidati[0], False, None
        if len(kandidati) > 1: return None, False, poraka_za_vise_lekari(kandidati, [prezime_poc])

    delovi = izvlechi_delovi_ime(prasanje)
    kandidati = najdi_lekari_po_delovi(delovi)
    if len(kandidati) > 1: return None, False, poraka_za_vise_lekari(kandidati, delovi)

    lekar = najdi_lekar_od_prasanje(prasanje)
    if lekar: return lekar, False, None

    lekar = lekar_od_zakazi_kontekst(kontekst)
    if lekar: return lekar, True, None

    if prasanje_e_baranje_slobodni(prasanje) and datum_od_prasanje_lokalno(prasanje):
        lekar = lekar_od_oddel_kontekst(kontekst)
        if lekar: return lekar, True, None
    return None, False, None

def lekari_pool_za_ko_sloboden(
    prasanje: str, kontekst: dict | None
) -> tuple[list[dict] | None, str | None]:
    """Кои лекари да се проверат за „кој е слободен". pool=None → сите."""
    if prasanje_bar_site_lekari_za_slobodni(prasanje): return None, None

    from ai._kernel.oddel_resolver import resolve_oddel
    resolved = resolve_oddel(prasanje)
    if resolved and resolved.ok and resolved.oddel:
        return zimi_lekari_po_specialty(resolved.oddel), resolved.oddel

    if not isinstance(kontekst, dict): return None, None

    oddel = _oddel_od_kontekst(kontekst)
    ids = kontekst.get("last_oddel_doctor_ids")
    if isinstance(ids, list) and ids:
        id_set = {int(x) for x in ids}
        pool = [l for l in zimi_site_lekari() if int(l["doctor_ID"]) in id_set]
        if pool: return pool, oddel
    if oddel:
        pool = zimi_lekari_po_specialty(oddel)
        if pool: return pool, oddel
    return None, None

# ─── Слотови + зафатени термини ───
def generiraj_slotovi_za_den(datum: date) -> list[datetime]:
    """30-мин слотови за работен ден (08:00 → 15:30). [] за саб./нед."""
    if datum.weekday() >= 5: return []
    slotovi = []
    momentalno = datetime.combine(datum, RABOTNO_VREME_OD)
    kraj = datetime.combine(datum, RABOTNO_VREME_DO)
    while momentalno < kraj:
        slotovi.append(momentalno)
        momentalno += timedelta(minutes=TRAENJE_TERMIN_MINUTI)
    return slotovi

def najdi_zafateni_slotovi(doctor_id: int, od_datum: date, do_datum: date) -> set:
    """Set од (datum, vreme) што се ВЕЌЕ закажани за лекар во интервал."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT DATE(datum_pregled) AS dp, "
            "TIME_FORMAT(TIME(vreme_pregled), '%H:%i') AS vp FROM Termin_pregled "
            "WHERE doctor_ID = %s AND DATE(datum_pregled) BETWEEN %s AND %s "
            "AND status_pregled NOT IN ('откажан', 'отказан')",
            (doctor_id, od_datum, do_datum))
        rezultati = cur.fetchall()
        cur.close()

        zafateni: set[tuple[date, time]] = set()
        for r in rezultati:
            d_raw, t_raw = r.get("dp"), r.get("vp")
            if d_raw is None or t_raw is None: continue

            # парсирање ДАТУМ → date
            if isinstance(d_raw, datetime): datum = d_raw.date()
            elif isinstance(d_raw, date): datum = d_raw
            elif isinstance(d_raw, (bytes, bytearray)):
                try: datum = datetime.strptime(d_raw.decode("utf-8", errors="ignore")[:10],
                                                "%Y-%m-%d").date()
                except ValueError: continue
            elif isinstance(d_raw, str):
                try: datum = datetime.strptime(d_raw.strip()[:10], "%Y-%m-%d").date()
                except ValueError: continue
            else: continue

            # парсирање ВРЕМЕ → time (без секунди)
            vreme: time | None = None
            if isinstance(t_raw, time): vreme = time(t_raw.hour, t_raw.minute)
            elif isinstance(t_raw, timedelta):
                vk = int(t_raw.total_seconds())
                vreme = time((vk // 3600) % 24, (vk % 3600) // 60)
            elif isinstance(t_raw, (bytes, bytearray)):
                t_raw = t_raw.decode("utf-8", errors="ignore").strip()
            if vreme is None and isinstance(t_raw, str):
                parts = t_raw.replace(".", ":").split(":")
                try: vreme = time(int(parts[0]), int(parts[1]))
                except (ValueError, IndexError): continue
            if vreme is None: continue
            zafateni.add((datum, vreme))
        return zafateni
    except Exception as e:
        print(f"[slobodni_termini] Greshka pri barebje zafateni: {e}")
        return set()
    finally:
        if conn: conn.close()

def pronajdi_slobodni_termini(doctor_id: int, na_datum: date | None = None) -> list[datetime]:
    """
    Слободни слотови за лекар:
      - ако `na_datum` е даден: само за тој ден
      - иначе: првите MAX_TERMINI термини во следните DENOVI_NAPRED дена.
    """
    denes = date.today()
    if na_datum is not None and na_datum < denes: na_datum = None

    if na_datum is not None:   # конкретен датум
        if na_datum.weekday() >= 5: return []
        zafateni = najdi_zafateni_slotovi(doctor_id, na_datum, na_datum)
        slobodni: list[datetime] = []
        for slot_dt in generiraj_slotovi_za_den(na_datum):
            if slot_dt < datetime.now(): continue
            sv = time(slot_dt.time().hour, slot_dt.time().minute)
            if (na_datum, sv) not in zafateni: slobodni.append(slot_dt)
        return slobodni

    # опсег денес + DENOVI_NAPRED
    do_datum = denes + timedelta(days=DENOVI_NAPRED)
    zafateni = najdi_zafateni_slotovi(doctor_id, denes, do_datum)
    slobodni = []
    for offset in range(DENOVI_NAPRED + 1):
        datum = denes + timedelta(days=offset)
        for slot_dt in generiraj_slotovi_za_den(datum):
            if slot_dt < datetime.now(): continue
            sv = time(slot_dt.time().hour, slot_dt.time().minute)
            if (datum, sv) not in zafateni:
                slobodni.append(slot_dt)
                if len(slobodni) >= MAX_TERMINI: return slobodni
    return slobodni

def termin_sloboden_na_datum_vreme(doctor_id: int, na_datum: date, vreme_str: str) -> bool:
    """Дали лекар е слободен на даден датум и час?"""
    if na_datum.weekday() >= 5: return False
    try:
        h_s, m_s = vreme_str.strip().split(":")[:2]
        t = time(int(h_s), int(m_s))
    except (ValueError, TypeError): return False

    slotovi = generiraj_slotovi_za_den(na_datum)
    if not any(s.time().hour == t.hour and s.time().minute == t.minute for s in slotovi):
        return False
    if datetime.combine(na_datum, t) < datetime.now(): return False
    zafateni = najdi_zafateni_slotovi(doctor_id, na_datum, na_datum)
    return (na_datum, time(t.hour, t.minute)) not in zafateni

def lekar_sloboden_na_termin(lekar: dict, na_datum: date, vreme_str: str) -> bool:
    """Wrapper за `termin_sloboden_na_datum_vreme`."""
    return termin_sloboden_na_datum_vreme(int(lekar["doctor_ID"]), na_datum, vreme_str)

def najdi_lekari_slobodni_na(
    na_datum: date, vreme_str: str, lekari_pool: list[dict] | None = None
) -> list[dict]:
    """Листа лекари што се слободни на даден датум и час."""
    slobodni = [l for l in (lekari_pool if lekari_pool is not None else zimi_site_lekari())
                if lekar_sloboden_na_termin(l, na_datum, vreme_str)]
    return sorted(slobodni, key=lambda x: (x.get("surname") or "", x.get("name") or ""))

# ─── Форматирање одговор за корисник ───
def _cas_vo_minuti(cas_str: str) -> int:
    """„09:30" → 570 минути од почеток на ден."""
    h, m = map(int, cas_str.split(":"))
    return h * 60 + m

def _kluc_period_za_cas(cas_str: str) -> str:
    """Период: „рано наутро / околу пладне / попладне"."""
    mins = _cas_vo_minuti(cas_str)
    if mins < 10 * 60: return "ran_nautro"
    if mins < 14 * 60: return "okolu_pladne"
    return "popladne"

_PERIOD_NASLOVI = {"ran_nautro": "Ран наутро", "okolu_pladne": "Околу пладне", "popladne": "Попладне"}
_PERIOD_REDO = ("ran_nautro", "okolu_pladne", "popladne")

def _opis_raspon_termini(casovi: list[str]) -> str:
    """Краток опис каде се слотовите („претпладне", „попладне", …)."""
    if not casovi: return ""
    mins = [_cas_vo_minuti(c) for c in casovi]
    min_m, max_m = min(mins), max(mins)
    if max_m <= 12 * 60 + 30: return "во текот на целото претпладне"
    if min_m >= 14 * 60: return "попладне"
    if min_m < 10 * 60 and max_m >= 14 * 60: return "низ целиот работен ден"
    if min_m >= 10 * 60 and max_m < 14 * 60: return "претпладне"
    return "во текот на работниот ден"

def _formatiraj_casovi_po_periodi(casovi: list[str]) -> list[str]:
    """Редови „Ран наутро: 08:30 | 09:00"."""
    po_period: dict[str, list[str]] = {}
    for cas in casovi:
        po_period.setdefault(_kluc_period_za_cas(cas), []).append(cas)
    redici: list[str] = []
    for kluc in _PERIOD_REDO:
        if kluc not in po_period: continue
        if redici: redici.append("")
        redici.append(f"{_PERIOD_NASLOVI[kluc]}: {' | '.join(po_period[kluc])}")
    return redici

def _formatiraj_den_lekar(lekar: dict, casovi: list[str], datum: date, weekday: int,
                           denovi: list[str]) -> str:
    """Еден ден: вовед + групирани часови."""
    ime = f"{lekar['name']} {lekar['surname']}"
    spec = lekar.get("specialty") or "Општа пракса"
    return "\n".join([
        f"За {denovi[weekday].lower()} ({format_datum(datum)}), кај д-р {ime} "
        f"({spec}) има слободни термини {_opis_raspon_termini(casovi)}:", "",
        *_formatiraj_casovi_po_periodi(casovi)])

def _footer_za_zakazuvanje(eden_datum: bool) -> str:
    """Кратко упатство по листа на слободни термини."""
    if eden_datum:
        return ("\n\nКажете ми кој од овие термини најмногу ви одговара "
                "(на пример: „Закажи во 09:30\").\nЗа друг работен ден — наведете нова дата.")
    return "\n\nКажете ми датум, час и лекар (на пример: „Закажи кај Петров во 10:00\")."

def formatiraj_odgovor(lekar: dict, slobodni: list[datetime],
                       na_datum: date | None = None) -> str:
    """Финална порака на македонски, групирано по ден."""
    DENOVI = ["Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"]
    ime = f"д-р {lekar['name']} {lekar['surname']}"
    spec = lekar.get("specialty") or "Општа пракса"
    zaglavie = f"{ime} ({spec})"

    if not slobodni:
        if na_datum is not None and na_datum.weekday() >= 5:
            return (f"Кај {zaglavie}, {format_datum(na_datum)} е викенд — прегледи се само "
                    "во работни денови.\n\nНаведете работен ден (на пр. „следниот "
                    "понеделник\") или прашајте без датум.")
        if na_datum is not None:
            return (f"За {DENOVI[na_datum.weekday()].lower()} ({format_datum(na_datum)}), "
                    f"кај {zaglavie} нема слободни термини.\n\nНаведете друга дата за "
                    "нова проверка или прашајте без конкретен датум.")
        return (f"Кај {zaglavie} за избраниот период нема слободни термини.\n\n"
                "Пробајте друг ден или друг лекар, или наведете конкретен датум и време.")

    po_den: dict[tuple[date, int], list[str]] = {}
    for dt in slobodni:
        po_den.setdefault((dt.date(), dt.weekday()), []).append(format_vreme(dt))

    if len(po_den) == 1:
        (datum, wd), casovi = next(iter(po_den.items()))
        return _formatiraj_den_lekar(lekar, casovi, datum, wd, DENOVI) + \
               _footer_za_zakazuvanje(eden_datum=True)

    delovi: list[str] = []
    for (datum, wd), casovi in po_den.items():
        if delovi: delovi.append("")
        delovi.append(_formatiraj_den_lekar(lekar, casovi, datum, wd, DENOVI))
    delovi.append(_footer_za_zakazuvanje(eden_datum=False))
    return "\n".join(delovi)

def formatiraj_odgovor_preku_ai(lekar: dict, slobodni: list[datetime],
                                  na_datum: date | None, prasanje: str) -> str:
    """Wrapper: засега делегира на локалниот форматер."""
    return formatiraj_odgovor(lekar, slobodni, na_datum=na_datum)

# ─── Одговори „кој е слободен" / „слободни по оддел" ───
def odgovor_slobodni_za_den_oddel(prasanje: str, na_datum: date,
                                    kontekst: dict | None) -> dict:
    """Слободни термини за СИТЕ лекари од оддел (од контекст)."""
    pool, oddel = lekari_pool_za_ko_sloboden(prasanje, kontekst)
    if not pool and isinstance(kontekst, dict):
        ids = kontekst.get("last_oddel_doctor_ids") or []
        id_set = {int(x) for x in ids}
        pool = [l for l in zimi_site_lekari() if int(l["doctor_ID"]) in id_set]

    den_ime = _IMENA_DEN[na_datum.weekday()].lower()
    datum_fmt = format_datum(na_datum)

    if na_datum.weekday() >= 5:
        return {"odgovor": f"На {den_ime}, {datum_fmt} е викенд — прегледи се само "
                "во работни денови.", "kontekst": kontekst}

    if oddel:
        linii = [f"Слободни термини на {den_ime}, {datum_fmt} — оддел „{oddel}“:", ""]
    else:
        linii = [f"Слободни термини на {den_ime}, {datum_fmt}:", ""]

    if not pool:
        linii.append("Немам зачувана листа лекари од претходната порака.")
        return {"odgovor": "\n".join(linii), "kontekst": kontekst}

    prv: dict | None = None
    for l in pool:
        slobodni = pronajdi_slobodni_termini(int(l["doctor_ID"]), na_datum=na_datum)
        ime = f"д-р {l.get('name', '')} {l.get('surname', '')}".strip()
        if slobodni:
            if prv is None: prv = l
            casovi = [format_vreme(dt) for dt in slobodni[:12]]
            extra = f" (+{len(slobodni) - 12} уште)" if len(slobodni) > 12 else ""
            linii.append(f"• {ime}: {', '.join(casovi)}{extra}")
        else:
            linii.append(f"• {ime}: нема слободни термини")
    linii.extend(["", "За закажување: „закажи кај [презиме] во [час]“ — датумот се зачувува."])

    ctx = dict(kontekst) if isinstance(kontekst, dict) else {}
    ctx["last_slobodni_datum"] = na_datum.strftime("%Y-%m-%d")
    if oddel:
        ctx["last_oddel"] = oddel
        ctx["last_oddel_doctor_ids"] = [int(l["doctor_ID"]) for l in pool]
    if prv:
        ctx["last_doctor_id"] = int(prv["doctor_ID"])
        ctx["zakazi_od_slobodni"] = {"doctor_id": int(prv["doctor_ID"]),
                                      "datum": na_datum.strftime("%Y-%m-%d")}
    return {"odgovor": "\n".join(linii), "kontekst": ctx}

def odgovor_ko_e_sloboden_na_termin(prasanje: str, na_datum: date, vreme_str: str,
                                     kontekst: dict | None = None) -> str:
    """Листа лекари што се слободни на конкретен датум и час."""
    den_ime = _IMENA_DEN[na_datum.weekday()].lower()
    datum_fmt = format_datum(na_datum)
    pool, oddel = lekari_pool_za_ko_sloboden(prasanje, kontekst)
    lekari = najdi_lekari_slobodni_na(na_datum, vreme_str, lekari_pool=pool)
    rv_od, rv_do = format_vreme(RABOTNO_VREME_OD), format_vreme(RABOTNO_VREME_DO)

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

    if not lekari: return prazen

    linii = [naslov, ""]
    for l in lekari:
        spec = (l.get("specialty") or "Општа пракса").strip()
        linii.append(f"- Д-р {l['name']} {l['surname']} ({spec})")

    if oddel:
        hint = (f"За закажување на {datum_fmt} во {vreme_str} напишете, на пр.:\n"
                f"„закажи кај {lekari[0]['surname']}\" или „може да ми закажете кај "
                f"{lekari[0]['surname']}\".\n(Датумот и часот од погоре се зачувуваат автоматски.)")
    else:
        hint = (f"За закажување наведете лекар, на пр.: „закажи кај {lekari[0]['surname']} "
                f"во {vreme_str}\".")
    linii.extend(["", hint])
    return "\n".join(linii)

# ─── AI fallback за датум + ажурирање контекст ───
def _datum_od_prasanje_so_ai(prasanje: str) -> date | None:
    """Резервно: ако локалното не препознае датум, прашаме Groq."""
    from ai._kernel.ai_json import is_ai_error_response, parse_ai_json
    from ai._kernel.groq_client import ask_ai

    denes = date.today().isoformat()
    prompt = (f"Денес е {denes}. Од прашањето извлечи датум за преглед (работен ден). "
              f"Прашање: „{prasanje}\"\nВрати JSON: {{\"datum\": \"YYYY-MM-DD\"}} "
              "или {\"datum\": null} ако нема датум.\nСамо JSON.")
    raw = ask_ai(prompt, system_prompt="Ти извлекуваш датуми. Само валиден JSON.")
    if is_ai_error_response(raw): return None
    data = parse_ai_json(raw, log_tag="datum_ai")
    val = data.get("datum")
    if not val: return None
    try:
        out = datetime.strptime(str(val).strip()[:10], "%Y-%m-%d").date()
        return out if out >= date.today() else None
    except ValueError: return None

def izvleci_datum_za_slobodni(prasanje: str, kontekst: dict | None = None) -> date | None:
    """Главно извлекување: 1) локален regex, 2) контекст, 3) AI."""
    baran = datum_od_prasanje_lokalno(prasanje)
    if baran is not None: return baran
    if prasanje_bar_datum_od_kontekst(prasanje): return datum_od_zakazi_kontekst(kontekst)
    return _datum_od_prasanje_so_ai(prasanje)

def datum_za_zakazi_kontekst(baran_datum: date | None,
                              slobodni: list[datetime]) -> str | None:
    """ISO датум за `zakazi_od_slobodni` (од барањето или од приказот)."""
    if baran_datum is not None: return baran_datum.strftime("%Y-%m-%d")
    if not slobodni: return None
    return sorted({dt.date() for dt in slobodni})[0].strftime("%Y-%m-%d")

def _azuriraj_kontekst_ko_sloboden(kontekst: dict | None, baran_datum: date,
                                    barano_vreme: str | None, lekari: list[dict],
                                    oddel: str | None, pool: list[dict] | None) -> dict:
    """По „кој е слободен" одговор, зачувај листа лекари + датум + час во контекст."""
    ctx = dict(kontekst) if isinstance(kontekst, dict) else {}
    if oddel:
        ctx["last_oddel"] = oddel
        if pool: ctx["last_oddel_doctor_ids"] = [int(l["doctor_ID"]) for l in pool]
    ctx["last_slobodni_datum"] = baran_datum.strftime("%Y-%m-%d")
    if barano_vreme: ctx["last_slobodni_vreme"] = barano_vreme
    if lekari:
        ctx["last_slobodni_doctor_ids"] = [int(l["doctor_ID"]) for l in lekari]
        prv = lekari[0]
        z: dict = {"doctor_id": int(prv["doctor_ID"]),
                   "datum": baran_datum.strftime("%Y-%m-%d")}
        if barano_vreme: z["vreme"] = barano_vreme
        ctx["zakazi_od_slobodni"] = z
        ctx["last_doctor_id"] = int(prv["doctor_ID"])
    return ctx

# ═══ ГЛАВНА ТОЧКА — повикана од handlers.py ═══
def odgovori_za_slobodni_termini(prasanje: str,
                                  kontekst: dict | None = None) -> str | dict:
    """
    Логиката оди по 4 случаи (по ред):
       1: „следен работен ден"
       1б: уточнување на датум (зачуван час + оддел)
       2: „кој е слободен на 25.05 во 12:00?"
       3: „слободни на датум" по оддел (без лекар)
       4 (стандард): „кога е слободен д-р X?"
    Враќа: текст ИЛИ dict {„odgovor": …, „kontekst": …}.
    """
    # ── СЛУЧАЈ 1: „следен работен ден" ──
    if prasanje_e_sleden_raboten_den(prasanje):
        sleden = sleden_raboten_datum()
        lekar, _, nejasno = resolviraj_lekar_za_slobodni(prasanje, kontekst)
        if nejasno: return {"odgovor": nejasno, "kontekst": kontekst}

        if lekar:
            slobodni = pronajdi_slobodni_termini(lekar["doctor_ID"], na_datum=sleden)
            text = formatiraj_odgovor_preku_ai(lekar, slobodni, sleden, prasanje)
            return {"odgovor": text, "kontekst": {
                "zakazi_od_slobodni": {
                    "doctor_id": int(lekar["doctor_ID"]),
                    "datum": datum_za_zakazi_kontekst(sleden, slobodni)},
                "last_doctor_id": int(lekar["doctor_ID"])}}

        return {"odgovor": (
            f"Следниот работен ден за закажување прегледи е "
            f"{_IMENA_DEN[sleden.weekday()]}, {format_datum(sleden)}.\n\n"
            f"Термини се закажуваат од понеделник до петок, "
            f"{format_vreme(RABOTNO_VREME_OD)}–{format_vreme(RABOTNO_VREME_DO)}. "
            "Во сабота и недела не се закажуваат прегледи.\n\n"
            "Кажи кај кој лекар сакаш термин (на пр. „следен работен ден кај Петров\") "
            "или повтори го името на лекарот од претходното барање."),
            "kontekst": kontekst}

    # ── СЛУЧАЈ 1б: само уточнување на датум (зачуван час + оддел) ──
    if prasanje_e_utochnuvanje_datum(prasanje):
        baran_datum = izvleci_datum_za_slobodni(prasanje, kontekst)
        if baran_datum:
            zacuvano_vreme = vreme_iz_kontekst(kontekst)
            if zacuvano_vreme:
                pool, oddel = lekari_pool_za_ko_sloboden(prasanje, kontekst)
                tekst = odgovor_ko_e_sloboden_na_termin(prasanje, baran_datum,
                                                         zacuvano_vreme, kontekst)
                lekari = najdi_lekari_slobodni_na(baran_datum, zacuvano_vreme, lekari_pool=pool)
                ctx = _azuriraj_kontekst_ko_sloboden(kontekst, baran_datum, zacuvano_vreme,
                                                      lekari, oddel, pool)
                return {"odgovor": tekst, "kontekst": ctx}
            if _ima_oddel_lekari_kontekst(kontekst) or _oddel_od_kontekst(kontekst):
                return odgovor_slobodni_za_den_oddel(prasanje, baran_datum, kontekst)

    # ── СЛУЧАЈ 2: „кој е слободен..." (датум + време, без лекар) ──
    if prasanje_e_ko_e_sloboden_datum_vreme(prasanje, kontekst):
        baran_datum = izvleci_datum_za_slobodni(prasanje, kontekst)
        barano_vreme = vreme_od_prasanje_lokalno(prasanje) or vreme_iz_kontekst(kontekst)
        oddel_ctx = _oddel_od_kontekst(kontekst)

        if not baran_datum:
            primer = ("„Кој од нив е слободен на 20.05 во 12:00\"" if oddel_ctx
                      else "„Кој е слободен во среда на 20.05 во 12:00\"")
            return {"odgovor": _MSG_FALI_DATUM_VREME.format(primer=primer),
                    "kontekst": kontekst}

        if not barano_vreme:
            if oddel_ctx and prasanje_e_baranje_slobodni(prasanje):
                return odgovor_slobodni_za_den_oddel(prasanje, baran_datum, kontekst)
            primer = ("„Кој од нив е слободен во 12:00\"" if oddel_ctx
                      else f"„Кој е слободен на {format_datum(baran_datum)} во 12:00\"")
            return {"odgovor": _MSG_FALI_VREME.format(datum=format_datum(baran_datum),
                                                       primer=primer),
                    "kontekst": kontekst}

        pool, oddel = lekari_pool_za_ko_sloboden(prasanje, kontekst)
        tekst = odgovor_ko_e_sloboden_na_termin(prasanje, baran_datum, barano_vreme, kontekst)
        lekari = najdi_lekari_slobodni_na(baran_datum, barano_vreme, lekari_pool=pool)
        ctx = _azuriraj_kontekst_ko_sloboden(kontekst, baran_datum, barano_vreme,
                                              lekari, oddel, pool)
        return {"odgovor": tekst, "kontekst": ctx}

    # ── СЛУЧАЈ 3: „слободни на датум" по оддел (без лекар) ──
    if prasanje_e_slobodni_po_oddel_datum(prasanje, kontekst):
        baran_datum = izvleci_datum_za_slobodni(prasanje, kontekst)
        if baran_datum:
            return odgovor_slobodni_za_den_oddel(prasanje, baran_datum, kontekst)

    # ── СЛУЧАЈ 4 (стандард): „кога е слободен д-р X?" ──
    lekar, _, nejasno = resolviraj_lekar_za_slobodni(prasanje, kontekst)
    if nejasno: return {"odgovor": nejasno, "kontekst": kontekst}

    if not lekar:
        if prasanje_bar_lekar_od_kontekst(prasanje):
            return {"odgovor": _MSG_NEMA_IZBRAN_LEKAR_KONTEKST, "kontekst": kontekst}
        return _MSG_NE_RAZBRAV_LEKAR

    # има лекар → провери слободни и зачувај контекст
    baran_datum = izvleci_datum_za_slobodni(prasanje, kontekst)
    slobodni = pronajdi_slobodni_termini(lekar["doctor_ID"], na_datum=baran_datum)
    text = formatiraj_odgovor_preku_ai(lekar, slobodni, baran_datum, prasanje)

    did = int(lekar["doctor_ID"])
    ctx = dict(kontekst) if isinstance(kontekst, dict) else {}
    ctx["zakazi_od_slobodni"] = {"doctor_id": did,
                                  "datum": datum_za_zakazi_kontekst(baran_datum, slobodni)}
    ctx["last_doctor_id"] = did
    return {"odgovor": text, "kontekst": ctx}
