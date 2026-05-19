"""
Преглед на идни дежурства (за сите корисници).

- „Прикажи ги дежурствата на лекарите" → сите идни дежурства
- „Кога е дежурна д-р X?" → дежурства за еден лекар
"""

from datetime import date, datetime, time
from collections import defaultdict

from database import get_connection
from ai._kernel.lekar_lookup import najdi_lekar_od_prasanje
from ai._kernel.transliteracija import transliterijaj
from ai._kernel.utils import format_datum, format_vreme
from ai.opsto.info_lekar import _as_time
from ai.direktor.dezurstvo_kontekst import izgradi_kontekst

_DENOVI_MK = (
    "Понеделник",
    "Вторник",
    "Среда",
    "Четврток",
    "Петок",
    "Сабота",
    "Недела",
)


def zimi_idni_dezurstva(doctor_id: int, limit: int = 30) -> list[dict]:
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT dezurstvo_ID, datum, oddel, vreme_od, vreme_do
            FROM Dezurstva
            WHERE doctor_ID = %s AND datum >= %s
            ORDER BY datum, vreme_od
            LIMIT %s
            """,
            (doctor_id, date.today(), limit),
        )
        rows = cur.fetchall()
        cur.close()
        return rows
    except Exception as e:
        print(f"[pregled_dezurstvo] greska: {e}")
        return []
    finally:
        if conn:
            conn.close()


def prasanje_e_site_dezurstva(prasanje: str) -> bool:
    """Листа дежурства за повеќе лекари / цел тим (не конкретно име)."""
    p = transliterijaj(prasanje).lower()
    if "дежур" not in p and "dezur" not in p:
        return False
    if najdi_lekar_od_prasanje(prasanje, koristi_ai=True):
        return False
    if any(
        w in p
        for w in (
            "прикажи",
            "прикази",
            "покажи",
            "prikazi",
            "pokazi",
            "листа",
            "list",
            "сите",
            "site",
            "на лекар",
            "лекарите",
            "лекарите",
            "докторите",
            "lekari",
            "doktori",
        )
    ):
        return True
    if "дежурствата" in p or "дежурства" in p:
        return True
    return False


def zimi_site_idni_dezurstva(limit: int = 60) -> list[dict]:
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT d.dezurstvo_ID, d.datum, d.oddel, d.vreme_od, d.vreme_do,
                   doc.doctor_ID, doc.name, doc.surname, doc.specialty
            FROM Dezurstva d
            JOIN Doctors doc ON d.doctor_ID = doc.doctor_ID
            WHERE d.datum >= %s
            ORDER BY d.datum, d.vreme_od, doc.surname, doc.name
            LIMIT %s
            """,
            (date.today(), limit),
        )
        rows = cur.fetchall()
        cur.close()
        return rows
    except Exception as e:
        print(f"[pregled_dezurstvo] site greska: {e}")
        return []
    finally:
        if conn:
            conn.close()


def _linija_dezurstvo(d: dict, *, so_lekar: bool = False) -> str:
    datum = d.get("datum")
    if isinstance(datum, datetime):
        datum = datum.date()
    od = format_vreme(d.get("vreme_od"))
    do = format_vreme(d.get("vreme_do"))
    oddel = (d.get("oddel") or "—").strip()
    if so_lekar:
        ime = f"д-р {d.get('name', '')} {d.get('surname', '')}".strip()
        spec = (d.get("specialty") or "").strip()
        lekar_del = f"{ime} ({spec})" if spec else ime
        return f"• {lekar_del} — {oddel} — {od}–{do}"
    if datum:
        return f"• {format_datum(datum)}, {oddel} — {od}–{do}"
    return f"• {oddel} — {od}–{do}"


def _formatiraj_site_dezurstva(rows: list[dict]) -> str:
    if not rows:
        return (
            "Нема закажани идни дежурства во системот.\n\n"
            "Директорот може да додаде дежурства преку административниот панел."
        )

    sega = datetime.now()
    po_datum: dict[date, list[dict]] = defaultdict(list)
    for r in rows:
        datum = r.get("datum")
        if isinstance(datum, datetime):
            datum = datum.date()
        if datum:
            po_datum[datum].append(r)

    delovi = ["Идни дежурства на лекарите:", ""]
    for datum in sorted(po_datum.keys()):
        den = _DENOVI_MK[datum.weekday()].lower()
        delovi.append(f"{den.capitalize()}, {datum.strftime('%d.%m.%Y')}:")
        for d in po_datum[datum]:
            linija = _linija_dezurstvo(d, so_lekar=True)
            if _e_na_dezurstvo_sega(d, sega):
                linija += "  ← сега на дежурство"
            delovi.append(linija)
        delovi.append("")

    if len(rows) >= 60:
        delovi.append("(Прикажани се првите 60 термини — за повеќе, админ панел.)")
    return "\n".join(delovi).strip()


def _e_na_dezurstvo_sega(d: dict, sega: datetime) -> bool:
    datum = d.get("datum")
    if isinstance(datum, datetime):
        datum = datum.date()
    vreme_od = _as_time(d.get("vreme_od"))
    vreme_do = _as_time(d.get("vreme_do"))
    if not datum or datum != sega.date() or not vreme_od or not vreme_do:
        return False
    t = sega.time()
    if vreme_do < vreme_od:
        return t >= vreme_od or t <= vreme_do
    return vreme_od <= t <= vreme_do


def odgovori_za_pregled_dezurstvo(
    prasanje: str,
    lekar: dict | None = None,
    kontekst: dict | None = None,
) -> dict:
    if prasanje_e_site_dezurstva(prasanje):
        rows = zimi_site_idni_dezurstva()
        return {"odgovor": _formatiraj_site_dezurstva(rows), "kontekst": kontekst}

    found = najdi_lekar_od_prasanje(prasanje)
    if not found:
        return {
            "odgovor": (
                "Не препознав за кој лекар прашуваш.\n"
                'Пример: „Дали д-р Марија Хубрева има дежурства во наредниот период?"'
            )
        }

    ime = f"д-р {found['name']} {found['surname']}"
    dezurstva = zimi_idni_dezurstva(found["doctor_ID"])
    sega = datetime.now()

    delovi = [f"Дежурства на {ime}", ""]

    if dezurstva:
        for d in dezurstva:
            if _e_na_dezurstvo_sega(d, sega):
                delovi.append(_linija_dezurstvo(d) + "  ← сега на дежурство")
            else:
                delovi.append(_linija_dezurstvo(d))
    else:
        delovi.append("Нема закажани идни дежурства во системот.")

    prv = dezurstva[0] if dezurstva else None
    return {
        "odgovor": "\n".join(delovi),
        "kontekst": izgradi_kontekst(found, prv),
    }
