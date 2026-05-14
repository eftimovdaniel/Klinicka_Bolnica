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


def _den_na_kraj_od_prashanje(p: str) -> str | None:
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


def cilj_datum_lokalno(prashanje: str) -> date | None:
    """Брзо препознавање на датум во прашање (кирилица по транслит.)."""
    p = transliterijaj(prashanje).lower()
    denes = date.today()

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

    ime_kraj = _den_na_kraj_od_prashanje(p)
    if ime_kraj:
        return _sleden_takov_kalendarski_den(denes, ime_kraj)

    m = _ISO_DATUM_RE.search(prashanje)
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


def izvleci_cilj_datum_za_slobodni(prashanje: str) -> date | None:
    """Датум наведен во прашањето (локално); без датум → првите слотови од денес."""
    return cilj_datum_lokalno(prashanje)


# gi zemame site lekari od the database
def zimi_site_lekari() -> list[dict]:
    conn = None
    # ostvaruvanje na konekcija so bazata
    try:
        conn = get_connection() 
        cur = conn.cursor(dictionary=True)
        # se izvlekuvat site lekari od bazata so ime i prezime
        cur.execute("""
            SELECT doctor_ID, name, surname, specialty
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
def najdi_lekar_so_ai(prashanje: str) -> dict | None:
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

Прашање од корисникот: „{prashanje}"

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


def formatiraj_odgovor(
    lekar: dict,
    slobodni: list[datetime],
    na_datum: date | None = None,
) -> str:
    """
    Формира порака на македонски, групирано по ден.
    Листа по ден + формална упатство за закажување.
    """
    DENOVI = [
        "Понеделник", "Вторник", "Среда", "Четврток",
        "Петок", "Сабота", "Недела",
    ]

    ime = f"Д-р {lekar['name']} {lekar['surname']}"
    specialnost = lekar.get("specialty") or "Општа пракса"
    uvod = f"{ime} — {specialnost}\n"

    if not slobodni:
        if na_datum is not None and na_datum.weekday() >= 5:
            return (
                uvod
                + f"\n{na_datum.strftime('%d.%m.%Y')} е викенд — прегледи се само во работни денови.\n\n"
                + "Прашај за конкретен работен ден (на пр. „следниот понеделник“) или без датум за првите слободни термини."
            )
        if na_datum is not None:
            return (
                uvod
                + f"\nЗа {DENOVI[na_datum.weekday()]}, {na_datum.strftime('%d.%m.%Y')} "
                + "немам пронајдено слободни термини.\n\n"
                + "Пробај друг ден или прашај без конкретен датум за првите слободни места во наредните денови."
            )
        return (
            uvod
            + "\nЗа избраниот период немам пронајдено слободни термини.\n\n"
            + "Можеш да пробаш со друг лекар или да ме прашаш повторно со појасно име. "
            + "Ако сакаш веднаш да закажеш конкретен датум и време, кажи на пример: "
            + "„Сакам преглед кај [презиме на лекар] на 2026-05-15 во 10:00“."
        )

    # Групирај термини по датум
    po_den = {}
    for dt in slobodni:
        kluc = (dt.date(), dt.weekday())
        po_den.setdefault(kluc, []).append(dt.strftime("%H:%M"))

    if na_datum is not None:
        zaglavie = f"Слободни термини за {DENOVI[na_datum.weekday()]}, {na_datum.strftime('%d.%m.%Y')}:"
    else:
        zaglavie = "Слободни термини (приказ по ден):"

    delovi = [uvod, "", zaglavie]
    for (datum, weekday), casovi in po_den.items():
        den_ime = DENOVI[weekday]
        datum_str = datum.strftime("%d.%m.%Y")
        casovi_str = ", ".join(casovi)
        delovi.append(f"• {den_ime}, {datum_str}: {casovi_str}")

    delovi.append(
        "\nДоколку сакате да закажете преглед кај избраниот лекар, одберете датум и час од листата погоре и во следната порака наведете го бараниот термин "
        f"(на пример: „Закажи преглед кај д-р {lekar['surname']} на {list(po_den.keys())[0][0].strftime('%Y-%m-%d')} во {list(po_den.values())[0][0]}“). "
        "Можете да употребите и сопствена формулација со иста смисла."
    )
    return "\n".join(delovi)


def odgovori_za_slobodni_termini(prashanje: str) -> str | dict:
    """
    Главна точка - повикана од router-от.

    Параметри:
        prashanje - целото прашање од корисникот (AI сам ќе извлече кој лекар)

    Враќа: текст или dict со „odgovor“ и „kontekst“ (за продолжување на закажување без повторно име).
    """
    # AI наоѓа кој лекар е во прашањето
    lekar = najdi_lekar_so_ai(prashanje)

    if not lekar:
        return (
            "Го разбирам барањето како прашање за слободни термини кај лекар, "
            "но не успеав да препознаам точно за кој лекар се работи.\n\n"
            "Напиши го името и презимето на лекарот како што стои во нашата листа "
            "(на пример: „Кога е слободен д-р Марко Петров?“ или „има ли термин кај Петров?“).\n\n"
            "Ако лекарот не работи кај нас, ќе треба да одбереш друг од секцијата „Лекари“ на сајтот."
        )
    cilj = izvleci_cilj_datum_za_slobodni(prashanje)
    slobodni = pronajdi_slobodni_termini(lekar["doctor_ID"], na_datum=cilj)
    text = formatiraj_odgovor(lekar, slobodni, na_datum=cilj)
    text += (
        "\n\nДоколку листата се однесува на еден датум, во следната порака доволно е да го наведете часот "
        "(на пример: „закажи во 10:30“). Ако се работи за повеќе денови, наведете го и датумот. "
        "Избраниот лекар од листата погоре останува запаметен за следното барање."
        if cilj
        else "\n\nДоколку листата обухвати повеќе денови, во следната порака наведете го датумот и часот. "
        "Избраниот лекар од листата погоре останува запаметен за следното барање."
    )

    ctx = {
        "zakazi_od_slobodni": {
            "doctor_id": int(lekar["doctor_ID"]),
            "datum": cilj.strftime("%Y-%m-%d") if cilj else None,
        }
    }
    return {"odgovor": text, "kontekst": ctx}
