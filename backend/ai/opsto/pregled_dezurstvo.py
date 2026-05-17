"""
Преглед на идни дежурства на лекар (за сите корисници).

„Кога е дежурна д-р X?" → листа датуми и времиња.
Директорот потоа може да користи promeni_dezurstvo за додавање/промена.
"""

from datetime import date, datetime, time

from database import get_connection
from ai._kernel.lekar_lookup import najdi_lekar_od_prasanje
from ai.opsto.info_lekar import format_vreme, _as_time, _format_datum
from ai.direktor.dezurstvo_kontekst import izgradи_kontekst


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


def _linija_dezurstvo(d: dict) -> str:
    datum = d.get("datum")
    if isinstance(datum, datetime):
        datum = datum.date()
    od = format_vreme(d.get("vreme_od"))
    do = format_vreme(d.get("vreme_do"))
    oddel = (d.get("oddel") or "—").strip()
    if datum:
        return f"• {_format_datum(datum)}, {oddel} — {od}–{do}"
    return f"• {oddel} — {od}–{do}"


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
        "kontekst": izgradи_kontekst(found, prv),
    }
