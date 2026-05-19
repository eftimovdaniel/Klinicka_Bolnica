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


# Работно време (може да го менуваш)
RABOTNO_VREME_OD = time(8, 0)    # pocetok na rabotno vrem od 08:00
RABOTNO_VREME_DO = time(16, 0)   # kraj na rabotno vreme do 16:00
TRAENJE_TERMIN_MINUTI = 30       # sekoj termin trae 30 minuti
DENOVI_NAPRED = 7
MAX_TERMINI = 8                  # MAX broj na termini vo eden den

# Име на ден (кирилица, после транслит.) → weekday 0=пон … 6=нед
_DEN_WD = {
    "понеделник": 0,
    "вторник": 1,
    "среда": 2,
    "четврток": 3,
    "петок": 4,
    "сабота": 5,
    "недела": 6,
}
# Подолги имиња први за алтернација (на пр. „четврток“ пред „петок“).
_DEN_ALT = "|".join(sorted(_DEN_WD.keys(), key=len, reverse=True))
_IMENA_DEN = ["понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"]

_RE_SLEDEN_RABOTEN_DEN = re.compile(
    r"(?:"
    r"(?:следен|следниот|нареден|наредниот|прв)\s+работен\s+ден"
    r"|работен\s+ден\s+(?:следен|нареден|наредниот|следниот)"
    r"|кога\s+е\s+(?:следниот|наредниот|првиот)?\s*работен\s+ден"
    r")",
    re.UNICODE,
)

_SLEDEN_DEN_RE = re.compile(
    rf"(?:следниот|наредниот|следен|нареден|за)(?:\s+во)?\s+({_DEN_ALT}|\w+)",
    re.IGNORECASE,
)
_RE_ZA_VO_DEN = re.compile(
    r"(?:за\s+)?во\s+([a-zа-яѓќѕџјљњџ]{4,12})\s*$",
    re.IGNORECASE | re.UNICODE,
)
_OVAA_DEN_RE = re.compile(
    rf"(?:оваа|овиот|овој)\s+({_DEN_ALT})",
    re.IGNORECASE,
)
# „слободен понеделник“, „има ли термин во петок“ — без „следниот“
_KONTEXT_I_DEN_RE = re.compile(
    rf"(?:(?:слободен|слободна|слободни|слободно)\w*\s+(?:за\s+)?(?:во\s+)?"
    rf"|(?:термин(?:и)?)\s+(?:за\s+)?(?:во\s+)?"
    rf"|(?:има\s+ли)\s+(?:нешто\s+)?(?:слободни\s+)?(?:за\s+)?(?:во\s+)?"
    rf"|(?:дали\s+има)\s+(?:нешто\s+)?(?:слободни\s+)?(?:за\s+)?(?:во\s+)?)"
    rf"({_DEN_ALT}|\w{{4,12}})\b",
    re.IGNORECASE,
)
_DATUM_BROJ_RE = re.compile(
    r"(?:на|за)\s+(\d{1,2})[\./\-](\d{1,2})(?:[\./\-](\d{2,4}))?",
    re.IGNORECASE,
)
_ISO_DATUM_RE = re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b")
_MESECI_BROJ: dict[str, int] = {
    "јануари": 1,
    "januari": 1,
    "февруари": 2,
    "fevruari": 2,
    "март": 3,
    "mart": 3,
    "април": 4,
    "april": 4,
    "мај": 5,
    "maj": 5,
    "јуни": 6,
    "juni": 6,
    "јули": 7,
    "juli": 7,
    "август": 8,
    "avgust": 8,
    "септември": 9,
    "septemvri": 9,
    "oktomvri": 10,
    "октомври": 10,
    "ноември": 11,
    "декември": 12,
}
_ORDINAL_SUF = r"(?:ти|ри|ви|ti|ri|vi|-ti|-ri|-vi)?"
_RE_DAN_MES = re.compile(
    r"(?:на\s+)?(\d{1,2})"
    + _ORDINAL_SUF
    + r"\s*(?:\.)?\s*("
    + "|".join(sorted(_MESECI_BROJ.keys(), key=len, reverse=True))
    + r")\b",
    re.UNICODE | re.IGNORECASE,
)


def _den_od_tekst(tekst: str) -> str | None:
    """Понеделник, вторник; скратено: вторни, vtornik."""
    t = transliterijaj(tekst or "").lower().strip()
    if not t:
        return None
    if t in _DEN_WD:
        return t
    _ALIAS = {
        "ponedel": "понеделник",
        "ponedelnik": "понеделник",
        "vtorni": "вторник",
        "vtornik": "вторник",
        "vtorik": "вторник",
        "sreda": "среда",
        "chetvrtok": "четврток",
        "petok": "петок",
        "sabota": "сабота",
        "nedela": "недела",
    }
    if t in _ALIAS:
        return _ALIAS[t]
    for ime in _DEN_WD:
        if len(t) >= 4 and (ime.startswith(t) or t.startswith(ime[:4])):
            return ime
    return None


def _den_od_match(m: re.Match) -> str | None:
    return _den_od_tekst(m.group(1) or "")


def _den_na_kraj_od_prasanje(p: str) -> str | None:
    """
    Ден во неделата на крај од прашањето („… Захариев понеделник?“),
    само ако има јасен контекст за термини/слободно време.
    """
    p2 = p.strip().rstrip("?!. ")
    _kontekst_den = re.compile(
        r"\b(кога|слободен|слободна|слободни|слободно|термин|има\s+ли|"
        r"нареден|наредниот|наредна|следен|следниот|следна)\b",
        re.IGNORECASE,
    )
    for ime in sorted(_DEN_WD.keys(), key=len, reverse=True):
        if not p2.endswith(ime):
            continue
        pred = p2[: len(p2) - len(ime)]
        if _kontekst_den.search(pred):
            return ime
    return None


def sleden_raboten_datum(denes: date | None = None) -> date:
    """Првиот пон–пет ден по денес (прескокнува сабота/недела)."""
    denes = denes or date.today()
    d = denes + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def prasanje_e_sleden_raboten_den(prasanje: str) -> bool:
    p = transliterijaj(prasanje).lower()
    return bool(_RE_SLEDEN_RABOTEN_DEN.search(p))


