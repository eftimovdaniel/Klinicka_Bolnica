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
from ai._kernel.db_helpers import normalize_int
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
    rf"(?:следниот|наредниот|следен|нареден|за|во)\s+({_DEN_ALT})",
    re.IGNORECASE,
)
_OVAA_DEN_RE = re.compile(
    rf"(?:оваа|овиот|овој)\s+({_DEN_ALT})",
    re.IGNORECASE,
)
# „слободен понеделник“, „има ли термин во петок“ — без „следниот“
_KONTEXT_I_DEN_RE = re.compile(
    rf"(?:(?:слободен|слободна|слободни|слободно)\w*\s+(?:во\s+)?"
    rf"|(?:термин(?:и)?)\s+(?:во\s+)?"
    rf"|(?:има\s+ли)\s+термин\s+(?:во\s+)?)"
    rf"({_DEN_ALT})\b",
    re.IGNORECASE,
)
_DATUM_BROJ_RE = re.compile(
    r"(?:на|за)\s+(\d{1,2})[\./\-](\d{1,2})(?:[\./\-](\d{2,4}))?",
    re.IGNORECASE,
)
_ISO_DATUM_RE = re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b")


def _den_od_match(m: re.Match) -> str | None:
    g = (m.group(1) or "").lower()
    return g if g in _DEN_WD else None


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


def baranje_e_zakazuvanje(prasanje: str) -> bool:
    """Дали пораката е закажување (не повторна проверка на слободни термини)."""
    q = transliterijaj(prasanje).lower()
    if re.search(r"\b\d{1,2}\s*[:.]\s*\d{2}\b", q):
        if any(
            x in q
            for x in (
                "закаж",
                "zakaz",
                "закажам",
                "да закаж",
                "термин",
                "преглед",
                "може да закаж",
                "можам да закаж",
            )
        ):
            return True
    if any(
        x in q
        for x in (
            "закажам",
            "да закажам",
            "да закаж",
            "сакам да закаж",
            "може да закаж",
            "можам да закаж",
            "да закажете",
            "да закажете",
        )
    ):
        return True
    if "закаж" in q and "откаж" not in q and not any(
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
    Пр. „други лекари од оваа специјалност", „а други од истата специјалности".
    """
    p = transliterijaj(prasanje).lower()
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
    if not any(x in p for x in ("лекар", "доктор", "lekari", "doktor")):
        return False
    return any(
        x in p
        for x in (
            "специјалност",
            "специјалности",
            "оддел",
            "истата",
            "оваа",
            "истиот",
            "истиов",
            "истиов",
            "specijalnost",
            "oddel",
        )
    )


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
    if lekar_od_zakazi_kontekst(kontekst) and any(
        x in p
        for x in (
            "лекарот",
            "лекар",
            "д-р",
            " др",
            "докторот",
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
        lekar = lekar_od_zakazi_kontekst(kontekst)
        return lekar, lekar is not None, None

    from ai._kernel.lekar_lookup import (
        izvlechi_delovi_ime,
        najdi_lekar_od_prasanje,
        najdi_lekari_po_delovi,
        poraka_za_vise_lekari,
    )

    delovi = izvlechi_delovi_ime(prasanje)
    kandidati = najdi_lekari_po_delovi(delovi)
    if len(kandidati) > 1:
        return None, False, poraka_za_vise_lekari(kandidati, delovi)

    lekar = najdi_lekar_od_prasanje(prasanje)
    if lekar:
        return lekar, False, None

    lekar = lekar_od_zakazi_kontekst(kontekst)
    return lekar, lekar is not None, None


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

    m = _KONTEXT_I_DEN_RE.search(p)
    if m:
        ime = _den_od_match(m)
        if ime:
            return _sleden_takov_kalendarski_den(denes, ime)

    ime_kraj = _den_na_kraj_od_prasanje(p)
    if ime_kraj:
        return _sleden_takov_kalendarski_den(denes, ime_kraj)

    m = _ISO_DATUM_RE.search(prasanje)
    if m:
        try:
            out = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return out if out >= denes else None
        except ValueError:
            pass

    m = _DATUM_BROJ_RE.search(p)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        g = int(m.group(3)) if m.group(3) else None
        return _parsiraj_dd_mm_gggg(denes, d, mo, g)

    return None


def izvleci_datum_za_slobodni(
    prasanje: str, kontekst: dict | None = None
) -> date | None:
    """Датум од прашање или од kontekst (претходно спомнат / избран ден)."""
    baran_datum = datum_od_prasanje_lokalno(prasanje)
    if baran_datum is not None:
        return baran_datum
    if prasanje_bar_datum_od_kontekst(prasanje):
        return datum_od_zakazi_kontekst(kontekst)
    return None


# gi zemame site lekari od the database
def zimi_site_lekari() -> list[dict]:
    conn = None
    # ostvaruvanje na konekcija so bazata
    try:
        conn = get_connection() 
        cur = conn.cursor(dictionary=True)
        # se izvlekuvat site lekari od bazata so ime i prezime
        cur.execute("""
            SELECT doctor_ID, name, surname, specialty, email
            FROM Doctors
            ORDER BY surname, name
        """)
        lekari = cur.fetchall()     # vo lekari gi stavame site lekari so fetchall
        cur.close()
        return lekari   # gi vraka site lekari
    except Exception as e:
        print(f"[slobodni_termini] Greshka pri zimanje na lekari: {e}")
        return []
    finally:
        if conn:
            conn.close()
#funkcija koja so pomos na ai gi zima lekarite
# koristam Groq AI i on g gleda lekarite od bazata
def najdi_lekar_so_ai(prasanje: str) -> dict | None:
    site_lekari = zimi_site_lekari()    # vo site_lekari se smesteni lekarite od the database
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
                if len(slobodni) >= MAX_TERMINI:
                    break
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
            "\n\nЗа закажување напишете го часот (на пр. „закажи во 08:30“). "
            "За друг ден — наведете нова дата."
        )
    return "\n\nЗа закажување наведете датум и час од листата."


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
            text = formatiraj_odgovor(lekar, slobodni, na_datum=sleden)
            ctx = {
                "zakazi_od_slobodni": {
                    "doctor_id": int(lekar["doctor_ID"]),
                    "datum": sleden.strftime("%Y-%m-%d"),
                }
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
    text = formatiraj_odgovor(lekar, slobodni, na_datum=baran_datum)

    did = int(lekar["doctor_ID"])
    ctx = {
        "zakazi_od_slobodni": {
            "doctor_id": did,
            "datum": baran_datum.strftime("%Y-%m-%d") if baran_datum else None,
        },
        "last_doctor_id": did,
    }
    return {"odgovor": text, "kontekst": ctx}
