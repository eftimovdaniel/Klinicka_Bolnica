"""
Информации за конкретен лекар.

Како работи:
1. AI (Groq) препознава за кој лекар прашува корисникот (од листа во DB).
2. Враќа: специјалност, email, дали е дежурен (+ упатство за преглед / слободни термини).
"""

from datetime import date, datetime, time, timedelta

from database import get_connection
from ai._kernel.lekar_lookup import najdi_lekar_od_prasanje
from ai._kernel.transliteracija import transliterijaj
from ai.pacient.slobodni_termini import (
    lekar_od_zakazi_kontekst,
    prasanje_bar_lekar_od_kontekst,
    prasanje_e_specijalnost_izbran_lekar,
)


def zimi_dezurstva_za_lekar(doctor_id: int, denovi_napred: int = 7) -> list[dict]:
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT datum, oddel, vreme_od, vreme_do
            FROM Dezurstva
            WHERE doctor_ID = %s
              AND datum BETWEEN %s AND %s
            ORDER BY datum, vreme_od
            """,
            (doctor_id, date.today(), date.today() + timedelta(days=denovi_napred)),
        )
        rezultati = cur.fetchall()
        cur.close()
        return rezultati
    except Exception as e:
        print(f"[info_lekar] dezurstva greska: {e}")
        return []
    finally:
        if conn:
            conn.close()


def format_vreme(v) -> str:
    """Претвора time/timedelta во HH:MM string."""
    if v is None:
        return "—"
    if hasattr(v, "strftime"):
        return v.strftime("%H:%M")
    if hasattr(v, "total_seconds"):
        s = int(v.total_seconds())
        return f"{s // 3600:02d}:{(s % 3600) // 60:02d}"
    return str(v)[:5]


def _as_time(v) -> time | None:
    if v is None:
        return None
    if isinstance(v, time):
        return v
    if hasattr(v, "hour") and hasattr(v, "minute"):
        return v  # datetime.time-like
    if hasattr(v, "total_seconds"):
        s = int(v.total_seconds())
        return time(s // 3600, (s % 3600) // 60)
    try:
        parts = str(v).strip().split(":")
        if len(parts) >= 2:
            return time(int(parts[0]), int(parts[1]))
    except (ValueError, TypeError):
        pass
    return None


def _format_datum(datum: date) -> str:
    return datum.strftime("%d.%m.%Y")


def _dezurstvo_datum_vreme(d: dict) -> tuple[date | None, time | None, time | None]:
    datum = d.get("datum")
    if isinstance(datum, datetime):
        datum = datum.date()
    return datum, _as_time(d.get("vreme_od")), _as_time(d.get("vreme_do"))


def _e_na_dezurstvo_sega(d: dict, sega: datetime) -> bool:
    datum, vreme_od, vreme_do = _dezurstvo_datum_vreme(d)
    if not datum or datum != sega.date() or not vreme_od or not vreme_do:
        return False
    t = sega.time()
    return vreme_od <= t <= vreme_do


def _sledno_dezurstvo(dezurstva: list[dict], sega: datetime) -> dict | None:
    """Прво дежурство што сè уште не завршило (денес или иднина)."""
    for d in dezurstva:
        datum, vreme_od, vreme_do = _dezurstvo_datum_vreme(d)
        if not datum or not vreme_od:
            continue
        if datum > sega.date():
            return d
        if datum == sega.date() and vreme_do and sega.time() < vreme_do:
            return d
    return None


def _linija_za_dezurstvo(d: dict, prefiks: str) -> str:
    datum, vreme_od, _ = _dezurstvo_datum_vreme(d)
    if not datum:
        return prefiks
    return f"{prefiks}\nДатум: {_format_datum(datum)}\nПочеток на дежурство: {format_vreme(vreme_od)}"


def _dezuren_status(dezurstva: list[dict]) -> str:
    """
    Дежурен: Да — само ако во моментот е на дежурство (со датум и почеток).
    Дежурен: Не — ако не е сега; ако има идно дежурство, се печати датум и почеток.
    """
    if not dezurstva:
        return "Дежурен: Не"

    sega = datetime.now()
    for d in dezurstva:
        if _e_na_dezurstvo_sega(d, sega):
            return _linija_za_dezurstvo(d, "Дежурен: Да")

    sledno = _sledno_dezurstvo(dezurstva, sega)
    if sledno:
        return _linija_za_dezurstvo(sledno, "Дежурен: Не")

    return "Дежурен: Не"


def _resolviraj_lekar(prasanje: str, kontekst: dict | None) -> tuple[dict | None, bool]:
    if prasanje_bar_lekar_od_kontekst(prasanje) or prasanje_e_specijalnost_izbran_lekar(prasanje):
        lekar = lekar_od_zakazi_kontekst(kontekst)
        if lekar:
            return lekar, True
    lekar = najdi_lekar_od_prasanje(prasanje)
    if lekar:
        return lekar, False
    lekar = lekar_od_zakazi_kontekst(kontekst)
    return lekar, lekar is not None


def _e_prasanje_dali_raboti(prasanje: str) -> bool:
    p = transliterijaj(prasanje).lower()
    return any(
        w in p
        for w in (
            "работи",
            "вработен",
            "дали работи",
            "дали е вработен",
            "работи ли",
            "има ли тука",
            "дали е тука",
            "во оваа болница",
            "во болницата",
            "dali raboti",
            "raboti li",
        )
    )


def _format_info_lekar(lekar: dict, prasanje: str, od_kontekst: bool) -> str:
    ime = f"Д-р {lekar['name']} {lekar['surname']}"
    spec = lekar.get("specialty") or "Општа пракса"
    email = (lekar.get("email") or "").strip()
    doctor_id = lekar["doctor_ID"]
    dezurstva = zimi_dezurstva_za_lekar(doctor_id)

    if prasanje_e_specijalnost_izbran_lekar(prasanje):
        return (
            f"А од која област е: {ime}\n\n"
            f"Специјалност: {spec}.\n"
            f"Email: {email if email else '—'}"
        )

    if _e_prasanje_dali_raboti(prasanje):
        naslov = f"Да, {ime} работи во Клиничка Болница Штип."
    else:
        naslov = f"Информации за {ime}"

    delovi = [
        naslov,
        "",
        f"Име и презиме: {lekar['name']} {lekar['surname']}",
        f"Специјалност / оддел: {spec}",
        f"Email: {email if email else '—'}",
        _dezuren_status(dezurstva),
        "",
        "Доколку сакате преглед, најавете се со кориснички профил на сајтот.",
        f'За слободни термини напишете: „Кога е слободен д-р {lekar["surname"]}?"',
    ]
    if od_kontekst:
        delovi.insert(1, "(Од претходната порака во разговорот.)")
    return "\n".join(delovi)


def _kontekst_posle_info(lekar: dict, kontekst: dict | None) -> dict:
    did = int(lekar["doctor_ID"])
    ctx = dict(kontekst) if isinstance(kontekst, dict) else {}
    ctx["zakazi_od_slobodni"] = {
        "doctor_id": did,
        "datum": (ctx.get("zakazi_od_slobodni") or {}).get("datum"),
    }
    ctx["last_doctor_id"] = did
    return ctx


def odgovori_za_info_lekar(prasanje: str, kontekst: dict | None = None) -> str | dict:
    lekar, od_kontekst = _resolviraj_lekar(prasanje, kontekst)

    if not lekar:
        if prasanje_bar_lekar_od_kontekst(prasanje) or prasanje_e_specijalnost_izbran_lekar(prasanje):
            return {
                "odgovor": (
                    "Не гледам зачуван избран лекар од претходната порака.\n\n"
                    "Прво наведете го лекарот (на пр. „Кога е слободен д-р Петровски?“) "
                    "или закажете преглед, па повторете."
                ),
                "kontekst": kontekst,
            }
        return {
            "odgovor": (
                "Не најдов лекар со тоа име во евиденцијата на Клиничка Болница Штип.\n"
                'Проверете го правописот или пребарајте на сајтот во делот „Лекари".\n'
                'Пример: „Информации за д-р Марко Петров" или „Дали работи др Марија Хубрева?"'
            ),
            "kontekst": kontekst if isinstance(kontekst, dict) else None,
        }

    text = _format_info_lekar(lekar, prasanje, od_kontekst)
    return {"odgovor": text, "kontekst": _kontekst_posle_info(lekar, kontekst)}