def prasanje_e_baranje_slobodni(prasanje: str) -> bool:
    """Прашање за слободни термини (не закажување)."""
    p = transliterijaj(prasanje).lower()
    if any(x in p for x in ("слобод", "slobod")):
        return True
    if "термин" in p or "termin" in p:
        if any(
            x in p
            for x in (
                "има",
                "дали",
                "кога",
                "слобод",
                "slobod",
                "провери",
                "proveri",
                "на ",
                " na ",
                "за ",
                " za ",
            )
        ):
            return True
        try:
            from ai.pacient.moi_pregledi import datum_za_pregledi_od_prasanje

            if datum_za_pregledi_od_prasanje(prasanje):
                return True
        except ImportError:
            if datum_od_prasanje_lokalno(prasanje):
                return True
    if re.search(r"\b(преглед|pregled)\w*\b", p) and (
        "слобод" in p or "slobod" in p or "провери" in p or "proveri" in p
    ):
        return True
    return False


def prasanje_e_slobodni_za_den(prasanje: str, kontekst: dict | None = None) -> bool:
    """Нов ден кај истиот лекар — „за во вторник“, „ама за вторник“."""
    if baranje_e_zakazuvanje(prasanje):
        return False
    if not datum_od_prasanje_lokalno(prasanje):
        return False
    if prasanje_e_baranje_slobodni(prasanje):
        return True
    if isinstance(kontekst, dict) and kontekst.get("zakazi_od_slobodni"):
        import re as _re

        p = transliterijaj(prasanje).lower()
        if _re.search(r"\b\d{1,2}\s*[:.]\s*\d{2}\b", p):
            return False
        return True
    return False


def prasanje_bar_lekar_od_kontekst(prasanje: str) -> bool:
    """„Избраниот/истиот лекар" — лекарот е во контекст од претходна порака."""
    p = transliterijaj(prasanje).lower()
    return any(
        x in p
        for x in (
            "избраниот лекар",
            "избраниот",
            "избраниов",
            "избран лекар",
            "истиот лекар",
            "истиот",
            "истиов",
            "погоре",
            "од листата",
            "од горе",
            "тогој лекар",
            "тој лекар",
            "го избрав",
            "izbraniot",
            "istiot",
        )
    )


def prasanje_e_otkazuvanje(prasanje: str) -> bool:
    """Откажување на термин (откажи, откажеш, откажам, …)."""
    p = transliterijaj(prasanje).lower()
    if "откаж" in p or "otkaz" in p:
        return True
    if "cancel" in p and "termin" in p:
        return True
    return any(
        x in p
        for x in (
            "сторнира",
            "поништи термин",
            "не доаѓам",
            "не сакам термин",
        )
    )


_RE_ZAKAZUVANJE = re.compile(
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


def baranje_e_zakazuvanje(prasanje: str) -> bool:
    """Дали пораката е закажување (не повторна проверка на слободни термини)."""
    raw = (prasanje or "").lower()
    q = transliterijaj(prasanje).lower()

    if _RE_ZAKAZUVANJE.search(q) or _RE_ZAKAZUVANJE.search(raw):
        if not any(
            w in q
            for w in (
                "слобод",
                "кога е",
                "има ли",
                "провери",
                "провер",
                "наредн",
                "следн",
            )
        ):
            return True

    if re.search(r"\b\d{1,2}\s*[:.]\s*\d{2}\b", q):
        if any(
            x in q or x in raw
            for x in (
                "закаж",
                "заказ",
                "zakaz",
                "термин",
                "преглед",
                "може да закаж",
                "може да заказ",
                "moze da zakaz",
            )
        ):
            return True
    return False


def prasanje_bar_datum_od_kontekst(prasanje: str) -> bool:
    """„Претходно спомнатиот / избраниот датум“ — датумот е во kontekst."""
    p = transliterijaj(prasanje).lower()
    return any(
        x in p
        for x in (
            "избраниот датум",
            "избрана дата",
            "избраниот",
            "претходно спомнати",
            "претходно",
            "претходниот",
            "спомнатиот датум",
            "спомнатиот",
            "истиот датум",
            "наведениот датум",
            "тогаш спомнати",
            "pretходно",
            "spomnat",
            "izbraniot datum",
        )
    )


def datum_od_zakazi_kontekst(kontekst: dict | None) -> date | None:
    """Датум зачуван по листа слободни термини / pending закажување."""
    if not isinstance(kontekst, dict):
        return None
    for key in ("zakazi_od_slobodni", "zakazi_pending"):
        z = kontekst.get(key)
        if not isinstance(z, dict) or not z.get("datum"):
            continue
        try:
            return datetime.strptime(str(z["datum"]).strip()[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
    return None


def prasanje_e_drugi_lekari_specijalnost(prasanje: str) -> bool:
    """
    Листа на други лекари од иста специјалност/оддел — lekari_oddel, не info_lekar.
    Пр. „други лекари од оваа специјалност", „лекари од истата специјалност".
    """
    p = transliterijaj(prasanje).lower()

    ima_spec_ref = any(
        x in p
        for x in (
            "специјалност",
            "специјалности",
            "оддел",
            "истата",
            "иста ",
            "оваа",
            "ова ",
            "истиот",
            "истиов",
            "specijalnost",
            "oddel",
            "istata",
            "ista ",
            "ovaa",
            "ova ",
        )
    )
    ima_lekari_pl = any(x in p for x in ("лекари", "lekari", "доктори", "doktori"))

    # „дај ми лекари од истата специјалност" (без зборот „други")
    if ima_lekari_pl and ima_spec_ref:
        if any(
            x in p
            for x in (
                "истата",
                "иста ",
                "оваа",
                "ова ",
                "istata",
                "ista ",
                "ovaa",
                "ova ",
            )
        ):
            return True
        if "од " in p and any(
            x in p for x in ("специјалност", "specijalnost", "оддел", "oddel")
        ):
            return True

    if not any(
        x in p
        for x in (
            "други",
            "друг ",
            "друга ",
            "уште",
            "останати",
            "drugi",
            "drug ",
            "ushte",
            "останati",
        )
    ):
        return False
    if not any(x in p for x in ("лекар", "лекари", "доктор", "lekari", "doktor")):
        return False
    return ima_spec_ref


def prasanje_e_specijalnost_izbran_lekar(
    prasanje: str, kontekst: dict | None = None
) -> bool:
    """
    Прашање за специјалност/област — „избраниот лекар“ или „лекарот“ од контекст.
    (не слободни термини)
    """
    if prasanje_e_drugi_lekari_specijalnost(prasanje):
        return False
    p = transliterijaj(prasanje).lower()
    ima_lekari_pl = any(x in p for x in ("лекари", "lekari", "доктори", "doktori"))
    if not any(
        x in p
        for x in (
            "област",
            "специјалност",
            "оддел",
            "каде работи",
            "која е",
            "кое е",
            "од која",
            "koja oblast",
            "vo koja",
            "specijalnost",
            "oblast",
            "oddel",
        )
    ):
        return False
    if prasanje_bar_lekar_od_kontekst(prasanje):
        return True
    if any(x in p for x in ("избран", "истиот", "погоре", "тој лекар", "togo lekar")):
        return True
    if ima_lekari_pl:
        return False
    if lekar_od_zakazi_kontekst(kontekst) and any(
        x in p
        for x in (
            "лекарот",
            "лекар ",
            " лекар",
            "д-р",
            " др",
            "докторот",
            "доктор ",
            "toj lekar",
            "togo lekar",
        )
    ):
        return True
    return False


def resolviraj_lekar_za_slobodni(
    prasanje: str, kontekst: dict | None
) -> tuple[dict | None, bool, str | None]:
    """
    Најди лекар за слободни термини.
    Враќа (lekar, od_kontekst, poraka_ako_nejasno).
    """
    if prasanje_bar_lekar_od_kontekst(prasanje):
        lekar = lekar_iz_izbran_kontekst(kontekst)
        if not lekar and isinstance(kontekst, dict):
            poraka = _poraka_izberi_lekar_od_lista(kontekst)
            if poraka:
                return None, False, poraka
        return lekar, lekar is not None, None

    from ai._kernel.lekar_lookup import (
        izvlechi_delovi_ime,
        najdi_lekar_od_prasanje,
        najdi_lekari_po_delovi,
        najdi_lekari_po_prezime,
        poraka_za_vise_lekari,
        prezime_na_pocetok_od_prasanje,
    )

    prezime_poc = prezime_na_pocetok_od_prasanje(prasanje)
    if prezime_poc:
        kandidati = najdi_lekari_po_prezime(prezime_poc)
        if len(kandidati) == 1:
            return kandidati[0], False, None
        if len(kandidati) > 1:
            return None, False, poraka_za_vise_lekari(kandidati, [prezime_poc])

    delovi = izvlechi_delovi_ime(prasanje)
    kandidati = najdi_lekari_po_delovi(delovi)
    if len(kandidati) > 1:
        return None, False, poraka_za_vise_lekari(kandidati, delovi)

    lekar = najdi_lekar_od_prasanje(prasanje)
    if lekar:
        return lekar, False, None

    lekar = lekar_od_zakazi_kontekst(kontekst)
    if lekar:
        return lekar, True, None

    if prasanje_e_baranje_slobodni(prasanje) and datum_od_prasanje_lokalno(prasanje):
        lekar = lekar_od_oddel_kontekst(kontekst)
        if lekar:
            return lekar, True, None

    return None, False, None


def _sleden_takov_kalendarski_den(denes: date, ime_den: str) -> date:
    """
    Нареден календарски ден со тоа име (0=пон … 6=нед).

    Примери: ако денес е недела и бараат понеделник → утре (+1).
    Ако денес е вторник и бараат понеделник → наредниот понеделник (+6), не вчерашниот.
    Ако денес е истиот ден (на пр. понеделник → понеделник) → следната недела (+7).
    """
    twd = _DEN_WD[ime_den]
    dwd = denes.weekday()
    days = (twd - dwd) % 7
    if days == 0:
        days = 7
    return denes + timedelta(days=days)


def _ovaa_nedela_den(denes: date, ime_den: str) -> date:
    """„Оваа среда“ = среда од тековната недела; ако е минато, следната недела."""
    twd = _DEN_WD[ime_den]
    pocetok = denes - timedelta(days=denes.weekday())
    cand = pocetok + timedelta(days=twd)
    if cand < denes:
        cand += timedelta(days=7)
    return cand


def _mesec_od_tekst(tekst: str) -> int | None:
    t = transliterijaj(tekst).lower().strip()
    if t in _MESECI_BROJ:
        return _MESECI_BROJ[t]
    for k, v in _MESECI_BROJ.items():
        if t.startswith(k[:3]) or k.startswith(t[:3]):
            return v
    return None


def _parsiraj_dan_mesec(p: str, denes: date) -> date | None:
    """„20 мај", „на 20.05" со име на месец."""
    m = _RE_DAN_MES.search(p)
    if not m:
        return None
    dan = int(m.group(1))
    mesec = _mesec_od_tekst(m.group(2))
    if not mesec:
        return None
    return _parsiraj_dd_mm_gggg(denes, dan, mesec, None)


def vreme_od_prasanje_lokalno(prasanje: str) -> str | None:
    """Час од „во 12:00", „12 часот". """
    p = transliterijaj(prasanje or "").lower().strip()
    if not p:
        return None
    m = re.search(r"\b(\d{1,2})\s*[:.]\s*(\d{2})\b", p)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return f"{h:02d}:{mi:02d}"
    m = re.search(
        r"(?:во|vo|at)\s+(\d{1,2})(?:\s*(?:час|часот|cas|casot))?\b",
        p,
    )
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23:
            return f"{h:02d}:00"
    m = re.search(r"\b(\d{1,2})\s*(?:час|часот|cas|casot)\b", p)
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23:
            return f"{h:02d}:00"
    return None


_KO_PRASANJE_RE = re.compile(
    r"\b(кој|која|кои|koj|koja|koi)\b",
    re.UNICODE | re.IGNORECASE,
)

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


def _ima_oddel_lekari_kontekst(kontekst: dict | None) -> bool:
    if not isinstance(kontekst, dict):
        return False
    ids = kontekst.get("last_oddel_doctor_ids")
    return isinstance(ids, list) and len(ids) > 0


def prasanje_e_od_niv_sloboden(prasanje: str) -> bool:
    """„Кој од нив е слободен …" — продолжување по листа лекари од оддел."""
    p = transliterijaj(prasanje).lower()
    if "слобод" not in p and "slobod" not in p:
        return False
    return any(m in p for m in _OD_NIV_SLOBODNI_MARKERS)


def prasanje_e_ko_e_sloboden_datum_vreme(
    prasanje: str, kontekst: dict | None = None
) -> bool:
    """„Кој/која е слободен …" или „кој од нив" по листа оддел — без конкретен лекар по име."""
    p = transliterijaj(prasanje).lower()
    if "слобод" not in p and "slobod" not in p:
        return False

    from ai._kernel.lekar_lookup import prasanje_ukazuva_kon_konkreten_lekar

    if _ima_oddel_lekari_kontekst(kontekst) and (
        prasanje_e_od_niv_sloboden(prasanje)
        or (_KO_PRASANJE_RE.search(p) and _oddel_od_kontekst(kontekst))
        or (
            prasanje_e_baranje_slobodni(prasanje)
            and datum_od_prasanje_lokalno(prasanje)
            and not vreme_od_prasanje_lokalno(prasanje)
            and not prasanje_ukazuva_kon_konkreten_lekar(prasanje)
        )
    ):
        return True

    baran_datum = datum_od_prasanje_lokalno(prasanje)
    barano_vreme = vreme_od_prasanje_lokalno(prasanje)
    if not baran_datum and not barano_vreme:
        return False
    if _KO_PRASANJE_RE.search(p):
        return True
    if baran_datum and barano_vreme:
        from ai._kernel.lekar_lookup import izvlechi_delovi_ime, najdi_lekar_od_delovi

        delovi = izvlechi_delovi_ime(prasanje)
        if not delovi or not najdi_lekar_od_delovi(delovi):
            return True
    return False


def _parsiraj_dd_mm_gggg(denes: date, d: int, m: int, g: int | None) -> date | None:
    god = g if g is not None else denes.year
    if god < 100:
        god += 2000
    try:
        out = date(god, m, d)
    except ValueError:
        return None
    if out < denes:
        if g is None and m >= denes.month:
            try:
                out = date(denes.year + 1, m, d)
            except ValueError:
                return None
        elif out < denes:
            return None
    return out


def datum_od_prasanje_lokalno(prasanje: str) -> date | None:
    """Брзо препознавање на датум во прашање (кирилица по транслит.)."""
    p = transliterijaj(prasanje).lower()
    denes = date.today()

    if _RE_SLEDEN_RABOTEN_DEN.search(p):
        return sleden_raboten_datum(denes)

    if "задутре" in p or "задутра" in p:
        return denes + timedelta(days=2)
    if re.search(r"\bутре\b", p):
        return denes + timedelta(days=1)

    m = _ISO_DATUM_RE.search(prasanje)
    if m:
        try:
            out = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return out if out >= denes else None
        except ValueError:
            pass

    dm = _parsiraj_dan_mesec(p, denes)
    if dm is not None:
        return dm

    m = _DATUM_BROJ_RE.search(p)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        g = int(m.group(3)) if m.group(3) else None
        parsed = _parsiraj_dd_mm_gggg(denes, d, mo, g)
        if parsed is not None:
            return parsed

    m = _OVAA_DEN_RE.search(p)
    if m:
        ime = _den_od_match(m)
        if ime:
            return _ovaa_nedela_den(denes, ime)

    m = _SLEDEN_DEN_RE.search(p)
    if m:
        ime = _den_od_match(m)
        if ime:
            return _sleden_takov_kalendarski_den(denes, ime)

    m = _RE_ZA_VO_DEN.search(p)
    if m:
        ime = _den_od_tekst(m.group(1))
        if ime:
            return _sleden_takov_kalendarski_den(denes, ime)

    m = _KONTEXT_I_DEN_RE.search(p)
    if m:
        ime = _den_od_match(m)
        if ime:
            return _sleden_takov_kalendarski_den(denes, ime)

    ime_kraj = _den_na_kraj_od_prasanje(p)
    if ime_kraj:
        return _sleden_takov_kalendarski_den(denes, ime_kraj)

    return None


def datum_za_zakazi_kontekst(
    baran_datum: date | None, slobodni: list[datetime]
) -> str | None:
    """ISO датум за zakazi_od_slobodni — од барањето или од прикажаните слотови."""
    if baran_datum is not None:
        return baran_datum.strftime("%Y-%m-%d")
    if not slobodni:
        return None
    dates = sorted({dt.date() for dt in slobodni})
    if len(dates) == 1:
        return dates[0].strftime("%Y-%m-%d")
    return dates[0].strftime("%Y-%m-%d")


def _datum_od_prasanje_so_ai(prasanje: str) -> date | None:
    """Резервно: датум од прашање преку Groq."""
    from ai._kernel.ai_json import is_ai_error_response, parse_ai_json
    from ai._kernel.groq_client import ask_ai

    denes = date.today().isoformat()
    prompt = f"""Денес е {denes}. Од прашањето извлечи датум за преглед (работен ден).
Прашање: „{prasanje}"

Врати JSON: {{"datum": "YYYY-MM-DD"}} или {{"datum": null}} ако нема датум.
Само JSON."""
    raw = ask_ai(prompt, system_prompt="Ти извлекуваш датуми. Само валиден JSON.")
    if is_ai_error_response(raw):
        return None
    data = parse_ai_json(raw, log_tag="datum_ai")
    val = data.get("datum")
    if not val:
        return None
    try:
        out = datetime.strptime(str(val).strip()[:10], "%Y-%m-%d").date()
        return out if out >= date.today() else None
    except ValueError:
        return None


def termin_sloboden_na_datum_vreme(
    doctor_id: int, na_datum: date, vreme_str: str
) -> bool:
    """
    Дали конкретниот термин (датум + час) е слободен.
    Не користи MAX_TERMINI — проверува точно бараниот слот во базата.
    """
    if na_datum.weekday() >= 5:
        return False
    try:
        h_s, m_s = vreme_str.strip().split(":")[:2]
        t = time(int(h_s), int(m_s))
    except (ValueError, TypeError):
        return False

    slotovi_den = generiraj_slotovi_za_den(na_datum)
    if not any(s.time().hour == t.hour and s.time().minute == t.minute for s in slotovi_den):
        return False

    slot_dt = datetime.combine(na_datum, t)
    if slot_dt < datetime.now():
        return False

    zafateni = najdi_zafateni_slotovi(doctor_id, na_datum, na_datum)
    return (na_datum, time(t.hour, t.minute)) not in zafateni


def lekar_sloboden_na_termin(lekar: dict, na_datum: date, vreme_str: str) -> bool:
    """Дали лекарот има слободен термин во тој работен ден и час."""
    return termin_sloboden_na_datum_vreme(
        int(lekar["doctor_ID"]), na_datum, vreme_str
    )


def zimi_lekari_po_specialty(specialty: str) -> list[dict[str, Any]]:
    """Лекари од еден оддел/специјалност (исто како lekari_oddel)."""
    if not (specialty or "").strip():
        return []
    try:
        with db_cursor() as (_, cur):
            cur.execute(
                """
                SELECT doctor_ID, name, surname, specialty, email
                FROM Doctors
                WHERE LOWER(TRIM(specialty)) = LOWER(TRIM(%s))
                ORDER BY surname, name
                """,
                (specialty.strip(),),
            )
            return fetch_all(cur)
    except Exception as e:
        print(f"[slobodni_termini] lekari po specialty greska: {e}")
        return []


def _oddel_od_kontekst(kontekst: dict | None) -> str | None:
    if not isinstance(kontekst, dict):
        return None
    for key in ("last_oddel", "oddel", "specialty"):
        val = kontekst.get(key)
        if val and str(val).strip():
            return str(val).strip()
    return None


def prasanje_bar_site_lekari_za_slobodni(prasanje: str) -> bool:
    """Корисникот сака слободни низ цела болница, не само претходниот оддел."""
    p = transliterijaj(prasanje).lower()
    return any(
        x in p
        for x in (
            "на болницата",
            "во болницата",
            "во целата",
            "целата болница",
            "кај било кој",
            "било кој лекар",
            "сите лекари",
            "site lekari",
            "celata bolnica",
        )
    )


def lekari_pool_za_ko_sloboden(
    prasanje: str, kontekst: dict | None
) -> tuple[list[dict] | None, str | None]:
    """
    Кои лекари да се проверат за „кој е слободен“.
    Враќа (pool, oddel_ime). pool=None → сите лекари.
    """
    if prasanje_bar_site_lekari_za_slobodni(prasanje):
        return None, None

    from ai._kernel.oddel_resolver import resolve_oddel

    resolved = resolve_oddel(prasanje)
    if resolved and resolved.ok and resolved.oddel:
        return zimi_lekari_po_specialty(resolved.oddel), resolved.oddel

    if not isinstance(kontekst, dict):
        return None, None

    oddel = _oddel_od_kontekst(kontekst)
    ids = kontekst.get("last_oddel_doctor_ids")
    if isinstance(ids, list) and ids:
        id_set = {int(x) for x in ids}
        site = zimi_site_lekari()
        pool = [l for l in site if int(l["doctor_ID"]) in id_set]
        if pool:
            return pool, oddel

    if oddel:
        pool = zimi_lekari_po_specialty(oddel)
        if pool:
            return pool, oddel

    return None, None


def najdi_lekari_slobodni_na(
    na_datum: date,
    vreme_str: str,
    lekari_pool: list[dict] | None = None,
) -> list[dict]:
    """Лекари со слободен термин на даден датум и час (опционално само од pool)."""
    slobodni: list[dict] = []
    for lekar in lekari_pool if lekari_pool is not None else zimi_site_lekari():
        if lekar_sloboden_na_termin(lekar, na_datum, vreme_str):
            slobodni.append(lekar)
    return sorted(slobodni, key=lambda x: (x.get("surname") or "", x.get("name") or ""))


def odgovor_slobodni_za_den_oddel(
    prasanje: str,
    na_datum: date,
    kontekst: dict | None,
) -> dict:
    """Слободни термини на датум за сите лекари од одделот (од контекст)."""
    pool, oddel = lekari_pool_za_ko_sloboden(prasanje, kontekst)
    if not pool and isinstance(kontekst, dict):
        ids = kontekst.get("last_oddel_doctor_ids") or []
        id_set = {int(x) for x in ids}
        pool = [l for l in zimi_site_lekari() if int(l["doctor_ID"]) in id_set]

    den_ime = _IMENA_DEN[na_datum.weekday()].lower()
    datum_fmt = na_datum.strftime("%d.%m.%Y")

    if na_datum.weekday() >= 5:
        naslov = (
            f"На {den_ime}, {datum_fmt} е викенд — прегледи се само во работни денови."
        )
        return {"odgovor": naslov, "kontekst": kontekst}

    if oddel:
        linii = [
            f"Слободни термини на {den_ime}, {datum_fmt} — оддел „{oddel}“:",
            "",
        ]
    else:
        linii = [f"Слободни термини на {den_ime}, {datum_fmt}:", ""]

    if not pool:
        linii.append("Немам зачувана листа лекари од претходната порака.")
        return {"odgovor": "\n".join(linii), "kontekst": kontekst}

    prv_so_termini: dict | None = None
    for lekar in pool:
        slobodni = pronajdi_slobodni_termini(int(lekar["doctor_ID"]), na_datum=na_datum)
        ime = f"д-р {lekar.get('name', '')} {lekar.get('surname', '')}".strip()
        if slobodni:
            if prv_so_termini is None:
                prv_so_termini = lekar
            casovi = [dt.strftime("%H:%M") for dt in slobodni[:12]]
            extra = f" (+{len(slobodni) - 12} уште)" if len(slobodni) > 12 else ""
            linii.append(f"• {ime}: {', '.join(casovi)}{extra}")
        else:
            linii.append(f"• {ime}: нема слободни термини")

    linii.extend(
        [
            "",
            "За закажување: „закажи кај [презиме] во [час]“ — датумот се зачувува.",
        ]
    )

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
    datum_fmt = na_datum.strftime("%d.%m.%Y")
    pool, oddel = lekari_pool_za_ko_sloboden(prasanje, kontekst)
    lekari = najdi_lekari_slobodni_na(na_datum, vreme_str, lekari_pool=pool)

    if oddel:
        naslov_den = (
            f"На {den_ime}, {datum_fmt} во {vreme_str} "
            f'на одделот „{oddel}" слободни се:'
        )
        prazen_den = (
            f"На {den_ime}, {datum_fmt} во {vreme_str} "
            f'на одделот „{oddel}" нема слободен лекар.\n\n'
            f"Работно време: {RABOTNO_VREME_OD.strftime('%H:%M')}–"
            f"{RABOTNO_VREME_DO.strftime('%H:%M')}, понеделник–петок.\n\n"
            "Пробајте друг час, друг лекар од листата погоре, или "
            "„Кога е слободен д-р [презиме]?“."
        )
    else:
        naslov_den = f"На {den_ime}, {datum_fmt} во {vreme_str} слободни се:"
        prazen_den = (
            f"На {den_ime}, {datum_fmt} во {vreme_str} нема слободен лекар за закажување.\n\n"
            f"Работно време: {RABOTNO_VREME_OD.strftime('%H:%M')}–"
            f"{RABOTNO_VREME_DO.strftime('%H:%M')}, понеделник–петок.\n\n"
            "Пробајте друг час или „Кога е слободен д-р [презиме]?“ за конкретен лекар."
        )

    if not lekari:
        return prazen_den

    linii = [naslov_den, ""]
    for l in lekari:
        spec = (l.get("specialty") or "Општа пракса").strip()
        linii.append(f"- Д-р {l['name']} {l['surname']} ({spec})")
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
    if prasanje_bar_datum_od_kontekst(prasanje):
        return datum_od_zakazi_kontekst(kontekst)
    return _datum_od_prasanje_so_ai(prasanje)


def formatiraj_odgovor_preku_ai(
    lekar: dict,
    slobodni: list[datetime],
    na_datum: date | None,
    prasanje: str,
) -> str:
    """Форматиран одговор од база (групирани периоди, без Groq)."""
    return formatiraj_odgovor(lekar, slobodni, na_datum=na_datum)


# gi zemame site lekari od the database
def zimi_site_lekari() -> list[dict[str, Any]]:
    try:
        with db_cursor() as (_, cur):
            cur.execute(
                """
                SELECT doctor_ID, name, surname, specialty, email
                FROM Doctors
                ORDER BY surname, name
                """
            )
            return fetch_all(cur)
    except Exception as e:
        print(f"[slobodni_termini] Greshka pri zimanje na lekari: {e}")
        return []
#funkcija koja so pomos na ai gi zima lekarite
# koristam Groq AI i on g gleda lekarite od bazata
def najdi_lekar_so_ai(prasanje: str) -> dict | None:
    from ai._kernel.groq_helpers import groq_zadolzhitelen

    if groq_zadolzhitelen():
        return None

    site_lekari = zimi_site_lekari()
    if not site_lekari:
        return None

    # Формираме listа на лекари како текст за AI
    lista_text = ""
    for lekar in site_lekari:
        spec = lekar.get("specialty") or "Општа пракса"
        lista_text += f"ID {lekar['doctor_ID']}: Д-р {lekar['name']} {lekar['surname']} - {spec}\n"

    # Прашање за AI
    full_prompt = f""" Листа на лекари во болницата:
{lista_text}

Прашање од корисникот: „{prasanje}"

За кој лекар се однесува прашањето (слободни термини, закажување, преглед кај лекар)?
Име може да биде нецелосно или на латиница. Ако се спомнуваат повеќе лекари, земи го најрелевантниот.
Врати само ID број или NONE.""".strip()

    # Повикај AI со специјален системски prompt (само број или NONE)
    odgovor = ask_ai(full_prompt, system_prompt=LEKAR_EXTRACT_PROMPT)

    # Парсирај го одговорот - очекуваме само број или NONE
    odgovor_cist = odgovor.strip().upper().replace(".", "").replace(",", "")

    if "NONE" in odgovor_cist:
        return None

    # Извлечи го првиот број од одговорот
    match = re.search(r"\d+", odgovor_cist)
    if not match:
        return None

    doctor_id = int(match.group())

    # Најди го лекарот во листата
    for lekar in site_lekari:
        if lekar["doctor_ID"] == doctor_id:
            return lekar

    return None


def lekar_od_oddel_kontekst(kontekst: dict | None) -> dict | None:
    """Единствен лекар од претходна листа по оддел (last_oddel_doctor_ids)."""
    if not isinstance(kontekst, dict):
        return None
    ids = kontekst.get("last_oddel_doctor_ids")
    if not isinstance(ids, list) or len(ids) != 1:
        return None
    try:
        did = int(ids[0])
    except (TypeError, ValueError):
        return None
    for lekar in zimi_site_lekari():
        if int(lekar["doctor_ID"]) == did:
            return lekar
    return None


def lekar_iz_izbran_kontekst(kontekst: dict | None) -> dict | None:
    """Лекар од претходна порака: закажи/слободни, единствен од оддел, last_doctor_id."""
    lekar = lekar_od_zakazi_kontekst(kontekst)
    if lekar:
        return lekar
    return lekar_od_oddel_kontekst(kontekst)


def _poraka_izberi_lekar_od_lista(kontekst: dict) -> str:
    """Помошна порака кога има повеќе лекари од претходна листа по оддел."""
    ids = kontekst.get("last_oddel_doctor_ids")
    if not isinstance(ids, list) or len(ids) < 2:
        return ""
    id_set: set[int] = set()
    for raw in ids:
        try:
            id_set.add(int(raw))
        except (TypeError, ValueError):
            continue
    iminja: list[str] = []
    for lekar in zimi_site_lekari():
        if int(lekar["doctor_ID"]) in id_set:
            ime = (lekar.get("name") or "").strip()
            prezime = (lekar.get("surname") or "").strip()
            if ime or prezime:
                iminja.append(f"д-р {ime} {prezime}".strip())
    if not iminja:
        return ""
    lista = ", ".join(iminja[:8])
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
    if baranje_e_zakazuvanje(prasanje):
        return False
    if not prasanje_e_baranje_slobodni(prasanje):
        return False
    if not datum_od_prasanje_lokalno(prasanje):
        return False
    if vreme_od_prasanje_lokalno(prasanje):
        return False
    from ai._kernel.lekar_lookup import najdi_lekar_od_prasanje

    if najdi_lekar_od_prasanje(prasanje):
        return False
    ids = kontekst.get("last_oddel_doctor_ids") if isinstance(kontekst, dict) else []
    return isinstance(ids, list) and len(ids) > 1


def lekar_od_zakazi_kontekst(kontekst: dict | None) -> dict | None:
    """Лекар од конверзација (листа слободни термини или недовршено закажување)."""
    if not kontekst:
        return None
    doctor_id = None
    zos = kontekst.get("zakazi_od_slobodni")
    if not isinstance(zos, dict):
        zos = kontekst.get("zakazi_pending")
    if isinstance(zos, dict):
        doctor_id = normalize_int(zos.get("doctor_id"))
    if doctor_id is None:
        doctor_id = normalize_int(kontekst.get("last_doctor_id"))
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

    slotovi = []
    momentalno = datetime.combine(datum, RABOTNO_VREME_OD)
    kraj = datetime.combine(datum, RABOTNO_VREME_DO)

    while momentalno < kraj:
        slotovi.append(momentalno)
        momentalno += timedelta(minutes=TRAENJE_TERMIN_MINUTI)

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
        rezultati = cur.fetchall()
        cur.close()

        zafateni: set[tuple[date, time]] = set()
        for r in rezultati:
            d_raw = r.get("dp")
            t_raw = r.get("vp")

            if d_raw is None or t_raw is None:
                continue

            if isinstance(d_raw, datetime):
                datum = d_raw.date()
            elif isinstance(d_raw, date):
                datum = d_raw
            elif isinstance(d_raw, (bytes, bytearray)):
                try:
                    datum = datetime.strptime(d_raw.decode("utf-8", errors="ignore")[:10], "%Y-%m-%d").date()
                except ValueError:
                    continue
            elif isinstance(d_raw, str):
                try:
                    datum = datetime.strptime(d_raw.strip()[:10], "%Y-%m-%d").date()
                except ValueError:
                    continue
            else:
                continue

            vreme: time | None = None
            if isinstance(t_raw, time):
                vreme = time(t_raw.hour, t_raw.minute)
            elif isinstance(t_raw, timedelta):
                vkupno = int(t_raw.total_seconds())
                vreme = time((vkupno // 3600) % 24, (vkupno % 3600) // 60)
            elif isinstance(t_raw, (bytes, bytearray)):
                t_raw = t_raw.decode("utf-8", errors="ignore").strip()

            if vreme is None:
                if isinstance(t_raw, str):
                    parts = t_raw.replace(".", ":").split(":")
                    try:
                        h, m = int(parts[0]), int(parts[1])
                        vreme = time(h, m)
                    except (ValueError, IndexError):
                        continue
                else:
                    continue

            zafateni.add((datum, vreme))

        return zafateni

    except Exception as e:
        print(f"[slobodni_termini] Greshka pri barebje zafateni: {e}")
        return set()
    finally:
        if conn:
            conn.close()


def pronajdi_slobodni_termini(doctor_id: int, na_datum: date | None = None) -> list[datetime]:
    """
    Слободни слотови за лекар.
    - Ако na_datum е зададен: само за тој календарски ден (работен ден).
    - Инаку: првите MAX_TERMINI слотови во следните DENOVI_NAPRED дена од денес.
    """
    denes = date.today()
    if na_datum is not None and na_datum < denes:
        na_datum = None

    if na_datum is not None:
        if na_datum.weekday() >= 5:
            return []

        zafateni = najdi_zafateni_slotovi(doctor_id, na_datum, na_datum)
        slobodni: list[datetime] = []
        for slot_datetime in generiraj_slotovi_za_den(na_datum):
            if slot_datetime < datetime.now():
                continue
            slot_vreme = slot_datetime.time()
            slot_vreme = time(slot_vreme.hour, slot_vreme.minute)
            if (na_datum, slot_vreme) not in zafateni:
                slobodni.append(slot_datetime)
        return slobodni

    do_datum = denes + timedelta(days=DENOVI_NAPRED)
    zafateni = najdi_zafateni_slotovi(doctor_id, denes, do_datum)

    slobodni = []
    for offset in range(DENOVI_NAPRED + 1):
        datum = denes + timedelta(days=offset)
        slotovi_za_den = generiraj_slotovi_za_den(datum)

        for slot_datetime in slotovi_za_den:
            if slot_datetime < datetime.now():
                continue

            slot_vreme = slot_datetime.time()
            slot_vreme = time(slot_vreme.hour, slot_vreme.minute)
            if (datum, slot_vreme) not in zafateni:
                slobodni.append(slot_datetime)

                if len(slobodni) >= MAX_TERMINI:
                    return slobodni

    return slobodni


def _footer_za_zakazuvanje(eden_datum: bool) -> str:
    """Кратко упатство по листа на слободни термини."""
    if eden_datum:
        return (
            "\n\nКажете ми кој од овие термини најмногу ви одговара "
            '(на пример: „Закажи во 09:30").\n'
            "За друг работен ден — наведете нова дата."
        )
    return (
        '\n\nКажете ми датум, час и лекар (на пример: „Закажи кај Петров во 10:00").'
    )


def _cas_vo_minuti(cas_str: str) -> int:
    h, m = map(int, cas_str.split(":"))
    return h * 60 + m


def _kluc_period_za_cas(cas_str: str) -> str:
    """Групирање на слотови: рано наутро / околу пладне / попладне."""
    mins = _cas_vo_minuti(cas_str)
    if mins < 10 * 60:
        return "ran_nautro"
    if mins < 14 * 60:
        return "okolu_pladne"
    return "popladne"


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
    min_m, max_m = min(mins), max(mins)
    if max_m <= 12 * 60 + 30:
        return "во текот на целото претпладне"
    if min_m >= 14 * 60:
        return "попладне"
    if min_m < 10 * 60 and max_m >= 14 * 60:
        return "низ целиот работен ден"
    if min_m >= 10 * 60 and max_m < 14 * 60:
        return "претпладне"
    return "во текот на работниот ден"


def _formatiraj_casovi_po_periodi(casovi: list[str]) -> list[str]:
    """Редови „Ран наутро: 08:30 | 09:00“."""
    po_period: dict[str, list[str]] = {}
    for cas in casovi:
        po_period.setdefault(_kluc_period_za_cas(cas), []).append(cas)
    redici: list[str] = []
    for kluc in _PERIOD_REDO:
        if kluc in po_period:
            if redici:
                redici.append("")
            redici.append(
                f"{_PERIOD_NASLOVI[kluc]}: {' | '.join(po_period[kluc])}"
            )
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
    datum_fmt = datum.strftime("%d.%m.%Y")
    ime_lekar = f"{lekar['name']} {lekar['surname']}"
    specialnost = lekar.get("specialty") or "Општа пракса"
    raspon = _opis_raspon_termini(casovi)
    delovi = [
        (
            f"За {den_ime} ({datum_fmt}), кај д-р {ime_lekar} ({specialnost}) "
            f"има слободни термини {raspon}:"
        ),
        "",
        *_formatiraj_casovi_po_periodi(casovi),
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

    ime_lekar = f"д-р {lekar['name']} {lekar['surname']}"
    specialnost = lekar.get("specialty") or "Општа пракса"
    zaglavie_lekar = f"{ime_lekar} ({specialnost})"

    if not slobodni:
        if na_datum is not None and na_datum.weekday() >= 5:
            return (
                f"Кај {zaglavie_lekar}, {na_datum.strftime('%d.%m.%Y')} е викенд — "
                "прегледи се само во работни денови.\n\n"
                "Наведете работен ден (на пр. „следниот понеделник“) или прашајте без датум."
            )
        if na_datum is not None:
            den = DENOVI[na_datum.weekday()].lower()
            return (
                f"За {den} ({na_datum.strftime('%d.%m.%Y')}), кај {zaglavie_lekar} "
                "нема слободни термини.\n\n"
                "Наведете друга дата за нова проверка или прашајте без конкретен датум."
            )
        return (
            f"Кај {zaglavie_lekar} за избраниот период нема слободни термини.\n\n"
            "Пробајте друг ден или друг лекар, или наведете конкретен датум и време."
        )

    po_den: dict[tuple[date, int], list[str]] = {}
    for dt in slobodni:
        kluc = (dt.date(), dt.weekday())
        po_den.setdefault(kluc, []).append(dt.strftime("%H:%M"))

    eden_den = len(po_den) == 1

    if eden_den:
        (datum, weekday), casovi = next(iter(po_den.items()))
        return (
            _formatiraj_den_lekar(lekar, casovi, datum, weekday, DENOVI)
            + _footer_za_zakazuvanje(eden_datum=True)
        )

    delovi: list[str] = []
    for (datum, weekday), casovi in po_den.items():
        if delovi:
            delovi.append("")
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
    if prasanje_e_sleden_raboten_den(prasanje):
        sleden = sleden_raboten_datum()
        den_ime = _IMENA_DEN[sleden.weekday()]
        datum_fmt = sleden.strftime("%d.%m.%Y")
        lekar, _, nejasno = resolviraj_lekar_za_slobodni(prasanje, kontekst)
        if nejasno:
            return {"odgovor": nejasno, "kontekst": kontekst}
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
            return {"odgovor": text, "kontekst": ctx}

        return {
            "odgovor": (
                f"Следниот работен ден за закажување прегледи е {den_ime}, {datum_fmt}.\n\n"
                f"Термини се закажуваат од понеделник до петок, "
                f"{RABOTNO_VREME_OD.strftime('%H:%M')}–{RABOTNO_VREME_DO.strftime('%H:%M')}. "
                "Во сабота и недела не се закажуваат прегледи.\n\n"
                "Кажи кај кој лекар сакаш термин (на пр. „следен работен ден кај Петров“) "
                "или повтори го името на лекарот од претходното барање."
            ),
            "kontekst": kontekst,
        }

    if prasanje_e_ko_e_sloboden_datum_vreme(prasanje, kontekst):
        baran_datum = izvleci_datum_za_slobodni(prasanje, kontekst)
        barano_vreme = vreme_od_prasanje_lokalno(prasanje)
        oddel_ctx = _oddel_od_kontekst(kontekst)
        if not baran_datum:
            primer = (
                f"„Кој од нив е слободен на 20.05 во 12:00“"
                if oddel_ctx
                else "„Кој е слободен во среда на 20.05 во 12:00“"
            )
            return {
                "odgovor": (
                    "За да проверам кој лекар е слободен, наведете датум и час.\n\n"
                    f"Пример: {primer}."
                ),
                "kontekst": kontekst,
            }
        if not barano_vreme:
            if oddel_ctx and prasanje_e_baranje_slobodni(prasanje):
                return odgovor_slobodni_za_den_oddel(prasanje, baran_datum, kontekst)
            primer = (
                "„Кој од нив е слободен во 12:00“"
                if oddel_ctx
                else f"„Кој е слободен на {baran_datum.strftime('%d.%m.%Y')} во 12:00“"
            )
            return {
                "odgovor": (
                    f"За {baran_datum.strftime('%d.%m.%Y')} наведете и час.\n\n"
                    f"Пример: {primer}."
                ),
                "kontekst": kontekst,
            }
        pool, oddel = lekari_pool_za_ko_sloboden(prasanje, kontekst)
        tekst = odgovor_ko_e_sloboden_na_termin(
            prasanje, baran_datum, barano_vreme, kontekst
        )
        lekari = najdi_lekari_slobodni_na(baran_datum, barano_vreme, lekari_pool=pool)
        ctx = dict(kontekst) if isinstance(kontekst, dict) else {}
        if oddel:
            ctx["last_oddel"] = oddel
            if pool:
                ctx["last_oddel_doctor_ids"] = [int(l["doctor_ID"]) for l in pool]
        ctx["last_slobodni_datum"] = baran_datum.strftime("%Y-%m-%d")
        ctx["last_slobodni_vreme"] = barano_vreme
        if lekari:
            ids_slob = [int(l["doctor_ID"]) for l in lekari]
            ctx["last_slobodni_doctor_ids"] = ids_slob
            pr = lekari[0]
            ctx["zakazi_od_slobodni"] = {
                "doctor_id": int(pr["doctor_ID"]),
                "datum": baran_datum.strftime("%Y-%m-%d"),
                "vreme": barano_vreme,
            }
            ctx["last_doctor_id"] = int(pr["doctor_ID"])
        return {"odgovor": tekst, "kontekst": ctx}

    if prasanje_e_slobodni_po_oddel_datum(prasanje, kontekst):
        baran_datum = izvleci_datum_za_slobodni(prasanje, kontekst)
        if baran_datum:
            return odgovor_slobodni_za_den_oddel(prasanje, baran_datum, kontekst)

    lekar, od_kontekst, nejasno = resolviraj_lekar_za_slobodni(prasanje, kontekst)
    if nejasno:
        return {"odgovor": nejasno, "kontekst": kontekst}

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
        return (
            "Го разбирам барањето како прашање за слободни термини кај лекар, "
            "но не успеав да препознаам точно за кој лекар се работи.\n\n"
            "Напиши го името и презимето на лекарот како што стои во нашата листа "
            '(на пример: „Кога е слободен д-р Марко Петров?" или „има ли термин кај Петров?").\n\n'
            'Ако лекарот не работи кај нас, ќе треба да одбереш друг од секцијата „Лекари" на сајтот.'
        )
    baran_datum = izvleci_datum_za_slobodni(prasanje, kontekst)
    slobodni = pronajdi_slobodni_termini(lekar["doctor_ID"], na_datum=baran_datum)
    text = formatiraj_odgovor_preku_ai(lekar, slobodni, baran_datum, prasanje)

    did = int(lekar["doctor_ID"])
    ctx = dict(kontekst) if isinstance(kontekst, dict) else {}
    ctx["zakazi_od_slobodni"] = {
        "doctor_id": did,
        "datum": datum_za_zakazi_kontekst(baran_datum, slobodni),
    }
    ctx["last_doctor_id"] = did
    return {"odgovor": text, "kontekst": ctx}
